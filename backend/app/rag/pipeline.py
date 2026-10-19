"""
app/rag/pipeline.py — RAG diagnostic pipeline

Three-stage pipeline called by POST /api/chat:

  Stage 1 — Embed:
    text-embedding-ada-002 (Azure OpenAI) converts question to 1536-dim vector

  Stage 2 — Retrieve:
    Azure AI Search vector search over HNSW index.
    Index contains chunks from: health summaries, work order descriptions,
    vision analysis results, inspection form notes.
    Similarity threshold 0.45 — only high-confidence context passed to GPT-4.
    Metadata filters: asset_id, substation_id, risk_band.

  Stage 3 — Generate:
    GPT-4 (Azure OpenAI) generates grounded answer from retrieved chunks.
    System prompt enforces: answer ONLY from provided context, cite sources,
    say "I don't have enough information" if context is insufficient.
    Safety-critical: hallucination prevention non-negotiable in utility domain.

Why RAG over fine-tuning:
  Data changes daily — new work orders, inspections, health score updates.
  RAG re-indexes without retraining. Fine-tuning would require a full
  training cycle for every data update.
"""

import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

AZURE_OAI_KEY      = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OAI_VERSION  = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
EMBED_DEPLOYMENT   = os.getenv("AZURE_OPENAI_DEPLOYMENT_EMBED", "text-embedding-ada-002")
GPT4_DEPLOYMENT    = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT4", "gpt-4")

SEARCH_ENDPOINT    = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY         = os.getenv("AZURE_SEARCH_API_KEY")
SEARCH_INDEX       = os.getenv("AZURE_SEARCH_INDEX_NAME", "substation-health-index")

SIMILARITY_THRESHOLD = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.45"))
TOP_K                = int(os.getenv("RAG_TOP_K", "5"))
VERIFY_SSL           = os.getenv("VERIFY_SSL", "true").lower() == "true"


def run_rag_pipeline(question: str, asset_id: Optional[str] = None) -> Dict:
    """
    Full RAG pipeline: embed → retrieve → generate.

    Args:
        question: Natural language question from the engineer
        asset_id: Optional filter — restrict retrieval to one transformer

    Returns:
        { "answer": str, "sources": List[str] }
    """
    embedding = _embed_question(question)
    chunks    = _vector_search(embedding, asset_id=asset_id)

    if not chunks:
        return {
            "answer":  "I don't have enough information in the knowledge base to answer this question. "
                       "Try asking about a specific transformer by ID, or check the dashboard for current health data.",
            "sources": [],
        }

    answer  = _generate_answer(question, chunks)
    sources = list({c["source"] for c in chunks if c.get("source")})

    return {"answer": answer, "sources": sources}


def _embed_question(question: str) -> List[float]:
    """Embed question using text-embedding-ada-002 (Azure OpenAI)."""
    from openai import AzureOpenAI
    import urllib3
    if not VERIFY_SSL:
        urllib3.disable_warnings()

    client = AzureOpenAI(
        api_key=AZURE_OAI_KEY,
        azure_endpoint=AZURE_OAI_ENDPOINT,
        api_version=AZURE_OAI_VERSION,
        http_client=_get_http_client(),
    )
    response = client.embeddings.create(input=question, model=EMBED_DEPLOYMENT)
    return response.data[0].embedding


def _vector_search(embedding: List[float], asset_id: Optional[str] = None) -> List[Dict]:
    """
    Retrieve top-K most relevant chunks from Azure AI Search.

    Uses HNSW vector index on the embedding field.
    Optionally filters by asset_id metadata field.
    Only returns chunks above SIMILARITY_THRESHOLD.
    """
    import requests as req
    import urllib3
    if not VERIFY_SSL:
        urllib3.disable_warnings()

    url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version=2023-11-01"
    headers = {"Content-Type": "application/json", "api-key": SEARCH_KEY}

    body: Dict = {
        "vectorQueries": [{
            "kind":     "vector",
            "vector":   embedding,
            "fields":   "embedding",
            "k":        TOP_K,
        }],
        "select": "content,source,asset_id,substation_name,risk_band,chunk_type",
        "top":    TOP_K,
    }
    if asset_id:
        body["filter"] = f"asset_id eq '{asset_id}'"

    resp = req.post(url, json=body, headers=headers, timeout=15, verify=VERIFY_SSL)
    resp.raise_for_status()

    chunks = []
    for item in resp.json().get("value", []):
        score = item.get("@search.score", 0)
        if score >= SIMILARITY_THRESHOLD:
            chunks.append({
                "content":          item.get("content", ""),
                "source":           item.get("source", ""),
                "asset_id":         item.get("asset_id", ""),
                "substation_name":  item.get("substation_name", ""),
                "risk_band":        item.get("risk_band", ""),
                "chunk_type":       item.get("chunk_type", ""),
                "score":            score,
            })
    return sorted(chunks, key=lambda c: c["score"], reverse=True)


def _generate_answer(question: str, chunks: List[Dict]) -> str:
    """Generate grounded GPT-4 answer from retrieved chunks."""
    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=AZURE_OAI_KEY,
        azure_endpoint=AZURE_OAI_ENDPOINT,
        api_version=AZURE_OAI_VERSION,
        http_client=_get_http_client(),
    )

    context = "\n\n".join([
        f"[{c.get('chunk_type', 'note')} | {c.get('source', 'unknown')}]\n{c['content']}"
        for c in chunks
    ])

    system_prompt = """You are an AI diagnostic assistant for power transformer fleet management.
Answer questions based ONLY on the provided context — work orders, health metrics, inspection notes, and AI vision analysis.
If the context does not contain enough information to answer, say exactly: "I don't have enough information in the available data to answer this."
Always cite your sources by referencing the [chunk_type | source] labels in your answer.
Be concise, factual, and safety-aware — this is a utility operations context."""

    response = client.chat.completions.create(
        model=GPT4_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.1,  # Low temperature for factual, consistent answers
        max_tokens=500,
    )
    return response.choices[0].message.content


def _get_http_client():
    """Return httpx client that bypasses SSL verification if VERIFY_SSL=false."""
    if not VERIFY_SSL:
        import httpx
        return httpx.Client(verify=False)
    return None
