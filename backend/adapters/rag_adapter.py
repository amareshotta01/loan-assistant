def retrieve(query: str, k: int = 4) -> list:
    # TODO: Member 2 integrates ChromaDB/FAISS here
    return [{"text": "Sample policy text regarding minimum credit scores.", "score": 0.92, "source": "policy_v1.pdf", "section": "3.1"}]