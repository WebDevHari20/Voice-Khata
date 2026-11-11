# Voice Khata backend

FastAPI backend for the Voice Khata ledger. It runs locally with a rule based
Hindi/Hinglish parser, append-only SQLite events, HTTP endpoints, and a
transcript-text WebSocket development path. Provider credentials are placeholders;
live Gnani STT/TTS and Gemini parsing are not connected yet.

## Run

From the repository root in PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r backend\requirements.txt
if (!(Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
py -m uvicorn backend.main:app --reload
```

The API starts at `http://127.0.0.1:8000`; interactive API docs are at
`http://127.0.0.1:8000/docs`. SQLite initializes automatically in
`backend/data/ledger.db`.

## Endpoints

- `GET /health` — process health.
- `POST /parse` — `{ "transcript": "Ramesh ka 340 udhaar" }`.
- `POST /ledger/apply` — `{ "events": [...] }` or a transcript.
- `GET /ledger/summary` — per-customer total and per-day totals.
- `GET /ledger/events?limit=100` — recent immutable event records.
- `POST /tts` — text response with `audio_available: false` until Timbre is wired.
- `WS /stream` — send a text frame containing `{"transcript":"..."}`. For
  local testing, the server returns transcript, TTS text, and ledger result JSON.

An audio binary WebSocket frame receives `provider_unavailable` until the
Gnani Prisma adapter is implemented. Query utterances are answered from local
SQL without an LLM call. This backend is a development-ready foundation, not a
production deployment: configure authentication, restrictive CORS, provider
adapters, encrypted storage, retention, and operational monitoring before
handling real customer data.
