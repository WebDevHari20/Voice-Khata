import re
from datetime import date
from .normalizer import normalize_hindi_numbers
from .dates import resolve_relative_date

def parse_transcript(transcript: str):
    """Local rule parser; returns query/entry intent or one clarification."""
    if not isinstance(transcript, str) or not transcript.strip():
        return [{"clarification": "Kripya apni baat dobara batayein."}]
    text = normalize_hindi_numbers(transcript.strip())
    low = text.lower()
    if any(w in low for w in ("kitna baki", "kitna baaki", "total", "hisab", "balance")):
        return [{"type": "query", "customer_name": _name(text), "date": date.today().isoformat(), "confidence": 0.9}]
    match = re.search(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)", text)
    if not match:
        return [{"clarification": "Rakam samajh nahi aayi. Kripya rakam dobara batayein."}]
    name = _name(text, match)
    if not name:
        return [{"clarification": "Kis customer ke liye entry karni hai?"}]
    if any(w in low for w in ("nahi", "galat", "correction")):
        return [{"clarification": "Correction ke liye event ID batayein."}]
    kind = "payment" if any(w in low for w in ("diya", "jama", "aaya", "paid", "payment")) else "credit"
    day = "parso" if "parso" in low else "kal" if "kal" in low else "aaj"
    return [{"type": kind, "customer_name": name, "amount": float(match.group(1)),
             "date": resolve_relative_date(day), "confidence": 0.86}]

def _name(text, amount_match=None):
    if amount_match:
        text = text[:amount_match.start()] + " " + text[amount_match.end():]
    text = re.sub(r"(?i)\b(udhaar|liya|baaki|diya|jama|aaya|paid|payment|rupees?|rupaye|rs|kal|parso|aaj|ka|ki|ke|ne|ko|hai|tha|total|hisab|kitna|baki|balance)\b", " ", text)
    words = re.findall(r"[A-Za-z]+", text)
    return " ".join(word.capitalize() for word in words) or None
