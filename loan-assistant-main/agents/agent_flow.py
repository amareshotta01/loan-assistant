import re

# -------------------------------
# 1. Intake Agent
# -------------------------------
def intake_agent(user_input, state):
    text = user_input.lower()

    numbers = re.findall(r'\d+', text)

    if "lakh" in text and numbers:
        state["loan_amount"] = int(numbers[0]) * 100000

    if ("salary" in text or "income" in text or "earn" in text) and numbers:
        state["income_monthly"] = int(numbers[0])

    if "year" in text and numbers:
        state["tenure_months"] = int(numbers[-1]) * 12

    if "credit" in text and numbers:
        state["credit_score"] = int(numbers[-1])

    if "emi" in text and numbers:
        state["existing_emi"] = int(numbers[-1])

    return state


# -------------------------------
# 2. Router Agent
# -------------------------------
def router_agent(state, user_input):
    missing = [k for k, v in state.items() if v is None]

    if missing:
        return "NEED_MORE_INFO", missing
    
    elif "policy" in user_input.lower() or "rule" in user_input.lower():
        return "RAG", None
    
    else:
        return "TOOLS", None


# -------------------------------
# 3. EMI Calculator
# -------------------------------
def emi_calculator(state):
    P = state["loan_amount"]
    r = 0.1 / 12
    t = state["tenure_months"]

    emi = (P * r * (1 + r)**t) / ((1 + r)**t - 1)

    income = state["income_monthly"]
    existing = state.get("existing_emi", 0) or 0

    total_emi = emi + existing
    burden = (total_emi / income) * 100

    if burden < 30:
        risk = "LOW"
    elif burden < 50:
        risk = "MEDIUM"
    else:
        risk = "HIGH"

    return {
        "emi": round(emi, 2),
        "emi_burden_pct": round(burden, 2),
        "risk_band": risk
    }


# -------------------------------
# 4. Decision Agent
# -------------------------------
def decision_agent(state, tool_result):
    income = state["income_monthly"]
    credit = state["credit_score"]
    risk = tool_result["risk_band"]

    reasons = []

    if income > 30000:
        reasons.append("Stable income")
    else:
        reasons.append("Low income")

    if credit and credit >= 650:
        reasons.append("Good credit score")
    else:
        reasons.append("Poor credit score")

    if risk == "LOW":
        reasons.append("Low EMI burden")
    else:
        reasons.append("High EMI burden")

    if income > 30000 and credit >= 650 and risk == "LOW":
        status = "APPROVE"
        confidence = 0.9
    elif risk == "HIGH":
        status = "REJECT"
        confidence = 0.85
    else:
        status = "MANUAL_REVIEW"
        confidence = 0.6

    return {
        "status": status,
        "reasoning": reasons,
        "confidence": confidence
    }


# -------------------------------
# 5. RAG Agent
# -------------------------------
def rag_agent(query):
    return "Based on policy (Section 3.1), minimum credit score required is 650."


# -------------------------------
# 6. Main Flow
# -------------------------------
def run_agent_flow(user_input):
    state = {
        "income_monthly": None,
        "loan_amount": None,
        "tenure_months": None,
        "credit_score": None,
        "existing_emi": None
    }

    print("User:", user_input)

    state = intake_agent(user_input, state)
    route, data = router_agent(state, user_input)

    if route == "NEED_MORE_INFO":
        return f"I still need: {', '.join(data)}"

    elif route == "RAG":
        return rag_agent(user_input)

    elif route == "TOOLS":
        tool_result = emi_calculator(state)
        decision = decision_agent(state, tool_result)

        return {
            "decision": decision,
            "tool_results": tool_result,
            "collected_inputs": state
        }


# -------------------------------
# 7. Run Script
# -------------------------------
if __name__ == "__main__":
    output = run_agent_flow(
        "I earn 50000 salary, want 5 lakh loan for 2 years, credit score 720"
    )
    print(output)