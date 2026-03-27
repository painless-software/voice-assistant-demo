"""
Handles a single Twilio Media Stream WebSocket connection.

Flow per call
─────────────
  1. Twilio dials in → POST /voice  →  TwiML <Connect><Stream> response
  2. Twilio opens WS  → ws://<host>/ws/media-stream
  3. We open a Gemini Live session in parallel
  4. Caller audio   → convert mulaw→PCM → Gemini Live
  5. Gemini audio   → convert PCM→mulaw → send back to Twilio
  6. Call ends → both sides close cleanly
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from .audio import twilio_mulaw_to_gemini_pcm, gemini_pcm_to_twilio_mulaw_b64
from .gemini_session import GeminiSession
from .config import settings

log = logging.getLogger(__name__)


async def handle_media_stream(websocket: WebSocket) -> None:
    """Entry-point called by the FastAPI WebSocket route."""
    await websocket.accept()
    log.debug("Twilio Media Stream WebSocket connected")

    stream_sid: str | None = None
    lang_code = settings.default_language

    async with GeminiSession(lang_code=lang_code) as gemini:
        # Two concurrent tasks:
        #   A) receive audio from Twilio → forward to Gemini
        #   B) receive audio from Gemini → forward to Twilio
        #
        # The Twilio side (A) is the authority on call lifetime: it only
        # exits when the caller hangs up ("stop" event / WebSocket close).
        # The Gemini side (B) may temporarily run out of audio between
        # model turns, so we must NOT tear down when it finishes – we
        # wait for the Twilio side to close first.
        _sid_holder: list = [None]
        twilio_to_gemini_task = asyncio.create_task(
            _twilio_to_gemini(websocket, gemini, _sid_holder)
        )
        gemini_to_twilio_task = asyncio.create_task(
            _gemini_to_twilio(websocket, gemini, _sid_holder)
        )

        # Wait for the Twilio side to finish (caller hung up).
        try:
            await twilio_to_gemini_task
        except Exception as exc:
            log.error("twilio→gemini task raised: %s", exc)
        finally:
            gemini_to_twilio_task.cancel()
            try:
                await gemini_to_twilio_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.error("gemini→twilio task raised: %s", exc)

    log.info("Media stream handler finished [stream_sid=%s]", _sid_holder[0])


# ---------------------------------------------------------------------------
# Twilio → Gemini direction
# ---------------------------------------------------------------------------


async def _twilio_to_gemini(
    ws: WebSocket,
    gemini: GeminiSession,
    sid_holder: list,
) -> None:
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                log.debug("Twilio stream connected event")

            elif event == "start":
                sid_holder[0] = msg["streamSid"]
                log.info("Twilio stream started [sid=%s]", sid_holder[0])
                # Detect language from custom parameters if passed via TwiML
                custom = msg.get("start", {}).get("customParameters", {})
                # (language detection from DTMF/IVR can be added here later)

            elif event == "media":
                payload_b64 = msg["media"]["payload"]
                pcm_16k = twilio_mulaw_to_gemini_pcm(payload_b64)
                await gemini.send_audio(pcm_16k)

            elif event == "stop":
                log.info("Twilio stream stopped")
                break

    except WebSocketDisconnect:
        log.debug("Twilio WebSocket disconnected")
    except Exception as exc:
        log.error("Error in twilio→gemini loop: %s", exc)


# ---------------------------------------------------------------------------
# Gemini → Twilio direction
# ---------------------------------------------------------------------------


async def _gemini_to_twilio(
    ws: WebSocket,
    gemini: GeminiSession,
    sid_holder: list,
) -> None:
    """Forward Gemini audio to Twilio for the entire call.

    ``receive_audio()`` yields audio chunks and returns when the
    underlying receive loop pushes a ``None`` sentinel (e.g. when the
    Gemini ``receive()`` iterator exhausts between turns or on
    reconnect).  We wrap it in an outer ``while True`` so we
    immediately re-enter and keep waiting for the next model turn
    rather than exiting and leaving the caller in silence.

    The loop only exits on cancellation (caller hung up) or a fatal
    Twilio WebSocket error.
    """
    try:
        while True:
            async for pcm_24k in gemini.receive_audio():
                stream_sid = sid_holder[0]
                if not stream_sid:
                    # Wait briefly for the start event to populate the SID
                    await asyncio.sleep(0.05)
                    stream_sid = sid_holder[0]
                if not stream_sid:
                    log.debug("No stream SID yet, dropping audio chunk")
                    continue

                mulaw_b64 = gemini_pcm_to_twilio_mulaw_b64(pcm_24k)
                media_msg = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": mulaw_b64},
                }
                await ws.send_text(json.dumps(media_msg))

                # Send a mark so we know when playback finishes
                mark_msg = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "gemini-chunk"},
                }
                await ws.send_text(json.dumps(mark_msg))

            # receive_audio() returned (None sentinel) – the Gemini
            # receive loop may have restarted.  Keep waiting.
            log.debug("Gemini audio stream paused, re-entering receive loop")

    except asyncio.CancelledError:
        log.debug("gemini→twilio task cancelled (call ending)")
    except WebSocketDisconnect:
        log.debug("Twilio WebSocket disconnected during send")
    except Exception as exc:
        log.error("Error in gemini→twilio loop: %s", exc)
