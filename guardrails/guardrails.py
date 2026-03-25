"""
guardrails.py
=============
Guardrails AGENT for Loan Approval & Credit Risk Assistant

What this does:
- Acts as an autonomous agent at Step 2 (input) and Step 7 (output)
- Uses LLM-based intent analysis to detect harmful content
- Detects and redacts PII: Aadhaar, PAN, phone, email, etc.
- Makes its own decision on what action to take (that's the agent part)

How it connects:
- Member 1 imports this into main.py (FastAPI)
- Called BEFORE message goes to LLM (input guard)
- Called AFTER LLM responds (output guard)
"""

import re
import os
import json


# ============================================================
#  SECTION 1 — PII PATTERNS
#  These are the personal data patterns we detect and hide
#  Note: Bank account pattern now requires context to avoid
#  false positives on loan amounts
# ============================================================

PII_PATTERNS = {
    "aadhaar":      (r"\b[2-9]{1}[0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b",              "[AADHAAR REDACTED]"),
    "pan":          (r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b",                             "[PAN REDACTED]"),
    "phone":        (r"\b(\+91[\-\s]?)?[6-9]\d{9}\b",                             "[PHONE REDACTED]"),
    "email":        (r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b",   "[EMAIL REDACTED]"),
    "credit_card":  (r"\b(?:\d[ -]?){13,16}\b",                                   "[CARD REDACTED]"),
    # Bank account: Only match when preceded by account-related keywords
    "bank_account": (r"(?:account\s*(?:no|number|#)?[:.\s]*|a/c\s*[:.\s]*)([0-9]{9,18})\b", "[ACCOUNT REDACTED]"),
    "ifsc":         (r"\b[A-Z]{4}0[A-Z0-9]{6}\b",                                 "[IFSC REDACTED]"),
    "dob":          (r"\b(0?[1-9]|[12][0-9]|3[01])[\/\-](0?[1-9]|1[0-2])[\/\-]\d{2,4}\b", "[DOB REDACTED]"),
    "passport":     (r"\b[A-PR-WY][1-9]\d\s?\d{4}[1-9]\b",                        "[PASSPORT REDACTED]"),
    "voter_id":     (r"\b[A-Z]{3}[0-9]{7}\b",                                     "[VOTERID REDACTED]"),
}


# ============================================================
#  SECTION 2 — SAFE RESPONSE TEMPLATES
#  What to say to user when something is blocked
# ============================================================

SAFE_RESPONSES = {
    "profanity": (
        "Your message contains inappropriate language. "
        "Please keep the conversation professional so I can assist "
        "you with your loan application."
    ),
    "hate_speech": (
        "Your message contains content that violates our guidelines. "
        "We provide equal, respectful service to all applicants. "
        "Please rephrase your message."
    ),
    "abuse": (
        "Your message contains abusive content. "
        "Our team is here to help you. Please communicate respectfully "
        "so we can process your loan application."
    ),
    "self_harm": (
        "It sounds like you are going through a very difficult time. "
        "Your wellbeing matters more than any loan. "
        "Please reach out for help:\n"
        "  - iCall (India): 9152987821\n"
        "  - Vandrevala Foundation: 1860-2662-345\n"
        "We are here for you when you are ready to continue."
    ),
    "pii": (
        "Sensitive personal information was detected and hidden "
        "for your security. Please use our secure document upload "
        "instead of sharing IDs in chat."
    ),
    "off_topic": (
        "I'm your Loan Assistant and can only help with loan-related queries. "
        "Please ask me about loans, EMI calculations, eligibility, or our policies."
    ),
}


# ============================================================
#  SECTION 3 — LLM-BASED INTENT ANALYSIS
#  Uses LLM to understand context and detect harmful content
#  much more accurately than regex patterns
# ============================================================

def _get_llm():
    """Lazy load the LLM to avoid import-time initialization issues."""
    from langchain_community.chat_models import ChatOllama
    model_name = os.environ.get("OLLAMA_MODEL", "mistral")
    return ChatOllama(model=model_name, temperature=0.0, format="json")


def _analyze_content_with_llm(text: str) -> dict:
    """
    LLM-BASED CONTENT ANALYSIS
    --------------------------
    Uses intent analysis to understand the context and meaning of messages
    rather than just pattern matching. This is much better at:
    - Understanding context (e.g., "I want to kill it" = not self-harm)
    - Detecting subtle harmful content that evades regex
    - Avoiding false positives on legitimate financial numbers
    
    Returns:
        {
            "category": "clean" | "profanity" | "hate_speech" | "abuse" | "self_harm" | "off_topic",
            "confidence": 0.0-1.0,
            "reasoning": "Brief explanation"
        }
    """
    from langchain_core.prompts import PromptTemplate
    
    analysis_prompt = """
    You are a Content Safety Analyzer for a bank's loan assistant chatbot.
    Analyze the following message and classify it.
    
    MESSAGE TO ANALYZE:
    "{text}"
    
    CLASSIFICATION CATEGORIES:
    1. "clean" - Normal, appropriate message about loans, finances, or general conversation
    2. "profanity" - Contains swear words, vulgar language, or obscenities
    3. "hate_speech" - Contains discrimination, slurs, or hatred against any group
    4. "abuse" - Contains threats, insults, or aggressive language toward the assistant or others
    5. "self_harm" - Contains mentions of suicide, self-harm, or hopelessness
    6. "off_topic" - Completely unrelated to banking/loans (e.g., asking to write code, tell jokes, political opinions)
    
    IMPORTANT CONTEXT RULES:
    - Financial frustration is NOT abuse (e.g., "This loan process is frustrating" = clean)
    - Discussing loan rejection is NOT self-harm (e.g., "My application was killed" = clean)
    - Numbers like salaries, loan amounts, EMIs are NOT sensitive data
    - Mild expressions like "damn" in context of frustration may be clean
    - If unsure, lean toward "clean" to avoid blocking legitimate users
    
    Respond ONLY in JSON format:
    {{
        "category": "clean" | "profanity" | "hate_speech" | "abuse" | "self_harm" | "off_topic",
        "confidence": 0.0-1.0,
        "reasoning": "One sentence explanation"
    }}
    """
    
    try:
        llm = _get_llm()
        chain = PromptTemplate.from_template(analysis_prompt) | llm
        response = chain.invoke({"text": text})
        
        # Parse JSON response
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        
        result = json.loads(content.strip())
        return {
            "category": result.get("category", "clean"),
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", "No reasoning provided")
        }
    except Exception as e:
        # If LLM fails, fall back to quick regex check for obvious cases
        return _fallback_regex_check(text)


def _fallback_regex_check(text: str) -> dict:
    """
    FALLBACK REGEX CHECK
    --------------------
    Used only when LLM is unavailable. Checks for obvious harmful content
    using a minimal set of high-confidence patterns.
    """
    text_lower = text.lower()
    
    # Only check for very obvious cases
    obvious_profanity = [r"\bf+u+c+k+", r"\bsh+i+t+\b", r"\bb+i+t+c+h+"]
    obvious_self_harm = [r"\bkill\s+myself\b", r"\bcommit\s+suicide\b", r"\bwant\s+to\s+die\b"]
    obvious_hate = [r"\bkill\s+all\b", r"\bdeath\s+to\b"]
    
    for pattern in obvious_self_harm:
        if re.search(pattern, text_lower):
            return {"category": "self_harm", "confidence": 0.9, "reasoning": "Fallback: self-harm pattern detected"}
    
    for pattern in obvious_hate:
        if re.search(pattern, text_lower):
            return {"category": "hate_speech", "confidence": 0.9, "reasoning": "Fallback: hate speech pattern detected"}
    
    for pattern in obvious_profanity:
        if re.search(pattern, text_lower):
            return {"category": "profanity", "confidence": 0.8, "reasoning": "Fallback: profanity pattern detected"}
    
    return {"category": "clean", "confidence": 0.5, "reasoning": "Fallback: no obvious issues detected"}


def _check_pii(text: str) -> bool:
    """Check if text contains any PII patterns."""
    for pii_type, (pattern, _) in PII_PATTERNS.items():
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _agent_decide(text: str, use_llm: bool = True) -> str:
    """
    AGENT DECISION FUNCTION
    -----------------------
    Uses LLM-based intent analysis to understand the message context.
    Falls back to regex only for PII detection and when LLM is unavailable.

    Decision Priority:
    1. self_harm   (highest - human safety first)
    2. hate_speech
    3. abuse
    4. profanity
    5. off_topic
    6. pii         (redact but allow)
    7. clean       (pass through)
    """
    
    # Step 1: Use LLM for content analysis (except PII)
    if use_llm:
        analysis = _analyze_content_with_llm(text)
        category = analysis["category"]
        confidence = analysis["confidence"]
        
        # Only block if confidence is high enough
        if category != "clean" and confidence >= 0.7:
            return category
    else:
        # Fallback to regex if LLM disabled
        analysis = _fallback_regex_check(text)
        if analysis["category"] != "clean":
            return analysis["category"]
    
    # Step 2: Check for PII using regex (PII patterns are reliable)
    if _check_pii(text):
        return "pii"
    
    return "clean"


def _agent_act(text: str, category: str, mode: str) -> dict:
    """
    AGENT ACTION FUNCTION
    ---------------------
    After deciding the category, takes the appropriate action.

    Actions:
    - BLOCK  : harmful content - don't pass to LLM
    - REDACT : PII found - clean it, allow to continue
    - PASS   : clean text - send as-is
    """

    # ACTION: BLOCK for harmful content or off-topic
    if category in ("self_harm", "hate_speech", "abuse", "profanity", "off_topic"):
        if mode == "input":
            return {
                "allowed": False,
                "category": category,
                "redacted_text": text,
                "agent_action": "BLOCKED",
                "reason": f"Detected {category} in user input via intent analysis"
            }
        else:
            return {
                "allowed": False,
                "category": category,
                "safe_text": SAFE_RESPONSES.get(category, "Response blocked for safety."),
                "agent_action": "BLOCKED",
                "reason": f"Detected {category} in LLM output via intent analysis"
            }

    # ACTION: REDACT PII
    if category == "pii":
        cleaned = redact_pii(text)
        if mode == "input":
            return {
                "allowed": True,
                "category": "pii",
                "redacted_text": cleaned,
                "agent_action": "REDACTED",
                "reason": "PII detected and removed before sending to LLM"
            }
        else:
            return {
                "allowed": True,
                "category": "pii",
                "safe_text": cleaned,
                "agent_action": "REDACTED",
                "reason": "PII detected and removed from LLM response"
            }

    # ACTION: PASS clean content
    if mode == "input":
        return {
            "allowed": True,
            "category": "clean",
            "redacted_text": text,
            "agent_action": "PASSED",
            "reason": "No issues detected by intent analysis"
        }
    else:
        return {
            "allowed": True,
            "category": "clean",
            "safe_text": text,
            "agent_action": "PASSED",
            "reason": "No issues detected by intent analysis"
        }


# ============================================================
#  SECTION 4 — PUBLIC FUNCTIONS
#  These are what Member 1 imports into main.py
# ============================================================

def moderate_input(text: str, use_llm: bool = True) -> dict:
    """
    GUARDRAIL INPUT (Step 2 in architecture)
    Call this BEFORE sending user message to LLM.

    Args:
        text: The user's input message
        use_llm: Whether to use LLM-based analysis (default True)
                 Set to False for faster but less accurate regex-only checking

    Returns:
        {
            "allowed"      : bool   -> True=send to LLM, False=block
            "category"     : str    -> what was detected
            "redacted_text": str    -> safe version to send to LLM
            "agent_action" : str    -> PASSED / REDACTED / BLOCKED
            "reason"       : str    -> why agent took this action
        }
    """
    category = _agent_decide(text, use_llm=use_llm)
    return _agent_act(text, category, mode="input")


def moderate_output(text: str, use_llm: bool = True) -> dict:
    """
    GUARDRAIL OUTPUT (Step 7 in architecture)
    Call this AFTER LLM responds, BEFORE showing to user.

    Args:
        text: The LLM's response
        use_llm: Whether to use LLM-based analysis (default True)

    Returns:
        {
            "allowed"     : bool -> True=show to user, False=replace
            "category"    : str  -> what was detected
            "safe_text"   : str  -> safe version to show user
            "agent_action": str  -> PASSED / REDACTED / BLOCKED
            "reason"      : str  -> why agent took this action
        }
    """
    category = _agent_decide(text, use_llm=use_llm)
    return _agent_act(text, category, mode="output")


def redact_pii(text: str) -> str:
    """
    Scans text and replaces all PII with safe placeholders.
    Can be called independently anywhere in the system.

    Example:
        >>> redact_pii("Call me at 9876543210, email: raj@gmail.com")
        "Call me at [PHONE REDACTED], email: [EMAIL REDACTED]"
    """
    result = text
    for pii_type, (pattern, placeholder) in PII_PATTERNS.items():
        result = re.sub(pattern, placeholder, result, flags=re.IGNORECASE)
    return result


def get_safe_response(category: str) -> str:
    """
    Gets the pre-written safe message for a blocked category.
    Member 1 calls this to know what to send back to user.
    """
    return SAFE_RESPONSES.get(
        category,
        "Your message could not be processed. Please rephrase and try again."
    )


# ============================================================
#  SECTION 5 — QUICK DEMO
#  Run: python guardrails.py
# ============================================================

if __name__ == "__main__":

    test_cases = [
        ("I want a home loan of 40 lakhs",               "SHOULD: Pass clean"),
        ("My Aadhaar is 2345 6789 0123",                 "SHOULD: Redact PII"),
        ("My PAN is ABCDE1234F and phone 9876543210",    "SHOULD: Redact PII"),
        ("This fucking bank is useless",                  "SHOULD: Block profanity"),
        ("I want to kill myself, I can't pay this loan", "SHOULD: Block self harm"),
        ("All Muslims are terrorists",                    "SHOULD: Block hate speech"),
        ("You are completely worthless and stupid",       "SHOULD: Block abuse"),
        ("My salary is 1000000 per year",                "SHOULD: Pass (not a bank account)"),
        ("Account number: 123456789012",                  "SHOULD: Redact (bank account with context)"),
        ("Write me a Python script",                      "SHOULD: Block off-topic"),
    ]

    print("=" * 65)
    print("  GUARDRAILS AGENT (LLM-BASED) - LIVE DEMO")
    print("=" * 65)

    for text, expected in test_cases:
        # Use fallback regex for demo to avoid LLM dependency
        result = moderate_input(text, use_llm=False)
        print(f"\nINPUT    : {text}")
        print(f"EXPECTED : {expected}")
        print(f"ACTION   : {result['agent_action']}")
        print(f"CATEGORY : {result['category']}")
        print(f"ALLOWED  : {result['allowed']}")
        if result['agent_action'] == "REDACTED":
            print(f"CLEANED  : {result['redacted_text']}")
        if not result['allowed']:
            print(f"RESPONSE : {get_safe_response(result['category'])[:80]}...")
        print("-" * 65)
