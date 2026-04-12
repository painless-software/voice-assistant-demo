---
status: pending
priority: p2
issue_id: barge-in-006
tags: [code-review, architecture, regression-risk]
dependencies: []
---

# Farewell + interrupt ordering is load-bearing but undocumented

## Problem Statement

The barge-in block at `voice_assistant/call_handler.py:248-257` runs **after** the farewell-detection block at `:225-239`. This ordering is load-bearing:

- If a single event has both `output_transcription` (with farewell text) and `interrupted=True`, the farewell block sets `draining=True`, then the interrupt block immediately sets `draining=False`. Net effect: agent said goodbye but caller barged in, so call stays open. **Correct.**
- If a future refactor moves the interrupt block above the farewell block, the logic silently breaks: `draining` would be set after the interrupt cleared it.

There is no comment marking this dependency, and no test exercises the same-event farewell+interrupted case.

## Findings

- `voice_assistant/call_handler.py:225-239` — farewell detection sets `draining`
- `voice_assistant/call_handler.py:254-256` — interrupt block clears `draining`
- No test in `tests/test_call_handler.py` constructs an event with both `output_text=` and `interrupted=True`
- Source: architecture-strategist + kieran-python-reviewer

## Proposed Solutions

### Option A — Add a regression test (recommended)
```python
async def test_farewell_and_interrupt_in_same_event_does_not_drain():
    ws = AsyncMock()
    call_end_event = asyncio.Event()
    events = [
        _make_event(output_text="Adé!", interrupted=True),  # both!
        _make_event(),
    ]
    await _run_adk(events, ws, call_end_event=call_end_event)
    assert not call_end_event.is_set()  # interrupt cancelled drain
```
- Pros: test pins down the contract; future refactor breaks loudly
- Effort: Small

### Option B — Add a code comment
```python
# NOTE: this block must run AFTER farewell detection so an event carrying
# both farewell text and interrupted=True correctly cancels drain.
```
- Pros: zero test maintenance
- Cons: comments lie; tests don't

### Option C — Both A and B

## Recommended Action
_(filled during triage)_

## Acceptance Criteria
- [ ] Either a regression test or a clear code comment (preferably both) makes the ordering dependency explicit

## Work Log
- 2026-04-09: Finding raised by architecture-strategist and kieran-python-reviewer
