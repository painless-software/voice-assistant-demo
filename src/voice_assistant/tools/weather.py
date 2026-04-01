"""Weather tool -- returns mock data for demo purposes."""

from __future__ import annotations


def get_current_weather(city: str) -> dict:
    """Get the current weather for a given city.

    Args:
        city: City name, e.g. 'Zürich'.
    """
    return {
        "status": "success",
        "city": city,
        "temperature_celsius": 18,
        "condition": "partly cloudy",
        "humidity_percent": 65,
    }
