import json
import os
import sqlite3
import uuid
from datetime import date
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "ledger.db"
db_env = os.getenv("DATABASE_PATH")
if db_env:
    cand = Path(db_env)
    if cand.is_absolute():
        DB_PATH = cand
    elif (Path.cwd() / cand).parent.exists():
        DB_PATH = (Path.cwd() / cand).resolve()
    elif (Path(__file__).resolve().parent.parent / cand).parent.exists():
        DB_PATH = (Path(__file__).resolve().parent.parent / cand).resolve()
    else:
        DB_PATH = (Path(__file__).resolve().parents[2] / cand).resolve()
else:
    DB_PATH = DEFAULT_DB
EVENT_TYPES = {"credit", "payment", "correction", "query", "undo"}
NAME_FILLERS = {"abhi", "just", "usne", "kiye", "kiya", "rupiya", "rupaye", "rupees", "lota", "lauta", "lautaya", "lautaye", "wapas", "returned", "return"}


def _canonical_customer_name(name):
    if not isinstance(name, str):
        return name
    words = name.split()
    # Speech filler often leaks into names (for example, "Ramesh abhi just usne").
    cleaned = [word for index, word in enumerate(words) if not (index > 0 and word.casefold() in NAME_FILLERS)]
    return " ".join(cleaned).strip()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with _connect() as conn:
        conn.executescript(schema)


def _validate_event(event):
    if not isinstance(event, dict):
        raise ValueError("each event must be an object")
    kind = event.get("type")
    if kind not in EVENT_TYPES:
        raise ValueError(f"unsupported event type: {kind}")
    if kind in {"query"}:
        raise ValueError("query events cannot be committed")
    confidence = event.get("confidence")
    if confidence is not None and (not isinstance(confidence, (int, float)) or confidence < 0.80 or confidence > 1):
        raise ValueError("event confidence must be between 0.80 and 1.0")
    if kind in {"credit", "payment", "correction"}:
        name, amount = event.get("customer_name"), event.get("amount")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("customer_name is required")
        if isinstance(amount, bool) or not isinstance(amount, (float, int)) or amount <= 0:
            raise ValueError("amount must be a positive number")
        event["customer_name"] = _canonical_customer_name(name)
        event["amount"] = round(float(amount), 2)
    if kind in {"correction", "undo"} and not event.get("corrects"):
        raise ValueError(f"{kind} events require corrects event_id")
    if not isinstance(event.get("meta", {}), dict):
        raise ValueError("meta must be an object")
    if kind == "correction" and event.get("meta", {}).get("replacement_type") not in {"credit", "payment"}:
        raise ValueError("correction meta.replacement_type must be credit or payment")


def apply_ledger_event(events):
    for event in events:
        _validate_event(event)
    committed = []
    with _connect() as conn:
        for event in events:
            event_id = event.get("event_id") or str(uuid.uuid4())
            conn.execute(
                "INSERT INTO events (event_id,type,customer_id,customer_name,amount,date,confidence,corrects,status,meta) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (event_id, event["type"], event.get("customer_id"), event.get("customer_name"),
                 event.get("amount"), event.get("date") or date.today().isoformat(), event.get("confidence"),
                 event.get("corrects"), "committed", json.dumps(event.get("meta", {}), ensure_ascii=False)),
            )
            committed.append(event_id)
    balances = get_ledger_summary()
    names = ", ".join(e.get("customer_name", "") for e in events if e.get("customer_name"))
    response = f"Entry save ho gayi{(' for ' + names) if names else ''}."
    return {"event_ids": committed, "balances": balances, "response_string": response}


def _active_events(conn):
    # Corrections and undos append audit events and deactivate the event they reference.
    return conn.execute("""
        SELECT e.* FROM events e
        WHERE e.status='committed'
          AND e.type IN ('credit','payment','correction')
          AND NOT EXISTS (
            SELECT 1 FROM events r WHERE r.status='committed'
              AND r.type IN ('correction','undo') AND r.corrects=e.event_id
          )
        ORDER BY e.rowid
    """).fetchall()


def get_ledger_summary():
    with _connect() as conn:
        rows = _active_events(conn)
    totals = {}
    daily = {}
    for row in rows:
        name = _canonical_customer_name(row["customer_name"]) or row["customer_id"] or "Unknown"
        key = (row["customer_id"], name)
        entry_kind = row["type"]
        if entry_kind == "correction":
            metadata = json.loads(row["meta"] or "{}")
            entry_kind = metadata.get("replacement_type", "credit")
        totals[key] = totals.get(key, 0.0) + (row["amount"] if entry_kind == "credit" else -row["amount"])
        day_key = (key, row["date"])
        daily[day_key] = daily.get(day_key, 0.0) + (row["amount"] if entry_kind == "credit" else -row["amount"])
    return [{"customer_id": cid, "customer": name, "net_due": round(amount, 2),
             "by_day": [{"date": day, "net_due": round(value, 2)} for (k, day), value in daily.items() if k == (cid, name)]}
            for (cid, name), amount in totals.items() if round(amount, 2) != 0]


def get_daily_credit_total(day=None):
    day = day or date.today().isoformat()
    with _connect() as conn:
        rows = _active_events(conn)
    total = 0.0
    for row in rows:
        if row["date"] != day:
            continue
        kind = row["type"]
        if kind == "correction":
            kind = json.loads(row["meta"] or "{}").get("replacement_type", "credit")
        if kind == "credit":
            total += float(row["amount"] or 0)
    return round(total, 2)


def get_reminder_consent(customer_name):
    key = _canonical_customer_name(customer_name).casefold()
    with _connect() as conn:
        row = conn.execute(
            "SELECT customer_name, reminders_opt_in, consent_updated_at FROM customer_preferences WHERE customer_key=?",
            (key,),
        ).fetchone()
    return {"customer_name": row["customer_name"] if row else _canonical_customer_name(customer_name),
            "opted_in": bool(row["reminders_opt_in"]) if row else False,
            "consent_updated_at": row["consent_updated_at"] if row else None}


def set_reminder_consent(customer_name, opted_in):
    canonical = _canonical_customer_name(customer_name)
    key = canonical.casefold()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO customer_preferences (customer_key, customer_name, reminders_opt_in, consent_updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(customer_key) DO UPDATE SET
                customer_name=excluded.customer_name,
                reminders_opt_in=excluded.reminders_opt_in,
                consent_updated_at=CURRENT_TIMESTAMP
        """, (key, canonical, int(opted_in)))
    return get_reminder_consent(canonical)


def prepare_reminder(customer_name):
    canonical, choices = resolve_customer_name(customer_name)
    if choices:
        return {"eligible": False, "reason": "ambiguous_customer", "choices": choices}
    if not canonical:
        return {"eligible": False, "reason": "unknown_customer"}
    consent = get_reminder_consent(canonical)
    if not consent["opted_in"]:
        return {"eligible": False, "reason": "customer_has_not_opted_in", "customer_name": canonical}
    match = next((row for row in get_ledger_summary() if row["customer"].casefold() == canonical.casefold()), None)
    if not match or match["net_due"] <= 0:
        return {"eligible": False, "reason": "no_outstanding_amount", "customer_name": canonical}
    amount = round(match["net_due"], 2)
    message = (f"Namaste {canonical}, aapke hisaab mein ₹{amount:g} baki dikh raha hai. "
               "Jab suvidha ho, kripya hisaab dekh lein. Agar payment ho chuki hai, "
               "to is sandesh ko nazarandaaz karein. Dhanyavaad.")
    return {"eligible": True, "customer_name": canonical, "amount": amount, "message": message,
            "delivery": "preview_only"}


def resolve_customer_name(customer_name):
    """Resolve a spoken partial name only when it identifies one ledger customer."""
    if not customer_name:
        return None, []
    names = sorted({row["customer"] for row in get_ledger_summary()})
    query = _canonical_customer_name(customer_name.strip()).casefold()
    exact = [name for name in names if name.casefold() == query]
    matches = [name for name in names if name.casefold().startswith(query)]
    if len(matches) > 1:
        return None, matches
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, matches
    return customer_name.strip(), []


def get_last_active_customer():
    """Finds the most recently active customer or single debtor from the ledger."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT customer_name FROM events WHERE customer_name IS NOT NULL AND customer_name != '' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row and row["customer_name"]:
            return _canonical_customer_name(row["customer_name"])
    summary = get_ledger_summary()
    debtors = [r["customer"] for r in summary if r.get("net_due", 0) > 0]
    if len(debtors) == 1:
        return debtors[0]
    if len(summary) == 1:
        return summary[0]["customer"]
    return None


def get_customer_net_due(customer_name):
    """Returns the current outstanding net due balance for a customer."""
    if not customer_name:
        return 0.0
    summary = get_ledger_summary()
    query = customer_name.strip().casefold()
    for row in summary:
        if row["customer"].casefold() == query:
            return float(row["net_due"])
    return 0.0


def get_events(limit=100):
    limit = max(1, min(int(limit), 500))
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["customer_name"] = _canonical_customer_name(item.get("customer_name"))
        try:
            item["meta"] = json.loads(item["meta"] or "{}")
        except json.JSONDecodeError:
            pass
        result.append(item)
    return result


def get_all_events():
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY rowid DESC").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["customer_name"] = _canonical_customer_name(item.get("customer_name"))
        try:
            item["meta"] = json.loads(item["meta"] or "{}")
        except json.JSONDecodeError:
            pass
        result.append(item)
    return result


def get_customer_balance(customer_name=None):
    balances = get_ledger_summary()
    resolved, choices = resolve_customer_name(customer_name)
    if choices:
        return {"balances": [], "response_string": "Kaun se customer ka hisaab? " + ", ".join(choices[:4]) + "."}
    matches = [item for item in balances if not resolved or item["customer"].casefold() == resolved.casefold()]
    if not matches:
        return {"balances": [], "response_string": f"{customer_name or 'Customer'} ka koi hisaab nahi mila."}
    if len(matches) == 1:
        item = matches[0]
        due = item["net_due"]
        answer = f"{item['customer']} ka baki {abs(due):g} rupaye hai." if due >= 0 else f"{item['customer']} ko {abs(due):g} rupaye dene hain."
    else:
        answer = "Hisaab mil gaya. Kripya customer ka poora naam batayein."
    return {"balances": matches, "response_string": answer}


def prepare_latest_correction(amount, customer_name=None):
    """Build an uncommitted correction draft for the latest active ledger event."""
    with _connect() as conn:
        active = _active_events(conn)
        target = next(
            (row for row in reversed(active)
             if not customer_name or (row["customer_name"] or "").casefold() == customer_name.casefold()),
            None,
        )
    if target is None:
        return None
    target_kind = target["type"]
    if target_kind == "correction":
        target_kind = json.loads(target["meta"] or "{}").get("replacement_type", "credit")
    return {
        "type": "correction",
        "customer_id": target["customer_id"],
        "customer_name": target["customer_name"],
        "amount": float(amount),
        "date": target["date"],
        "confidence": 0.86,
        "corrects": target["event_id"],
        "meta": {
            "replacement_type": target_kind,
            "previous_amount": target["amount"],
        },
    }
