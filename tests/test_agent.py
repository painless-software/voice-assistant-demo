"""Unit tests for the ADK agent definition."""

from __future__ import annotations

from unittest.mock import MagicMock

from voice_assistant.agent import _instruction_provider, root_agent


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
    assert "end_call" in tool_names


def test_root_agent_has_instruction():
    assert root_agent.instruction is not None


def test_root_agent_model():
    assert "gemini" in str(root_agent.model).lower()


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
