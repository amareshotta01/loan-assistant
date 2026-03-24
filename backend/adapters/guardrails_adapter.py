def moderate_input(text: str) -> dict:
    # TODO: Member 4 integrates text moderation here
    return {"action": "ALLOW", "categories": [], "redacted_text": text}

def moderate_output(text: str) -> dict:
    # TODO: Member 4 integrates output checking here
    return {"action": "ALLOW", "categories": [], "safe_text": text}