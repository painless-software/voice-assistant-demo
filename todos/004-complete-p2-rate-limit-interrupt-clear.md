---
status: pending
priority: p2
issue_id: barge-in-004
tags: [code-review, security, resource-exhaustion, observability]
dependencies: []
---

# No rate limit / debounce on barge-in clear path

## Problem Statement

`voice_assistant/call_handler.py:248-257` sends a Twilio `clear` and writes a `log.info` line on **every** event with `interrupted=True`. Gemini Live can emit multiple consecutive interrupted events during a single barge-in window, and a misbehaving upstream (or an attacker exploiting the unauthenticated `/ws/media-stream` — see todo 007) can drive this much higher.

Impact (within `MAX_CALL_DURATION = 300s`):
- Unbounded `clear` frames sent to Twilio (likely tolerated, but wasteful)
- Unbounded `log.info` lines (expensive for structured-logging pipelines / log-aggregator costs)
- Bounded only by `MAX_CALL_DURATION`, no per-call cap

## Findings

- `voice_assistant/call_handler.py:248-257` — no debounce
- `voice_assistant/call_handler.py:33` — `MAX_CALL_DURATION = 5 * 60`
- Source: security-sentinel + architecture-strategist

## Proposed Solutions

### Option A — Time-based debounce
Track `last_clear_at` and ignore interrupts within ~50ms of the previous clear.
- Pros: bounds the worst case
- Cons: another stateful local; choice of threshold is empirical
- Effort: Small

### Option B — "Already cleared this turn" latch
Set a flag when we send a clear; reset on next user-turn boundary (input_transcription text). Combines naturally with todo 001 (interrupt latch).
- Pros: no time math, fits the architecture
- Cons: relies on solving todo 001 first
- Effort: Small (when paired with 001)

### Option C — Demote subsequent log lines to DEBUG
Keep the first interrupt at INFO, demote follow-ups to DEBUG.
- Pros: cheapest fix for the log-flooding half
- Cons: doesn't address unbounded `clear` sends

## Recommended Action
_(filled during triage)_

## Acceptance Criteria
- [ ] Repeated `interrupted=True` events within a single barge-in window send at most one `clear` to Twilio
- [ ] Log noise is bounded (one INFO line per barge-in, not per event)
- [ ] Test covers consecutive interrupted events

## Work Log
- 2026-04-09: Finding raised by security-sentinel and architecture-strategist
