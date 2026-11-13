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

- `GET /health` â€” process health.
- `POST /parse` â€” `{ "transcript": "Ramesh ka 340 udhaar" }`.
- `POST /ledger/apply` â€” `{ "events": [...] }` or a transcript.
- `GET /ledger/summary` â€” per-customer total and per-day totals.
- `GET /ledger/events?limit=100` â€” recent immutable event records.
- `GET /ledger/export.xlsx` â€” Excel workbook with balances and full event history.
- `POST /tts` â€” synthesize text to a WAV response with Timbre.
- `WS /stream` â€” send raw mono PCM16 audio as 1,024-byte binary frames at the
  configured source sample rate; Prisma returns final transcript segments.
  A text frame containing `{"transcript":"..."}` remains available for local testing.
- Entries up to ?1,000 are appended after parsing; entries above ?1,000 ask for
  spoken or button confirmation. Corrections above that threshold also ask for
  confirmation. Say “nahi, 430” to revise an amount; a correction to a saved
  entry creates a replacement event with an audit link.
- Say “Ramesh ne abhi 200 diye” to append a payment and reduce Ramesh's balance.
  Say “Ramesh ne udhaar pura chuka diya” to append a payment for the full
  outstanding amount. Multiple names in the same phrase are supported. Settled
  customers disappear from the active balance list while their immutable event
  history remains available for audit.- Prisma receives a retail-ledger topic hint and up to 200 existing customer
  names as keyterms. Hands-free mode keeps the microphone session active until
  the shopkeeper turns it off or says â€œstop listening.â€

Query utterances are answered from local SQL without an LLM call. Prisma's
documented transcript messages do not carry a numeric confidence score; the
backend applies the confidence gate when a client supplies one. This backend is
a development-ready foundation, not a
production deployment: configure authentication, restrictive CORS, provider
adapters, encrypted storage, retention, and operational monitoring before
handling real customer data.

## Judging requirements and guardrails

- Browser microphone capture requests echo cancellation, noise suppression, and automatic gain control. Prisma is warmed when the voice socket is configured; amount aliases are handled locally after transcription. Accuracy in live shop noise still depends on the device microphone and Prisma's recognition result.
- Balance queries are answered from local SQLite without an LLM. Response text is returned immediately and spoken with the device's Hindi speech voice when available; Timbre is the browser fallback. End-to-end speech latency still depends on recognition and the device.
- Ambiguous customer prefixes pause for a short spoken choice and keep the draft until the shopkeeper names one customer.
- Reminder consent is stored per customer. `POST /reminders/prepare` returns a polite preview only after opt-in and only for an outstanding balance. There is no SMS or WhatsApp delivery configured, so this API never sends a reminder.
- The SQLite ledger is stored locally under `backend/data`. Keep the backend bound to localhost for the local-first setup; remote deployment needs authentication and encrypted storage before it handles real ledger data.
