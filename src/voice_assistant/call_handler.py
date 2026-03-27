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

    lang_code = settings.default_language
    call_end_event = asyncio.Event()

    async with GeminiSession(lang_code=lang_code) as gemini:
        _sid_holder: list = [None]
        twilio_to_gemini_task = asyncio.create_task(
            _twilio_to_gemini(websocket, gemini, _sid_holder, call_end_event)
        )
        gemini_to_twilio_task = asyncio.create_task(
            _gemini_to_twilio(websocket, gemini, _sid_holder, call_end_event)
        )

        done, pending = await asyncio.wait(
            [twilio_to_gemini_task, gemini_to_twilio_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await websocket.close()
    log.info("Media stream handler finished [stream_sid=%s]", _sid_holder[0])


# ---------------------------------------------------------------------------
# Twilio → Gemini direction
# ---------------------------------------------------------------------------


async def _twilio_to_gemini(
    ws: WebSocket,
    gemini: GeminiSession,
    sid_holder: list,
    call_end_event: asyncio.Event,
) -> None:
    try:
        while True:
            if call_end_event.is_set():
                log.info("Call ended by caller request")
                break

            raw = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                log.debug("Twilio stream connected event")

            elif event == "start":
                sid_holder[0] = msg["streamSid"]
                log.info("Twilio stream started [sid=%s]", sid_holder[0])

            elif event == "media":
                payload_b64 = msg["media"]["payload"]
                pcm_16k = twilio_mulaw_to_gemini_pcm(payload_b64)
                await gemini.send_audio(pcm_16k)

            elif event == "stop":
                log.info("Twilio stream stopped")
                break

    except asyncio.TimeoutError:
        pass
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
    call_end_event: asyncio.Event,
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
                if gemini.call_end_requested:
                    log.info("Caller indicated no need to continue conversation")
                    call_end_event.set()
                    return

                stream_sid = sid_holder[0]
                if not stream_sid:
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

                mark_msg = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "gemini-chunk"},
                }
                await ws.send_text(json.dumps(mark_msg))

            if gemini.call_end_requested:
                log.info("Caller indicated no need to continue conversation")
                call_end_event.set()
                break

            log.debug("Gemini audio stream paused, re-entering receive loop")

    except asyncio.CancelledError:
        log.debug("gemini→twilio task cancelled (call ending)")
    except WebSocketDisconnect:
        log.debug("Twilio WebSocket disconnected during send")
    except Exception as exc:
        log.error("Error in gemini→twilio loop: %s", exc)
