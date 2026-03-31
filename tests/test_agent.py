"""Unit tests for ADK agent configuration."""

from __future__ import annotations

from voice_assistant.agent import root_agent
from voice_assistant.config import GEMINI_MODEL, GEMINI_LIVE_MODEL
from voice_assistant.tools import get_current_weather


def test_agent_name():
    assert root_agent.name == "voice_assistant"


def test_agent_text_model():
    assert root_agent.model.model == GEMINI_MODEL


def test_agent_live_model():
    assert root_agent.model.live_model == GEMINI_LIVE_MODEL


def test_agent_has_weather_tool():
    assert get_current_weather in root_agent.tools


def test_agent_instruction_is_callable():
    assert callable(root_agent.instruction)


def test_agent_instruction_contains_language():
    text = root_agent.instruction(None)
    assert "Swiss German" in text
