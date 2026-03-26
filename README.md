
# Customer Service Demo

A voice chat based on Twilio telephony infrastructure and a conversational interface
that supports Swiss German, French and Italian.

## Architecture

```
Caller → Twilio PSTN → Twilio Media Stream (WebSocket)
                              ↕  mulaw 8kHz
                       FastAPI server (this app)
                              ↕  PCM 16kHz / 24kHz
                       Gemini Live API (STT + LLM + TTS)
```

- **Twilio** handles the phone number and streams raw audio over WebSocket
- **Gemini 2.0 Flash Live** is a single model doing STT + conversation + TTS natively
- **FastAPI** glues them together and handles format conversion (mulaw ↔ PCM)

## Project structure

```
voice-assistant-demo/
├── src/voice_assistant/
│   ├── app.py            # FastAPI app – HTTP + WebSocket endpoints
│   ├── call_handler.py   # Per-call audio bridge (Twilio ↔ Gemini)
│   ├── gemini_session.py # Gemini Live API session wrapper
│   ├── audio.py          # mulaw/PCM format conversion utilities
│   └── config.py         # Settings loaded from .env
├── scripts/
│   └── provision_twilio.py  # Buy / configure Twilio phone number
├── pyproject.toml
├── .env.example
└── start.sh              # Dev launcher (ngrok + server)
```

## Setup

### 1. Prerequisites

| Tool | Purpose |
|------|---------|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Python + dependency management |
| [just](https://just.systems/man/en/) | Task runner |
| [ngrok](https://ngrok.com/download) | Expose localhost to Twilio |
| Twilio account | Phone number + webhooks |
| Google AI Studio key **or** Google Cloud project | Gemini Live API |

### 2. Configure secrets

```bash
just init-env      # copies .env.example → .env (skips if .env exists)
# Edit .env and fill in your credentials
```

Minimum `.env` for Google AI Studio (easiest):
```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+41xxxxxxxxx
GOOGLE_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEFAULT_LANGUAGE=de-CH
```

For Vertex AI instead of AI Studio, leave `GOOGLE_API_KEY` empty and set:
```
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
# Then authenticate: gcloud auth application-default login
```

### 3. Sync dependencies

```bash
just sync
```

`uv` resolves and installs everything – no manual venv creation needed.

### 4. Get a Twilio phone number

```bash
# List numbers already on your account
just twilio-list

# Buy a new Swiss number (run after `just dev` so PUBLIC_URL is in .env)
just twilio-buy           # defaults to country=CH
just twilio-buy country=US   # fallback if no CH numbers are available

# Or update the webhook on an existing number
just twilio-set-webhook +41XXXXXXXXX
```

> **Note**: Twilio may not always have local Swiss (+41) numbers available.
> If none are found, try `country=US` for testing, or buy a number manually
> in the [Twilio Console](https://console.twilio.com) and use `twilio-set-webhook`.

### 5. Start the server

```bash
just dev     # starts ngrok + FastAPI server (full dev flow)
```

`start.sh` (called by `just dev`) will:
1. Start ngrok and auto-detect the public HTTPS URL
2. Write `PUBLIC_URL` into `.env`
3. Print the webhook URL to configure in Twilio
4. Start the FastAPI server via `uv run`

To start without ngrok (when `PUBLIC_URL` is already set in `.env`):
```bash
just serve
```

### 6. Test it

Call your Twilio phone number. Gemini will greet you in Swiss German (or whichever
language you set as `DEFAULT_LANGUAGE`) and you can have a conversation.

## Languages

| Code | Language | Gemini voice |
|------|----------|-------------|
| `de-CH` | Swiss German | Leda |
| `fr-CH` | Swiss French | Aoede |
| `it-CH` | Swiss Italian | Zephyr |

Change `DEFAULT_LANGUAGE` in `.env` to switch the default.
Future work: detect the caller's preferred language via a DTMF IVR menu and
pass it as a custom parameter in the TwiML.

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/voice` | Twilio webhook – returns TwiML |
| `WS` | `/ws/media-stream` | Twilio Media Stream WebSocket |
| `GET` | `/docs` | Swagger UI |

## Roadmap (next steps)

- [ ] IVR language selection menu (press 1 for German, 2 for French, 3 for Italian)
- [ ] RAG: upload product PDFs → vector store → Gemini function calling
- [ ] Calendar integration: check free slots and book appointments via Google Calendar API
- [ ] Call recording and transcript logging
- [ ] Interruption / barge-in handling
- [ ] Docker / Cloud Run deployment

## Initial Prompt

I want to create a customer support hotline solution.
- There should be a phone number that I can call (e.g. Twilio).
- A friendly voice answers in Swiss German, Swiss French a Swiss Italian (e.g. Google Gemini).
- I can ask question and the voice answers politely.
- Later I want to add agent functionality and upload product documents to craft answers from, attach calendars to help with scheduling appointments with a sales person.

**Response:** see [SOLUTION](SOLUTION.md)
