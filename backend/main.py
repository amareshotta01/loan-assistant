# backend/main.py
from fastapi import FastAPI, HTTPException
from backend.schemas import ChatRequest, ChatResponse, RagQueryRequest, RagQueryResponse
from backend.orchestrator import handle_chat
from backend.adapters import rag_adapter
import time

app = FastAPI(title="Loan Approval & Credit Risk Assistant API")

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        # Pass the request to your autonomous orchestrator
        response = await handle_chat(
            session_id=request.session_id, 
            message=request.message,
            metadata=request.metadata
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rag/query", response_model=RagQueryResponse)
async def rag_query_endpoint(request: RagQueryRequest):
    """Direct endpoint for Streamlit debugging and evaluation notebooks."""
    try:
        chunks = rag_adapter.retrieve(request.query, request.k)
        return RagQueryResponse(chunks=chunks)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))