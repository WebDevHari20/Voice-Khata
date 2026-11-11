async def stream_tts(websocket, text: str):
    """Development fallback: return speakable text until Timbre is configured."""
    await websocket.send_json({"type": "tts_text", "text": text, "audio_available": False})
