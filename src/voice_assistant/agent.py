"""ADK agent definition for the customer service voice assistant."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext

from .config import build_instruction, settings
from .tools import ALL_TOOLS


def _instruction_provider(ctx: ReadonlyContext) -> str:
    """Dynamic instruction provider that reads language from session state."""
    lang = ctx.state.get("language", settings.default_language)
    return build_instruction(lang)


root_agent = Agent(
    name="customer_service",
    model="gemini-2.0-flash",
    description="Swiss customer service agent that handles phone calls in multiple languages.",
    instruction=_instruction_provider,
    tools=ALL_TOOLS,
)
