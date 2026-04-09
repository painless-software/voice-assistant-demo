---
status: pending
priority: p2
issue_id: barge-in-001
tags: [code-review, correctness, async, latency]
dependencies: []
---

# Stale audio plays after Twilio `clear` (no interrupt latch)

## Problem Statement

The new barge-in handler at `voice_assistant/call_handler.py:248-257` calls `continue` to drop *the current event's* audio after sending Twilio `clear`. But if Gemini Live already pushed several audio events into ADK's `runner.run_live(...)` async iterator buffer **before** emitting `interrupted=True`, the next loop iterations will send those stale audio events to Twilio AFTER the `clear`. Twilio's `clear` only flushes its outbound buffer once — anything we `send_text` after the clear plays normally.

Net effect: caller hears 60-300ms of stale agent audio after barging in. The clear "fires" (and unit tests prove that) but the feature doesn't feel snappy on real calls.

## Findings

- `voice_assistant/call_handler.py:257` — `continue` only handles the current event
- `voice_assistant/call_handler.py:206-211` — `async for event in runner.run_live(...)` iterator can buffer events ahead of consumption
- Unit tests in `tests/test_call_handler.py:385-466` cannot detect this race because they feed events synchronously through `_fake_run_live`

Source: performance-oracle review (highest-impact finding in the PR).

## Proposed Solutions

### Option A — Interrupt latch boolean (recommended)
```python
interrupted_latch = False  # initialize at top of _adk_to_twilio
...
if event.interrupted:
    interrupted_latch = True
    # send clear, cancel drain, continue
if interrupted_latch and (audio in event):
    continue  # drop stale buffered audio
if event.input_transcription and event.input_transcription.text:
    interrupted_latch = False  # next user turn started
```
- Pros: minimal change, handles real backlog scenario
- Cons: adds one more local-state flag to the loop
- Effort: Small (10-15 LOC + 2 tests)
- Risk: low

### Option B — Aggressive drain via `runner.run_live` cancellation
Cancel the current `async for` and restart it. Heavier-handed; may lose in-flight transcription/state.
- Pros: bulletproof
- Cons: complex, may break drain/farewell logic, untested
- Effort: Medium
- Risk: medium-high

### Option C — Defer to follow-up + document the limitation in PR description
Land as-is, note "stale-audio-after-clear race may exist; needs real phone test".
- Pros: zero-cost now
- Cons: known incomplete behavior

## Recommended Action
_(filled during triage)_

## Acceptance Criteria
- [ ] Add `interrupted_latch` (or equivalent) so audio events arriving after the interrupt are dropped until the next user-turn boundary
- [ ] Add a test that simulates audio events queued after an interrupt and asserts they are NOT forwarded to Twilio
- [ ] Manual test on a real phone call confirms the barge-in feels snappy (no stale audio after "stop")

## Work Log
- 2026-04-09: Finding raised by performance-oracle review on `feat/barge-in-support`
