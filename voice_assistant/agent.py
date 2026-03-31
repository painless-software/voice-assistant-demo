"""
Google ADK agent definition for the voice assistant.

The ``root_agent`` is discovered automatically by the ADK CLI
(``adk web voice_assistant``, ``adk run voice_assistant``).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator

from google.adk.agents.llm_agent import Agent
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest

from .config import settings, GEMINI_MODEL, GEMINI_LIVE_MODEL
from .tools import get_current_weather


class _DualModelGemini(Gemini):
    """Gemini wrapper that uses one model for text and another for live audio."""

    live_model: str = GEMINI_LIVE_MODEL

    @contextlib.asynccontextmanager
    async def connect(
        self, llm_request: LlmRequest
    ) -> AsyncGenerator[BaseLlmConnection]:
        llm_request.model = self.live_model
        async with super().connect(llm_request) as conn:
            yield conn


root_agent = Agent(
    model=_DualModelGemini(model=GEMINI_MODEL),
    name="voice_assistant",
    description="Swiss customer service voice assistant",
    instruction=lambda _ctx: settings.system_instruction(),
    tools=[get_current_weather],
)
