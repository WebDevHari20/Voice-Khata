from contextlib import asynccontextmanager
import os
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
        set_reminder_consent, get_last_active_customer, get_customer_net_due,
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
        set_reminder_consent, get_last_active_customer, get_customer_net_due,
    )
    from nlu.gemini_parser import extract_customer_name, parse_transcript
    from nlu.normalizer import normalize_hindi_numbers


YES_WORDS = {
    "haan", "han", "ha", "yes", "yep", "yeah", "correct", "sahi", "theek", "thik",
    "bilkul", "confirm", "save", "kar", "karo", "ji", "jee", "hai", "sure", "ok", "okay",
    "हाँ", "हां", "सही", "ठीक", "बिल्कुल", "कन्फर्म", "करो", "जी", "सेव", "हाँजी"
}
NO_WORDS = {
    "nahi", "nahin", "nahiin", "no", "nope", "not", "wrong", "galat", "cancel", "mat", "rok",
    "नहीं", "नही", "गलत", "कैंसिल", "मत", "रोको", "ना"
}


def _confirmation_intent(text):
    low = text.lower().strip()
    words = [t.strip("।,!?") for t in low.split()]
    if words and any(w in NO_WORDS for w in words):
        return "no"
    if words and not re.search(r"\d", normalize_hindi_numbers(text)) and any(w in YES_WORDS for w in words):
        return "yes"
    return None


def _amount_in(text):
    normalized = normalize_hindi_numbers(text)
    matches = re.findall(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)", normalized)
    return float(matches[-1]) if matches else None


def _clean_correction(text):
    return re.sub(r"(?i)\b(nahi|nahin|nahiin|no|not|wrong|correct|galat|correction|error|mistake|actually|change|badlo|instead|amount|rakam|paise|make|it|to|the)\b", " ", text).strip(" ,.!?")


def _confirmation_prompt(event):
    customer = event.get("customer_name") or "customer"
    amount = f"{float(event.get('amount', 0)):g}"
    if event.get("type") in {"bulk_payment", "full_settlement"}:
        return (
            f"{customer} ka kul {amount} rupaye baki hisaab clear karun? Haan ya nahi boliye. / "
            f"क्या {customer} का कुल {amount} रुपये बकाया हिसाब चुकता करें? हाँ या नहीं बोलिए।"
        )
    if event.get("type") == "correction":
        previous = f"{float(event['meta'].get('previous_amount', 0)):g}"
        return (
            f"{customer} ki purani entry {previous} se {amount} rupaye karun? Haan ya nahi boliye. / "
            f"क्या {customer} की पुरानी एंट्री {previous} से {amount} रुपये करें? हाँ या नहीं बोलिए।"
        )
    if event.get("type") == "payment":
        return (
            f"Maine {customer} se {amount} rupaye payment suna. Kya ise save karun? / "
            f"क्या {customer} से {amount} रुपये जमा दर्ज करें? हाँ या नहीं बोलिए।"
        )
    return (
        f"Maine {customer} ka {amount} rupaye udhaar suna. Kya ise save karun? / "
        f"क्या {customer} का {amount} रुपये उधार दर्ज करें? हाँ या नहीं बोलिए।"
    )


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
    key = os.getenv("GNANI_API_KEY") or os.getenv("GNANI_PRISMA_KEY") or ""
    return {
        "status": "ok",
        "has_env_key": bool(key),
        "env_key_prefix": key[:8] if key else "",
        "env_key_len": len(key) if key else 0,
    }


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
        cust = events[0].get("customer_name") or get_last_active_customer()
        return get_customer_balance(cust)
    for event in events:
        if isinstance(event, dict) and (not event.get("customer_name") or event.get("is_pronoun")):
            event["customer_name"] = get_last_active_customer()
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

            # Full settlement command (e.g. "he returned his whole money", "isne poora paisa de diya", "उसने पूरा पैसा वापस कर दिया")
            full_amount_cue = bool(re.search(r"\b(pura|poora|poore|pure|saara|saare|sab|full|complete|whole|all)\b", voice_command) or any(w in voice_command for w in ("पूरा", "पूरी", "पूरे", "सारा", "सारे", "सब")))
            repayment_cue = bool(re.search(r"\b(chuka|chukaya|chukadiya|clear|paid|settle|wapas|wapis|return|returned|lota|lauta|gave)\b", voice_command) or any(w in voice_command for w in ("चुका", "चुकाया", "वापस", "लौटाया", "दिया", "क्लियर", "चुकता")))
            money_cue = bool(re.search(r"\b(money|paisa|paise|amount|dues|debt|balance|hisaab|hisab)\b", voice_command) or any(w in voice_command for w in ("पैसा", "पैसे", "हिसाब", "बकाया")))
            has_spoken_amount = _amount_in(voice_command) is not None
            full_settlement = (full_amount_cue and (repayment_cue or money_cue) and not has_spoken_amount) or (repayment_cue and money_cue and not has_spoken_amount)
            if full_settlement:
                summary = get_ledger_summary()
                balances = {row["customer"].casefold(): row["net_due"] for row in summary}
                names_map = {row["customer"].casefold(): row["customer"] for row in summary}
                target_customer = None
                for c_lower, c_orig in names_map.items():
                    if c_lower in voice_command.lower():
                        target_customer = c_orig
                        break
                if not target_customer:
                    target_customer = get_last_active_customer()
                if not target_customer:
                    reply = "Kis customer ka poora hisaab clear karna hai? Naam boliye. / किस ग्राहक का पूरा हिसाब क्लियर करना है? नाम बताइए।"
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                total_due = balances.get(target_customer.casefold(), 0.0)
                if total_due <= 0:
                    reply = f"{target_customer} ka koi baki udhaar nahi hai. / {target_customer} का कोई बाकी उधार नहीं है।"
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
                pending_event = {
                    "type": "bulk_payment",
                    "customer_name": target_customer,
                    "amount": round(total_due, 2),
                    "events": [{
                        "type": "payment",
                        "customer_name": target_customer,
                        "amount": round(total_due, 2),
                        "date": date.today().isoformat(),
                        "confidence": 0.95,
                        "meta": {"source": "spoken_full_settlement"}
                    }]
                }
                prompt = _confirmation_prompt(pending_event)
                await stream_tts(websocket, prompt)
                await websocket.send_json({"type": "confirmation_required", "event": pending_event, "text": prompt})
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
            if not events[0].get("customer_name") or events[0].get("is_pronoun"):
                resolved_name = get_last_active_customer()
                if not resolved_name:
                    reply = "Kis customer ne paise wapas kiye? Naam batayein. / किस ग्राहक के लिए एंट्री करनी है? नाम बताएं।"
                    await stream_tts(websocket, reply)
                    await websocket.send_json({"type": "clarification", "text": reply})
                    continue
            else:
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
                amt = events[0].get("amount", 0)
                verb = "jama" if events[0].get("type") == "payment" else "udhaar"
                h_verb = "जमा" if events[0].get("type") == "payment" else "उधार"
                cur_bal = get_customer_net_due(resolved_name)
                resp = f"{resolved_name} ka {amt:g} rupaye {verb} ho gaya. Baki balance {cur_bal:g} rupaye hai. / {resolved_name} का {amt:g} रुपये {h_verb} दर्ज हो गया। बाकी बैलेंस {cur_bal:g} रुपये है।"
                result["response_string"] = resp
                await stream_tts(websocket, resp)
                await websocket.send_json({"type": "ledger_result", **result})
            else:
                pending_event = events[0]
                prompt = _confirmation_prompt(pending_event)
                await stream_tts(websocket, prompt)
                await websocket.send_json({"type": "confirmation_required", "event": pending_event, "text": prompt})
    except WebSocketDisconnect:
        return

