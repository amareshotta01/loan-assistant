# backend/agents/retrieval_agent.py
"""
RETRIEVAL AGENT
===============
Handles RAG (Retrieval Augmented Generation) by searching ChromaDB
for relevant policy chunks. Now with TTL caching for improved performance.
"""

from backend.adapters import rag_adapter
from perf.cache import cached_retrieval


def _do_retrieval(query: str) -> dict:
    """
    Internal function that performs the actual RAG retrieval.
    This is wrapped by cached_retrieval for caching.
    """
    chunks = rag_adapter.retrieve(query, k=4)
    
    if chunks:
        return {"used_rag": True, "chunks": chunks}
    else:
        return {"used_rag": False, "chunks": []}


def process(user_message: str) -> tuple:
    """
    In a fully autonomous setup, an LLM would write the search query.
    For speed, we pass the user's message directly to our RAG adapter.
    
    Now with caching: Identical queries within TTL window are served from cache.
    
    Returns:
        tuple: (rag_data_dict, cache_hit_bool)
        - rag_data_dict: {"used_rag": bool, "chunks": list}
        - cache_hit: True if served from cache, False if fresh retrieval
    """
    # Use cached retrieval - returns (result, cache_hit)
    rag_data, cache_hit = cached_retrieval(
        query=user_message,
        retrieval_fn=_do_retrieval
    )
    
    return rag_data, cache_hit
