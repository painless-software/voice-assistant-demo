"""Weather tool -- returns mock data for demo purposes."""

from __future__ import annotations

from typing import Annotated

from . import tool


@tool
def get_current_weather(
    city: Annotated[str, "City name, e.g. 'Zürich'"],
) -> dict:
    """Get the current weather for a given city."""
    return {
        "city": city,
        "temperature_celsius": 18,
        "condition": "partly cloudy",
        "humidity_percent": 65,
    }
