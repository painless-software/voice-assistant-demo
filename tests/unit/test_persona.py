"""Unit tests for persona loading, validation, and prompt composition."""

from __future__ import annotations

import pytest

from unittest.mock import patch

from voice_assistant.config import (
    PERSONA,
    PERSONA_BLOCK,
    _default_persona_name,
    _load_persona,
    _render_persona_block,
    build_instruction,
    load_all_personas,
    settings,
)


# ---------------------------------------------------------------------------
# Persona loading
# ---------------------------------------------------------------------------


def test_load_persona_returns_dict():
    persona = _load_persona("velo_shop")
    assert isinstance(persona, dict)
    assert persona["name"] == "Velo Züri"


def test_load_persona_has_required_fields():
    persona = _load_persona("velo_shop")
    assert "name" in persona
    assert "allowed_topics" in persona
    assert "out_of_scope_decline" in persona


def test_load_persona_missing_file_raises():
    with pytest.raises(EnvironmentError, match="Persona file not found"):
        _load_persona("nonexistent_persona")


def test_load_persona_has_business_facts():
    persona = _load_persona("velo_shop")
    assert "business_facts" in persona
    assert "hours" in persona["business_facts"]


# ---------------------------------------------------------------------------
# Persona block rendering
# ---------------------------------------------------------------------------


def test_render_persona_block_contains_name():
    block = _render_persona_block(PERSONA)
    assert "Velo Züri" in block


def test_render_persona_block_contains_topics():
    block = _render_persona_block(PERSONA)
    assert "YOUR EXPERTISE" in block
    assert "Velo-Reparatur" in block


def test_render_persona_block_contains_facts():
    block = _render_persona_block(PERSONA)
    assert "BUSINESS INFORMATION" in block
    assert "Canyon" in block


def test_render_persona_block_contains_scope_rules():
    block = _render_persona_block(PERSONA)
    assert "SCOPE RULES" in block
    assert "NEVER pretend" in block


def test_render_persona_block_contains_decline():
    block = _render_persona_block(PERSONA)
    assert "ausserhalb meines Bereichs" in block


def test_render_minimal_persona():
    minimal = {
        "name": "Test Shop",
        "allowed_topics": ["Topic A"],
        "out_of_scope_decline": "Sorry, can't help with that.",
    }
    block = _render_persona_block(minimal)
    assert "Test Shop" in block
    assert "Topic A" in block
    assert "No additional facts available." in block


# ---------------------------------------------------------------------------
# Module-level persona state
# ---------------------------------------------------------------------------


def test_persona_loaded_at_module_level():
    assert PERSONA["name"] == "Velo Züri"
    assert len(PERSONA_BLOCK) > 100


# ---------------------------------------------------------------------------
# Prompt composition with persona
# ---------------------------------------------------------------------------


def test_build_instruction_contains_persona_name():
    instruction = build_instruction("de-CH")
    assert "Velo Züri" in instruction


def test_build_instruction_contains_scope_rules():
    instruction = build_instruction("de-CH")
    assert "SCOPE RULES" in instruction
    assert "NEVER pretend" in instruction


def test_build_instruction_contains_decline_template():
    instruction = build_instruction("de-CH")
    assert "ausserhalb meines Bereichs" in instruction


def test_build_instruction_still_has_escalation():
    instruction = build_instruction("de-CH")
    assert "ESCALATION" in instruction


# ---------------------------------------------------------------------------
# Greeting override
# ---------------------------------------------------------------------------


def test_greeting_override_from_persona():
    profile = settings.language_profile("de-CH")
    assert "Velo Züri" in profile["greeting"]


def test_greeting_override_preserves_other_fields():
    profile = settings.language_profile("de-CH")
    assert "voice_name" in profile
    assert "fallback_reply" in profile


def test_greeting_fallback_for_unknown_locale():
    profile = settings.language_profile("xx-XX")
    # Falls back to default language profile; persona may or may not have
    # a greeting for the default locale, but the profile must have a greeting.
    assert "greeting" in profile


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_load_all_personas():
    personas = load_all_personas()
    assert "velo_shop" in personas
    assert personas["velo_shop"]["name"] == "Velo Züri"


def test_default_persona_name_picks_first_available(monkeypatch):
    monkeypatch.delenv("PERSONA", raising=False)
    name = _default_persona_name()
    assert name == "velo_shop"


def test_default_persona_name_returns_empty_when_no_files(tmp_path, monkeypatch):
    monkeypatch.delenv("PERSONA", raising=False)
    with patch("voice_assistant.config._PERSONAS_DIR", tmp_path):
        assert _default_persona_name() == ""


def test_load_persona_invalid_yaml(tmp_path):
    (tmp_path / "bad.yaml").write_text("just a string")
    with patch("voice_assistant.config._PERSONAS_DIR", tmp_path):
        with pytest.raises(EnvironmentError, match="YAML mapping"):
            _load_persona("bad")


def test_load_persona_missing_required_fields(tmp_path):
    (tmp_path / "incomplete.yaml").write_text("name: Test\n")
    with patch("voice_assistant.config._PERSONAS_DIR", tmp_path):
        with pytest.raises(EnvironmentError, match="missing required fields"):
            _load_persona("incomplete")
