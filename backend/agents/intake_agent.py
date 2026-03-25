import os
import re
import json
import logging
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

# Environment variable configuration
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.0"))

# We use JSON format so the AI always replies with computer-readable data
llm = ChatOllama(model=OLLAMA_MODEL, temperature=OLLAMA_TEMPERATURE, format="json")


# ============================================================
#  SECTION 1 — REGEX-BASED VALUE EXTRACTION (Pre-LLM)
#  Reliably extracts and converts values before LLM processing
# ============================================================

def _parse_indian_number(text: str) -> float:
    """
    Parses Indian number formats to actual numeric values.
    
    Examples:
        "10 lakh" -> 1000000
        "10L" -> 1000000
        "1.5 crore" -> 15000000
        "50k" -> 50000
        "25,00,000" -> 2500000
        "500000" -> 500000
    """
    if not text:
        return None
    
    text = text.lower().strip()
    text = text.replace(',', '').replace(' ', '')
    
    # Handle crore variations
    crore_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:cr|crore|crores)', text)
    if crore_match:
        return float(crore_match.group(1)) * 10000000
    
    # Handle lakh variations
    lakh_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:l|lakh|lakhs|lac|lacs)', text)
    if lakh_match:
        return float(lakh_match.group(1)) * 100000
    
    # Handle thousand variations
    thousand_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:k|thousand|thousands)', text)
    if thousand_match:
        return float(thousand_match.group(1)) * 1000
    
    # Handle plain numbers
    plain_match = re.search(r'(\d+(?:\.\d+)?)', text)
    if plain_match:
        return float(plain_match.group(1))
    
    return None


def _convert_tenure_to_months(value: float, unit: str) -> int:
    """
    Converts tenure to months based on unit.
    
    Examples:
        (5, "years") -> 60
        (36, "months") -> 36
        (2.5, "yrs") -> 30
    """
    unit = unit.lower().strip()
    
    if unit in ['year', 'years', 'yr', 'yrs', 'y']:
        return int(value * 12)
    elif unit in ['month', 'months', 'mo', 'mos', 'm']:
        return int(value)
    else:
        # Default: assume months if unit unclear
        return int(value)


def _extract_values_regex(message: str) -> dict:
    """
    PRE-LLM EXTRACTION using regex patterns.
    This runs BEFORE the LLM to reliably extract numeric values.
    
    Extracts:
    - loan_amount: From phrases like "loan of 10 lakhs", "10L loan", "borrow 50 lakh"
    - income_monthly: From "salary 50000", "earn 5 lakh per month", "income 60k", "monthly income"
    - tenure_months: From "5 years", "36 months", "tenure 10 yrs"
    - age: From "age 35", "I am 28 years old"
    - credit_score: From "credit score 750", "CIBIL 680"
    - interest_rate: From "12%", "10.5% interest", "rate of 11"
    """
    extracted = {
        "loan_amount": None,
        "income_monthly": None,
        "income_annual": None,  # Will be converted to monthly
        "tenure_months": None,
        "age": None,
        "credit_score": None,
        "interest_rate": None
    }
    
    msg_lower = message.lower()
    
    # ---- LOAN AMOUNT ----
    # Patterns: "loan of 10 lakhs", "10L loan", "borrow 50 lakh", "loan amount 20 lacs"
    loan_patterns = [
        r'(?:loan|borrow|borrowing|principal|amount)[\s:]*(?:of\s+)?(?:rs\.?\s*)?(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)',
        r'(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)\s*(?:rs\.?\s*)?(?:loan|for\s+loan)',
        r'(?:need|want|require|looking\s+for)[\s:]*(?:rs\.?\s*)?(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)\s*(?:loan)?',
    ]
    
    for pattern in loan_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            extracted["loan_amount"] = _parse_indian_number(match.group(1))
            break
    
    # ---- MONTHLY INCOME / SALARY ----
    # Patterns: "salary 50000", "earn 5 lakh", "income 60k per month", "monthly income 80000"
    monthly_income_patterns = [
        r'(?:monthly\s+)?(?:salary|income|earn|earning|earns|making)[\s:]*(?:is\s+)?(?:rs\.?\s*)?(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)\s*(?:per\s+month|monthly|pm|/\s*month|a\s+month)?',
        r'(?:i\s+)?(?:earn|make|get)[\s:]*(?:rs\.?\s*)?(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)\s*(?:per\s+month|monthly|pm|/\s*month|a\s+month)?',
        r'(?:monthly\s+income|monthly\s+salary|salary\s+per\s+month|income\s+per\s+month)[\s:]*(?:is\s+)?(?:rs\.?\s*)?(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)',
        r'(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)\s*(?:rs\.?\s*)?(?:salary|income|per\s+month|monthly)',
    ]
    
    for pattern in monthly_income_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            extracted["income_monthly"] = _parse_indian_number(match.group(1))
            break
    
    # ---- ANNUAL INCOME ----
    # Patterns: "annual income 6 lakh", "yearly salary 8L", "income 10 lakh per annum"
    annual_income_patterns = [
        r'(?:annual|yearly|per\s+annum|pa|p\.a\.)\s*(?:salary|income|earning)?[\s:]*(?:is\s+)?(?:rs\.?\s*)?(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)',
        r'(?:salary|income|earning)[\s:]*(?:is\s+)?(?:rs\.?\s*)?(\d+(?:\.\d+)?\s*(?:cr|crore|crores|l|lakh|lakhs|lac|lacs|k|thousand)?)\s*(?:annual|yearly|per\s+annum|pa|p\.a\.)',
    ]
    
    for pattern in annual_income_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            annual = _parse_indian_number(match.group(1))
            if annual:
                extracted["income_annual"] = annual
                # Convert to monthly if no monthly income already found
                if not extracted["income_monthly"]:
                    extracted["income_monthly"] = annual / 12
            break
    
    # ---- TENURE ----
    # Patterns: "5 years", "36 months", "tenure 10 yrs", "for 3 years"
    tenure_patterns = [
        r'(?:tenure|term|period|duration|repayment)[\s:]*(?:of\s+)?(\d+(?:\.\d+)?)\s*(years?|yrs?|y|months?|mos?|m)',
        r'(?:for|over|in)\s+(\d+(?:\.\d+)?)\s*(years?|yrs?|y|months?|mos?|m)',
        r'(\d+(?:\.\d+)?)\s*(years?|yrs?|y|months?|mos?|m)\s*(?:tenure|term|period|loan)',
    ]
    
    for pattern in tenure_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            value = float(match.group(1))
            unit = match.group(2)
            extracted["tenure_months"] = _convert_tenure_to_months(value, unit)
            break
    
    # ---- AGE ----
    # Patterns: "age 35", "I am 28 years old", "28 years", "aged 40"
    age_patterns = [
        r'(?:age|aged)[\s:]*(?:is\s+)?(\d+)',
        r'(?:i\s+am|i\'m)\s+(\d+)\s*(?:years?\s*old)?',
        r'(\d+)\s*(?:years?\s*old)',
    ]
    
    for pattern in age_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            age_val = int(match.group(1))
            # Sanity check: age should be between 18 and 100
            if 18 <= age_val <= 100:
                extracted["age"] = age_val
                break
    
    # ---- CREDIT SCORE ----
    # Patterns: "credit score 750", "CIBIL 680", "score of 720"
    credit_patterns = [
        r'(?:credit\s*score|cibil|cibil\s*score|score)[\s:]*(?:is\s+)?(\d{3})',
        r'(\d{3})\s*(?:credit\s*score|cibil)',
    ]
    
    for pattern in credit_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            score = int(match.group(1))
            # Sanity check: credit score should be between 300 and 900
            if 300 <= score <= 900:
                extracted["credit_score"] = score
                break
    
    # ---- INTEREST RATE ----
    # Patterns: "12%", "10.5% interest", "rate of 11", "interest rate 9.5"
    interest_patterns = [
        r'(?:interest\s*rate|rate|roi|interest)[\s:]*(?:of\s+)?(\d+(?:\.\d+)?)\s*%?',
        r'(\d+(?:\.\d+)?)\s*%\s*(?:interest|rate|roi)?',
        r'@\s*(\d+(?:\.\d+)?)\s*%?',
    ]
    
    for pattern in interest_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            rate = float(match.group(1))
            # Sanity check: interest rate should be between 1 and 30
            if 1 <= rate <= 30:
                extracted["interest_rate"] = rate
                break
    
    # Clean up: remove None values and annual income (already converted)
    del extracted["income_annual"]
    
    return {k: v for k, v in extracted.items() if v is not None}


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
    except Exception as e:
        logger.warning(f"Intent classification failed: {e}, defaulting to policy_question")
        # Default to policy_question if classification fails (safer than assuming loan application)
        return "policy_question"


def process(user_message: str, current_state: dict) -> dict:
    """
    INTAKE AGENT WITH INTENT-BASED ROUTING
    --------------------------------------
    1. FIRST: Extracts values using reliable regex patterns
    2. THEN: Classifies the user's intent
    3. FINALLY: Routes to appropriate flow
    
    This two-stage approach ensures:
    - Numeric values (loan amount, income, tenure) are reliably extracted
    - Tenure in years is auto-converted to months
    - Annual income is auto-converted to monthly income
    - Indian number formats (lakhs, crores) are properly parsed
    """
    
    # Step 1: PRE-LLM EXTRACTION using regex (reliable)
    regex_extracted = _extract_values_regex(user_message)
    logger.info(f"Regex extraction result: {regex_extracted}")
    
    # Step 2: Classify the intent
    intent = classify_intent(user_message)
    logger.info(f"Intent classified as: {intent}")
    
    # Step 3: Merge regex-extracted values with current state
    # New values from regex override old values
    merged_state = {
        "loan_amount": regex_extracted.get("loan_amount") or current_state.get("loan_amount"),
        "income_monthly": regex_extracted.get("income_monthly") or current_state.get("income_monthly"),
        "tenure_months": regex_extracted.get("tenure_months") or current_state.get("tenure_months"),
        "age": regex_extracted.get("age") or current_state.get("age"),
        "credit_score": regex_extracted.get("credit_score") or current_state.get("credit_score"),
        "interest_rate": regex_extracted.get("interest_rate") or current_state.get("interest_rate") or 12.5,
    }
    
    # Step 4: For policy questions, general queries - skip data collection
    if intent in ["policy_question", "general"]:
        return {
            "intent": intent,
            **merged_state,
            "missing_fields": [],  # No fields required for policy questions
            "route_to": "rag" if intent == "policy_question" else "general"
        }
    
    # Step 5: For calculations - return merged state with tool routing
    if intent == "calculation":
        # Check what's still missing for calculation
        missing = []
        if not merged_state.get("loan_amount"):
            missing.append("loan_amount")
        if not merged_state.get("tenure_months"):
            missing.append("tenure (in years or months)")
        
        return {
            "intent": intent,
            **merged_state,
            "missing_fields": missing,
            "route_to": "tools" if not missing else "need_info"
        }
    
    # Step 6: For loan applications - check what fields are still needed
    required_fields = ["loan_amount", "income_monthly", "tenure_months", "age"]
    missing_fields = []
    
    for field in required_fields:
        if not merged_state.get(field):
            # Use friendly names for missing fields
            friendly_names = {
                "loan_amount": "loan amount",
                "income_monthly": "monthly income/salary",
                "tenure_months": "loan tenure (in years or months)",
                "age": "your age"
            }
            missing_fields.append(friendly_names.get(field, field))
    
    return {
        "intent": "loan_application",
        **merged_state,
        "missing_fields": missing_fields,
        "route_to": "loan_flow" if not missing_fields else "need_info"
    }


# ============================================================
#  SECTION 2 — DEMO / TEST
# ============================================================

if __name__ == "__main__":
    test_cases = [
        "I want a loan of 10 lakhs for 5 years",
        "My salary is 50000 per month",
        "I earn 6 lakh per annum",
        "Calculate EMI for 20L at 12% for 3 years",
        "I am 35 years old with credit score 750",
        "Need 1 crore loan, tenure 20 yrs, I earn 1.5L monthly",
        "What is the interest rate for home loan?",
        "loan amount 15 lacs, tenure 10 years, monthly salary 80k",
    ]
    
    print("=" * 70)
    print("  INTAKE AGENT - VALUE EXTRACTION TEST")
    print("=" * 70)
    
    for test in test_cases:
        result = _extract_values_regex(test)
        print(f"\nInput: {test}")
        print(f"Extracted: {result}")
        print("-" * 70)
