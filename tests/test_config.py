"""Unit tests for config, settings, and instruction composition."""

from __future__ import annotations

import pytest

from voice_assistant.config import (
    LANGUAGE_PROFILES,
    Settings,
    build_instruction,
    settings,
)


# ---------------------------------------------------------------------------
# build_instruction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lang_code,expected_display",
    [
        ("de-CH", "Swiss German"),
        ("de-DE", "Standard German"),
        ("fr-CH", "Swiss French"),
        ("it-CH", "Swiss Italian"),
    ],
)
def test_build_instruction_contains_language(lang_code, expected_display):
    instruction = build_instruction(lang_code)
    assert expected_display in instruction


def test_build_instruction_includes_escalation():
    instruction = build_instruction("de-CH")
    assert "ESCALATION" in instruction


def test_build_instruction_includes_tool_guidance():
    instruction = build_instruction("de-CH")
    assert "get_current_weather" in instruction


def test_build_instruction_default_language():
    instruction = build_instruction(settings.default_language)
    assert len(instruction) > 100  # non-trivial content


def test_build_instruction_none_uses_default():
    instruction = build_instruction(None)
    default_display = LANGUAGE_PROFILES[settings.default_language]["display"]
    assert default_display in instruction


# ---------------------------------------------------------------------------
# Language profiles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang_code", ["de-CH", "de-DE", "fr-CH", "it-CH"])
def test_language_profile_has_required_keys(lang_code):
    profile = LANGUAGE_PROFILES[lang_code]
    assert "display" in profile
    assert "voice_name" in profile
    assert "greeting" in profile


def test_language_profile_lookup():
    profile = settings.language_profile("fr-CH")
    assert profile["display"] == "Swiss French"


def test_language_profile_fallback_to_default():
    profile = settings.language_profile("xx-XX")
    default_profile = LANGUAGE_PROFILES[settings.default_language]
    assert profile == default_profile


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------


def test_validate_missing_google_key_raises():
    s = Settings(google_api_key=None, google_cloud_project=None)
    with pytest.raises(EnvironmentError, match="GOOGLE_API_KEY"):
        s.validate(require_twilio=False)


def test_validate_with_api_key_passes():
    s = Settings(google_api_key="fake-key")
    s.validate(require_twilio=False)  # should not raise


def test_validate_twilio_required_raises_when_missing():
    s = Settings(
        google_api_key="fake-key",
        twilio_account_sid="",
        twilio_auth_token="",
        twilio_phone_number="",
    )
    with pytest.raises(EnvironmentError, match="TWILIO_ACCOUNT_SID"):
        s.validate(require_twilio=True)


def test_validate_twilio_not_required_skips_twilio():
    s = Settings(
        google_api_key="fake-key",
        twilio_account_sid="",
    )
    s.validate(require_twilio=False)  # should not raise


def test_use_vertex_ai_false_when_api_key_set():
    s = Settings(google_api_key="key", google_cloud_project="proj")
    assert s.use_vertex_ai() is False


def test_use_vertex_ai_true_when_only_project():
    s = Settings(google_api_key=None, google_cloud_project="proj")
    assert s.use_vertex_ai() is True
