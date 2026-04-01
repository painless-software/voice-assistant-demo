"""Unit tests for ADK tool functions (TDD -- tests written before implementation)."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# end_call tool
# ---------------------------------------------------------------------------


def test_end_call_returns_status_dict():
    from voice_assistant.tools.end_call import end_call

    result = end_call(reason="Customer said goodbye")
    assert result["status"] == "call_ended"
    assert result["reason"] == "Customer said goodbye"


def test_end_call_with_farewell_message():
    from voice_assistant.tools.end_call import end_call

    result = end_call(reason="Customer done", farewell_message="Thank you!")
    assert result["farewell_message"] == "Thank you!"


def test_end_call_farewell_defaults_to_empty():
    from voice_assistant.tools.end_call import end_call

    result = end_call(reason="Done")
    assert result["farewell_message"] == ""


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
