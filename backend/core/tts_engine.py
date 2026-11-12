import asyncio
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TTS_URL = os.getenv("GNANI_TIMBRE_URL", "https://api.vachana.ai/api/v1/tts/inference")
PLACEHOLDERS = {"", "replace-me", "your-api-key", "placeholder"}


def _api_key():
    for value in (os.getenv("GNANI_TIMBRE_KEY"), os.getenv("GNANI_API_KEY")):
        value = (value or "").strip()
        if value and value.lower() not in PLACEHOLDERS:
            return value
    return None


def _request_audio(text):
    payload = {
        "text": text,
        "model": os.getenv("GNANI_TIMBRE_MODEL", "timbre-v3.0"),
        "voice": os.getenv("GNANI_TIMBRE_VOICE", "Shivani"),
        "language": os.getenv("GNANI_TIMBRE_LANGUAGE", "auto"),
        "audio_config": {
            "encoding": "linear_pcm",
            "container": "wav",
            "num_channels": 1,
            "sample_rate": 24000,
            "sample_width": 2,
        },
    }
    request = Request(
        TTS_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"X-API-Key-ID": _api_key(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Timbre returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Timbre: {exc.reason}") from exc


async def synthesize_audio(text):
    if not _api_key():
        raise RuntimeError("GNANI_API_KEY is not configured")
    return await asyncio.to_thread(_request_audio, text)


async def stream_tts(websocket, text):
    import base64

    try:
        audio = await synthesize_audio(text)
    except RuntimeError as exc:
        await websocket.send_json({
            "type": "tts_text",
            "text": text,
            "audio_available": False,
            "detail": str(exc),
        })
        return
    await websocket.send_json({
        "type": "audio_chunk",
        "audio": base64.b64encode(audio).decode("ascii"),
        "mime_type": "audio/wav",
        "text": text,
        "is_final": True,
    })
