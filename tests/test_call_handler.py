"""Unit tests for call_handler — Twilio↔ADK bridge logic."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_assistant.call_handler import (
    _adk_to_twilio,
    _twilio_to_adk,
    _wait_for_goodbye_mark,
    handle_media_stream,
)

# Patch paths for call_handler module
_CH = "voice_assistant.call_handler"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _twilio_msg(event: str, **kwargs) -> str:
    """Build a JSON Twilio WS message."""
    msg = {"event": event, **kwargs}
    return json.dumps(msg)


def _make_event(
    *,
    audio_data: bytes | None = None,
    output_text: str | None = None,
    input_text: str | None = None,
    interrupted: bool | None = None,
) -> SimpleNamespace:
    """Build a fake ADK event with the requested attributes."""
    parts = []
    if audio_data is not None:
        parts.append(
            SimpleNamespace(
                inline_data=SimpleNamespace(data=audio_data),
                function_call=None,
            )
        )
    content = SimpleNamespace(parts=parts) if parts else SimpleNamespace(parts=[])

    output_transcription = None
    if output_text is not None:
        output_transcription = SimpleNamespace(text=output_text)

    input_transcription = None
    if input_text is not None:
        input_transcription = SimpleNamespace(text=input_text)

    return SimpleNamespace(
        content=content,
        output_transcription=output_transcription,
        input_transcription=input_transcription,
        interrupted=interrupted,
    )


async def _fake_run_live(events, **kwargs):
    """Async generator that yields pre-built events."""
    for e in events:
        yield e


# ---------------------------------------------------------------------------
# _wait_for_goodbye_mark
# ---------------------------------------------------------------------------


async def test_goodbye_mark_returns_on_mark():
    ws = AsyncMock()
    ws.receive_text.side_effect = [
        _twilio_msg("media", media={"payload": "abc"}),
        _twilio_msg("mark", mark={"name": "goodbye-done"}),
    ]
    await _wait_for_goodbye_mark(ws)
    assert ws.receive_text.call_count == 2


async def test_goodbye_mark_returns_on_stop():
    ws = AsyncMock()
    ws.receive_text.return_value = _twilio_msg("stop")
    await _wait_for_goodbye_mark(ws)


async def test_goodbye_mark_ignores_other_marks():
    ws = AsyncMock()
    ws.receive_text.side_effect = [
        _twilio_msg("mark", mark={"name": "adk-chunk"}),
        _twilio_msg("mark", mark={"name": "goodbye-done"}),
    ]
    await _wait_for_goodbye_mark(ws)
    assert ws.receive_text.call_count == 2


# ---------------------------------------------------------------------------
# _twilio_to_adk
# ---------------------------------------------------------------------------


@patch("voice_assistant.call_handler.twilio_mulaw_to_gemini_pcm", return_value=b"pcm")
async def test_twilio_forwards_media_to_live_queue(mock_convert):
    ws = AsyncMock()
    ws.receive_text.side_effect = [
        _twilio_msg("start", streamSid="SM1"),
        _twilio_msg("media", media={"payload": "AAAA"}),
        _twilio_msg("stop"),
    ]
    live_queue = MagicMock()
    sid_holder: list[str | None] = [None]
    call_end_event = asyncio.Event()

    await _twilio_to_adk(ws, live_queue, sid_holder, call_end_event)

    mock_convert.assert_called_once_with("AAAA")
    assert live_queue.send_realtime.call_count == 1
    blob = live_queue.send_realtime.call_args[0][0]
    assert blob.mime_type == "audio/pcm;rate=16000"


async def test_twilio_start_sets_sid():
    ws = AsyncMock()
    ws.receive_text.side_effect = [
        _twilio_msg("start", streamSid="SM-ABC"),
        _twilio_msg("stop"),
    ]
    sid_holder: list[str | None] = [None]

    await _twilio_to_adk(ws, MagicMock(), sid_holder, asyncio.Event())

    assert sid_holder[0] == "SM-ABC"


async def test_twilio_stop_breaks_loop():
    ws = AsyncMock()
    ws.receive_text.return_value = _twilio_msg("stop")
    live_queue = MagicMock()

    await _twilio_to_adk(ws, live_queue, [None], asyncio.Event())

    live_queue.send_realtime.assert_not_called()


async def test_twilio_connected_handled():
    ws = AsyncMock()
    ws.receive_text.side_effect = [
        _twilio_msg("connected"),
        _twilio_msg("stop"),
    ]

    await _twilio_to_adk(ws, MagicMock(), [None], asyncio.Event())


@patch("voice_assistant.call_handler._wait_for_goodbye_mark", new_callable=AsyncMock)
async def test_twilio_call_end_triggers_goodbye_wait(mock_wait):
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    call_end_event.set()

    await _twilio_to_adk(ws, MagicMock(), [None], call_end_event)

    mock_wait.assert_awaited_once_with(ws)


@patch("voice_assistant.call_handler.GOODBYE_GRACE_PERIOD", 0.01)
async def test_twilio_goodbye_timeout():
    ws = AsyncMock()

    # receive_text blocks forever — _wait_for_goodbye_mark never returns
    async def _hang():
        await asyncio.sleep(999)

    ws.receive_text = _hang
    call_end_event = asyncio.Event()
    call_end_event.set()

    await asyncio.wait_for(
        _twilio_to_adk(ws, MagicMock(), [None], call_end_event),
        timeout=2.0,
    )


async def test_twilio_receive_timeout_handled():
    ws = AsyncMock()
    ws.receive_text.side_effect = asyncio.TimeoutError()

    await _twilio_to_adk(ws, MagicMock(), [None], asyncio.Event())


async def test_twilio_generic_error_handled():
    ws = AsyncMock()
    ws.receive_text.side_effect = RuntimeError("boom")

    await _twilio_to_adk(ws, MagicMock(), [None], asyncio.Event())


async def test_twilio_websocket_disconnect_handled():
    from fastapi import WebSocketDisconnect

    ws = AsyncMock()
    ws.receive_text.side_effect = WebSocketDisconnect()

    await _twilio_to_adk(ws, MagicMock(), [None], asyncio.Event())


# ---------------------------------------------------------------------------
# _adk_to_twilio
# ---------------------------------------------------------------------------


def _run_adk(events, ws, sid_holder=None, call_end_event=None):
    """Helper to call _adk_to_twilio with mocked runner."""
    runner = MagicMock()
    runner.run_live = lambda **kw: _fake_run_live(events, **kw)
    return _adk_to_twilio(
        ws=ws,
        runner=runner,
        user_id="u",
        session_id="s",
        live_queue=MagicMock(),
        run_config=MagicMock(),
        sid_holder=sid_holder or ["SM-1"],
        call_end_event=call_end_event or asyncio.Event(),
    )


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="bXVsYXc=",
)
async def test_adk_audio_forwarded(mock_convert):
    ws = AsyncMock()
    events = [_make_event(audio_data=b"\x00\x01")]

    await _run_adk(events, ws)

    mock_convert.assert_called_once_with(b"\x00\x01")
    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    assert sent[0]["event"] == "media"
    assert sent[0]["streamSid"] == "SM-1"
    assert sent[0]["media"]["payload"] == "bXVsYXc="
    assert sent[1]["event"] == "mark"
    assert sent[1]["mark"]["name"] == "adk-chunk"


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_adk_audio_dropped_without_sid(mock_convert):
    ws = AsyncMock()
    events = [_make_event(audio_data=b"\x00")]

    with patch("voice_assistant.call_handler.asyncio.sleep", new_callable=AsyncMock):
        await _run_adk(events, ws, sid_holder=[None])

    ws.send_text.assert_not_called()


@pytest.mark.parametrize(
    "phrase",
    [
        "Auf Wiederhören!",
        "Adé!",
        "Au revoir et bonne journée!",
        "Arrivederci!",
        "Goodbye!",
    ],
)
@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_farewell_detection_triggers_drain(mock_convert, phrase):
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    events = [
        _make_event(output_text=phrase),
        _make_event(),  # empty event — triggers drain completion
    ]

    await _run_adk(events, ws, call_end_event=call_end_event)

    assert call_end_event.is_set()
    # Check goodbye-done mark was sent
    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    marks = [m for m in sent if m.get("mark", {}).get("name") == "goodbye-done"]
    assert len(marks) == 1


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_drain_cancelled_on_caller_speech(mock_convert):
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    events = [
        _make_event(output_text="Uf Wiederhöre!"),  # triggers drain
        _make_event(input_text="Wait, one more question"),  # cancels drain
        _make_event(),  # empty — but drain is cancelled, so loop continues
        _make_event(output_text="Goodbye!"),  # re-triggers drain
        _make_event(),  # completes drain
    ]

    await _run_adk(events, ws, call_end_event=call_end_event)

    assert call_end_event.is_set()


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_drain_not_triggered_without_farewell(mock_convert):
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    events = [
        _make_event(output_text="Wie chan ich Ihne hälfe?"),
        _make_event(audio_data=b"\x00"),
        _make_event(),
    ]

    await _run_adk(events, ws, call_end_event=call_end_event)

    assert not call_end_event.is_set()


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_goodbye_mark_has_correct_stream_sid(mock_convert):
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    events = [
        _make_event(output_text="Auf Wiederhören"),
        _make_event(),
    ]

    await _run_adk(events, ws, sid_holder=["SM-XYZ"], call_end_event=call_end_event)

    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    goodbye = [m for m in sent if m.get("mark", {}).get("name") == "goodbye-done"]
    assert goodbye[0]["streamSid"] == "SM-XYZ"


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_drain_cancel_resets_draining_state(mock_convert):
    """Verify lines 222-223: drain cancel log + draining = False."""
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    # Farewell with audio triggers drain, then caller input cancels it.
    # Because drain is cancelled, empty event does NOT end the call.
    # The loop ends naturally when events are exhausted.
    events = [
        _make_event(output_text="Adé!", audio_data=b"\x00"),  # drain ON, but has audio
        _make_event(input_text="Halt, no e Frag"),  # drain OFF
        _make_event(),  # empty — but drain is off, so no termination
    ]

    await _run_adk(events, ws, call_end_event=call_end_event)

    # call_end_event should NOT be set — drain was cancelled
    assert not call_end_event.is_set()


# ---------------------------------------------------------------------------
# Barge-in / interruption handling
# ---------------------------------------------------------------------------


async def test_interrupted_sends_twilio_clear():
    """An interrupted event from ADK triggers a Twilio `clear` event."""
    ws = AsyncMock()
    events = [_make_event(interrupted=True)]

    await _run_adk(events, ws, sid_holder=["SM-XYZ"])

    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    clears = [m for m in sent if m.get("event") == "clear"]
    assert len(clears) == 1
    assert clears[0]["streamSid"] == "SM-XYZ"


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_interrupted_skips_audio(mock_convert):
    """Audio carried on an interrupted event must not be forwarded to Twilio."""
    ws = AsyncMock()
    events = [_make_event(audio_data=b"\x00\x01", interrupted=True)]

    await _run_adk(events, ws)

    mock_convert.assert_not_called()
    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    media_msgs = [m for m in sent if m.get("event") == "media"]
    assert media_msgs == []


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_interrupt_cancels_drain(mock_convert):
    """Barge-in during goodbye drain cancels draining instead of ending the call."""
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    events = [
        _make_event(output_text="Adé!", audio_data=b"\x00"),  # drain ON
        _make_event(interrupted=True),  # caller interrupts — drain OFF
        _make_event(),  # drain is off, so this does NOT terminate
    ]

    await _run_adk(events, ws, call_end_event=call_end_event)

    assert not call_end_event.is_set()
    # And a clear event was sent for the interruption
    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    assert any(m.get("event") == "clear" for m in sent)


async def test_interrupted_without_sid_is_noop():
    """If no streamSid is known yet, an interruption must not crash or send clear."""
    ws = AsyncMock()
    events = [_make_event(interrupted=True)]

    await _run_adk(events, ws, sid_holder=[None])

    ws.send_text.assert_not_called()


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="bXVsYXc=",
)
async def test_audio_flows_after_new_user_turn(mock_convert):
    """After an interrupt, audio resumes only once a new user turn begins."""
    ws = AsyncMock()
    events = [
        _make_event(interrupted=True),
        _make_event(input_text="Warte, ich han no e Frag"),  # new user turn
        _make_event(audio_data=b"\x02\x03"),  # agent's new response
    ]

    await _run_adk(events, ws)

    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    # Expect: 1 clear, then 1 media + 1 mark from the third event
    assert sent[0]["event"] == "clear"
    assert sent[1]["event"] == "media"
    assert sent[1]["media"]["payload"] == "bXVsYXc="
    assert sent[2]["event"] == "mark"


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_audio_buffered_after_interrupt_is_dropped(mock_convert):
    """Audio events arriving AFTER an interrupt but before the new user turn
    (i.e. still-buffered output from the interrupted turn) must not be
    forwarded to Twilio — otherwise they defeat the Twilio `clear`.
    """
    ws = AsyncMock()
    events = [
        _make_event(interrupted=True),
        _make_event(audio_data=b"\x00"),  # stale buffered audio
        _make_event(audio_data=b"\x01"),  # stale buffered audio
    ]

    await _run_adk(events, ws)

    mock_convert.assert_not_called()
    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    media_msgs = [m for m in sent if m.get("event") == "media"]
    assert media_msgs == []


async def test_consecutive_interrupts_send_single_clear():
    """Multiple interrupted events within one barge-in window produce at most
    one Twilio `clear` (debounced via interrupt latch).
    """
    ws = AsyncMock()
    events = [
        _make_event(interrupted=True),
        _make_event(interrupted=True),
        _make_event(interrupted=True),
    ]

    await _run_adk(events, ws)

    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    clears = [m for m in sent if m.get("event") == "clear"]
    assert len(clears) == 1


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_farewell_and_interrupt_same_event_does_not_end_call(mock_convert):
    """Regression: an event carrying BOTH farewell text AND interrupted=True
    must cancel the drain (barge-in wins) rather than terminating the call.
    This pins down the load-bearing block order in ``_adk_to_twilio``.
    """
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    events = [
        _make_event(output_text="Adé!", interrupted=True),
        _make_event(input_text="Nei warte!"),
    ]

    await _run_adk(events, ws, call_end_event=call_end_event)

    assert not call_end_event.is_set()
    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    assert any(m.get("event") == "clear" for m in sent)


@patch(
    "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
    return_value="x",
)
async def test_stale_farewell_while_latched_does_not_end_call(mock_convert):
    """A buffered event with farewell text arriving while interrupt_latched
    must NOT re-arm draining. Without this guard the call could end
    spuriously after the latch clears.
    """
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    events = [
        _make_event(interrupted=True),  # latch ON
        _make_event(output_text="Adé!"),  # stale farewell — must be ignored
        _make_event(input_text="Nei!"),  # clears latch
        _make_event(),  # empty, non-audio — must NOT trigger drain completion
    ]

    await _run_adk(events, ws, call_end_event=call_end_event)

    assert not call_end_event.is_set()


async def test_interrupt_handling_with_real_adk_event():
    """Schema-drift guard: run the barge-in path with a real
    google.adk.events.Event instance (not a SimpleNamespace fake).
    Fails loudly if ADK renames or retypes the ``interrupted`` field.
    """
    from google.adk.events.event import Event

    ws = AsyncMock()
    real_event = Event(invocation_id="inv-1", author="model", interrupted=True)

    await _run_adk([real_event], ws, sid_holder=["SM-REAL"])

    sent = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
    clears = [m for m in sent if m.get("event") == "clear"]
    assert len(clears) == 1
    assert clears[0]["streamSid"] == "SM-REAL"


# ---------------------------------------------------------------------------
# Remaining _adk_to_twilio tests
# ---------------------------------------------------------------------------


async def test_adk_call_end_event_preset_breaks_loop():
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    call_end_event.set()
    events = [_make_event()]

    await _run_adk(events, ws, call_end_event=call_end_event)
    # Should not hang — breaks immediately after processing the event


async def test_adk_websocket_disconnect_handled():
    from fastapi import WebSocketDisconnect

    ws = AsyncMock()
    ws.send_text.side_effect = WebSocketDisconnect()
    events = [_make_event(audio_data=b"\x00")]

    with patch(
        "voice_assistant.call_handler.gemini_pcm_to_twilio_mulaw_b64",
        return_value="x",
    ):
        await _run_adk(events, ws)


async def test_adk_generic_error_handled():
    ws = AsyncMock()

    async def _raising_gen(**kw):
        raise RuntimeError("unexpected")
        yield

    runner = MagicMock()
    runner.run_live = _raising_gen

    await _adk_to_twilio(
        ws=ws,
        runner=runner,
        user_id="u",
        session_id="s",
        live_queue=MagicMock(),
        run_config=MagicMock(),
        sid_holder=["SM-1"],
        call_end_event=asyncio.Event(),
    )


async def test_adk_cancelled_error_handled():
    ws = AsyncMock()

    async def _raising_gen(**kw):
        raise asyncio.CancelledError
        yield  # make it an async generator

    runner = MagicMock()
    runner.run_live = _raising_gen

    await _adk_to_twilio(
        ws=ws,
        runner=runner,
        user_id="u",
        session_id="s",
        live_queue=MagicMock(),
        run_config=MagicMock(),
        sid_holder=["SM-1"],
        call_end_event=asyncio.Event(),
    )


# ---------------------------------------------------------------------------
# handle_media_stream (orchestrator)
# ---------------------------------------------------------------------------


@patch(f"{_CH}._adk_to_twilio", new_callable=AsyncMock)
@patch(f"{_CH}._twilio_to_adk", new_callable=AsyncMock)
@patch(f"{_CH}.LiveRequestQueue")
@patch(f"{_CH}.InMemoryRunner")
@patch(f"{_CH}.settings")
async def test_handle_media_stream_normal_flow(
    mock_settings, mock_runner_cls, mock_queue_cls, mock_twilio, mock_adk
):
    mock_settings.language_profile.return_value = {"voice_name": "Leda"}

    mock_runner = MagicMock()
    mock_session = MagicMock()
    mock_session.id = "session-1"
    mock_runner.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_cls.return_value = mock_runner

    mock_queue = MagicMock()
    mock_queue_cls.return_value = mock_queue

    ws = AsyncMock()

    await handle_media_stream(ws)

    ws.accept.assert_awaited_once()
    mock_runner.session_service.create_session.assert_awaited_once()
    mock_queue.send_content.assert_called_once()
    mock_twilio.assert_awaited_once()
    mock_adk.assert_awaited_once()
    mock_queue.close.assert_called_once()
    ws.close.assert_awaited_once()


@patch(f"{_CH}._adk_to_twilio", new_callable=AsyncMock)
@patch(f"{_CH}._twilio_to_adk", new_callable=AsyncMock)
@patch(f"{_CH}.LiveRequestQueue")
@patch(f"{_CH}.InMemoryRunner")
@patch(f"{_CH}.settings")
@patch(f"{_CH}.MAX_CALL_DURATION", 0.01)
async def test_handle_media_stream_timeout(
    mock_settings, mock_runner_cls, mock_queue_cls, mock_twilio, mock_adk
):
    mock_settings.language_profile.return_value = {"voice_name": "Leda"}

    mock_runner = MagicMock()
    mock_session = MagicMock()
    mock_session.id = "session-1"
    mock_runner.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_cls.return_value = mock_runner
    mock_queue_cls.return_value = MagicMock()

    async def _hang(*a, **kw):
        await asyncio.sleep(999)

    # Make both tasks hang so timeout fires
    mock_twilio.side_effect = _hang
    mock_adk.side_effect = _hang

    ws = AsyncMock()

    await asyncio.wait_for(handle_media_stream(ws), timeout=5.0)

    ws.close.assert_awaited_once()


@patch(f"{_CH}._adk_to_twilio", new_callable=AsyncMock)
@patch(f"{_CH}._twilio_to_adk", new_callable=AsyncMock)
@patch(f"{_CH}.LiveRequestQueue")
@patch(f"{_CH}.InMemoryRunner")
@patch(f"{_CH}.settings")
async def test_handle_media_stream_one_task_finishes_other_cancelled(
    mock_settings, mock_runner_cls, mock_queue_cls, mock_twilio, mock_adk
):
    """When one task finishes, the other (still running) gets cancelled."""
    mock_settings.language_profile.return_value = {"voice_name": "Leda"}

    mock_runner = MagicMock()
    mock_session = MagicMock()
    mock_session.id = "session-1"
    mock_runner.session_service.create_session = AsyncMock(return_value=mock_session)
    mock_runner_cls.return_value = mock_runner
    mock_queue_cls.return_value = MagicMock()

    async def _hang(*a, **kw):
        await asyncio.sleep(999)

    # Twilio task returns immediately, ADK task hangs
    mock_twilio.return_value = None
    mock_adk.side_effect = _hang

    ws = AsyncMock()

    await asyncio.wait_for(handle_media_stream(ws), timeout=5.0)

    ws.close.assert_awaited_once()
