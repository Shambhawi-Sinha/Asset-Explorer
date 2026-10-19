"""
endpoints/chat.py — POST /api/chat

BFF endpoint for the RAG diagnostic chatbot.

Security: Azure OpenAI API key and Azure AI Search key NEVER reach the browser.
React sends only the question string.

RAG pipeline (live mode):
  1. Embed question → text-embedding-ada-002 (Azure OpenAI)
  2. Vector search → Azure AI Search (HNSW index, top-K retrieval)
     Sources: health summaries, work order descriptions, vision analysis,
              inspection form notes
  3. GPT-4 grounded answer with source citations
     Similarity threshold > 0.45 — answers only from retrieved context
     (safety-critical: hallucinations unacceptable)

Mock mode:
  Returns informative placeholder — no Azure credentials needed.
  Full RAG pipeline explained to recruiter / interviewer reading the mock response.
"""

import os
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["chat"])

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sources: List[str] = []


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Natural language diagnostic question → grounded GPT-4 answer.

    All Azure credentials accessed server-side — none reach the browser.
    In mock mode: friendly explanation of what the pipeline does in production.
    """
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Question cannot be empty")

    if MOCK_MODE:
        return ChatResponse(
            answer=(
                f'You asked: "{request.question}"\n\n'
                "The RAG diagnostic chatbot is running in mock mode.\n\n"
                "In production, this pipeline:\n"
                "  1. Embeds your question using text-embedding-ada-002 (Azure OpenAI)\n"
                "  2. Runs a vector search on Azure AI Search across health summaries, "
                "work order history, inspection notes, and AI vision analysis results\n"
                "  3. Passes the top-K retrieved chunks to GPT-4 to generate a grounded "
                "answer with source citations (similarity threshold 0.45 — no hallucinations)\n\n"
                "To enable live chat: set MOCK_MODE=false and configure AZURE_OPENAI_API_KEY, "
                "AZURE_OPENAI_ENDPOINT, AZURE_SEARCH_ENDPOINT, and AZURE_SEARCH_API_KEY in .env"
            ),
            sources=["mock-mode — RAG pipeline not active"]
        )

    try:
        # Lazy import to avoid Azure client init at startup when not needed
        from app.rag.pipeline import run_rag_pipeline
        result = run_rag_pipeline(question=request.question)
        return ChatResponse(
            answer=result["answer"],
            sources=result.get("sources", [])
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {exc}")
