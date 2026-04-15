"""
Google ADK agent definition for the voice assistant.

The ``root_agent`` is discovered automatically by the ADK CLI
(``adk web .``, ``adk run voice_assistant``).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest

from .config import GEMINI_MODEL, GEMINI_LIVE_MODEL, build_instruction, settings
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


def _instruction_provider(ctx: ReadonlyContext) -> str:
    """Dynamic instruction provider that reads language from session state."""
    lang = ctx.state.get("language", settings.default_language)
    return build_instruction(lang)


root_agent = Agent(
    model=_DualModelGemini(model=GEMINI_MODEL),
    name="customer_service",
    description="Swiss customer service voice assistant",
    instruction=_instruction_provider,
    tools=ALL_TOOLS,
)
