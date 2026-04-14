---
status: pending
priority: p3
issue_id: arch-001
tags: [architecture, refactor, follow-up]
dependencies: []
---

# `_adk_to_twilio` is approaching unmaintainable inline state machine

## Problem Statement

`voice_assistant/call_handler.py:194-313` (`_adk_to_twilio`) now implements at least 4 implicit state transitions (idle → speaking → draining → ending, plus interrupt branches) using local booleans (`draining`, future `interrupted_latch`) and `continue` guards. The barge-in PR adds yet another inlined branch.

Adding the next event-level concern (function calls, error events, end-of-turn markers, session resumption) will require yet more inlined branches and silent ordering dependencies (see todo 006). This is the classic "procedural state machine growing past its seams" smell.

## Findings

- `_adk_to_twilio` does 8 distinct things in 110 lines:
  1. ADK event iteration
  2. Transcription logging
  3. Farewell detection
  4. Drain state machine
  5. **Barge-in clear (new)**
  6. PCM→mulaw conversion
  7. Twilio framing (media + mark)
  8. `goodbye-done` mark emission
- Tests in `tests/test_call_handler.py` already work around the complexity by constructing `SimpleNamespace` events with many optional fields
- Source: architecture-strategist

## Proposed Solutions

### Option A — Extract `CallState` class
```python
class CallState:
    def on_event(self, event) -> list[OutboundMessage]:
        # transitions live here, single source of truth for ordering
```
Loop becomes a 5-line pump: read, dispatch, send.
- Pros: orderings are explicit; tests assert on intent; pays off immediately when next branch added
- Cons: medium-large refactor; touches a hot path; needs careful test migration

### Option B — Extract Twilio framing first
Move `gemini_pcm_to_twilio_mulaw_b64` + `{"event":"media",...}` / `{"event":"mark",...}` / `{"event":"clear",...}` dicts into a `voice_assistant/twilio_protocol.py` module. Loop sends "audio"/"mark"/"clear" intents.
- Pros: smaller scope; lets tests stop asserting on JSON shapes
- Cons: doesn't address the state-machine sprawl

### Option C — Defer
Land barge-in as-is (no follow-up). Pay the cost when next branch is added.
- Pros: no work
- Cons: technical debt compounds

## Recommended Action
**Defer until the next event-level branch is needed (function-call handling, error events, etc.).** When that PR is opened, do the `CallState` extraction first.

## Acceptance Criteria
- [ ] Decision documented (defer / extract now)
- [ ] If extracting: `_adk_to_twilio` becomes ≤30 lines and the state machine has a single source of truth

## Work Log
- 2026-04-09: Finding raised by architecture-strategist
