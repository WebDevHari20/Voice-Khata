from datetime import date, timedelta

def resolve_relative_date(word: str, today: date | None = None) -> str:
    today = today or date.today()
    value = word.lower().strip()
    if value == "kal": return (today - timedelta(days=1)).isoformat()
    if value == "parso": return (today - timedelta(days=2)).isoformat()
    return today.isoformat()
