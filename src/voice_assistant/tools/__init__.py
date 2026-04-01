"""Agent tools -- plain Python functions passed to ADK Agent(tools=[...])."""

from .end_call import end_call
from .weather import get_current_weather

ALL_TOOLS = [get_current_weather, end_call]
