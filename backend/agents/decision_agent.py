from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import PromptTemplate

llm = ChatOllama(model="mistral", temperature=0.2)


def _is_policy_question(tool_results: dict, rag_data: dict) -> bool:
    """
    Determines if this is a policy/information question vs a loan application decision.
    Policy questions have RAG data but no meaningful tool results.
    """
    has_rag = rag_data.get("used_rag", False) and len(rag_data.get("chunks", [])) > 0
    has_tools = any([
        tool_results.get("emi"),
        tool_results.get("is_eligible") is not None,
        tool_results.get("risk_band") not in [None, "UNKNOWN"]
    ])
    
    # If we have RAG data but no meaningful tool calculations, it's a policy question
    return has_rag and not has_tools


def process(user_message: str, tool_results: dict, rag_data: dict, chat_history: str) -> tuple[str, dict]:
    """
    DECISION AGENT
    --------------
    Handles two types of responses:
    1. Policy Questions: Uses RAG data to answer informational queries
    2. Loan Decisions: Uses tool results to make approval/rejection decisions
    """
    
    # Determine if this is a policy question or loan decision
    is_policy = _is_policy_question(tool_results, rag_data)
    
    if is_policy:
        # POLICY QUESTION MODE: Answer based on RAG context
        policy_prompt = """
        You are a helpful Bank Policy Assistant.
        
        Conversation History: {history}
        User's Question: {message}
        
        Relevant Bank Policy Information:
        {rag}
        
        INSTRUCTIONS:
        1. Answer the user's question based ONLY on the policy information provided above.
        2. Be concise, professional, and helpful.
        3. If the information is not in the context, say "I don't have information about that in our policy documents."
        4. Format any monetary values appropriately (use $ for amounts mentioned in the policy).
        5. Do NOT make up information that is not in the context.
        """
        
        # Format RAG chunks for the prompt
        rag_context = "\n\n".join([
            f"--- Policy Excerpt ---\n{chunk.get('text', '')}"
            for chunk in rag_data.get("chunks", [])
        ])
        
        chain = PromptTemplate.from_template(policy_prompt) | llm
        reply = chain.invoke({
            "history": chat_history,
            "message": user_message,
            "rag": rag_context if rag_context else "No relevant policy information found."
        }).content
        
        decision = {
            "status": "INFO_PROVIDED",
            "reasoning": ["Answered policy/information question using RAG"],
            "confidence": 0.85
        }
        
        return reply, decision
    
    # LOAN DECISION MODE: Make approval/rejection decision
    loan_prompt = """
    You are the Final Decision Agent for a bank.
    
    Conversation History: {history}
    User's Latest Request: {message}
    Financial Math Results: {tools}
    Bank Policies: {rag}
    
    Write a polite, professional response explaining the outcome. 
    IMPORTANT: You must format ALL monetary values in Indian Rupees (Rs.) or as specified.
    Look carefully at the Financial Math Results. 
    If 'is_eligible' is False OR the 'risk_band' is HIGH, you MUST decline the loan and explain the specific reason why. 
    If 'is_eligible' is True AND the 'risk_band' is LOW or MEDIUM, you may approve it.
    Include the calculated EMI if available.
    """
    
    rag_context = "\n".join([
        chunk.get('text', '')[:500] 
        for chunk in rag_data.get("chunks", [])[:3]
    ])
    
    chain = PromptTemplate.from_template(loan_prompt) | llm
    reply = chain.invoke({
        "history": chat_history,
        "message": user_message, 
        "tools": tool_results, 
        "rag": rag_context if rag_context else "No specific policies retrieved."
    }).content
    
    # Smarter decision logic combining Eligibility Tool AND Risk Tool
    is_eligible = tool_results.get("is_eligible", True)
    risk_band = tool_results.get("risk_band", "UNKNOWN")
    
    if not is_eligible:
        status = "REJECT"
        reason = "Failed basic age or income eligibility rules."
    elif risk_band == "HIGH":
        status = "REJECT"
        reason = f"Calculated Risk Band is {risk_band}"
    elif risk_band in ["LOW", "MEDIUM"]:
        status = "APPROVE"
        reason = f"Risk band is {risk_band} and eligibility checks passed."
    else:
        # No tool data available yet
        status = "PENDING"
        reason = "Awaiting complete financial information for decision."
        
    decision = {
        "status": status,
        "reasoning": [reason],
        "confidence": 0.9 if status in ["APPROVE", "REJECT"] else 0.5
    }
    
    return reply, decision
