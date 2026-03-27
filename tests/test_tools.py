"""Unit tests for Gemini tool declarations and mock implementations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from google.genai import types

from voice_assistant.gemini_session import (
    GeminiSession,
    LIVE_TOOLS,
    TOOL_GET_WEATHER,
    _mock_get_weather,
)
from voice_assistant.config import GEMINI_LIVE_MODEL


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_model_is_live_2_5_flash():
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
def test_mock_get_weather_returns_expected_keys(city):
    result = _mock_get_weather(city)
    assert result["city"] == city
    assert "temperature_celsius" in result
    assert "condition" in result
    assert "humidity_percent" in result


def test_mock_get_weather_values_are_sensible():
    result = _mock_get_weather("Zürich")
    assert isinstance(result["temperature_celsius"], (int, float))
    assert isinstance(result["humidity_percent"], (int, float))
    assert isinstance(result["condition"], str)


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------


def test_execute_tool_routes_weather():
    result = GeminiSession._execute_tool("get_current_weather", {"city": "Bern"})
    assert result["city"] == "Bern"
    assert "temperature_celsius" in result


def test_execute_tool_unknown_returns_error():
    result = GeminiSession._execute_tool("nonexistent_tool", {})
    assert "error" in result


def test_execute_tool_weather_missing_city_defaults():
    result = GeminiSession._execute_tool("get_current_weather", {})
    assert result["city"] == "Unknown"


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

    # Build a fake tool_call with one function call
    fc = MagicMock()
    fc.name = "get_current_weather"
    fc.args = {"city": "Lausanne"}

    tool_call = MagicMock()
    tool_call.function_calls = [fc]

    await session._handle_tool_call(tool_call)

    session._session.send_tool_response.assert_awaited_once()
    call_kwargs = session._session.send_tool_response.call_args
    responses = call_kwargs.kwargs["function_responses"]
    assert len(responses) == 1
    assert responses[0].name == "get_current_weather"
    assert responses[0].response["city"] == "Lausanne"


@pytest.mark.asyncio
async def test_handle_tool_call_multiple_functions():
    """Verify parallel function calls are all executed and returned."""
    session = GeminiSession.__new__(GeminiSession)
    session._session = AsyncMock()

    fc1 = MagicMock()
    fc1.name = "get_current_weather"
    fc1.args = {"city": "Zürich"}

    fc2 = MagicMock()
    fc2.name = "get_current_weather"
    fc2.args = {"city": "Basel"}

    tool_call = MagicMock()
    tool_call.function_calls = [fc1, fc2]

    await session._handle_tool_call(tool_call)

    call_kwargs = session._session.send_tool_response.call_args
    responses = call_kwargs.kwargs["function_responses"]
    assert len(responses) == 2
    assert responses[0].response["city"] == "Zürich"
    assert responses[1].response["city"] == "Basel"
