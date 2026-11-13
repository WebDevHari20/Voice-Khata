from contextlib import asynccontextmanager
from pathlib import Path
import re
import sys
from datetime import date
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

load_dotenv(Path(__file__).with_name(".env"))

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from .core.stt_stream import stream_audio_to_stt
    from .core.tts_engine import stream_tts, synthesize_audio
    from .core.excel_export import build_workbook
    from .database.ledger_ops import (
        apply_ledger_event, get_customer_balance, get_ledger_summary,
        get_all_events, get_daily_credit_total, get_reminder_consent, initialize_database,
        prepare_latest_correction, prepare_reminder, resolve_customer_name,
        set_reminder_consent,
    )
    from .nlu.gemini_parser import extract_customer_name, parse_transcript
    from .nlu.normalizer import normalize_hindi_numbers
except (ImportError, ValueError):
    from core.stt_stream import stream_audio_to_stt
    from core.tts_engine import stream_tts, synthesize_audio
    from core.excel_export import build_workbook
    from database.ledger_ops import (
        apply_ledger_event, get_customer_balance, get_ledger_summary,
        get_all_events, get_daily_credit_total, get_reminder_consent, initialize_database,
        prepare_latest_correction, prepare_reminder, resolve_customer_name,
        set_reminder_consent,
    )
    from nlu.gemini_parser import extract_customer_name, parse_transcript
    from nlu.normalizer import normalize_hindi_numbers


YES_WORDS = {"haan", "han", "ha", "yes", "yep", "correct", "sahi", "theek", "thik", "bilkul", "confirm", "save", "kar", "karo", "ji", "jee", "hai"}
NO_WORDS = {"nahi", "nahin", "nahiin", "no", "nope", "not", "wrong", "galat", "cancel", "mat"}


def _confirmation_intent(text):
    words = re.findall(r"[a-z]+", text.lower())
    if words and words[0] in NO_WORDS:
        return "no"
    if words and not re.search(r"\d", normalize_hindi_numbers(text)) and all(word in YES_WORDS for word in words):
        return "yes"
    return None


def _amount_in(text):
    normalized = normalize_hindi_numbers(text)
    matches = re.findall(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)", normalized)
    return float(matches[-1]) if matches else None


def _clean_correction(text):
    return re.sub(r"(?i)\b(nahi|nahin|nahiin|no|not|wrong|correct|galat|correction|error|mistake|actually|change|badlo|instead|amount|rakam|paise|make|it|to|the)\b", " ", text).strip(" ,.!?")


def _confirmation_prompt(event):
    if event.get("type") == "bulk_payment":
        return f"{event['customer_name']} ka kul {float(event['amount']):g} rupaye baki clear karun? Haan ya nahi boliye."
    amount = f"{float(event['amount']):g}"
    customer = event["customer_name"]
    if event["type"] == "correction":
        previous = f"{float(event['meta'].get('previous_amount', 0)):g}"
        return f"{customer} ki purani entry {previous} rupaye se {amount} rupaye karun? Haan ya nahi boliye."
    if event["type"] == "payment":
        return f"Maine {customer} se {amount} rupaye payment suna. Kya ye sahi hai? Haan ya nahi boliye."
    return f"Maine {customer} ka {amount} rupaye udhaar suna. Kya ise save karun? Haan ya nahi boliye."


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Voice Khata API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/parse")
def parse(payload: dict):
    transcript = payload.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        raise HTTPException(status_code=422, detail="transcript must be a non-empty string")
    return parse_transcript(transcript)


@app.post("/ledger/apply")
def ledger_apply(payload: dict):
    events = payload.get("events")
    if events is None and isinstance(payload.get("transcript"), str):
        events = parse_transcript(payload["transcript"])
    if not isinstance(events, list) or not events:
        raise HTTPException(status_code=422, detail="provide a non-empty events array or transcript")
    if isinstance(events[0], dict) and events[0].get("type") == "query":
        return get_customer_balance(events[0].get("customer_name"))
    try:
        return apply_ledger_event(events)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/ledger/summary")
def ledger_summary():
    return get_ledger_summary()


@app.post("/tts")
async def tts(payload: dict):
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="text must be a non-empty string")
    try:
        audio = await synthesize_audio(text.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav", headers={"Content-Disposition": "inline; filename=voice-khata.wav"})


@app.get("/ledger/events")
def ledger_events(limit: int = 100):
    try:
        from .database.ledger_ops import get_events
    except (ImportError, ValueError):
        from database.ledger_ops import get_events
    return get_events(limit)


@app.get("/ledger/export.xlsx")
def ledger_export_excel():
    workbook = build_workbook(get_ledger_summary(), get_all_events())
    filename = f"voice-khata-{date.today().isoformat()}.xlsx"
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/customers/{customer_name}/reminder-consent")
def reminder_consent(customer_name: str):
    return get_reminder_consent(customer_name)


@app.put("/customers/{customer_name}/reminder-consent")
def update_reminder_consent(customer_name: str, payload: dict):
    opted_in = payload.get("opted_in")
    if not isinstance(opted_in, bool):
        raise HTTPException(status_code=422, detail="opted_in must be a boolean")
    return set_reminder_consent(customer_name, opted_in)


@app.post("/reminders/prepare")
def reminder_prepare(payload: dict):
    customer_name = payload.get("customer_name")
    if not isinstance(customer_name, str) or not customer_name.strip():
        raise HTTPException(status_code=422, detail="customer_name is required")
    try:
        result = prepare_reminder(customer_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    pending_event = None
    try:
        async for transcript, confidence in stream_audio_to_stt(websocket):
            await websocket.send_json({
                "type": "transcript", "text": transcript, "confidence": confidence,
                "confidence_source": "client" if confidence is not None else "not-provided-by-prisma",
            })
            if confidence is not None and confidence < 0.80:
                await stream_tts(websocket, "Kripya dobara bole.")
                continue

            voice_command = transcript.lower().strip(" .!?\t")
            if voice_command in {"stop", "stop listening", "stop microphone", "band karo", "sunna band", "mic band", "bas"}:
                await websocket.send_json({"type": "control", "action": "stop_listening"})
                continue

            if pending_event and pending_event.get("type") in {"needs_customer", "needs_query_customer"}:
                options = pending_event["choices"]
                heard = voice_command.casefold()
                selected = [name for name in options if name.casefold() in heard]
                if len(selected) == 1:
                    if pending_event["type"] == "needs_query_customer":
                        balance = get_customer_balance(selected[0])
                        pending_event = None
                        await websocket.send_json({"type": "query_result", **balance})
                        continue
                    event = pending_event["event"]
                    event["customer_name"] = selected[0]
                    pending_event = None
                    if event.get("amount", 0) > 1000:
                        prompt = _confirmation_prompt(event)
                        pending_event = event
                        await stream_tts(websocket, prompt)
                        await websocket.send_json({"type": "confirmation_required", "event": event, "text": prompt})
                    else:
                        result = apply_ledger_event([event])
                        await stream_tts(websocket, result["response_string"])
                        await websocket.send_json({"type": "ledger_result", **result})
                    continue
                prompt = "Kripya poora naam chunein: " + " ya ".join(options[:4]) + "."
                await stream_tts(websocket, prompt)
                await websocket.send_json({"type": "clarification", "text": prompt})
                continue

            # A spoken full-settlement command appends payment events; audit history is retained.
            full_amount_cue = re.search(r"\b(pura|poora|poore|pure|saara|saare|sab|full|complete)\b", voice_command)
            repayment_cue = re.search(r"\b(chuka|chukaya|chukadiya|clear|paid|settle|wapas|return|returned|lota|lauta)\b", voice_command)
            has_spoken_amount = _amount_in(voice_command) is not None
            full_settlement = bool(full_amount_cue and repayment_cue and not has_spoken_amount)
            legacy_settlement = bool(re.search(r"\b(pura|poora|pure)\b.*\b(chuka|chukaya|clear|paid|settle)\b|\b(chuka|chukaya)\s+(diya|diye)\b", voice_command))
            if full_settlement or legacy_settlement:
                spoken_names = re.findall(r"\b([a-z]+)\s+ne\b", voice_command)
                if not spoken_names:
                    reply = "Kis customer ka poora hisaab clear karna hai? Naam boliye."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                balances = {row["customer"].casefold(): row["net_due"] for row in get_ledger_summary()}
                events_to_commit = []
                resolved_names = []
                ambiguous = []
                for spoken_name in dict.fromkeys(spoken_names):
                    resolved_name, choices = resolve_customer_name(spoken_name)
                    if choices:
                        ambiguous.extend(choices)
                    elif resolved_name and balances.get(resolved_name.casefold(), 0) > 0:
                        resolved_names.append(resolved_name)
                        events_to_commit.append({"type": "payment", "customer_name": resolved_name,
                            "amount": round(balances[resolved_name.casefold()], 2), "date": date.today().isoformat(),
                            "confidence": 0.86, "meta": {"source": "spoken_full_settlement"}})
                if ambiguous:
                    reply = "Naam clear nahi hai. Kripya poora naam boliye: " + ", ".join(sorted(set(ambiguous))[:4]) + "."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                if not events_to_commit:
                    reply = "In customers ka koi baki udhaar nahi mila."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                total = round(sum(event["amount"] for event in events_to_commit), 2)
                if total > 1000:
                    pending_event = {"type": "bulk_payment", "customer_name": " aur ".join(resolved_names),
                        "amount": total, "events": events_to_commit}
                    prompt = _confirmation_prompt(pending_event)
                    await stream_tts(websocket, prompt)
                    await websocket.send_json({"type": "confirmation_required", "event": pending_event, "text": prompt})
                    continue
                result = apply_ledger_event(events_to_commit)
                result["response_string"] = "Poora baki clear ho gaya. " + result["response_string"]
                await stream_tts(websocket, result["response_string"])
                await websocket.send_json({"type": "ledger_result", **result})
                continue

            if pending_event and pending_event.get("type") == "needs_direction":
                words = set(re.findall(r"[a-z]+", transcript.lower()))
                if words.intersection({"udhaar", "udhar", "credit", "borrowed", "loan", "liya", "baaki", "baki"}):
                    pending_event["type"] = "credit"
                elif words.intersection({"payment", "paid", "jama", "received", "aaya", "diya"}):
                    pending_event["type"] = "payment"
                else:
                    amount = _amount_in(transcript)
                    if amount is not None:
                        pending_event["amount"] = amount
                    if words.intersection(NO_WORDS):
                        pending_event = None
                        reply = "Theek hai, entry cancel kar di."
                        await stream_tts(websocket, reply)
                        await websocket.send_json({"type": "confirmation_cancelled", "text": reply})
                        continue
                    reply = "Yeh udhaar tha ya payment? Kripya ek chunein."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                resolved_name, choices = resolve_customer_name(pending_event.get("customer_name"))
                if choices:
                    pending_event = None
                    reply = "Customer ka naam clear nahi hua. Kripya poora naam aur udhaar ya payment dobara batayein: " + ", ".join(choices[:4]) + "."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                pending_event["customer_name"] = resolved_name
                if pending_event.get("amount", 0) <= 1000:
                    result = apply_ledger_event([pending_event])
                    pending_event = None
                    await stream_tts(websocket, result["response_string"])
                    await websocket.send_json({"type": "ledger_result", **result})
                    continue
                prompt = _confirmation_prompt(pending_event)
                await stream_tts(websocket, prompt)
                await websocket.send_json({"type": "confirmation_required", "event": pending_event, "text": prompt})
                continue

            intent = _confirmation_intent(transcript)
            if pending_event and intent == "yes":
                result = apply_ledger_event(pending_event.get("events", [pending_event]))
                pending_event = None
                await stream_tts(websocket, result["response_string"])
                await websocket.send_json({"type": "ledger_result", **result})
                continue

            correction_terms = {"actually", "change", "badlo", "instead", "rakam", "wrong", "correct", "error", "mistake", "not"}
            has_amount_correction = bool(correction_terms.intersection(re.findall(r"[a-z]+", transcript.lower())))
            has_negative_word = bool(NO_WORDS.intersection(re.findall(r"[a-z]+", transcript.lower())))
            if pending_event and (intent == "no" or has_negative_word or has_amount_correction):
                corrected_text = _clean_correction(transcript)
                corrected = parse_transcript(corrected_text) if corrected_text else []
                amount = _amount_in(transcript)
                if amount is not None:
                    pending_event["amount"] = amount
                    if corrected and "clarification" not in corrected[0] and corrected[0].get("type") in {"credit", "payment"}:
                        pending_event["customer_name"] = corrected[0]["customer_name"]
                        if pending_event["type"] == "correction":
                            pending_event["meta"]["replacement_type"] = corrected[0]["type"]
                        else:
                            pending_event["type"] = corrected[0]["type"]
                    if pending_event.get("type") != "bulk_payment" and amount <= 1000:
                        result = apply_ledger_event([pending_event])
                        pending_event = None
                        await stream_tts(websocket, result["response_string"])
                        await websocket.send_json({"type": "ledger_result", **result})
                        continue
                    prompt = _confirmation_prompt(pending_event)
                    await stream_tts(websocket, prompt)
                    await websocket.send_json({"type": "confirmation_required", "event": pending_event, "text": prompt})
                elif intent == "no":
                    pending_event = None
                    reply = "Theek hai, entry save nahi ki. Jab taiyar hon, naam aur rakam dobara batayein."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "confirmation_cancelled", "text": reply})
                else:
                    reply = "Rakam samajh nahi aayi. Kripya sahi rakam boliye, ya haan ya nahi kahiye."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                continue

            correction_words = {"nahi", "nahin", "nahiin", "no", "not", "galat", "correction", "wrong", "correct", "error", "mistake", "actually", "change", "badlo"}
            is_correction = bool(correction_words.intersection(re.findall(r"[a-z]+", transcript.lower())))
            if not pending_event and is_correction and _amount_in(transcript) is not None:
                corrected_text = _clean_correction(transcript)
                corrected = parse_transcript(corrected_text) if corrected_text else []
                customer_name = extract_customer_name(corrected_text) if corrected_text else None
                if corrected and "clarification" not in corrected[0]:
                    customer_name = corrected[0].get("customer_name")
                customer_name, choices = resolve_customer_name(customer_name)
                if choices:
                    reply = "Kaun si entry sudharni hai? " + ", ".join(choices[:4]) + ". Kripya poora naam boliye."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                pending_event = prepare_latest_correction(_amount_in(transcript), customer_name)
                if pending_event:
                    if pending_event["amount"] <= 1000:
                        result = apply_ledger_event([pending_event])
                        await stream_tts(websocket, result["response_string"])
                        await websocket.send_json({"type": "ledger_result", **result})
                        continue
                    prompt = _confirmation_prompt(pending_event)
                    await stream_tts(websocket, prompt)
                    await websocket.send_json({"type": "confirmation_required", "event": pending_event, "text": prompt})
                else:
                    reply = "Mujhe us customer ki pichhli entry nahi mili. Kripya naam aur rakam ke saath dobara batayein."
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                continue

            events = parse_transcript(transcript)
            if not events or "clarification" in events[0]:
                if events and events[0].get("draft"):
                    pending_event = {"type": "needs_direction", **events[0]["draft"]}
                prompt = events[0].get("clarification", "Kripya naam aur rakam dobara batayein.") if events else "Kripya dobara bole."
                await stream_tts(websocket, prompt)
                await websocket.send_json({"type": "clarification", "text": prompt})
                continue
            if events[0]["type"] == "query":
                if events[0].get("metric") == "daily_credit":
                    total = get_daily_credit_total(events[0].get("query_date"))
                    day_word = "Aaj" if events[0].get("query_date") == date.today().isoformat() else "Us din"
                    balance = {"balances": [], "daily_credit_total": total,
                        "response_string": f"{day_word} {total:g} rupaye ka udhaar gaya."}
                    await websocket.send_json({"type": "query_result", **balance})
                    continue
                query_name = events[0].get("customer_name")
                resolved_name, choices = resolve_customer_name(query_name)
                if choices:
                    pending_event = {"type": "needs_query_customer", "choices": choices[:4]}
                    reply = "Kaun se " + " ya ".join(choices[:4]) + " ka hisaab?"
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                balance = get_customer_balance(resolved_name)
                await websocket.send_json({"type": "query_result", **balance})
                continue
            resolved_name, choices = resolve_customer_name(events[0].get("customer_name"))
            if choices:
                pending_event = {"type": "needs_customer", "event": events[0], "choices": choices[:4]}
                reply = "Kaun se customer: " + " ya ".join(choices[:4]) + "?"
                await stream_tts(websocket, reply)
                await websocket.send_json({"type": "clarification", "text": reply})
                continue
            events[0]["customer_name"] = resolved_name
            if pending_event:
                await websocket.send_json({"type": "confirmation_cancelled", "text": "Pichli draft entry cancel kar di."})
            if events[0].get("amount", 0) <= 1000:
                result = apply_ledger_event(events)
                await stream_tts(websocket, result["response_string"])
                await websocket.send_json({"type": "ledger_result", **result})
            else:
                pending_event = events[0]
                prompt = _confirmation_prompt(pending_event)
                await stream_tts(websocket, prompt)
                await websocket.send_json({"type": "confirmation_required", "event": pending_event, "text": prompt})
    except WebSocketDisconnect:
        return

