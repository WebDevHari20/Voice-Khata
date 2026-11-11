import json
import os
import sqlite3
import uuid
from datetime import date
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "ledger.db"
DB_PATH = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB)))
if not DB_PATH.is_absolute():
    DB_PATH = (Path(__file__).resolve().parents[2] / DB_PATH).resolve()
EVENT_TYPES = {"credit", "payment", "correction", "query", "undo"}


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
        event["customer_name"] = name.strip()
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
        ORDER BY e.date, e.rowid
    """).fetchall()


def get_ledger_summary():
    with _connect() as conn:
        rows = _active_events(conn)
    totals = {}
    daily = {}
    for row in rows:
        name = row["customer_name"] or row["customer_id"] or "Unknown"
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
            for (cid, name), amount in totals.items()]


def get_events(limit=100):
    limit = max(1, min(int(limit), 500))
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["meta"] = json.loads(item["meta"] or "{}")
        except json.JSONDecodeError:
            pass
        result.append(item)
    return result


def get_customer_balance(customer_name=None):
    balances = get_ledger_summary()
    matches = [item for item in balances if not customer_name or item["customer"].casefold() == customer_name.casefold()]
    if not matches:
        return {"balances": [], "response_string": f"{customer_name or 'Customer'} ka koi hisaab nahi mila."}
    if len(matches) == 1:
        item = matches[0]
        due = item["net_due"]
        answer = f"{item['customer']} ka baki {abs(due):g} rupaye hai." if due >= 0 else f"{item['customer']} ko {abs(due):g} rupaye dene hain."
    else:
        answer = "Hisaab mil gaya. Kripya customer ka poora naam batayein."
    return {"balances": matches, "response_string": answer}
