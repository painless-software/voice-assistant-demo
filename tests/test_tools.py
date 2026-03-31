"""Unit tests for tool implementations."""

from __future__ import annotations

import pytest

from voice_assistant.tools import get_current_weather


@pytest.mark.parametrize(
    "city",
    ["Zürich", "Bern", "Genève", "Lugano", ""],
)
def test_get_weather_returns_expected_keys(city):
    result = get_current_weather(city)
    assert result["city"] == city
    assert "temperature_celsius" in result
    assert "condition" in result
    assert "humidity_percent" in result


def test_get_weather_values_are_sensible():
    result = get_current_weather("Zürich")
    assert isinstance(result["temperature_celsius"], (int, float))
    assert isinstance(result["humidity_percent"], (int, float))
    assert isinstance(result["condition"], str)
