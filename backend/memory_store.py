# backend/memory_store.py
from typing import Dict, Any

# In-memory dictionary for local testing (can be swapped for Redis/DB later)
_sessions: Dict[str, Dict[str, Any]] = {}

def load(session_id: str) -> Dict[str, Any]:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "entities": {
                "income_monthly": None,
                "loan_amount": None,
                "tenure_months": None,
                "credit_score": None,
                "existing_emi": None
            },
            "summary": ""
        }
    return _sessions[session_id]

def save(session_id: str, state: Dict[str, Any], summary_update: bool = False):
    # TODO: Implement LangChain summarization logic here if summary_update is True
    _sessions[session_id] = state