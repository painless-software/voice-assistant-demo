"""Tests for Phase enum, CallContext, and transition validation."""

from __future__ import annotations

import json

import pytest

from voice_assistant.state import (
    CallContext,
    Phase,
    ToolInvocation,
    can_transition,
)


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "from_phase,to_phase",
    [
        # Happy path
        (Phase.CONNECTING, Phase.GREETING),
        (Phase.GREETING, Phase.CONVERSATION),
        (Phase.CONVERSATION, Phase.FAREWELL),
        (Phase.FAREWELL, Phase.ENDED),
        # Escalation
        (Phase.CONVERSATION, Phase.ESCALATION),
        (Phase.ESCALATION, Phase.TRANSFERRING),
        (Phase.TRANSFERRING, Phase.ENDED),
        (Phase.ESCALATION, Phase.CONVERSATION),
        # Error paths
        (Phase.CONNECTING, Phase.ERROR),
        (Phase.CONNECTING, Phase.ENDED),
        (Phase.CONVERSATION, Phase.ERROR),
        (Phase.FAREWELL, Phase.ERROR),
        (Phase.ERROR, Phase.ENDED),
        (Phase.ERROR, Phase.CONVERSATION),
        # Direct disconnects
        (Phase.GREETING, Phase.ENDED),
        (Phase.CONVERSATION, Phase.ENDED),
        (Phase.ESCALATION, Phase.ENDED),
    ],
)
def test_valid_transition(from_phase, to_phase):
    assert can_transition(from_phase, to_phase) is True


@pytest.mark.parametrize(
    "from_phase,to_phase",
    [
        (Phase.ENDED, Phase.CONNECTING),
        (Phase.ENDED, Phase.CONVERSATION),
        (Phase.GREETING, Phase.FAREWELL),
        (Phase.FAREWELL, Phase.CONVERSATION),
        (Phase.TRANSFERRING, Phase.GREETING),
        (Phase.CONNECTING, Phase.CONVERSATION),
        (Phase.CONNECTING, Phase.FAREWELL),
    ],
)
def test_invalid_transition(from_phase, to_phase):
    assert can_transition(from_phase, to_phase) is False


# ---------------------------------------------------------------------------
# CallContext creation and immutability
# ---------------------------------------------------------------------------


def test_default_phase_is_connecting():
    ctx = CallContext()
    assert ctx.phase == Phase.CONNECTING


def test_frozen_cannot_assign():
    ctx = CallContext()
    with pytest.raises(AttributeError):
        ctx.phase = Phase.GREETING  # type: ignore[misc]


def test_transition_returns_new_context():
    ctx = CallContext()
    new_ctx = ctx.transition(Phase.GREETING)
    assert new_ctx.phase == Phase.GREETING
    assert ctx.phase == Phase.CONNECTING  # original unchanged


def test_transition_sets_phase_entered_at():
    ctx = CallContext()
    new_ctx = ctx.transition(Phase.GREETING)
    assert new_ctx.phase_entered_at != ""


def test_transition_to_ended_sets_ended_at():
    ctx = CallContext(phase=Phase.CONVERSATION)
    new_ctx = ctx.transition(Phase.ENDED)
    assert new_ctx.ended_at != ""


def test_invalid_transition_raises():
    ctx = CallContext(phase=Phase.ENDED)
    with pytest.raises(ValueError, match="Invalid transition"):
        ctx.transition(Phase.GREETING)


def test_record_tool():
    ctx = CallContext()
    inv = ToolInvocation(
        name="get_weather", args={"city": "Bern"}, result={"temp": 18}
    )
    new_ctx = ctx.record_tool(inv)
    assert len(new_ctx.tool_invocations) == 1
    assert new_ctx.tool_invocations[0].name == "get_weather"
    assert len(ctx.tool_invocations) == 0  # original unchanged


def test_tool_invocations_are_tuple():
    ctx = CallContext()
    assert isinstance(ctx.tool_invocations, tuple)


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_to_json_produces_valid_json():
    ctx = CallContext(call_id="test-123", language="fr-CH")
    raw = ctx.to_json()
    parsed = json.loads(raw)
    assert parsed["call_id"] == "test-123"
    assert parsed["phase"] == "CONNECTING"


def test_round_trip():
    ctx = CallContext(
        call_id="rt-001",
        caller_number="+41791234567",
        language="de-CH",
        phase=Phase.CONVERSATION,
        turn_count=5,
        consecutive_errors=1,
    )
    inv = ToolInvocation(
        name="weather",
        args={"city": "Zürich"},
        result={"temp": 20},
        duration_ms=42.5,
    )
    ctx = ctx.record_tool(inv)
    restored = CallContext.from_json(ctx.to_json())
    assert restored.call_id == ctx.call_id
    assert restored.phase == ctx.phase
    assert restored.turn_count == ctx.turn_count
    assert len(restored.tool_invocations) == 1
    assert restored.tool_invocations[0].name == "weather"
    assert restored.tool_invocations[0].duration_ms == 42.5


def test_round_trip_empty_context():
    ctx = CallContext()
    restored = CallContext.from_json(ctx.to_json())
    assert restored == ctx


def test_phase_serialized_as_name():
    ctx = CallContext(phase=Phase.ESCALATION)
    raw = ctx.to_json()
    assert '"ESCALATION"' in raw
