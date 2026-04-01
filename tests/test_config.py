"""Unit tests for config and instruction composition (TDD)."""

from __future__ import annotations


def test_build_instruction_contains_language_display():
    from voice_assistant.config import build_instruction

    instruction = build_instruction("de-CH")
    assert "Swiss German" in instruction


def test_build_instruction_french():
    from voice_assistant.config import build_instruction

    instruction = build_instruction("fr-CH")
    assert "Swiss French" in instruction


def test_build_instruction_includes_escalation():
    from voice_assistant.config import build_instruction

    instruction = build_instruction("de-CH")
    assert "ESCALATION" in instruction


def test_build_instruction_includes_tool_guidance():
    from voice_assistant.config import build_instruction

    instruction = build_instruction("de-CH")
    assert "get_current_weather" in instruction


def test_build_instruction_default_language():
    from voice_assistant.config import build_instruction, settings

    instruction = build_instruction(settings.default_language)
    assert instruction  # non-empty
