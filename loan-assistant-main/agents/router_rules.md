# Router Rules - Loan Assistant

## When to Ask Missing Info (NEED_MORE_INFO)
- If any of these are missing:
  - income_monthly
  - loan_amount
  - tenure_months
  - credit_score
  - existing_emi

Example:
User: "I want a loan"
→ Ask for missing details

---

## When to Call RAG
- If user asks about:
  - policy
  - rules
  - eligibility criteria
  - documents

Example:
User: "What is minimum credit score?"
→ Call RAG

---

## When to Call Tools
- When all required fields are available
- Perform EMI calculation
- Perform risk analysis

Example:
User provides all details
→ Call tools → decision agent