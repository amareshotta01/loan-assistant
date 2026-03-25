import os
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_community.chat_models import ChatOllama 
from langchain_core.prompts import PromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ---------------------------------------------------------
# 1. CONFIGURATION FROM ENVIRONMENT VARIABLES
# ---------------------------------------------------------
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")
CHROMA_DB_DIR = os.environ.get("CHROMA_DB_DIR", os.path.join(os.path.dirname(__file__), "chroma_db"))
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RAG_DEFAULT_K = int(os.environ.get("RAG_DEFAULT_K", "5"))

# ---------------------------------------------------------
# 2. LAZY INITIALIZATION (avoids import-time errors)
# ---------------------------------------------------------
_llm = None
_vector_store = None
_embeddings = None


def _get_llm():
    """Lazy load the LLM to avoid import-time initialization issues."""
    global _llm
    if _llm is None:
        print(f"Initializing Ollama LLM with model: {OLLAMA_MODEL}")
        _llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.0)
    return _llm


def _get_embeddings():
    """Lazy load embeddings model."""
    global _embeddings
    if _embeddings is None:
        print(f"Loading embeddings model: {EMBEDDING_MODEL}")
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _embeddings


def _get_vector_store():
    """Lazy load the vector store to avoid import-time initialization issues."""
    global _vector_store
    if _vector_store is None:
        print(f"Connecting to ChromaDB at: {CHROMA_DB_DIR}")
        _vector_store = Chroma(persist_directory=CHROMA_DB_DIR, embedding_function=_get_embeddings())
    return _vector_store


# ---------------------------------------------------------
# 3. CORE DELIVERABLE: THE RETRIEVAL FUNCTION
# ---------------------------------------------------------
def retrieve(query: str, k: int = None) -> list[dict]:
    """
    Searches the local ChromaDB and returns the top k relevant chunks.
    
    Args:
        query: The search query
        k: Number of results to return (default from RAG_DEFAULT_K env var)
    """
    if k is None:
        k = RAG_DEFAULT_K
        
    vector_store = _get_vector_store()
    results = vector_store.similarity_search_with_score(query, k=k)
    
    formatted_results = []
    for doc, score in results:
        formatted_results.append({
            "text": doc.page_content,
            "score": float(score), 
            "source": doc.metadata.get("source", "master_policy_document.txt"),
            "section": doc.metadata.get("section", "General")
        })
    return formatted_results


# ---------------------------------------------------------
# 4. FULL RAG GENERATION PIPELINE
# ---------------------------------------------------------
def generate_rag_answer(query: str) -> dict:
    """Generate an answer using RAG pipeline with policy documents."""
    chunks = retrieve(query, k=RAG_DEFAULT_K) 
    context_text = "\n\n".join([f"Context Chunk:\n{c['text']}" for c in chunks])

    prompt_template = """
    You are an incredibly strict Loan and Credit Risk Compliance Auditor. 
    You evaluate queries strictly against the provided CONTEXT. 
    You have zero imagination. You never invent website portals, login steps, or external advice.

    CRITICAL RULES:
    1. If the exact answer is not in the context, your ONLY output must be: "REJECTED: Information not found in company policy."
    2. Read the time limits carefully. If a rule says "only after X months", and the user is at Y months (where Y < X), the action is FORBIDDEN.
    3. Use Rs. for all Indian Rupee amounts.
    
    CONTEXT:
    {context}
    
    USER QUESTION:
    {question}
    
    You MUST format your answer exactly like this:
    POLICY CITED: [Quote the exact sentence from the context, or write 'None']
    DECISION: [Approved / Denied / Cannot Determine]
    EXPLANATION: [One factual sentence explaining why, with NO extra advice]
    """
    
    prompt = PromptTemplate.from_template(prompt_template)
    llm = _get_llm()
    chain = prompt | llm
    
    response = chain.invoke({"context": context_text, "question": query})
    
    return {
        "answer": response.content,
        "chunks_used": len(chunks)
    }


def ingest_new_text(text: str, filename: str) -> int:
    """Chunks a newly uploaded text file and adds it to the existing ChromaDB."""
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = text_splitter.split_text(text)
    
    # Add metadata so we know where it came from
    metadatas = [{"source": filename, "section": "User Uploaded"} for _ in chunks]
    
    # Add to the existing vector store
    vector_store = _get_vector_store()
    vector_store.add_texts(texts=chunks, metadatas=metadatas)
    return len(chunks)
