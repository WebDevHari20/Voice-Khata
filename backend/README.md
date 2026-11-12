# Voice Khata backend

FastAPI backend for the Voice Khata ledger. It runs locally with a rule based
Hindi/Hinglish parser, append-only SQLite events, HTTP endpoints, and a
transcript-text WebSocket development path. Prisma v3.0 audio streaming and
Timbre v3.0 speech generation use Gnani's speech APIs. Gemini parsing remains
optional and is not called by the rule-first parser.

## Run

From the repository root in PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r backend\requirements.txt
if (!(Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
# Put the API key with both STT and TTS scopes in backend\.env as GNANI_API_KEY.
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
- `POST /tts` — synthesize text to a WAV response with Timbre.
- `WS /stream` — send raw mono PCM16 audio as 1,024-byte binary frames at the
  configured source sample rate; Prisma returns final transcript segments.
  A text frame containing `{"transcript":"..."}` remains available for local testing.

Query utterances are answered from local SQL without an LLM call. Prisma's
documented transcript messages do not carry a numeric confidence score; the
backend applies the confidence gate when a client supplies one. This backend is
a development-ready foundation, not a
production deployment: configure authentication, restrictive CORS, provider
adapters, encrypted storage, retention, and operational monitoring before
handling real customer data.
