from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

load_dotenv(Path(__file__).with_name(".env"))

from .core.stt_stream import stream_audio_to_stt
from .core.tts_engine import stream_tts, synthesize_audio
from .database.ledger_ops import apply_ledger_event, get_customer_balance, get_ledger_summary, initialize_database
from .nlu.gemini_parser import parse_transcript


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Voice Khata API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
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
    from .database.ledger_ops import get_events
    return get_events(limit)


@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        async for transcript, confidence in stream_audio_to_stt(websocket):
            await websocket.send_json({
                "type": "transcript", "text": transcript, "confidence": confidence,
                "confidence_source": "client" if confidence is not None else "not-provided-by-prisma",
            })
            if confidence is not None and confidence < 0.80:
                await stream_tts(websocket, "Kripya dobara bole.")
                continue
            events = parse_transcript(transcript)
            if not events or "clarification" in events[0]:
                prompt = events[0].get("clarification", "Kripya naam aur rakam dobara batayein.") if events else "Kripya dobara bole."
                await stream_tts(websocket, prompt)
                await websocket.send_json({"type": "clarification", "text": prompt})
                continue
            if events[0]["type"] == "query":
                from .database.ledger_ops import get_customer_balance
                balance = get_customer_balance(events[0].get("customer_name"))
                reply = balance["response_string"]
                await stream_tts(websocket, reply)
                await websocket.send_json({"type": "ledger_result", **balance})
                continue
            result = apply_ledger_event(events)
            await stream_tts(websocket, result["response_string"])
            await websocket.send_json({"type": "ledger_result", **result})
    except WebSocketDisconnect:
        return

