import os
from fastapi import WebSocketDisconnect


async def stream_audio_to_stt(websocket):
    """Accept text transcript frames for local development.

    Binary audio needs the provider adapter, intentionally left behind the
    GNANI_PRISMA_KEY placeholder until the account's wire protocol is known.
    """
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        if message.get("text") is not None:
            import json
            try:
                payload = json.loads(message["text"])
            except json.JSONDecodeError:
                payload = {"transcript": message["text"]}
            transcript = payload.get("transcript")
            if isinstance(transcript, str) and transcript.strip():
                yield transcript.strip(), float(payload.get("confidence", 0.95))
            else:
                await websocket.send_json({"type": "error", "detail": "send {transcript: ...} text frame"})
        elif message.get("bytes") is not None:
            await websocket.send_json({
                "type": "provider_unavailable",
                "detail": "Audio STT adapter is not configured. Send a transcript text frame for local development.",
                "provider_key_present": os.getenv("GNANI_PRISMA_KEY", "").strip() not in {"", "replace-me"},
            })
