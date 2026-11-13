import re
from datetime import date
try:
    from .normalizer import normalize_hindi_numbers
    from .dates import resolve_relative_date
except (ImportError, ValueError):
    from normalizer import normalize_hindi_numbers
    from dates import resolve_relative_date

def extract_customer_name(transcript: str):
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    text = normalize_hindi_numbers(transcript.strip())
    match = re.search(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)", text)
    return _name(text, match)


def parse_transcript(transcript: str):
    """Local rule parser; returns query/entry intent or one clarification."""
    if not isinstance(transcript, str) or not transcript.strip():
        return [{"clarification": "Kripya apni baat dobara batayein."}]
    text = normalize_hindi_numbers(transcript.strip())
    low = text.lower()
    if any(w in low for w in ("kitna", "kitne", "kitni", "baaki", "baki", "total", "hisab", "hisaab", "balance", "owe", "owes", "owed", "how much", "कितना", "कितने", "कितनी", "बाकी", "कुल", "हिसाब")):
        relative_day = next((word for word in ("aaj", "kal", "parso", "आज", "कल", "परसों") if word in low), None)
        daily_credit_query = relative_day is not None and any(word in low for word in ("udhaar", "udhar", "credit", "gaya", "gayi", "diya", "उधार", "गया"))
        return [{"type": "query", "customer_name": None if daily_credit_query else _name(text),
                 "metric": "daily_credit" if daily_credit_query else "customer_balance",
                 "query_date": resolve_relative_date(relative_day) if daily_credit_query else None,
                 "date": date.today().isoformat(), "confidence": 0.9}]
    match = re.search(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)", text)
    if not match:
        return [{"clarification": "Rakam samajh nahi aayi. Kripya rakam dobara batayein."}]
    amount = float(match.group(1))
    name = _name(text, match)
    if not name:
        return [{"clarification": "Kis customer ke liye entry karni hai?"}]
    if any(w in low for w in ("nahi", "nahin", "galat", "correction")):
        return [{"clarification": "Correction ke liye event ID batayein."}]
    explicit_payment = any(w in low for w in ("jama", "aaya", "paid", "payment", "received", "repaid", "mila", "wapas", "lota", "lauta", "lautaya", "lautaye", "returned", "return", "जमा", "आया", "वापस", "लौटाया"))
    credit_cue = any(w in low for w in ("udhaar", "udhar", "liya", "liye", "borrowed", "loan", "baaki", "baki", "उधार", "लिया", "बाकी"))
    payment_verb = any(w in low for w in ("diya", "diye", "di", "gave", "lota", "lauta", "lautaya", "lautaye", "wapas", "दिया", "दिए"))
    if explicit_payment or (" se " in f" {low} " and any(w in low for w in ("liya", "liye"))) or " से " in f" {low} ":
        kind = "payment"
    elif payment_verb and "ko" not in low.split() and "को" not in low.split():
        kind = "payment"
    elif credit_cue or (payment_verb and ("ko" in low.split() or "को" in low.split())):
        kind = "credit"
    else:
        return [{
            "clarification": "Yeh udhaar tha ya payment? Kripya batayein.",
            "draft": {
                "customer_name": name,
                "amount": amount,
                "date": date.today().isoformat(),
                "confidence": 0.86,
            },
        }]
    day = "parso" if "parso" in low or "परसों" in low else "kal" if "kal" in low or "कल" in low else "aaj"
    return [{"type": kind, "customer_name": name, "amount": amount,
             "date": resolve_relative_date(day), "confidence": 0.86}]

STOP_WORDS_HINDI = {"उधार", "जमा", "रुपये", "रुपया", "पैसे", "का", "की", "के", "ने", "को", "से", "है", "था", "थी", "थे", "दिया", "दिए", "लिया", "लिए", "कुल", "हिसाब", "कितना", "बाकी", "दिला", "मिला", "वापस", "चुकता", "खाता"}


def _name(text, amount_match=None):
    if amount_match:
        text = text[:amount_match.start()] + " " + text[amount_match.end():]
    text = re.sub(r"(?i)\b(udhaa?r|liya|liye|kiya|kiye|borrowed|loan|baaki|diya|diye|di|jama|aaya|abhi|just|usne|pura|poora|chuka|chukaya|chukadiya|paid|payment|received|repaid|gave|mila|returned|return|wapas|lota|lauta|lautaya|lautaye|rupees?|rupiya|rupaye|paise|rs|kal|parso|aaj|ka|ki|ke|ne|ko|se|hai|hain|tha|the|total|hisab|hisaab|kitna|kitne|kitni|baki|balance|owe|owes|owed|how|much|what|is|does|customer|make|it|to|the|not|wrong|error|mistake|actually|should|be|change|correct|batayiye|bataiye|bataye|batana|batado|batao|dikhaye|dikhaiye|please|zara|kripya)\b", " ", text)
    tokens = [t.strip("।,!? \t") for t in text.split()]
    words = [t for t in tokens if t and t not in STOP_WORDS_HINDI and not re.match(r"^\d+(?:\.\d+)?$", t)]
    if not words:
        return None
    return " ".join(w.capitalize() if re.match(r"^[A-Za-z]+$", w) else w for w in words)
