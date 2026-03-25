import json
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import PromptTemplate

# We use JSON format so the AI always replies with computer-readable data
llm = ChatOllama(model="mistral", temperature=0.0, format="json")


def classify_intent(user_message: str) -> str:
    """
    INTENT CLASSIFICATION
    ---------------------
    Determines which type of query the user is making:
    - "loan_application": User wants to apply for a loan (needs financial data collection)
    - "policy_question": User is asking about policies, rates, eligibility rules (use RAG)
    - "calculation": User wants EMI calculation or eligibility check (use tools)
    - "general": General greeting or unrelated query
    """
    intent_prompt = """
    You are an Intent Classifier for a bank assistant. Analyze the user's message and classify it.
    
    User Message: {message}
    
    CLASSIFICATION RULES:
    1. "loan_application" - User explicitly wants to APPLY for a loan, start an application, or provide their financial details for a loan
       Examples: "I want to apply for a loan", "I need a home loan of 50 lakhs", "Start my loan application"
    
    2. "policy_question" - User is ASKING ABOUT policies, rules, interest rates, eligibility criteria, fees, penalties, credit cards, or any informational question about bank products
       Examples: "What is the interest rate?", "What are the eligibility criteria?", "Tell me about foreclosure policy", "What documents are needed?", "What is the processing fee?", "How does EMI calculation work?"
    
    3. "calculation" - User wants to CALCULATE something specific like EMI, check eligibility with specific numbers they provide
       Examples: "Calculate my EMI for 10 lakhs at 12% for 5 years", "Am I eligible for a loan if my salary is 50000?"
    
    4. "general" - Greetings, thanks, general conversation, or unclear intent
       Examples: "Hello", "Thank you", "What can you do?"
    
    Respond ONLY in JSON format:
    {{"intent": "loan_application" | "policy_question" | "calculation" | "general"}}
    """
    
    chain = PromptTemplate.from_template(intent_prompt) | llm
    response = chain.invoke({"message": user_message})
    
    try:
        cleaned_content = response.content.strip()
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3]
        result = json.loads(cleaned_content.strip())
        return result.get("intent", "general")
    except:
        # Default to policy_question if classification fails (safer than assuming loan application)
        return "policy_question"


def process(user_message: str, current_state: dict) -> dict:
    """
    INTAKE AGENT WITH INTENT-BASED ROUTING
    --------------------------------------
    First classifies the user's intent, then either:
    - Collects financial data (for loan applications)
    - Skips data collection (for policy questions / RAG queries)
    """
    
    # Step 1: Classify the intent
    intent = classify_intent(user_message)
    
    # Step 2: For policy questions, general queries, or calculation requests - skip data collection
    if intent in ["policy_question", "general"]:
        return {
            "intent": intent,
            "loan_amount": current_state.get("loan_amount"),
            "income_monthly": current_state.get("income_monthly"),
            "tenure_months": current_state.get("tenure_months"),
            "age": current_state.get("age"),
            "credit_score": current_state.get("credit_score"),
            "missing_fields": [],  # No fields required for policy questions
            "route_to": "rag" if intent == "policy_question" else "general"
        }
    
    # Step 3: For calculations - MUST extract values from the message first
    if intent == "calculation":
        calc_prompt = """
        You are a Financial Data Extractor. Extract numeric values from the user's calculation request.
        
        User Message: {message}
        Current Known Data: {current_state}
        
        EXTRACTION RULES:
        - "10 lakh" or "10L" = 1000000, "50 lakh" = 5000000, "1 crore" = 10000000
        - "5 years" = 60 months, "10 years" = 120 months, "3 years" = 36 months
        - Interest rate: look for percentage like "10%", "12.5%", "8.5%"
        - If a value exists in current_state, keep it unless the user provides a new one
        
        Respond ONLY in JSON format:
        {{
            "loan_amount": (number in rupees, e.g., 1000000 for 10 lakhs, or null if not mentioned),
            "interest_rate": (annual percentage as number, e.g., 10 for 10%, or null - default will be 12.5),
            "tenure_months": (number of months, e.g., 60 for 5 years, or null),
            "income_monthly": (number or null),
            "age": (number or null),
            "credit_score": (number or null)
        }}
        """
        
        chain = PromptTemplate.from_template(calc_prompt) | llm
        response = chain.invoke({"message": user_message, "current_state": json.dumps(current_state)})
        
        try:
            cleaned_content = response.content.strip()
            if cleaned_content.startswith("```json"):
                cleaned_content = cleaned_content[7:]
            if cleaned_content.endswith("```"):
                cleaned_content = cleaned_content[:-3]
            extracted = json.loads(cleaned_content.strip())
            
            # Merge with current state (new values override old)
            return {
                "intent": intent,
                "loan_amount": extracted.get("loan_amount") or current_state.get("loan_amount"),
                "income_monthly": extracted.get("income_monthly") or current_state.get("income_monthly"),
                "tenure_months": extracted.get("tenure_months") or current_state.get("tenure_months"),
                "interest_rate": extracted.get("interest_rate") or 12.5,  # Default interest rate
                "age": extracted.get("age") or current_state.get("age"),
                "credit_score": extracted.get("credit_score") or current_state.get("credit_score"),
                "missing_fields": [],
                "route_to": "tools"
            }
        except:
            return {
                "intent": intent,
                "loan_amount": current_state.get("loan_amount"),
                "income_monthly": current_state.get("income_monthly"),
                "tenure_months": current_state.get("tenure_months"),
                "age": current_state.get("age"),
                "credit_score": current_state.get("credit_score"),
                "missing_fields": [],
                "route_to": "tools"
            }
    
    # Step 4: For loan applications - collect financial data
    prompt = """
    You are an Intake Agent for a bank. Read the user's message and extract financial data.
    Current known data: {current_state}
    User Message: {message}
    
    Respond ONLY in JSON format with these exact keys:
    "loan_amount": (number or null),
    "income_monthly": (number or null),
    "tenure_months": (number or null),
    "age": (number or null),
    "credit_score": (number or null),
    "missing_fields": (list of strings for what is still needed, e.g., ["income_monthly", "credit_score"])
    
    IMPORTANT: Only include fields in "missing_fields" that are TRULY missing and null in the current state.
    If a field already has a value in current_state, DO NOT add it to missing_fields.
    """
    
    chain = PromptTemplate.from_template(prompt) | llm
    response = chain.invoke({"current_state": json.dumps(current_state), "message": user_message})
    
    try:
        cleaned_content = response.content.strip()
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:]
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3]
            
        result = json.loads(cleaned_content.strip())
        result["intent"] = "loan_application"
        result["route_to"] = "loan_flow"
        return result
    except:
        return {
            "intent": "loan_application",
            "loan_amount": None, 
            "income_monthly": None, 
            "missing_fields": ["loan_amount", "income_monthly", "age", "tenure_months"],
            "route_to": "loan_flow"
        }
