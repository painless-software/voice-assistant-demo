"""Unit tests for ADK tool functions (TDD -- tests written before implementation)."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# get_current_weather tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "city",
    ["Zürich", "Bern", "Genève", "Lugano", ""],
)
def test_get_weather_returns_expected_keys(city):
    from voice_assistant.tools.weather import get_current_weather

    result = get_current_weather(city=city)
    assert result["status"] == "success"
    assert result["city"] == city
    assert "temperature_celsius" in result
    assert "condition" in result
    assert "humidity_percent" in result


def test_get_weather_values_are_sensible():
    from voice_assistant.tools.weather import get_current_weather

    result = get_current_weather(city="Zürich")
    assert isinstance(result["temperature_celsius"], (int, float))
    assert isinstance(result["humidity_percent"], (int, float))
    assert isinstance(result["condition"], str)
