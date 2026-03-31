"""Unit tests for configuration constants."""

from __future__ import annotations

from voice_assistant.config import GEMINI_MODEL, GEMINI_LIVE_MODEL


def test_model_name():
    assert GEMINI_MODEL == "gemini-2.5-flash"


def test_live_model_name():
    assert GEMINI_LIVE_MODEL == "gemini-2.5-flash-native-audio-latest"
