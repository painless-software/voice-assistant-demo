"""
Google ADK agent definition for the voice assistant.

The ``root_agent`` is discovered automatically by the ADK CLI
(``adk web .``, ``adk run voice_assistant``).

Each persona YAML in ``voice_assistant/personas/`` becomes a separate
ADK agent.  When multiple personas exist they are registered as
sub-agents of a lightweight router so the ADK web UI shows them all
in the agent dropdown.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest

from .config import (
    GEMINI_MODEL,
    GEMINI_LIVE_MODEL,
    build_instruction_for_persona,
    load_all_personas,
    settings,
)
from .tools import ALL_TOOLS


class _DualModelGemini(Gemini):
    """Gemini wrapper that uses one model for text and another for live audio.

    When the voice backend is ElevenLabs, the live model stays on the
    standard text model (no native audio) because TTS is handled externally.
    """

    live_model: str = (
        GEMINI_MODEL if settings.voice_backend == "elevenlabs" else GEMINI_LIVE_MODEL
    )

    @contextlib.asynccontextmanager
    async def connect(
        self, llm_request: LlmRequest
    ) -> AsyncGenerator[BaseLlmConnection]:
        original_model = llm_request.model
        llm_request.model = self.live_model
        try:
            async with super().connect(llm_request) as conn:
                yield conn
        finally:
            llm_request.model = original_model


def _make_instruction_provider(persona: dict):
    """Create a per-persona instruction provider for ADK."""

    def _provider(ctx: ReadonlyContext, _persona: dict = persona) -> str:
        lang = ctx.state.get("language", settings.default_language)
        return build_instruction_for_persona(_persona, lang)

    return _provider


def _agent_name(persona: dict) -> str:
    """Derive a valid ADK agent name from a persona."""
    return persona["name"].lower().replace(" ", "_").replace("ü", "ue")


def _build_persona_agent(persona: dict) -> Agent:
    """Create an ADK Agent for a single persona."""
    return Agent(
        model=_DualModelGemini(model=GEMINI_MODEL),
        name=_agent_name(persona),
        description=f"{persona['name']} voice assistant",
        instruction=_make_instruction_provider(persona),
        tools=ALL_TOOLS,
    )


# ---------------------------------------------------------------------------
# Build agents from all persona YAML files
# ---------------------------------------------------------------------------

_all_personas = load_all_personas()
if not _all_personas:
    raise EnvironmentError(
        "No persona YAML files found in voice_assistant/personas/. "
        "Add at least one persona file to start the agent."
    )
_persona_agents = [_build_persona_agent(p) for p in _all_personas.values()]

if len(_persona_agents) == 1:
    # Single persona → use directly as root agent
    root_agent = _persona_agents[0]
else:
    # Multiple personas → router delegates to the right sub-agent
    root_agent = Agent(
        model=Gemini(model=GEMINI_MODEL),
        name="voice_assistant",
        description="Voice assistant router — delegates to persona-specific agents",
        instruction=(
            "You are a router. The user will be connected to one of your "
            "specialist agents. Transfer the conversation to the most "
            "appropriate agent immediately."
        ),
        sub_agents=list(_persona_agents),  # type: ignore[arg-type]
    )
