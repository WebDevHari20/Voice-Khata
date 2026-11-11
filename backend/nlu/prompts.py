LLM_FALLBACK_PROMPT = """
Extract ledger events from the following transcript. 
Strict JSON schema only:
[
  {
    "type": "credit | payment | correction | query | undo",
    "customer_name": "string",
    "amount": number,
    "date": "YYYY-MM-DD",
    "confidence": number
  }
]
Transcript: {transcript}
"""
