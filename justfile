# Voice Assistant Demo – task runner
# Run `just` to see available recipes.
# Requires: uv, just, ngrok

set dotenv-load := true
set shell := ["bash", "-euo", "pipefail", "-c"]

port := env("PORT", "8080")

# ── Default ────────────────────────────────────────────────────────────────────

# Show this usage screen (default)
@help:
    just --list

# ── Setup ──────────────────────────────────────────────────────────────────────

# Copy .env.example → .env (skip if .env already exists)
[group('setup')]
init-env:
    @if [ -f .env ]; then \
        echo ".env already exists – skipping"; \
    else \
        cp .env.example .env; \
        echo "Created .env from .env.example – fill in your secrets before running."; \
    fi

# Sync dependencies declared in pyproject.toml (incl. dev extras)
[group('setup')]
sync:
    uv sync --extra dev

# Show resolved dependency tree
[group('setup')]
deps:
    uv tree

# Buy a new Twilio phone number  (PUBLIC_URL must be set in .env)
[group('setup')]
twilio-buy country="CH":
    uv run python scripts/provision_twilio.py --buy \
        --country {{ country }} \
        --webhook "${PUBLIC_URL}/voice"

# Update the voice webhook on an existing Twilio number
# Usage: just twilio-set-webhook +41XXXXXXXXX
[group('setup')]
twilio-set-webhook phone:
    uv run python scripts/provision_twilio.py \
        --update-webhook {{ phone }} "${PUBLIC_URL}/voice"

# ── Development ────────────────────────────────────────────────────────────────

# Start the server locally (no ngrok) – PUBLIC_URL must be set in .env
serve:
    uv run python -m voice_assistant

# Start ngrok tunnel + server (full dev flow)
dev:
    @bash start.sh

# ── Twilio utilities ───────────────────────────────────────────────────────────

# List all Twilio phone numbers on your account
twilio-list:
    uv run python scripts/provision_twilio.py --list-numbers

# ── Quality ────────────────────────────────────────────────────────────────────

# Run the test suite
test:
    uv run pytest -v

# Type-check with pyright
typecheck:
    uv run pyright src/

# Lint + format check with ruff
lint:
    uv run ruff check src/ scripts/
    uv run ruff format --check src/ scripts/

# Auto-fix lint issues and format in place
fmt:
    uv run ruff check --fix src/ scripts/
    uv run ruff format src/ scripts/
