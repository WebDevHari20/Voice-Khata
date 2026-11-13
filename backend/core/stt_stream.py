import asyncio
import json
import os


STT_URL = os.getenv("GNANI_PRISMA_URL", "wss://api.vachana.ai/stt/v3/stream")
PLACEHOLDERS = {"", "replace-me", "your-api-key", "placeholder"}


def _api_key():
    for value in (os.getenv("GNANI_PRISMA_KEY"), os.getenv("GNANI_API_KEY")):
        value = (value or "").strip()
        if value and value.lower() not in PLACEHOLDERS:
            return value
    return None


async def _connect_prisma(key, sample_rate, language_code):
    from websockets.asyncio.client import connect
    from ..database.ledger_ops import get_ledger_summary

    customer_names = [row["customer"] for row in get_ledger_summary()][:200]

    return await connect(
        STT_URL,
        additional_headers={
            "x-api-key-id": key,
            "language_code": language_code,
            "model": "prisma-v3.0",
            "format": "transliterate",
            "x-sample-rate": str(sample_rate),
            "topic": "Kirana shop ledger: customer names, udhaar, payments, rupee amounts, and dates.",
            "keyterms": json.dumps(customer_names, ensure_ascii=False),
            "x-min-speech-ms": "180",
            "x-min-silence-ms": "500",
        },
        open_timeout=15,
        max_size=None,
    )


async def stream_audio_to_stt(websocket):
    """Proxy raw PCM to Prisma; transcript text frames work without credentials."""
    key = _api_key()
    sample_rate, language_code = 16000, "indic-auto"
    provider = provider_read = None
    client_read = asyncio.create_task(websocket.receive())
    try:
        while True:
            waiting = {client_read}
            if provider_read:
                waiting.add(provider_read)
            done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)

            if client_read in done:
                message = client_read.result()
                if message.get("type") == "websocket.disconnect":
                    return
                client_read = asyncio.create_task(websocket.receive())
                if message.get("text") is not None:
                    try:
                        payload = json.loads(message["text"])
                    except json.JSONDecodeError:
                        payload = {"transcript": message["text"]}
                    if isinstance(payload.get("transcript"), str) and payload["transcript"].strip():
                        yield payload["transcript"].strip(), float(payload.get("confidence", 0.95))
                    elif payload.get("type") == "configure":
                        sample_rate = int(payload.get("sample_rate", sample_rate))
                        language_code = payload.get("language_code", language_code)
                        if sample_rate not in {8000, 16000, 44100, 48000}:
                            await websocket.send_json({"type": "error", "detail": "sample_rate must be 8000, 16000, 44100, or 48000"})
                        elif key and provider is None:
                            try:
                                provider = await _connect_prisma(key, sample_rate, language_code)
                                provider_read = asyncio.create_task(provider.recv())
                            except Exception as exc:
                                await websocket.send_json({"type": "provider_error", "detail": f"Prisma connection failed: {exc}"})
                    else:
                        await websocket.send_json({"type": "error", "detail": "send transcript text, a configure frame, or raw PCM audio"})
                elif message.get("bytes") is not None:
                    if not key:
                        await websocket.send_json({"type": "provider_unavailable", "detail": "Set GNANI_API_KEY in backend/.env to enable Prisma STT."})
                        continue
                    frame = message["bytes"]
                    if len(frame) != 1024:
                        await websocket.send_json({"type": "error", "detail": "Prisma expects raw mono PCM16 frames of exactly 1024 bytes."})
                        continue
                    if provider is None:
                        try:
                            provider = await _connect_prisma(key, sample_rate, language_code)
                            provider_read = asyncio.create_task(provider.recv())
                        except Exception as exc:
                            await websocket.send_json({"type": "provider_error", "detail": f"Prisma connection failed: {exc}"})
                            continue
                    try:
                        await provider.send(frame)
                    except Exception as exc:
                        await websocket.send_json({"type": "provider_error", "detail": f"Prisma send failed: {exc}"})
                        await provider.close()
                        provider = provider_read = None

            if provider_read and provider_read in done:
                try:
                    raw = provider_read.result()
                except Exception as exc:
                    await websocket.send_json({"type": "provider_error", "detail": f"Prisma stream ended: {exc}"})
                    provider = provider_read = None
                    continue
                provider_read = asyncio.create_task(provider.recv())
                try:
                    event = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    await websocket.send_json({"type": "provider_error", "detail": "Prisma returned an unreadable message"})
                    continue
                if event.get("type") == "transcript" and event.get("text", "").strip():
                    # Prisma's documented transcript event does not include confidence.
                    yield event["text"].strip(), None
                elif event.get("type") == "error":
                    await websocket.send_json({"type": "provider_error", "detail": event.get("message", "Prisma reported an error")})
                else:
                    await websocket.send_json({"type": "stt_status", **event})
    finally:
        client_read.cancel()
        if provider_read:
            provider_read.cancel()
        if provider:
            await provider.close()
