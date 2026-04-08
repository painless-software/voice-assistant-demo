"""
Handles a single Twilio Media Stream WebSocket connection via Google ADK.

Flow per call
-------------
  1. Twilio dials in -> POST /voice -> TwiML <Connect><Stream> response
  2. Twilio opens WS -> ws://<host>/ws/media-stream
  3. We create an ADK Runner with a LiveRequestQueue
  4. Caller audio -> convert mulaw->PCM -> LiveRequestQueue (realtime blob)
  5. ADK events -> extract PCM audio -> convert PCM->mulaw -> Twilio
  6. Call ends -> both sides close cleanly
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import root_agent
from .audio import gemini_pcm_to_twilio_mulaw_b64, twilio_mulaw_to_gemini_pcm
from .config import settings

log = logging.getLogger(__name__)

# Max call duration (seconds) as safety timeout
MAX_CALL_DURATION = 5 * 60

# Max seconds to wait for Twilio to finish playing the goodbye audio
GOODBYE_GRACE_PERIOD = 10


async def handle_media_stream(websocket: WebSocket) -> None:
    """Entry-point called by the FastAPI WebSocket route."""
    await websocket.accept()
    log.debug("Twilio Media Stream WebSocket connected")

    profile = settings.language_profile()
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
    session = await runner.session_service.create_session(
        app_name="voice_assistant", user_id=user_id
    )
    session_id = session.id

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

    try:
        await asyncio.wait_for(
            asyncio.wait(
                [twilio_task, adk_task],
                return_when=asyncio.FIRST_COMPLETED,
            ),
            timeout=MAX_CALL_DURATION,
        )
    except asyncio.TimeoutError:
        log.warning("Call exceeded max duration (%ds), terminating", MAX_CALL_DURATION)

    for task in [twilio_task, adk_task]:
        if not task.done():
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
                # Wait for Twilio to finish playing the goodbye audio.
                log.info("Call ending — waiting for goodbye playback to finish")
                try:
                    await asyncio.wait_for(
                        _wait_for_goodbye_mark(ws),
                        timeout=GOODBYE_GRACE_PERIOD,
                    )
                except asyncio.TimeoutError:
                    log.warning(
                        "Goodbye grace period (%ds) expired", GOODBYE_GRACE_PERIOD
                    )
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


async def _wait_for_goodbye_mark(ws: WebSocket) -> None:
    """Read Twilio messages until the 'goodbye-done' mark is echoed back."""
    while True:
        raw = await ws.receive_text()
        msg = json.loads(raw)
        if (
            msg.get("event") == "mark"
            and msg.get("mark", {}).get("name") == "goodbye-done"
        ):
            log.info("Twilio confirmed goodbye playback complete")
            return
        if msg.get("event") == "stop":
            log.info("Twilio stream stopped while waiting for goodbye mark")
            return


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
    draining = False
    draining_audio_seen = False
    try:
        async for event in runner.run_live(
            user_id=user_id,
            session_id=session_id,
            live_request_queue=live_queue,
            run_config=run_config,
        ):
            # -- Detect end_call tool invocation --
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call and part.function_call.name == "end_call":
                        log.info(
                            "Agent invoked end_call tool — draining remaining audio"
                        )
                        draining = True

            # -- Transcription logging --
            if hasattr(event, "input_transcription") and event.input_transcription:
                if (
                    hasattr(event.input_transcription, "text")
                    and event.input_transcription.text
                ):
                    log.info("User said: %s", event.input_transcription.text)
                    # Caller spoke again while we were winding down — stay on
                    # the line and let the model handle the new input.
                    if draining:
                        log.info("Caller spoke during goodbye — cancelling drain")
                        draining = False
                        draining_audio_seen = False

            if hasattr(event, "output_transcription") and event.output_transcription:
                if (
                    hasattr(event.output_transcription, "text")
                    and event.output_transcription.text
                ):
                    log.debug("Agent said: %s", event.output_transcription.text)

            # -- Audio data --
            has_audio = False
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

                        has_audio = True
                        if draining:
                            draining_audio_seen = True
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

            # Once draining, we've heard goodbye audio, and this event has
            # none, the turn is done.  Without the audio_seen guard the loop
            # would break on the very first non-audio event after end_call
            # (e.g. the function_call event itself).
            if draining and draining_audio_seen and not has_audio:
                log.info("Goodbye audio fully sent — sending final mark")
                stream_sid = sid_holder[0]
                if stream_sid:
                    final_mark = {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": "goodbye-done"},
                    }
                    await ws.send_text(json.dumps(final_mark))
                call_end_event.set()
                break

            if call_end_event.is_set():
                log.info("Ending ADK stream after end_call")
                break

    except asyncio.CancelledError:
        log.debug("adk->twilio task cancelled (call ending)")
    except WebSocketDisconnect:
        log.debug("Twilio WebSocket disconnected during send")
    except Exception as exc:
        log.error("Error in adk->twilio loop: %s", exc)
