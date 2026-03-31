"""Unit tests for Gemini tool declarations, mock implementations, and receive loop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from voice_assistant.config import GEMINI_LIVE_MODEL
from voice_assistant.gemini_session import (
    LIVE_TOOLS,
    TOOL_GET_WEATHER,
    GeminiSession,
    execute_tool,
    mock_get_weather,
)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_model_is_flash_live():
    assert GEMINI_LIVE_MODEL == "gemini-3.1-flash-live-preview"


# ---------------------------------------------------------------------------
# Tool declaration
# ---------------------------------------------------------------------------


def test_tool_declaration_name():
    assert TOOL_GET_WEATHER.name == "get_current_weather"


def test_tool_declaration_has_city_parameter():
    props = TOOL_GET_WEATHER.parameters.properties
    assert "city" in props
    assert props["city"].type == types.Type.STRING


def test_tool_declaration_city_is_required():
    assert "city" in TOOL_GET_WEATHER.parameters.required


def test_live_tools_contains_weather():
    assert len(LIVE_TOOLS) == 1
    fn_names = [fd.name for fd in LIVE_TOOLS[0].function_declarations]
    assert "get_current_weather" in fn_names


# ---------------------------------------------------------------------------
# Mock weather implementation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "city",
    ["Zürich", "Bern", "Genève", "Lugano", ""],
)
def testmock_get_weather_returns_expected_keys(city):
    result = mock_get_weather(city)
    assert result["city"] == city
    assert "temperature_celsius" in result
    assert "condition" in result
    assert "humidity_percent" in result


def testmock_get_weather_values_are_sensible():
    result = mock_get_weather("Zürich")
    assert isinstance(result["temperature_celsius"], (int, float))
    assert isinstance(result["humidity_percent"], (int, float))
    assert isinstance(result["condition"], str)


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------


def test_execute_tool_routes_weather():
    result = execute_tool("get_current_weather", {"city": "Bern"})
    assert result["city"] == "Bern"
    assert "temperature_celsius" in result


def test_execute_tool_unknown_returns_error():
    result = execute_tool("nonexistent_tool", {})
    assert "error" in result


def test_execute_tool_weather_missing_city_returns_error():
    result = execute_tool("get_current_weather", {})
    assert "error" in result


# ---------------------------------------------------------------------------
# Config wiring – tools are included in LiveConnectConfig
# ---------------------------------------------------------------------------


@patch("voice_assistant.gemini_session.settings")
def test_build_config_includes_tools(mock_settings):
    mock_settings.default_language = "de-CH"
    mock_settings.language_profile.return_value = {
        "voice_name": "Leda",
    }
    mock_settings.system_instruction.return_value = "You are a helpful assistant."
    mock_settings.use_vertex_ai.return_value = False
    mock_settings.google_api_key = "fake-key"

    session = GeminiSession.__new__(GeminiSession)
    session._lang_code = "de-CH"
    session._profile = mock_settings.language_profile("de-CH")
    session._client = MagicMock()

    config = session._build_config()
    assert config.tools is not None
    assert len(config.tools) == 1
    fn_names = [fd.name for fd in config.tools[0].function_declarations]
    assert "get_current_weather" in fn_names


# ---------------------------------------------------------------------------
# _handle_tool_call sends responses back to the session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_tool_call_sends_response():
    """Verify that _handle_tool_call executes the tool and sends results back."""
    session = GeminiSession.__new__(GeminiSession)
    session._session = AsyncMock()

    fc = MagicMock()
    fc.id = "call_123"
    fc.name = "get_current_weather"
    fc.args = {"city": "Lausanne"}

    tool_call = MagicMock()
    tool_call.function_calls = [fc]

    await session._handle_tool_call(tool_call)

    session._session.send_tool_response.assert_awaited_once()
    call_kwargs = session._session.send_tool_response.call_args
    responses = call_kwargs.kwargs["function_responses"]
    assert len(responses) == 1
    assert responses[0].id == "call_123"
    assert responses[0].name == "get_current_weather"
    assert responses[0].response["city"] == "Lausanne"


@pytest.mark.asyncio
async def test_handle_tool_call_multiple_functions():
    """Verify parallel function calls are all executed and returned."""
    session = GeminiSession.__new__(GeminiSession)
    session._session = AsyncMock()

    fc1 = MagicMock()
    fc1.id = "call_1"
    fc1.name = "get_current_weather"
    fc1.args = {"city": "Zürich"}

    fc2 = MagicMock()
    fc2.id = "call_2"
    fc2.name = "get_current_weather"
    fc2.args = {"city": "Basel"}

    tool_call = MagicMock()
    tool_call.function_calls = [fc1, fc2]

    await session._handle_tool_call(tool_call)

    call_kwargs = session._session.send_tool_response.call_args
    responses = call_kwargs.kwargs["function_responses"]
    assert len(responses) == 2
    assert responses[0].id == "call_1"
    assert responses[0].response["city"] == "Zürich"
    assert responses[1].id == "call_2"
    assert responses[1].response["city"] == "Basel"


# ---------------------------------------------------------------------------
# Receive loop – multi-turn behaviour
# ---------------------------------------------------------------------------


def _make_audio_response(data: bytes):
    """Build a fake Gemini response carrying audio data."""
    resp = MagicMock()
    resp.data = data
    resp.server_content = None
    resp.tool_call = None
    resp.text = None
    return resp


def _make_server_content_response(
    *,
    audio_data: bytes | None = None,
    turn_complete: bool = False,
    interrupted: bool = False,
    input_text: str | None = None,
    output_text: str | None = None,
):
    """Build a fake Gemini response with server_content fields."""
    resp = MagicMock()
    resp.data = None
    resp.tool_call = None
    resp.text = None

    sc = MagicMock()
    sc.interrupted = interrupted

    if audio_data:
        part = MagicMock()
        part.inline_data.data = audio_data
        sc.model_turn.parts = [part]
    else:
        sc.model_turn = None

    if input_text:
        sc.input_transcription.text = input_text
    else:
        sc.input_transcription = None

    if output_text:
        sc.output_transcription.text = output_text
    else:
        sc.output_transcription = None

    resp.server_content = sc
    return resp


@pytest.mark.asyncio
async def test_receive_loop_stays_alive_across_turns():
    """The receive loop must keep running across multiple model turns.

    The None sentinel should only be pushed when the loop exits (e.g.
    the async iterator is exhausted), NOT between turns.
    """
    session = GeminiSession.__new__(GeminiSession)
    session._response_queue = asyncio.Queue()

    # Simulate two model turns: greeting + answer to a follow-up
    turn_1_audio = b"\x00" * 100
    turn_2_audio = b"\xff" * 100

    async def _turn_1():
        yield _make_audio_response(turn_1_audio)
        yield _make_server_content_response(turn_complete=True)

    async def _turn_2():
        yield _make_audio_response(turn_2_audio)
        yield _make_server_content_response(turn_complete=True)

    def _empty():
        return

    mock_session = MagicMock()
    mock_session.receive.side_effect = [_turn_1(), _turn_2(), _empty()]
    session._session = mock_session

    await session._receive_loop()

    # Collect everything from the queue
    chunks = []
    while not session._response_queue.empty():
        chunks.append(session._response_queue.get_nowait())

    # Both audio chunks must be present, followed by a single None sentinel
    assert chunks == [turn_1_audio, turn_2_audio, None]


@pytest.mark.asyncio
async def test_receive_loop_handles_server_content_audio():
    """Audio delivered via server_content.model_turn.parts should be queued."""
    session = GeminiSession.__new__(GeminiSession)
    session._response_queue = asyncio.Queue()

    audio = b"\xab" * 50

    async def _turn():
        yield _make_server_content_response(audio_data=audio)

    def _empty():
        return

    mock_session = MagicMock()
    mock_session.receive.side_effect = [_turn(), _empty()]
    session._session = mock_session

    await session._receive_loop()

    chunks = []
    while not session._response_queue.empty():
        chunks.append(session._response_queue.get_nowait())

    assert chunks == [audio, None]


@pytest.mark.asyncio
async def test_receive_loop_handles_tool_call_mid_conversation():
    """A tool call between audio turns should be dispatched without
    breaking the loop."""
    session = GeminiSession.__new__(GeminiSession)
    session._response_queue = asyncio.Queue()

    audio_before = b"\x01" * 50
    audio_after = b"\x02" * 50

    fc = MagicMock()
    fc.id = "call_456"
    fc.name = "get_current_weather"
    fc.args = {"city": "Bern"}

    tool_resp = MagicMock()
    tool_resp.data = None
    tool_resp.server_content = None
    tool_resp.text = None
    tool_resp.tool_call.function_calls = [fc]

    send_tool_response = AsyncMock()

    async def _turn_1():
        yield _make_audio_response(audio_before)
        yield tool_resp

    async def _turn_2():
        yield _make_audio_response(audio_after)

    def _empty():
        return

    mock_session = MagicMock()
    mock_session.receive.side_effect = [_turn_1(), _turn_2(), _empty()]
    mock_session.send_tool_response = send_tool_response
    session._session = mock_session

    await session._receive_loop()

    chunks = []
    while not session._response_queue.empty():
        chunks.append(session._response_queue.get_nowait())

    # Both audio chunks present; tool call handled in-between
    assert chunks == [audio_before, audio_after, None]
    send_tool_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_receive_loop_sentinel_on_cancellation():
    """When the loop is cancelled, the None sentinel must still be pushed
    so that receive_audio() terminates cleanly."""
    session = GeminiSession.__new__(GeminiSession)
    session._response_queue = asyncio.Queue()

    async def _slow_receive():
        yield _make_audio_response(b"\x00" * 10)
        # Simulate blocking forever (until cancelled)
        await asyncio.sleep(999)

    mock_session = MagicMock()
    mock_session.receive.return_value = _slow_receive()
    session._session = mock_session

    task = asyncio.create_task(session._receive_loop())
    await asyncio.sleep(0.05)  # let it process the first response
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    chunks = []
    while not session._response_queue.empty():
        chunks.append(session._response_queue.get_nowait())

    # Audio chunk + None sentinel
    assert len(chunks) == 2
    assert chunks[0] == b"\x00" * 10
    assert chunks[1] is None
