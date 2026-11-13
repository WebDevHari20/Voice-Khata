# Voice Khata system architecture

This diagram describes the implementation that is currently in the repository. The Gemini fallback from the original concept is **not wired into the live path**.

## System view

```mermaid
flowchart LR
  subgraph Device[Shopkeeper device]
    PWA[React PWA\nPush-to-talk and hands-free mic\nTyped phrase fallback]
    BrowserSpeech[Browser Hindi speech synthesis\nFast query answers and TTS fallback]
    SQLite[(SQLite\nbackend/data/ledger.db)]
    Events[(events\nappend-only ledger history)]
    Preferences[(customer_preferences\nreminder opt-in)]
    PWA -->|query text / fallback speech| BrowserSpeech
    SQLite --- Events
    SQLite --- Preferences
  end

  subgraph API[FastAPI backend]
    WS[WebSocket /stream]
    HTTP[REST API]
    STT[STT stream adapter]
    Normalize[Hindi / Hinglish number normalizer]
    Rules[Rule-based intent and entity parser]
    Router[Command router\nquery, entry, correction, settlement]
    Ledger[Ledger operations\nbalances, audit links, SQL queries]
    Reminder[Reminder consent gate\nand polite preview]
    Export[XLSX workbook generator\nBalances + Event History]
    TTS[Timbre TTS adapter\nstock voice]
  end

  Prisma[(Gnani Prisma STT API)]
  Timbre[(Gnani Timbre TTS API)]
  Gemini[Gemini parsing\nplanned only; not active]
  Contact[SMS / WhatsApp\nnot configured]

  PWA -->|16 kHz mono PCM frames| WS
  WS --> STT -->|audio stream| Prisma
  Prisma -->|final transcript| STT --> WS
  WS --> Normalize --> Rules --> Router
  Router --> Ledger --> SQLite
  Ledger -->|query result JSON immediately| WS --> PWA
  WS -->|entry result / clarification| PWA
  WS --> TTS --> Timbre
  Timbre -->|audio_chunk| WS --> PWA
  TTS -.->|provider unavailable: tts_text| WS
  PWA -->|device voice fallback| BrowserSpeech

  PWA -->|summary, events, consent, export| HTTP
  HTTP --> Ledger
  HTTP --> Reminder --> Preferences
  Reminder -.->|preview only; no delivery| Contact
  HTTP --> Export --> SQLite
  Gemini -. not called .-> Rules
```

## Voice entry path

```mermaid
sequenceDiagram
  participant User as Shopkeeper
  participant PWA as React PWA
  participant API as FastAPI /stream
  participant STT as Prisma STT
  participant NLU as Local normalizer + rules
  participant DB as SQLite ledger
  participant TTS as Timbre / device voice

  User->>PWA: Press mic and speak
  PWA->>API: PCM16 audio frames over WebSocket
  API->>STT: Stream audio
  STT-->>API: Final transcript
  API->>NLU: Normalize numbers, parse intent and customer
  NLU-->>API: Query, event, or clarification
  alt Balance query
    API->>DB: Read customer or daily balance
    DB-->>API: Result
    API-->>PWA: Query result immediately
    PWA->>TTS: Speak with browser Hindi voice
  else New event at or below ₹1,000
    API->>DB: Append credit or payment event
    API->>TTS: Generate spoken acknowledgement
  else Event above ₹1,000 or ambiguous intent/name
    API-->>PWA: Ask for confirmation or a full customer name
    User->>PWA: Confirm or clarify by voice
    PWA->>API: Follow-up transcript over WebSocket
    API->>DB: Append only after required confirmation
  end
  TTS-->>PWA: Audio, or text fallback for device speech
```

## Ledger and guardrails

- Credits, payments, corrections, and settlements are stored as ledger events. A correction appends a replacement event linked to the event it corrects; it does not overwrite the original.
- A payment reduces the customer's balance. When a full-repayment command is recognized, the backend records a payment for the outstanding balance. Zero-balance customers are omitted from the active balance view; event history remains.
- Ordinary entries up to ₹1,000 are committed without a confirmation prompt. Larger entries require confirmation. Ambiguous customer prefixes retain the draft until the shopkeeper chooses a full name.
- Balance queries use local SQL and do not call Gemini. Browser speech synthesis speaks query results immediately when available; Timbre is used for other spoken output, with a device voice fallback.
- Reminder preferences are stored per customer. The backend can prepare a fixed, polite message only after opt-in and only when a balance is owed. It does not send SMS or WhatsApp messages because no delivery provider is configured.
- The workbook export is generated locally from balances and the full event history. `Open in Excel` uses the desktop `ms-excel:` protocol when installed; `Download Excel` is the browser fallback.
- SQLite is local-first and the backend is started on `127.0.0.1`. A remote deployment needs authentication and encrypted storage.

## Interfaces

| Interface | Purpose |
| --- | --- |
| `WS /stream` | Audio in, transcripts, clarifications, ledger results, and spoken response audio out |
| `GET /ledger/summary` | Active customer balances and per-day totals |
| `GET /ledger/events` | Recent ledger event history |
| `GET /ledger/export.xlsx` | Excel workbook with `Balances` and `Event History` sheets |
| `POST /parse` | Inspect a transcript with the local rule parser |
| `POST /ledger/apply` | Apply explicit ledger events or parsed transcript data |
| `GET/PUT /customers/{customer_name}/reminder-consent` | Read or update reminder opt-in state |
| `POST /reminders/prepare` | Prepare a polite reminder preview after consent; no message is sent |
| `POST /tts` | Request Timbre audio for text |

## Current limits

Prisma recognition quality depends on its model, the microphone, and shop noise. Its current transcript event does not provide a numeric confidence score, so automatic confidence scoring is unavailable on that provider path. There is no active Gemini fallback, messaging delivery service, remote authentication, or encrypted remote database configuration.
