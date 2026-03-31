"""
Call state model -- Phase enum, CallContext, and transition validation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any


class Phase(Enum):
    CONNECTING = auto()
    GREETING = auto()
    CONVERSATION = auto()
    FAREWELL = auto()
    ESCALATION = auto()
    TRANSFERRING = auto()
    ERROR = auto()
    ENDED = auto()


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: set[tuple[Phase, Phase]] = {
    # Happy path
    (Phase.CONNECTING, Phase.GREETING),
    (Phase.GREETING, Phase.CONVERSATION),
    (Phase.CONVERSATION, Phase.FAREWELL),
    (Phase.FAREWELL, Phase.ENDED),
    # Escalation path
    (Phase.CONVERSATION, Phase.ESCALATION),
    (Phase.ESCALATION, Phase.TRANSFERRING),
    (Phase.TRANSFERRING, Phase.ENDED),
    # Escalation fallback
    (Phase.ESCALATION, Phase.CONVERSATION),
    # Error paths
    (Phase.CONNECTING, Phase.ERROR),
    (Phase.CONNECTING, Phase.ENDED),
    (Phase.GREETING, Phase.ERROR),
    (Phase.CONVERSATION, Phase.ERROR),
    (Phase.ESCALATION, Phase.ERROR),
    (Phase.TRANSFERRING, Phase.ERROR),
    (Phase.ERROR, Phase.ENDED),
    (Phase.ERROR, Phase.CONVERSATION),  # recovery
    # Any phase -> ENDED on disconnect
    (Phase.GREETING, Phase.ENDED),
    (Phase.CONVERSATION, Phase.ENDED),
    (Phase.ESCALATION, Phase.ENDED),
    (Phase.ERROR, Phase.ENDED),
}


def can_transition(from_phase: Phase, to_phase: Phase) -> bool:
    """Return True if transitioning from *from_phase* to *to_phase* is valid."""
    return (from_phase, to_phase) in _VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# ToolInvocation record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolInvocation:
    name: str
    args: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# CallContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallContext:
    call_id: str = ""
    caller_number: str = ""
    language: str = "de-CH"

    phase: Phase = Phase.CONNECTING
    phase_entered_at: str = ""  # ISO 8601

    tool_invocations: tuple[ToolInvocation, ...] = ()
    turn_count: int = 0
    consecutive_errors: int = 0

    escalation_reason: str = ""
    transfer_target: str = ""

    started_at: str = ""  # ISO 8601
    ended_at: str = ""  # ISO 8601

    # -- helpers ------------------------------------------------------------

    def transition(self, to_phase: Phase) -> CallContext:
        """Return a new CallContext with the phase changed.

        Raises ValueError if the transition is not valid.
        """
        if not can_transition(self.phase, to_phase):
            raise ValueError(
                f"Invalid transition: {self.phase.name} -> {to_phase.name}"
            )
        now = datetime.now(timezone.utc).isoformat()
        updates: dict[str, Any] = {"phase": to_phase, "phase_entered_at": now}
        if to_phase == Phase.ENDED and not self.ended_at:
            updates["ended_at"] = now
        return replace(self, **updates)

    def record_tool(self, invocation: ToolInvocation) -> CallContext:
        """Return a new CallContext with the invocation appended."""
        return replace(
            self, tool_invocations=self.tool_invocations + (invocation,)
        )

    # -- serialization ------------------------------------------------------

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        d = asdict(self)
        d["phase"] = self.phase.name
        invocations = []
        for inv in self.tool_invocations:
            invocations.append(asdict(inv))
        d["tool_invocations"] = invocations
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> CallContext:
        """Deserialize from a JSON string."""
        d = json.loads(raw)
        d["phase"] = Phase[d["phase"]]
        d["tool_invocations"] = tuple(
            ToolInvocation(**inv) for inv in d["tool_invocations"]
        )
        return cls(**d)
