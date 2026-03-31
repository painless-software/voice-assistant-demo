"""
Tool functions available to the voice assistant agent.

ADK auto-generates the function declaration schema from the signature
and docstring — no manual FunctionDeclaration wrappers needed.
"""

from __future__ import annotations


def get_current_weather(city: str) -> dict:
    """Get the current weather for a given city.

    Args:
        city: City name, e.g. 'Zurich'.
    """
    # TODO: Replace with a real weather API call.
    return {
        "city": city,
        "temperature_celsius": 18,
        "condition": "partly cloudy",
        "humidity_percent": 65,
    }
