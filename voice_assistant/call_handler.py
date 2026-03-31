"""
Handles a single Twilio Media Stream WebSocket connection via Google ADK.

Flow per call
─────────────
  1. Twilio dials in -> POST /voice  ->  TwiML <Connect><Stream> response
  2. Twilio opens WS  -> ws://<host>/ws/media-stream
  3. We create an ADK Runner with a LiveRequestQueue
  4. Caller audio   -> convert mulaw->PCM -> LiveRequestQueue (realtime blob)
  5. ADK events     -> extract PCM audio  -> convert PCM->mulaw -> Twilio
  6. Call ends -> both sides close cleanly
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types

from google.adk.runners import InMemoryRunner
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig

from .agent import root_agent
from .audio import twilio_mulaw_to_gemini_pcm, gemini_pcm_to_twilio_mulaw_b64
from .config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Goodbye detection
# ---------------------------------------------------------------------------

GOODBYE_PATTERNS = [
    re.compile(r"\bgoodbye\b", re.IGNORECASE),
    re.compile(r"\bno\s+need\s+to\s+continue\b", re.IGNORECASE),
    re.compile(r"\bno\s+need\s+for\b", re.IGNORECASE),
    re.compile(r"\bthat('s| is) all\b", re.IGNORECASE),
    re.compile(r"\bthat('s| is) it\b", re.IGNORECASE),
    re.compile(r"\bthat('s| is) everything\b", re.IGNORECASE),
    re.compile(r"\bcall\s+you\s+later\b", re.IGNORECASE),
    re.compile(r"\bsee\s+you\s+(later|again|soon)\b", re.IGNORECASE),
    re.compile(r"\bhave\s+a\s+(nice|good|great)\s+day\b", re.IGNORECASE),
    re.compile(r"\bbye\b", re.IGNORECASE),
    re.compile(r"\bthanks?\s+(for\s+calling|you\s+help)\b", re.IGNORECASE),
    re.compile(r"\btschüss(i)?\b", re.IGNORECASE),
    re.compile(r"\btschüß(i)?\b", re.IGNORECASE),
    re.compile(r"\bauf\s+wieder(s)?hören\b", re.IGNORECASE),
    re.compile(r"\bad[eéèêë](r)?\b", re.IGNORECASE),
    re.compile(r"\bciao\b", re.IGNORECASE),
    re.compile(r"\barrivederci\b", re.IGNORECASE),
    re.compile(r"\bmerci(\s+(beaucoup|tant))?\b", re.IGNORECASE),
    re.compile(r"\bdanke(\s+(schön|sehr))?\b", re.IGNORECASE),
    re.compile(r"\bgracias?\b", re.IGNORECASE),
    re.compile(r"\ba\s+rever\b", re.IGNORECASE),
    re.compile(r"\bnão\s+preciso\s+mais\b", re.IGNORECASE),
    re.compile(r"\bestá\s+bem(\s+assim)?\b", re.IGNORECASE),
]


def _is_goodbye(transcription: str) -> bool:
    """Return True if the transcription indicates the caller wants to end."""
    if not transcription:
        return False
    cleaned = transcription.strip().rstrip('.,!?;:"').lower()
    if any(pattern.search(cleaned) for pattern in GOODBYE_PATTERNS):
        return True
    if any(pattern.search(transcription.lower()) for pattern in GOODBYE_PATTERNS):
        return True
    return False


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


async def handle_media_stream(websocket: WebSocket) -> None:
    """Entry-point called by the FastAPI WebSocket route."""
    await websocket.accept()
    log.debug("Twilio Media Stream WebSocket connected")

    lang_code = settings.default_language
    profile = settings.language_profile(lang_code)
    call_end_event = asyncio.Event()

    runner = InMemoryRunner(agent=root_agent, app_name="voice_assistant")
    live_queue = LiveRequestQueue()

    run_config = RunConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=profile["voice_name"],
                )
            )
        ),
    )

    user_id = "twilio_caller"
    session_id = f"call_{uuid4().hex}"

    # Trigger greeting as first message
    live_queue.send_content(
        types.Content(
            role="user",
            parts=[types.Part(text="[SYSTEM] Greet the customer now.")],
        )
    )

    sid_holder: list[str | None] = [None]
    twilio_task = asyncio.create_task(
        _twilio_to_adk(websocket, live_queue, sid_holder, call_end_event)
    )
    adk_task = asyncio.create_task(
        _adk_to_twilio(
            websocket,
            runner,
            user_id,
            session_id,
            live_queue,
            run_config,
            sid_holder,
            call_end_event,
        )
    )

    done, pending = await asyncio.wait(
        [twilio_task, adk_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    live_queue.close()
    await websocket.close()
    log.info("Media stream handler finished [stream_sid=%s]", sid_holder[0])


# ---------------------------------------------------------------------------
# Twilio -> ADK direction
# ---------------------------------------------------------------------------


async def _twilio_to_adk(
    ws: WebSocket,
    live_queue: LiveRequestQueue,
    sid_holder: list[str | None],
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
                live_queue.send_realtime(
                    types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
                )

            elif event == "stop":
                log.info("Twilio stream stopped")
                break

    except asyncio.TimeoutError:
        pass
    except WebSocketDisconnect:
        log.debug("Twilio WebSocket disconnected")
    except Exception as exc:
        log.error("Error in twilio->adk loop: %s", exc)


# ---------------------------------------------------------------------------
# ADK -> Twilio direction
# ---------------------------------------------------------------------------


async def _adk_to_twilio(
    ws: WebSocket,
    runner: InMemoryRunner,
    user_id: str,
    session_id: str,
    live_queue: LiveRequestQueue,
    run_config: RunConfig,
    sid_holder: list[str | None],
    call_end_event: asyncio.Event,
) -> None:
    try:
        async for event in runner.run_live(
            user_id=user_id,
            session_id=session_id,
            live_request_queue=live_queue,
            run_config=run_config,
        ):
            # -- Goodbye detection via input transcription --
            if event.input_transcription and event.input_transcription.text:
                log.info("User said: %s", event.input_transcription.text)
                if _is_goodbye(event.input_transcription.text):
                    log.warning(
                        "Caller indicated end of conversation: %s",
                        event.input_transcription.text,
                    )
                    call_end_event.set()

            if event.output_transcription and event.output_transcription.text:
                log.debug("Agent said: %s", event.output_transcription.text)

            # -- Audio data --
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.inline_data and part.inline_data.data:
                        stream_sid = sid_holder[0]
                        if not stream_sid:
                            await asyncio.sleep(0.05)
                            stream_sid = sid_holder[0]
                        if not stream_sid:
                            log.debug("No stream SID yet, dropping audio chunk")
                            continue

                        mulaw_b64 = gemini_pcm_to_twilio_mulaw_b64(
                            part.inline_data.data
                        )
                        media_msg = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": mulaw_b64},
                        }
                        await ws.send_text(json.dumps(media_msg))

                        mark_msg = {
                            "event": "mark",
                            "streamSid": stream_sid,
                            "mark": {"name": "adk-chunk"},
                        }
                        await ws.send_text(json.dumps(mark_msg))

            if call_end_event.is_set():
                log.info("Ending ADK stream after goodbye")
                break

    except asyncio.CancelledError:
        log.debug("adk->twilio task cancelled (call ending)")
    except WebSocketDisconnect:
        log.debug("Twilio WebSocket disconnected during send")
    except Exception as exc:
        log.error("Error in adk->twilio loop: %s", exc)
