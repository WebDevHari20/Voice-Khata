import re

PHRASES = {"teen sau chaalis": "340", "dhai sau": "250", "sawa sau": "125", "paune do sau": "175", "derh sau": "150"}

def normalize_hindi_numbers(text: str) -> str:
    result = text.lower()
    for phrase, value in sorted(PHRASES.items(), key=lambda pair: -len(pair[0])):
        result = re.sub(rf"\b{re.escape(phrase)}\b", value, result)
    return result
