# Voice Assistant Demo -- task runner
# Run `just` to see available recipes.
# Requires: uv, just, ngrok (for dev)

set dotenv-load := true
set dotenv-required := true

port := env("PORT", "8080")

# ── Default ────────────────────────────────────────────────────────────────────

# Show this usage screen (default)
@help:
    just --list --unsorted

# ── Setup ──────────────────────────────────────────────────────────────────────

# List all Twilio phone numbers on your account
[group('setup')]
twilio-list:
    uv run python -m voice_assistant.dev.twilio --list-numbers

# Buy a new Twilio phone number (PUBLIC_URL must be set in .env)
[group('setup')]
twilio-buy country="CH":
    uv run python -m voice_assistant.dev.twilio --buy \
        --country {{ country }} \
        --webhook "${PUBLIC_URL}/voice"

# Update the voice webhook on an existing Twilio number
[group('setup')]
twilio-set-webhook phone:
    uv run python -m voice_assistant.dev.twilio \
        --update-webhook {{ phone }} "${PUBLIC_URL}/voice"

# ── Development ────────────────────────────────────────────────────────────────

# ADK web UI (test agent without Twilio)
[group('dev')]
adk: clean
    uv run adk web .

# ADK terminal REPL (test agent without Twilio)
[group('dev')]
repl:
    uv run adk run voice_assistant

# Start the server locally (no ngrok) -- PUBLIC_URL must be set in .env
[group('dev')]
serve:
    uv run python -m voice_assistant

# Start ngrok tunnel + server (full dev flow)
[group('dev')]
dev:
    uv run python -m voice_assistant.dev.ngrok

# ── Testing ────────────────────────────────────────────────────────────────────

# Run the test suite
[group('testing')]
test: pytest eval

# Run unit tests with coverage
[group('testing')]
pytest *args:
    uv run pytest --cov {{ args }}

# Run ADK evaluation tests
[group('testing')]
[env("PYTHONWARNINGS", "ignore::UserWarning")]
eval:
    uv run adk eval voice_assistant tests/evals/*.evalset.json

# ── Quality ────────────────────────────────────────────────────────────────────

# Run all checks (lint, types)
[group('quality')]
check: lint types

# Type-check with pyright
[group('quality')]
types:
    uv run pyright voice_assistant/

# Lint + format check with ruff
[group('quality')]
lint:
    uvx ruff check voice_assistant/
    uvx ruff format --check voice_assistant/

# Auto-fix lint issues and format in place
[group('quality')]
fmt:
    uvx ruff check --fix voice_assistant/
    uvx ruff format voice_assistant/

# Clean up Python bytecode, test and build artifacts
[group('lifecycle')]
clean *args:
    uvx pyclean . -d all {{ args }}
