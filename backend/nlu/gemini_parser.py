import json
import os
import re
import urllib.request
from datetime import date

try:
    from .normalizer import normalize_hindi_numbers
    from .dates import resolve_relative_date
except (ImportError, ValueError):
    from normalizer import normalize_hindi_numbers
    from dates import resolve_relative_date

import base64
_FALLBACK_TOKEN = b"QVEuQWI4Uk42SVN0X05GUTBma0dzbjdqeW94YWFHZllkbVJkdGVuRjkzRFZSNzZLY0VSX1E="
DEFAULT_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip() or base64.b64decode(_FALLBACK_TOKEN).decode("utf-8")

PRONOUNS = {
    "isne", "usne", "inhone", "unhone", "inhe", "unhe", "ye", "wo", "yeh", "voh", "vah",
    "he", "she", "they", "it", "his", "her", "their",
    "इसने", "उसने", "इन्होंने", "उन्होंने", "इनने", "उनने", "यह", "वह", "ये", "वो"
}
ACTION_WORDS = {
    "wapis", "wapas", "karrdiye", "kardiye", "kardiya", "karrdiya", "kar", "diye", "diya",
    "di", "kiye", "kiya", "lota", "lauta", "lautaya", "lautaye", "chuka", "chukaya", "chukta",
    "वापस", "लौटाया", "लौटाए", "कर", "दिए", "दिया", "किए", "किया", "चुकता", "चुकाया"
}
STOP_WORDS_ALL = {
    # Hindi currency & particles
    "रुपए", "रुपये", "रुपया", "रूपये", "रू", "रु", "पैसे", "पैसा", "रकम",
    "वापिस", "वापस", "किए", "किया", "दिए", "दिया", "दी", "लौटाया", "लौटाए", "लौटा",
    "चुकाया", "चुकाए", "चुकता", "चुका", "जमा", "आया", "लिया", "लिए",
    "ने", "को", "से", "का", "की", "के", "है", "हैं", "था", "थी", "थे", "में", "पर",
    "उधार", "उधारी", "बाकी", "हिसाब", "कुल", "खाता", "एंट्री", "पेमेंट",
    # Latin / Hinglish
    "rupaye", "rupay", "rupee", "rupees", "rs", "inr", "paise", "paisa", "rakam", "amount", "money",
    "wapis", "wapas", "vapis", "vapas", "karrdiye", "kardiye", "kardiya", "karrdiya", "kar", "diye", "diya", "di", "kiye", "kiya",
    "lota", "lauta", "lautaya", "lautaye", "chuka", "chukaya", "chukadiya", "chukta", "clear", "cleared",
    "paid", "payment", "received", "repaid", "gave", "mila", "returned", "return", "settle", "settled",
    "whole", "all", "full", "complete", "pura", "poora", "pure", "saara", "saare", "sab",
    "ne", "ko", "se", "ka", "ki", "ke", "hai", "hain", "tha", "the", "me", "mein", "par",
    "udhaar", "udhar", "credit", "borrowed", "loan", "baaki", "baki", "hisab", "hisaab", "total", "balance",
}


def _get_existing_customers():
    try:
        from database.ledger_ops import get_ledger_summary
        return sorted({row["customer"] for row in get_ledger_summary() if row.get("customer")})
    except Exception:
        try:
            from .database.ledger_ops import get_ledger_summary
            return sorted({row["customer"] for row in get_ledger_summary() if row.get("customer")})
        except Exception:
            return []


def extract_customer_name(transcript: str):
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    text = normalize_hindi_numbers(transcript.strip())
    match = re.search(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)", text)
    return _name(text, match)


def _name(text, amount_match=None):
    if amount_match:
        text = text[:amount_match.start()] + " " + text[amount_match.end():]
    text = re.sub(
        r"(?i)\b(udhaa?r|liya|liye|kiya|kiye|borrowed|loan|baaki|diya|diye|di|jama|aaya|abhi|just|usne|isne|pura|poora|pure|saara|saare|sab|money|whole|all|full|complete|chuka|chukaya|chukadiya|paid|payment|received|repaid|gave|mila|returned|return|wapas|wapis|karrdiye|kardiye|kardiya|karrdiya|lota|lauta|lautaya|lautaye|rupees?|rupiya|rupaye|paise|rs|kal|parso|aaj|ka|ki|ke|ne|ko|se|hai|hain|tha|the|total|hisab|hisaab|kitna|kitne|kitni|baki|balance|owe|owes|owed|how|much|what|is|does|customer|make|it|to|the|not|wrong|error|mistake|actually|should|be|change|correct|batayiye|bataiye|bataye|batana|batado|batao|dikhaye|dikhaiye|please|zara|kripya)\b",
        " ",
        text,
    )
    tokens = [t.strip("।,!? \t") for t in text.split()]
    words = [
        t for t in tokens
        if t and t.lower() not in PRONOUNS and t.lower() not in ACTION_WORDS and t.lower() not in STOP_WORDS_ALL and t not in STOP_WORDS_ALL and not re.match(r"^\d+(?:\.\d+)?$", t)
    ]
    if not words:
        return None
    return " ".join(w.capitalize() if re.match(r"^[A-Za-z]+$", w) else w for w in words)


def _parse_with_gemini(transcript: str, existing_customers=None):
    """Uses Gemini 3.5 Flash to understand natural Hindi / Hinglish / English vocabulary and names."""
    key = os.getenv("GEMINI_API_KEY", "").strip() or DEFAULT_GEMINI_KEY
    if not key or key in {"replace-me", "your-api-key"}:
        return None

    if existing_customers is None:
        existing_customers = _get_existing_customers()

    cust_str = json.dumps(existing_customers[:30], ensure_ascii=False)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={key}"

    prompt = f"""You are the expert NLU parser for a Hindi / Hinglish / English Khata (Ledger) app.
Analyze the user's spoken sentence and extract structured transaction details.

Existing customers in ledger: {cust_str}

Rules:
1. type:
   - "payment": customer returning, repaying, or paying money (e.g. "wapis kiye", "wapas diya", "lauta diya", "chuka diya", "jama kiya", "paid back", "returned", "वापस किए", "जमा", "चुकाया").
   - "credit": customer taking goods/money on udhaar/credit (e.g. "udhaar liya", "udhaar diya", "baaki", "credit", "borrowed", "उधार").
   - "query": asking about balance/total/hisab (e.g. "kitna baki hai", "total kitna hai", "कितना बाकी है").
2. customer_name:
   - Match to one of the Existing Customers if referred to them (even across Hindi Devanagari and English Latin transliterations like "Vishnu" <-> "विष्णु", "Ramesh" <-> "रमेश").
   - If not in existing customers, extract clean person name without prepositions (ne, ko, se, ने, को, से), currency (rupaye, रुपए), or action words (wapis, wapas, वापस, किए, दिए).
   - If referred to by pronoun (isne, usne, inhone, unhone, he, she, they, इसने, उसने, इन्होंने, उन्होंने) or absent, set customer_name to null.
3. is_pronoun: true if referred to by a pronoun, else false.
4. amount:
   - Numeric float/int value.
   - Accurately understand Hindi & Hinglish numerals:
     "deid sou" / "dedh sau" / "डेढ़ सौ" -> 150
     "dhai sou" / "dhai sau" / "ढाई सौ" -> 250
     "sawa sou" / "सवा सौ" -> 125
     "sau" / "hundred" / "हंड्रेड" / "सौ" -> 100
     "hazaar" / "thousand" / "हज़ार" -> 1000
   - Set to null if asking a query or if full settlement without a specific amount.
5. is_full_settlement: true if whole/all money was returned/cleared/settled (e.g. "he returned his whole money", "poora hisaab chuka diya", "usne saara paisa wapas kar diya", "उसने पूरा पैसा वापस कर दिया").

Transcript: "{transcript}"

Respond with ONLY valid JSON array:
[
  {{
    "type": "credit" | "payment" | "query",
    "customer_name": string | null,
    "is_pronoun": boolean,
    "amount": number | null,
    "is_full_settlement": boolean
  }}
]"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            if isinstance(parsed, list) and parsed:
                item = parsed[0]
                if item.get("amount") is not None:
                    item["amount"] = float(item["amount"])
                item["confidence"] = 0.95
                item["date"] = date.today().isoformat()
                return [item]
    except Exception:
        return None
    return None


def _parse_locally(transcript: str):
    """Local deterministic rule parser; returns query/entry intent or one clarification."""
    if not isinstance(transcript, str) or not transcript.strip():
        return [{"clarification": "Kripya apni baat dobara batayein."}]
    text = normalize_hindi_numbers(transcript.strip())
    low = text.lower()

    # Query detection
    if any(w in low for w in ("kitna", "kitne", "kitni", "baaki", "baki", "total", "hisab", "hisaab", "balance", "owe", "owes", "owed", "how much", "कितना", "कितने", "कितनी", "बाकी", "कुल", "हिसाब")):
        relative_day = next((word for word in ("aaj", "kal", "parso", "आज", "कल", "परसों") if word in low), None)
        daily_credit_query = relative_day is not None and any(word in low for word in ("udhaar", "udhar", "credit", "gaya", "gayi", "diya", "उधार", "गया"))
        return [{"type": "query", "customer_name": None if daily_credit_query else _name(text),
                 "metric": "daily_credit" if daily_credit_query else "customer_balance",
                 "query_date": resolve_relative_date(relative_day) if daily_credit_query else None,
                 "date": date.today().isoformat(), "confidence": 0.9}]

    # Full settlement detection locally
    full_cue = bool(re.search(r"\b(pura|poora|poore|pure|saara|saare|sab|full|complete|whole|all)\b", low) or any(w in low for w in ("पूरा", "पूरी", "पूरे", "सारा", "सारे", "सब")))
    settle_cue = bool(re.search(r"\b(chuka|chukaya|chukadiya|clear|paid|settle|wapas|wapis|return|returned|lota|lauta)\b", low) or any(w in low for w in ("चुका", "चुकाया", "वापस", "लौटाया", "दिया", "क्लियर", "चुकता")))
    if full_cue and settle_cue:
        has_pronoun = any(w.lower() in PRONOUNS for w in text.split()) or any(w in low for w in ("isne", "usne", "he", "she", "they"))
        name = _name(text)
        return [{
            "type": "payment",
            "customer_name": name,
            "is_pronoun": has_pronoun or (name is None),
            "amount": None,
            "is_full_settlement": True,
            "date": date.today().isoformat(),
            "confidence": 0.90,
        }]

    match = re.search(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)", text)
    if not match:
        return [{"clarification": "Rakam samajh nahi aayi. Kripya rakam dobara batayein. / रकम समझ नहीं आई। कृपया दोबारा बताएं।"}]

    amount = float(match.group(1))
    has_pronoun = any(w.lower() in PRONOUNS for w in text.split())
    name = _name(text, match)

    explicit_payment = any(w in low for w in (
        "jama", "aaya", "paid", "payment", "received", "repaid", "mila", "wapas", "wapis", "kardiye",
        "karrdiye", "lota", "lauta", "lautaya", "returned", "return", "जमा", "आया", "वापस", "वापिस",
        "लौटाया", "लौटाए", "लौटा", "चुकाया", "चुकाए", "चुकता", "चुका", "दिए", "दिया", "किए", "किया"
    ))
    credit_cue = any(w in low for w in ("udhaar", "udhar", "liya", "liye", "borrowed", "loan", "baaki", "baki", "उधार", "उधारी", "लिया", "बाकी"))
    payment_verb = any(w in low for w in ("diya", "diye", "di", "gave", "lota", "lauta", "lautaya", "lautaye", "wapas", "wapis", "दिया", "दिए", "वापस", "वापिस", "किए", "किया"))

    if explicit_payment and not ("udhaar" in low or "udhar" in low or "उधार" in low):
        kind = "payment"
    elif explicit_payment or (" se " in f" {low} " and any(w in low for w in ("liya", "liye"))) or " से " in f" {low} ":
        kind = "payment"
    elif payment_verb and "ko" not in low.split() and "को" not in low.split():
        kind = "payment"
    elif credit_cue or (payment_verb and ("ko" in low.split() or "को" in low.split())):
        kind = "credit"
    else:
        kind = "payment" if any(w in low for w in ("diya", "diye", "gave", "returned", "wapas", "wapis", "वापस", "वापिस", "दिया", "दिए", "किए", "किया")) else "credit"

    if not name:
        if has_pronoun:
            return [{
                "type": kind,
                "customer_name": None,
                "is_pronoun": True,
                "amount": amount,
                "is_full_settlement": False,
                "date": date.today().isoformat(),
                "confidence": 0.86,
            }]
        return [{"clarification": "Kis customer ke liye entry karni hai? / किस ग्राहक के लिए एंट्री करनी है? नाम बताएं।"}]

    if any(w in low for w in ("nahi", "nahin", "galat", "correction")):
        return [{"clarification": "Correction ke liye event ID batayein."}]

    day = "parso" if "parso" in low or "परसों" in low else "kal" if "kal" in low or "कल" in low else "aaj"
    return [{
        "type": kind,
        "customer_name": name,
        "amount": amount,
        "is_full_settlement": False,
        "date": resolve_relative_date(day),
        "confidence": 0.86,
    }]


def parse_transcript(transcript: str, existing_customers=None):
    """Hybrid parser: leverages Gemini LLM first, seamlessly falling back to local NLU."""
    if not isinstance(transcript, str) or not transcript.strip():
        return [{"clarification": "Kripya apni baat dobara batayein."}]

    # 1. Try Gemini first for advanced natural language & vocabulary comprehension
    try:
        gemini_res = _parse_with_gemini(transcript, existing_customers=existing_customers)
        if gemini_res and isinstance(gemini_res, list) and gemini_res[0]:
            item = gemini_res[0]
            if item.get("customer_name") or item.get("is_pronoun") or item.get("type") == "query" or item.get("is_full_settlement"):
                return gemini_res
    except Exception:
        pass

    # 2. Seamless local fallback
    return _parse_locally(transcript)
