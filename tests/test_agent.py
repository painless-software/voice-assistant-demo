"""Unit tests for the ADK agent definition."""

from __future__ import annotations

from unittest.mock import MagicMock

from voice_assistant.agent import _DualModelGemini, _instruction_provider, root_agent
from voice_assistant.config import GEMINI_MODEL, GEMINI_LIVE_MODEL


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------


def test_root_agent_exists():
    assert root_agent is not None


def test_root_agent_name():
    assert root_agent.name == "customer_service"


def test_root_agent_has_tools():
    tool_names = [t.__name__ for t in root_agent.tools]
    assert "get_current_weather" in tool_names


def test_root_agent_has_instruction():
    assert root_agent.instruction is not None


def test_root_agent_text_model():
    assert root_agent.model.model == GEMINI_MODEL


def test_root_agent_live_model():
    assert root_agent.model.live_model == GEMINI_LIVE_MODEL


def test_dual_model_is_gemini_subclass():
    assert isinstance(root_agent.model, _DualModelGemini)


# ---------------------------------------------------------------------------
# Instruction provider
# ---------------------------------------------------------------------------


def test_instruction_provider_uses_language_from_state():
    ctx = MagicMock()
    ctx.state = {"language": "fr-CH"}
    instruction = _instruction_provider(ctx)
    assert "Swiss French" in instruction


def test_instruction_provider_defaults_to_configured_language():
    ctx = MagicMock()
    ctx.state = {}
    instruction = _instruction_provider(ctx)
    # Should use default language from settings
    assert len(instruction) > 100


def test_instruction_provider_italian():
    ctx = MagicMock()
    ctx.state = {"language": "it-CH"}
    instruction = _instruction_provider(ctx)
    assert "Swiss Italian" in instruction
