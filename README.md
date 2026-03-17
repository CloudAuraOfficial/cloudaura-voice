# CloudAura Voice

AI-powered voice agent that handles inbound phone calls via Twilio, routes them through LiveKit SIP into a real-time voice pipeline (Deepgram STT, OpenAI LLM, configurable TTS), and logs every interaction to Airtable.

## Architecture

```mermaid
graph LR
    A[Phone Call] -->|PSTN| B[Twilio]
    B -->|POST /webhooks/twilio/voice| C[FastAPI<br/>voice_api]
    C -->|TwiML SIP Dial| D[LiveKit Cloud<br/>SIP Trunk]
    D -->|Room Join| E[Voice Worker<br/>voice_worker]

    subgraph "Voice Pipeline"
        E --> F[Silero VAD]
        F --> G[Deepgram STT<br/>nova-2-phonecall]
        G --> H[OpenAI LLM<br/>gpt-4o-mini]
        H --> I[TTS<br/>OpenAI nova /<br/>ElevenLabs]
    end

    I -->|Audio| D
    B -->|POST /webhooks/twilio/status| C
    E -->|Call complete| J[Airtable<br/>Interaction Logs]
    C --> K[/metrics<br/>Prometheus]

    style C fill:#e1f5fe
    style E fill:#fff3e0
    style J fill:#e8f5e9
```

## Quick Start

```bash
# Clone the repository
git clone https://github.com/CloudAuraOfficial/cloudaura-voice.git
cd cloudaura-voice

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys (LiveKit, Deepgram, OpenAI, Twilio, Airtable)

# Start both services
docker compose up -d
```

This starts two containers:
- **voice_api** (port 8005) -- FastAPI server for webhooks and health checks
- **voice_worker** -- LiveKit agent worker that joins rooms and runs the voice pipeline

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/health` | Health check (returns status + environment) | None |
| `GET` | `/` | Landing page (static HTML) | None |
| `GET` | `/metrics` | Prometheus metrics (auto-instrumented) | None |
| `POST` | `/webhooks/twilio/voice` | Twilio inbound call webhook -- returns TwiML to route call into LiveKit room via SIP | Twilio signature |
| `POST` | `/webhooks/twilio/status` | Twilio call status callback -- updates Airtable on terminal states (completed, failed, no-answer, busy, canceled) | Twilio signature |
| `POST` | `/webhooks/livekit/webhook` | LiveKit room event receiver (room_started, room_finished, participant_joined/left) | None |
| `GET` | `/docs` | OpenAPI docs (non-production only) | None |

## Tech Stack

| Component | Technology |
|-----------|------------|
| API Framework | FastAPI + Uvicorn |
| Voice Pipeline | LiveKit Agents SDK (`VoicePipelineAgent`) |
| VAD | Silero VAD (pre-loaded at import time) |
| STT | Deepgram `nova-2-phonecall` (en-US, punctuation, interim results) |
| LLM | OpenAI `gpt-4o-mini` (temperature 0.4) |
| TTS | OpenAI `nova` (default) or ElevenLabs `eleven_turbo_v2_5` (configurable) |
| Telephony | Twilio (SIP trunking to LiveKit Cloud) |
| Call Logging | Airtable (pyairtable SDK) |
| Metrics | prometheus-fastapi-instrumentator |
| Logging | structlog (structured JSON) |
| Configuration | pydantic-settings (`.env` file) |

## Configuration

All configuration is via environment variables (`.env` file).

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `LIVEKIT_URL` | LiveKit Cloud WebSocket URL | Yes | -- |
| `LIVEKIT_API_KEY` | LiveKit API key | Yes | -- |
| `LIVEKIT_API_SECRET` | LiveKit API secret | Yes | -- |
| `LIVEKIT_SIP_HOST` | LiveKit SIP hostname | No | `sip.livekit.cloud` |
| `DEEPGRAM_API_KEY` | Deepgram API key for STT | Yes | -- |
| `OPENAI_API_KEY` | OpenAI API key for LLM + TTS | Yes | -- |
| `OPENAI_MODEL` | OpenAI model for conversation | No | `gpt-4o-mini` |
| `TTS_PROVIDER` | TTS engine: `openai` or `elevenlabs` | No | `openai` |
| `ELEVENLABS_API_KEY` | ElevenLabs API key | No | -- |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice identifier | No | -- |
| `ELEVENLABS_MODEL_ID` | ElevenLabs model | No | `eleven_turbo_v2_5` |
| `TWILIO_ACCOUNT_SID` | Twilio account SID | Yes | -- |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | Yes | -- |
| `TWILIO_PHONE_NUMBER` | Twilio phone number (E.164) | Yes | -- |
| `AIRTABLE_API_KEY` | Airtable personal access token | Yes | -- |
| `AIRTABLE_BASE_ID` | Airtable base identifier | Yes | -- |
| `AIRTABLE_TABLE_NAME` | Airtable table for interactions | No | `Interactions` |
| `APP_HOST` | API bind host | No | `0.0.0.0` |
| `APP_PORT` | API bind port | No | `8000` |
| `ENVIRONMENT` | Runtime environment | No | `development` |
| `PUBLIC_BASE_URL` | Public-facing base URL | No | -- |
| `LOG_LEVEL` | Logging level | No | `INFO` |

## Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing
```

## Monitoring

- **Health check**: `GET /health` returns `{"status": "ok", "environment": "..."}`.
- **Prometheus metrics**: `GET /metrics` exposes auto-instrumented FastAPI request metrics.
- **Docker health check**: The `voice_api` container checks `http://localhost:8000/health` every 30s.
- **Structured logs**: All log output is JSON via structlog, including call lifecycle events (`twilio.inbound_call`, `agent.room_connected`, `agent.pipeline_started`, `agent.session_closed`).

### Call Flow Lifecycle

1. Inbound call hits Twilio, which POSTs to `/webhooks/twilio/voice`
2. API returns TwiML routing the call into a LiveKit room via SIP (`call_{CallSid}_{caller}`)
3. Voice worker joins the room, starts the voice pipeline (VAD + STT + LLM + TTS)
4. Transcript is accumulated in memory during the call
5. On disconnect, the full transcript and call metadata are persisted to Airtable
6. Twilio status callback updates the record with final duration and resolution status

## Project Structure

```
cloudaura-voice/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── app/
│   ├── main.py              # FastAPI app factory, Prometheus, exception handlers
│   ├── agent.py             # LiveKit voice agent (entrypoint, CallSession, pipeline)
│   ├── config.py            # pydantic-settings configuration
│   ├── logging_config.py    # structlog setup
│   ├── models/
│   │   └── schemas.py       # Pydantic models (HealthResponse, InteractionRecord, etc.)
│   ├── prompts/
│   │   └── system_prompt.py # Agent persona and greeting message
│   ├── routers/
│   │   ├── health.py        # GET /health
│   │   └── webhooks.py      # Twilio + LiveKit webhook handlers
│   ├── services/
│   │   ├── airtable_service.py  # Airtable CRUD for call interactions
│   │   └── twilio_service.py    # TwiML generation, signature validation
│   └── static/              # Landing page assets
└── tests/
```
