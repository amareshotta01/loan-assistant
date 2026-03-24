def answer_with_citations(message: str, chunks: list, state: dict) -> str:
    # TODO: Implement LangChain Ollama Mistral call
    return "Based on our policy (Section 3.1), the minimum required credit score is 650."

def decide_and_explain(state: dict, tool_results: dict) -> tuple[str, dict]:
    # TODO: Implement LangChain Ollama Mistral call
    reply = "Your application looks solid based on the calculated risk."
    decision = {"status": "APPROVE", "reasoning": ["Risk band is LOW", "EMI burden is acceptable"], "confidence": 0.85}
    return reply, decision