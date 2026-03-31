"""
FastAPI application – HTTP + WebSocket endpoints.

Endpoints
─────────
  POST /voice          Twilio webhook – returns TwiML that opens the Media Stream
  GET  /health         Health check
  WS   /ws/media-stream  Twilio sends real-time audio here
"""

from __future__ import annotations

import logging
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

from .call_handler import handle_media_stream
from .config import settings

log = logging.getLogger(__name__)

app = FastAPI(title="Voice Assistant Demo", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    settings.validate()
    log.info(
        "Voice Assistant started | default_lang=%s | public_url=%s",
        settings.default_language,
        settings.public_url or "(not set)",
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Twilio voice webhook  →  TwiML response
# ---------------------------------------------------------------------------


@app.post("/voice")
async def twilio_voice_webhook(request: Request) -> Response:
    """
    Twilio calls this when someone dials the phone number.
    We respond with TwiML telling Twilio to:
      1. Play a short hold tone while the WebSocket is set up
      2. Connect to our WebSocket Media Stream
    """
    form = await request.form()
    caller = form.get("From", "unknown")
    log.info("Incoming call from %s", caller)

    # Build the WebSocket URL from the public URL configured via env
    public_url = settings.public_url.rstrip("/")
    if public_url.startswith("https://"):
        ws_url = public_url.replace("https://", "wss://", 1)
    elif public_url.startswith("http://"):
        ws_url = public_url.replace("http://", "ws://", 1)
    else:
        ws_url = f"wss://{public_url}"

    ws_url = f"{ws_url}/ws/media-stream"

    twiml = _build_twiml(ws_url)
    return Response(content=twiml, media_type="application/xml")


def _build_twiml(ws_url: str) -> str:
    """
    Returns TwiML XML string:

    <?xml version="1.0" encoding="UTF-8"?>
    <Response>
      <Connect>
        <Stream url="wss://…/ws/media-stream" />
      </Connect>
    </Response>
    """
    response = Element("Response")
    connect = SubElement(response, "Connect")
    stream = SubElement(connect, "Stream")
    stream.set("url", ws_url)
    xml_bytes = tostring(response, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}'


# ---------------------------------------------------------------------------
# Twilio Media Stream WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws/media-stream")
async def media_stream_ws(websocket: WebSocket) -> None:
    await handle_media_stream(websocket)
