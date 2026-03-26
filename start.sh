#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh  –  dev launcher for the voice assistant
#
# What it does:
#   1. Starts ngrok to get a public HTTPS URL
#   2. Writes PUBLIC_URL to .env
#   3. Starts the FastAPI server via uv run
#
# Prerequisites:
#   • uv  (https://docs.astral.sh/uv/getting-started/installation/)
#   • ngrok installed and authenticated (ngrok config add-authtoken <token>)
#   • .env file with at minimum TWILIO_* and GOOGLE_API_KEY set
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PORT="${PORT:-8080}"

# ── .env bootstrap ────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example – please fill in your secrets, then re-run."
  exit 1
fi

# ── ngrok ─────────────────────────────────────────────────────────────────────
if ! command -v ngrok &>/dev/null; then
  echo "ERROR: ngrok not found. Install it from https://ngrok.com/download"
  exit 1
fi

# Kill any previous ngrok instance on this port
pkill -f "ngrok http ${PORT}" 2>/dev/null || true
sleep 1

echo "Starting ngrok on port ${PORT}…"
ngrok http "${PORT}" --log=stdout > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!

# Wait for ngrok to be ready and fetch the public URL
PUBLIC_URL=""
for i in $(seq 1 20); do
  PUBLIC_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
    | uv run --no-project python3 -c \
        "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" \
        2>/dev/null || true)
  if [[ "$PUBLIC_URL" == https://* ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "ERROR: Could not determine ngrok public URL. Check /tmp/ngrok.log"
  kill $NGROK_PID 2>/dev/null || true
  exit 1
fi

echo "ngrok public URL: ${PUBLIC_URL}"

# Persist PUBLIC_URL in .env
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

# ── FastAPI server via uv run ─────────────────────────────────────────────────
trap "kill $NGROK_PID 2>/dev/null; echo 'Stopped.'" EXIT INT TERM

PUBLIC_URL="${PUBLIC_URL}" uv run python -m voice_assistant
