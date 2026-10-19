"""
rag_indexing.py — Build Azure AI Search vector index for RAG chat
=================================================================
Chunks transformer-related documents (maintenance manuals, inspection reports,
work order history, health analysis outputs), generates embeddings with
text-embedding-ada-002, and upserts them into an Azure AI Search HNSW index.

Run this as a batch job (e.g., via Azure DevOps scheduled pipeline) whenever:
  - New work orders are closed
  - New inspection reports are uploaded to Fulcrum
  - Monthly health score reports are generated
  - Engineering bulletins or technical notes are added

Index schema: each document chunk carries:
  - id (str)          — unique chunk ID
  - asset_id (str)    — transformer it relates to (enables per-asset filtering in search)
  - doc_type (str)    — "work_order" | "inspection" | "health_report" | "manual" | "bulletin"
  - text (str)        — chunk text (max ~500 tokens)
  - embedding ([float]) — 1536-dim ada-002 embedding
  - created_at (str)  — ISO 8601 timestamp
  - source_ref (str)  — WO number, Fulcrum record ID, report filename, etc.
"""

import os
import json
import hashlib
import datetime
from typing import Optional
import openai
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    ExhaustiveKnnAlgorithmConfiguration,
)
from azure.core.credentials import AzureKeyCredential


# ── Config ────────────────────────────────────────────────────────────────────

SEARCH_ENDPOINT  = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY       = os.environ["AZURE_SEARCH_KEY"]
INDEX_NAME       = os.environ.get("AZURE_SEARCH_INDEX", "asset-health-index")

OPENAI_KEY       = os.environ["AZURE_OPENAI_KEY"]
OPENAI_ENDPOINT  = os.environ["AZURE_OPENAI_ENDPOINT"]
EMBED_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-ada-002")

CHUNK_SIZE    = 400     # target tokens per chunk
CHUNK_OVERLAP = 50      # overlap tokens between consecutive chunks
BATCH_SIZE    = 100     # upsert batch size (Azure Search limit: 1000 docs/batch)
VECTOR_DIMS   = 1536    # text-embedding-ada-002 output dimension


# ── Azure clients ─────────────────────────────────────────────────────────────

def _search_index_client() -> SearchIndexClient:
    return SearchIndexClient(
        endpoint=SEARCH_ENDPOINT,
        credential=AzureKeyCredential(SEARCH_KEY),
    )


def _search_client() -> SearchClient:
    return SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(SEARCH_KEY),
    )


def _openai_client() -> openai.AzureOpenAI:
    return openai.AzureOpenAI(
        api_key=OPENAI_KEY,
        azure_endpoint=OPENAI_ENDPOINT,
        api_version="2024-02-01",
    )


# ── Step 1: Index creation (idempotent) ───────────────────────────────────────

def ensure_index_exists() -> None:
    """
    Create the Azure AI Search HNSW vector index if it doesn't already exist.
    Safe to call on every pipeline run — no-ops if index is present.
    """
    idx_client = _search_index_client()

    fields = [
        SimpleField(name="id",         type=SearchFieldDataType.String,  key=True, filterable=True),
        SimpleField(name="asset_id",   type=SearchFieldDataType.String,  filterable=True),
        SimpleField(name="doc_type",   type=SearchFieldDataType.String,  filterable=True),
        SimpleField(name="created_at", type=SearchFieldDataType.String,  filterable=True, sortable=True),
        SimpleField(name="source_ref", type=SearchFieldDataType.String,  filterable=True),
        SearchableField(name="text",   type=SearchFieldDataType.String),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=VECTOR_DIMS,
            vector_search_profile_name="hnsw-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(name="hnsw-config"),
            ExhaustiveKnnAlgorithmConfiguration(name="knn-config"),
        ],
        profiles=[
            VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw-config"),
        ],
    )

    index = SearchIndex(name=INDEX_NAME, fields=fields, vector_search=vector_search)

    try:
        idx_client.create_index(index)
        print(f"[rag_indexing] Created index '{INDEX_NAME}'")
    except Exception:
        print(f"[rag_indexing] Index '{INDEX_NAME}' already exists — skipping creation")


# ── Step 2: Text chunking ─────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Word-boundary chunking with overlap.
    Approximate token count: 1 token ≈ 0.75 words (English).
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    step = max(chunk_size - overlap, 1)

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += step

    return chunks


def _chunk_id(asset_id: str, source_ref: str, chunk_index: int) -> str:
    """Stable, reproducible chunk ID (safe for upsert idempotency)."""
    raw = f"{asset_id}::{source_ref}::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Step 3: Embedding generation ─────────────────────────────────────────────

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate ada-002 embeddings for a list of text chunks.
    Batches automatically handle Azure OpenAI rate limits (100 texts/call max).
    """
    client = _openai_client()
    all_embeddings: list[list[float]] = []

    EMBED_BATCH = 16    # Conservative batch size for ada-002

    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i: i + EMBED_BATCH]
        response = client.embeddings.create(
            input=batch,
            model=EMBED_DEPLOYMENT,
        )
        all_embeddings.extend([item.embedding for item in response.data])

    return all_embeddings


# ── Step 4: Upsert to Azure AI Search ────────────────────────────────────────

def upsert_documents(documents: list[dict]) -> None:
    """
    Batch-upsert document chunks to Azure AI Search.
    Uses upload_documents which creates-or-replaces based on key ('id').
    """
    client = _search_client()
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i: i + BATCH_SIZE]
        result = client.upload_documents(documents=batch)
        failed = [r for r in result if not r.succeeded]
        if failed:
            print(f"[rag_indexing] ⚠ {len(failed)} documents failed to upsert in batch {i // BATCH_SIZE}")


# ── High-level indexing functions ─────────────────────────────────────────────

def index_work_order(
    asset_id: str,
    wo_id: str,
    description: str,
    wo_type: str,
    created_date: str,
    failure_code: Optional[str] = None,
) -> None:
    """Index a single work order. Called after WO creation or closure."""
    text = (
        f"Work Order {wo_id} for transformer {asset_id}. "
        f"Type: {wo_type}. Date: {created_date}. "
        f"Description: {description}."
        + (f" Failure code: {failure_code}." if failure_code else "")
    )
    _index_single_document(asset_id, wo_id, "work_order", text, created_date)


def index_inspection_report(
    asset_id: str,
    record_id: str,
    report_text: str,
    inspection_date: str,
) -> None:
    """Index a Fulcrum inspection report — chunked if long."""
    _index_chunked_document(asset_id, record_id, "inspection", report_text, inspection_date)


def index_health_report(
    asset_id: str,
    report_id: str,
    report_text: str,
    report_date: str,
) -> None:
    """Index a monthly health score narrative report."""
    _index_chunked_document(asset_id, report_id, "health_report", report_text, report_date)


def index_technical_document(
    doc_id: str,
    doc_text: str,
    doc_type: str = "manual",
    asset_id: str = "ALL",
    source_ref: str = "",
) -> None:
    """Index a fleet-wide technical document (manual, bulletin). asset_id='ALL' for global docs."""
    created_at = datetime.datetime.utcnow().isoformat()
    _index_chunked_document(asset_id, source_ref or doc_id, doc_type, doc_text, created_at)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _index_single_document(
    asset_id: str,
    source_ref: str,
    doc_type: str,
    text: str,
    created_at: str,
) -> None:
    """Embed and upsert a single short document (no chunking)."""
    embedding = embed_texts([text])[0]
    doc = {
        "id":         _chunk_id(asset_id, source_ref, 0),
        "asset_id":   asset_id,
        "doc_type":   doc_type,
        "text":       text,
        "embedding":  embedding,
        "created_at": created_at,
        "source_ref": source_ref,
    }
    upsert_documents([doc])


def _index_chunked_document(
    asset_id: str,
    source_ref: str,
    doc_type: str,
    text: str,
    created_at: str,
) -> None:
    """Chunk a long document, embed all chunks, upsert to search."""
    chunks = chunk_text(text)
    if not chunks:
        return

    embeddings = embed_texts(chunks)
    docs = [
        {
            "id":         _chunk_id(asset_id, source_ref, i),
            "asset_id":   asset_id,
            "doc_type":   doc_type,
            "text":       chunk,
            "embedding":  emb,
            "created_at": created_at,
            "source_ref": source_ref,
        }
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
    ]
    upsert_documents(docs)
    print(f"[rag_indexing] Indexed {len(docs)} chunks for {asset_id}/{source_ref} ({doc_type})")


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="Asset Explorer RAG indexer")
    parser.add_argument("--init-index", action="store_true", help="Create index if not exists")
    parser.add_argument("--index-file", type=str, help="JSON file with documents to index")
    args = parser.parse_args()

    if args.init_index:
        ensure_index_exists()

    if args.index_file:
        with open(args.index_file) as f:
            docs = json.load(f)
        for doc in docs:
            if doc.get("doc_type") == "work_order":
                index_work_order(
                    asset_id=doc["asset_id"],
                    wo_id=doc["wo_id"],
                    description=doc["description"],
                    wo_type=doc["wo_type"],
                    created_date=doc["created_date"],
                    failure_code=doc.get("failure_code"),
                )
            else:
                index_technical_document(
                    doc_id=doc.get("doc_id", "unknown"),
                    doc_text=doc["text"],
                    doc_type=doc.get("doc_type", "manual"),
                    asset_id=doc.get("asset_id", "ALL"),
                    source_ref=doc.get("source_ref", ""),
                )
        print(f"[rag_indexing] Done — indexed {len(docs)} documents.")
