# backend/main.py
import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.schemas import ChatRequest, ChatResponse, RagQueryRequest, RagQueryResponse
from backend.orchestrator import handle_chat
from backend.adapters import rag_adapter

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Rate limiter setup
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Loan Approval & Credit Risk Assistant API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
async def chat_endpoint(request: ChatRequest, req: Request):
    try:
        logger.info(f"Chat request received for session: {request.session_id}")
        # Pass the request to your autonomous orchestrator
        response = await handle_chat(
            session_id=request.session_id, 
            message=request.message,
            metadata=request.metadata
        )
        return response
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rag/query", response_model=RagQueryResponse)
async def rag_query_endpoint(request: RagQueryRequest):
    """Direct endpoint for Streamlit debugging and evaluation notebooks."""
    try:
        chunks = rag_adapter.retrieve(request.query, request.k)
        return RagQueryResponse(chunks=chunks)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload")
@limiter.limit("5/minute")
async def upload_document(req: Request, file: UploadFile = File(...)):
    try:
        logger.info(f"Document upload request: {file.filename}")
        content = await file.read()
        text_content = content.decode("utf-8")
        
        # Pass it to the RAG Adapter to store in ChromaDB
        chunks_added = rag_adapter.add_document(text_content, file.filename)
        
        logger.info(f"Document {file.filename} ingested with {chunks_added} chunks")
        return {"status": "success", "filename": file.filename, "chunks_added": chunks_added}
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")
