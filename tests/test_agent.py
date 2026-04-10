"""Unit tests for the ADK agent definition."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from voice_assistant.agent import _DualModelGemini, _instruction_provider, root_agent
from voice_assistant.config import GEMINI_MODEL, GEMINI_LIVE_MODEL


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------


def test_root_agent_exists():
    assert root_agent is not None


def test_root_agent_name():
    assert root_agent.name == "customer_service"


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
