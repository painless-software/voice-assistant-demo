# Voice Assistant Demo – task runner
# Run `just` to see available recipes.
# Requires: uv, just, ngrok (for dev)

set dotenv-load := true
set shell := ["bash", "-euo", "pipefail", "-c"]

port := env("PORT", "8080")

# ── Default ────────────────────────────────────────────────────────────────────

# Show this usage screen (default)
@help:
    just --list --unsorted

# ── Setup ──────────────────────────────────────────────────────────────────────

# Copy .env.example -> .env (skip if .env already exists)
[group('setup')]
init-env:
    @if [ -f .env ]; then \
        echo ".env already exists – skipping"; \
    else \
        cp .env.example .env; \
        echo "Created .env from .env.example – fill in your secrets before running."; \
    fi

# List all Twilio phone numbers on your account
[group('setup')]
twilio-list:
    uv run python -m voice_assistant.twilio_ops --list-numbers

# Buy a new Twilio phone number  (PUBLIC_URL must be set in .env)
[group('setup')]
twilio-buy country="CH":
    uv run python -m voice_assistant.twilio_ops --buy \
        --country {{ country }} \
        --webhook "${PUBLIC_URL}/voice"

# Update the voice webhook on an existing Twilio number
[group('setup')]
twilio-set-webhook phone:
    uv run python -m voice_assistant.twilio_ops \
        --update-webhook {{ phone }} "${PUBLIC_URL}/voice"

# ── Development ────────────────────────────────────────────────────────────────

# ADK web UI (test agent without Twilio)
[group('dev')]
web: clean
    uv run adk web .

# ADK terminal UI (test agent without Twilio)
[group('dev')]
repl:
    uv run adk run voice_assistant

# Start the server locally (no ngrok) – PUBLIC_URL must be set in .env
[group('dev')]
serve:
    uv run python -m voice_assistant

# Start ngrok tunnel + server (full dev flow)
[group('dev')]
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    PORT="${PORT:-{{ port }}}"

    if ! command -v ngrok &>/dev/null; then
      echo "ERROR: ngrok not found. Install it from https://ngrok.com/download"
      exit 1
    fi

    pkill -f "ngrok http ${PORT}" 2>/dev/null || true
    sleep 1

    echo "Starting ngrok on port ${PORT}…"
    ngrok http "${PORT}" --log=stdout > /tmp/ngrok.log 2>&1 &
    NGROK_PID=$!

    PUBLIC_URL=""
    for i in $(seq 1 20); do
      PUBLIC_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
        | python3 -c \
            "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" \
            2>/dev/null || true)
      if [[ "$PUBLIC_URL" == https://* ]]; then break; fi
      sleep 1
    done

    if [[ -z "$PUBLIC_URL" ]]; then
      echo "ERROR: Could not determine ngrok public URL. Check /tmp/ngrok.log"
      kill $NGROK_PID 2>/dev/null || true
      exit 1
    fi

    echo "ngrok public URL: ${PUBLIC_URL}"

    if grep -q "^PUBLIC_URL=" .env; then
      sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=${PUBLIC_URL}|" .env
    else
      echo "PUBLIC_URL=${PUBLIC_URL}" >> .env
    fi

    echo ""
    echo "───────────────────────────────────────────────────────"
    echo "  Webhook URL for Twilio:  ${PUBLIC_URL}/voice"
    echo "  WebSocket URL:           wss://$(echo "$PUBLIC_URL" | sed 's|https://||')/ws/media-stream"
    echo "───────────────────────────────────────────────────────"
    echo ""

    trap "kill $NGROK_PID 2>/dev/null; echo 'Stopped.'" EXIT INT TERM
    PUBLIC_URL="${PUBLIC_URL}" uv run python -m voice_assistant

# ── Quality ────────────────────────────────────────────────────────────────────

# Lint + format check with ruff
[group('quality')]
lint:
    uv run ruff check voice_assistant/ tests/
    uv run ruff format --check voice_assistant/ tests/

# Auto-fix lint issues and format in place
[group('quality')]
fmt:
    uv run ruff check --fix voice_assistant/ tests/
    uv run ruff format voice_assistant/ tests/

# Type-check with pyright
[group('quality')]
typecheck:
    uv run pyright voice_assistant/

# Run tests with coverage
[group('quality')]
test *args:
    uv run pytest --cov=voice_assistant --cov-report=term-missing {{ args }}

# Remove bytecode, caches, and build artifacts
[group('lifecycle')]
clean:
    uvx pyclean . -d all
