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
from google.adk.events.event import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import root_agent
from .audio import gemini_pcm_to_twilio_mulaw_b64, twilio_mulaw_to_gemini_pcm
from .config import FAREWELL_PHRASES, settings
from .elevenlabs_tts import ElevenLabsTTS

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

    use_elevenlabs = settings.voice_backend == "elevenlabs"

    if use_elevenlabs:
        run_config = RunConfig(response_modalities=["TEXT"])
    else:
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

    tts: ElevenLabsTTS | None = None
    if use_elevenlabs:
        tts = ElevenLabsTTS()
        # Eagerly open the ElevenLabs WebSocket so the TLS+WS handshake
        # completes concurrently with ADK session setup rather than blocking
        # the first audio chunk.
        await tts.connect(
            voice_id=profile["elevenlabs_voice_id"],
            model_id=settings.elevenlabs_model_id,
            api_key=settings.elevenlabs_api_key,
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
            tts=tts,
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
# ADK -> Twilio direction: per-event helpers
# ---------------------------------------------------------------------------


class _CallLoopState:
    """Mutable state shared across per-event helpers in ``_adk_to_twilio``."""

    __slots__ = ("draining", "interrupt_latched")

    def __init__(self) -> None:
        self.draining: bool = False
        # Set when a Twilio ``clear`` has been delivered. While set,
        # stale agent audio and farewell phrases are dropped until the
        # caller's next turn clears the latch.
        self.interrupt_latched: bool = False


def _process_input_transcription(event: Event, state: _CallLoopState) -> None:
    """Log caller speech and clear drain / interrupt latch on new user turn."""
    if not (hasattr(event, "input_transcription") and event.input_transcription):
        return
    if not (
        hasattr(event.input_transcription, "text") and event.input_transcription.text
    ):
        return
    log.info("User said: %s", event.input_transcription.text)
    if state.draining:
        log.info("Caller spoke during goodbye — cancelling drain")
        state.draining = False
    state.interrupt_latched = False


async def _handle_interrupt(
    event: Event,
    state: _CallLoopState,
    ws: WebSocket,
    sid_holder: list[str | None],
    tts: ElevenLabsTTS | None = None,
) -> bool:
    """Send Twilio ``clear`` on barge-in. Returns True to skip the event."""
    if not getattr(event, "interrupted", None):
        return False
    if not state.interrupt_latched:
        stream_sid = sid_holder[0]
        if stream_sid:
            log.info("Caller interrupted agent — clearing Twilio buffer")
            await ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))
            state.interrupt_latched = True
        else:
            log.info("Caller interrupted but streamSid not available yet")
        # Only tear down the TTS session on the leading-edge interrupt;
        # repeat "interrupted" events within the same barge-in window
        # should not re-close an already-closed socket.
        if tts is not None:
            await tts.interrupt()
    state.draining = False
    return True


def _mark_draining_if_farewell(text: str, state: _CallLoopState) -> None:
    """Set ``state.draining`` when ``text`` contains a farewell phrase."""
    if not text:
        return
    log.debug("Agent said: %s", text)
    if not state.draining and any(fp in text.lower() for fp in FAREWELL_PHRASES):
        log.info("Farewell phrase detected in agent speech — draining")
        state.draining = True


def _detect_farewell(event: Event, state: _CallLoopState) -> None:
    """Detect farewell phrases in the Gemini audio-mode output transcription."""
    transcription = getattr(event, "output_transcription", None)
    text = getattr(transcription, "text", None) if transcription else None
    if text:
        _mark_draining_if_farewell(text, state)


def _detect_farewell_from_text(event: Event, state: _CallLoopState) -> None:
    """Detect farewell phrases in text-mode content (ElevenLabs path)."""
    _mark_draining_if_farewell(_extract_text(event), state)


async def _send_pcm_chunk(
    ws: WebSocket,
    sid_holder: list[str | None],
    pcm: bytes,
    mark_name: str | None = None,
) -> bool:
    """Forward one PCM chunk to Twilio as mulaw. Returns True if sent."""
    stream_sid = sid_holder[0]
    if not stream_sid:
        await asyncio.sleep(0.05)
        stream_sid = sid_holder[0]
    if not stream_sid:
        log.debug("No stream SID yet, dropping audio chunk")
        return False

    mulaw_b64 = gemini_pcm_to_twilio_mulaw_b64(pcm)
    await ws.send_text(
        json.dumps(
            {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": mulaw_b64},
            }
        )
    )
    if mark_name:
        await ws.send_text(
            json.dumps(
                {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": mark_name},
                }
            )
        )
    return True


async def _relay_audio(
    event: Event,
    ws: WebSocket,
    sid_holder: list[str | None],
) -> bool:
    """Forward audio from ADK to Twilio. Returns True if audio was sent."""
    has_audio = False
    if not (event.content and event.content.parts):
        return has_audio
    for part in event.content.parts:
        if not (part.inline_data and part.inline_data.data):
            continue
        if await _send_pcm_chunk(
            ws, sid_holder, part.inline_data.data, mark_name="adk-chunk"
        ):
            has_audio = True
    return has_audio


def _extract_text(event: Event) -> str:
    """Extract text content from an ADK event's parts (used in text mode)."""
    if not (event.content and event.content.parts):
        return ""
    return "".join(part.text for part in event.content.parts if part.text)


async def _tts_audio_to_twilio(
    tts: ElevenLabsTTS,
    ws: WebSocket,
    sid_holder: list[str | None],
) -> None:
    """Background task: read PCM audio from ElevenLabs and forward to Twilio."""
    async for pcm_chunk in tts.receive_audio():
        # No mark on TTS chunks — unlike the goodbye-done mark, these have
        # no consumer and Twilio echoes them back as noise events.
        await _send_pcm_chunk(ws, sid_holder, pcm_chunk)


async def _finish_drain(
    ws: WebSocket,
    sid_holder: list[str | None],
    call_end_event: asyncio.Event,
) -> None:
    """Send the goodbye-done mark and signal call termination."""
    log.info("Goodbye audio fully sent — sending final mark")
    stream_sid = sid_holder[0]
    if stream_sid:
        await ws.send_text(
            json.dumps(
                {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "goodbye-done"},
                }
            )
        )
    call_end_event.set()


# ---------------------------------------------------------------------------
# ADK -> Twilio direction: main loop
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
    tts: ElevenLabsTTS | None = None,
) -> None:
    state = _CallLoopState()
    tts_receiver: asyncio.Task | None = None
    try:
        async for event in runner.run_live(
            user_id=user_id,
            session_id=session_id,
            live_request_queue=live_queue,
            run_config=run_config,
        ):
            _process_input_transcription(event, state)

            if await _handle_interrupt(event, state, ws, sid_holder, tts=tts):
                await _cancel_tts_receiver(tts_receiver)
                tts_receiver = None
                continue
            if state.interrupt_latched:
                continue

            if tts is not None:
                # ElevenLabs text-mode path
                _detect_farewell_from_text(event, state)
                text = _extract_text(event)
                if text:
                    # Reconnect after a prior barge-in closed the socket.
                    if not tts.is_connected:
                        profile = settings.language_profile()
                        await tts.connect(
                            voice_id=profile["elevenlabs_voice_id"],
                            model_id=settings.elevenlabs_model_id,
                            api_key=settings.elevenlabs_api_key,
                        )
                    # Receiver is (re)started once per TTS session —
                    # either on the very first text chunk of the call, or
                    # after a post-interrupt reconnect.
                    if tts_receiver is None or tts_receiver.done():
                        tts_receiver = asyncio.create_task(
                            _tts_audio_to_twilio(tts, ws, sid_holder)
                        )
                    await tts.send_text(text)

                if state.draining:
                    await tts.flush()
                    if tts_receiver:
                        await tts_receiver
                        tts_receiver = None
                    await _finish_drain(ws, sid_holder, call_end_event)
                    break
            else:
                # Gemini native-audio path
                _detect_farewell(event, state)
                has_audio = await _relay_audio(event, ws, sid_holder)

                if state.draining and not has_audio:
                    await _finish_drain(ws, sid_holder, call_end_event)
                    break

            if call_end_event.is_set():
                break

    except asyncio.CancelledError:
        log.debug("adk->twilio task cancelled (call ending)")
    except WebSocketDisconnect:
        log.debug("Twilio WebSocket disconnected during send")
    except Exception as exc:
        log.error("Error in adk->twilio loop: %s", exc)
    finally:
        if tts is not None:
            await tts.interrupt()
        await _cancel_tts_receiver(tts_receiver)


async def _cancel_tts_receiver(task: asyncio.Task | None) -> None:
    """Cancel a TTS receiver task and wait for it to fully unwind.

    Awaiting the cancellation prevents one final ``ws.send_text`` from
    firing after a Twilio ``clear`` (audible bleed on barge-in) and
    prevents zombie tasks from piling up under load.
    """
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
