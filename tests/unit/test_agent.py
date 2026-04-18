"""Unit tests for the ADK agent definition."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_assistant.agent import (
    _DualModelGemini,
    _make_instruction_provider,
    root_agent,
)
from voice_assistant.config import GEMINI_MODEL, GEMINI_LIVE_MODEL, PERSONA


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------


def test_root_agent_exists():
    assert root_agent is not None


def test_root_agent_name():
    # Agent name derived from active persona
    assert root_agent.name == "velo_zueri"


def test_root_agent_has_no_tools_for_native_audio():
    # Native audio live model does not support function calling.
    # Tools are disabled until that limitation is lifted.
    assert root_agent.tools == []


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
    provider = _make_instruction_provider(PERSONA)
    ctx = MagicMock()
    ctx.state = {"language": "fr-CH"}
    instruction = provider(ctx)
    assert "Swiss French" in instruction


def test_instruction_provider_defaults_to_configured_language():
    provider = _make_instruction_provider(PERSONA)
    ctx = MagicMock()
    ctx.state = {}
    instruction = provider(ctx)
    # Should use default language from settings
    assert len(instruction) > 100


def test_instruction_provider_italian():
    provider = _make_instruction_provider(PERSONA)
    ctx = MagicMock()
    ctx.state = {"language": "it-CH"}
    instruction = provider(ctx)
    assert "Swiss Italian" in instruction


# ---------------------------------------------------------------------------
# _DualModelGemini.connect — model swapping
# ---------------------------------------------------------------------------


async def test_dual_model_connect_swaps_model():
    """connect() temporarily sets llm_request.model to the live model."""
    dual = _DualModelGemini(model=GEMINI_MODEL)
    llm_request = MagicMock()
    llm_request.model = GEMINI_MODEL

    mock_conn = AsyncMock()
    with patch.object(
        _DualModelGemini.__mro__[1],  # Gemini base class
        "connect",
        return_value=AsyncMock(),
    ) as mock_super_connect:
        # Make super().connect() an async context manager that yields mock_conn
        mock_super_connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_super_connect.return_value.__aexit__ = AsyncMock(return_value=False)

        async with dual.connect(llm_request) as conn:
            # During the context, model should be the live model
            assert llm_request.model == GEMINI_LIVE_MODEL
            assert conn is mock_conn

    # After exiting, model should be restored
    assert llm_request.model == GEMINI_MODEL


# ---------------------------------------------------------------------------
# Module-level agent wiring
# ---------------------------------------------------------------------------


def test_no_personas_raises():
    import voice_assistant.agent as agent_mod

    with patch("voice_assistant.config.load_all_personas", return_value={}):
        with pytest.raises(EnvironmentError, match="No persona YAML files"):
            importlib.reload(agent_mod)

    # Restore module to working state
    importlib.reload(agent_mod)


def test_multiple_personas_creates_router():
    import voice_assistant.agent as agent_mod

    second_persona = {
        "name": "Test Shop",
        "allowed_topics": ["Topic A"],
        "out_of_scope_decline": "Sorry.",
    }
    two_personas = {
        "velo_shop": PERSONA,
        "test_shop": second_persona,
    }
    with patch("voice_assistant.config.load_all_personas", return_value=two_personas):
        importlib.reload(agent_mod)
        assert agent_mod.root_agent.name == "voice_assistant"
        assert len(agent_mod.root_agent.sub_agents) == 2

    # Restore module to working state
    importlib.reload(agent_mod)
