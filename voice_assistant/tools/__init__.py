"""Agent tools -- plain Python functions passed to ADK Agent(tools=[...])."""

from .weather import get_current_weather

ALL_TOOLS: list = [get_current_weather]
