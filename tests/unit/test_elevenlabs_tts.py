"""Unit tests for ElevenLabs streaming TTS client."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest

from voice_assistant.elevenlabs_tts import ElevenLabsTTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _audio_msg(pcm_data: bytes) -> str:
    """Build a JSON ElevenLabs audio response."""
    return json.dumps({"audio": base64.b64encode(pcm_data).decode()})


def _final_msg() -> str:
    return json.dumps({"isFinal": True})


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


async def test_connect_times_out_when_unreachable():
    """connect() raises TimeoutError instead of hanging if ElevenLabs is unreachable."""
    import asyncio

    async def _never_connect(*a, **kw):
        await asyncio.sleep(10)

    tts = ElevenLabsTTS()
    with patch("voice_assistant.elevenlabs_tts._CONNECT_TIMEOUT", 0.01):
        with patch(
            "voice_assistant.elevenlabs_tts.websockets.connect",
            side_effect=_never_connect,
        ):
            with pytest.raises(asyncio.TimeoutError):
                await tts.connect("v", "m", "k")

    assert not tts.is_connected


@patch("voice_assistant.elevenlabs_tts.websockets.connect", new_callable=AsyncMock)
async def test_connect_sends_bos(mock_connect):
    ws = AsyncMock()
    mock_connect.return_value = ws

    tts = ElevenLabsTTS()
    await tts.connect("voice-1", "model-1", "key-1")

    mock_connect.assert_awaited_once()
    url = mock_connect.call_args[0][0]
    assert "voice-1" in url
    assert "model_id=model-1" in url
    assert "output_format=pcm_24000" in url

    bos = json.loads(ws.send.call_args[0][0])
    assert bos["text"] == " "
    assert "voice_settings" in bos
    assert "generation_config" in bos


# ---------------------------------------------------------------------------
# send_text
# ---------------------------------------------------------------------------


@patch("voice_assistant.elevenlabs_tts.websockets.connect", new_callable=AsyncMock)
async def test_send_text(mock_connect):
    ws = AsyncMock()
    mock_connect.return_value = ws

    tts = ElevenLabsTTS()
    await tts.connect("v", "m", "k")
    ws.send.reset_mock()

    await tts.send_text("Hello world ")

    msg = json.loads(ws.send.call_args[0][0])
    assert msg["text"] == "Hello world "
    assert msg["try_trigger_generation"] is True


# ---------------------------------------------------------------------------
# flush
# ---------------------------------------------------------------------------


@patch("voice_assistant.elevenlabs_tts.websockets.connect", new_callable=AsyncMock)
async def test_flush_sends_empty_text(mock_connect):
    ws = AsyncMock()
    mock_connect.return_value = ws

    tts = ElevenLabsTTS()
    await tts.connect("v", "m", "k")
    ws.send.reset_mock()

    await tts.flush()

    msg = json.loads(ws.send.call_args[0][0])
    assert msg["text"] == ""


# ---------------------------------------------------------------------------
# receive_audio
# ---------------------------------------------------------------------------


@patch("voice_assistant.elevenlabs_tts.websockets.connect", new_callable=AsyncMock)
async def test_receive_audio_yields_pcm_chunks(mock_connect):
    ws = AsyncMock()
    ws.__aiter__ = lambda self: self
    chunks = [_audio_msg(b"\x00\x01"), _audio_msg(b"\x02\x03"), _final_msg()]
    ws.__anext__ = AsyncMock(side_effect=chunks + [StopAsyncIteration])
    mock_connect.return_value = ws

    tts = ElevenLabsTTS()
    await tts.connect("v", "m", "k")

    received = []
    async for chunk in tts.receive_audio():
        received.append(chunk)

    assert received == [b"\x00\x01", b"\x02\x03"]


@patch("voice_assistant.elevenlabs_tts.websockets.connect", new_callable=AsyncMock)
async def test_receive_audio_skips_empty_audio_field(mock_connect):
    ws = AsyncMock()
    ws.__aiter__ = lambda self: self
    chunks = [
        json.dumps({"audio": None}),
        _audio_msg(b"\x01"),
        _final_msg(),
    ]
    ws.__anext__ = AsyncMock(side_effect=chunks + [StopAsyncIteration])
    mock_connect.return_value = ws

    tts = ElevenLabsTTS()
    await tts.connect("v", "m", "k")

    received = []
    async for chunk in tts.receive_audio():
        received.append(chunk)

    assert received == [b"\x01"]


# ---------------------------------------------------------------------------
# interrupt
# ---------------------------------------------------------------------------


@patch("voice_assistant.elevenlabs_tts.websockets.connect", new_callable=AsyncMock)
async def test_interrupt_closes_websocket(mock_connect):
    ws = AsyncMock()
    mock_connect.return_value = ws

    tts = ElevenLabsTTS()
    await tts.connect("v", "m", "k")

    await tts.interrupt()

    ws.close.assert_awaited_once()
    assert tts._ws is None


async def test_receive_audio_handles_connection_closed():
    """receive_audio handles ConnectionClosed gracefully."""
    import websockets

    ws = AsyncMock()
    ws.__aiter__ = lambda self: self
    ws.__anext__ = AsyncMock(side_effect=websockets.ConnectionClosed(None, None))

    tts = ElevenLabsTTS()
    tts._ws = ws  # inject directly, skip connect

    received = [c async for c in tts.receive_audio()]
    assert received == []
    assert not tts.is_connected


async def test_receive_audio_clears_ws_on_unexpected_error():
    """A non-ConnectionClosed error (e.g. malformed JSON) still clears _ws
    so subsequent send_text() doesn't write to a dead socket."""
    ws = AsyncMock()
    ws.__aiter__ = lambda self: self
    ws.__anext__ = AsyncMock(return_value="not-valid-json{")

    tts = ElevenLabsTTS()
    tts._ws = ws

    with pytest.raises(json.JSONDecodeError):
        async for _ in tts.receive_audio():
            pass

    assert not tts.is_connected


@patch("voice_assistant.elevenlabs_tts.websockets.connect", new_callable=AsyncMock)
async def test_interrupt_handles_close_error(mock_connect):
    """A close() failure from the underlying websocket is logged, not raised."""
    import websockets

    ws = AsyncMock()
    ws.close.side_effect = websockets.InvalidState("already closed")
    mock_connect.return_value = ws

    tts = ElevenLabsTTS()
    await tts.connect("v", "m", "k")

    await tts.interrupt()  # should not raise

    assert tts._ws is None


# ---------------------------------------------------------------------------
# Methods are safe to call without connect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,args",
    [
        ("send_text", ("hello",)),
        ("flush", ()),
        ("interrupt", ()),
    ],
)
async def test_method_without_connect_is_noop(method, args):
    tts = ElevenLabsTTS()
    await getattr(tts, method)(*args)  # should not raise


async def test_receive_audio_without_connect_yields_nothing():
    tts = ElevenLabsTTS()
    assert [c async for c in tts.receive_audio()] == []
