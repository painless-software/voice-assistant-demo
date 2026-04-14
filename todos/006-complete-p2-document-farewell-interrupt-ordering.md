---
status: complete
priority: p2
issue_id: barge-in-006
tags: [code-review, architecture, regression-risk]
dependencies: []
---

# Farewell + interrupt ordering is load-bearing but undocumented

## Problem Statement

**Resolved.** The barge-in handler (`_handle_interrupt`) now runs BEFORE
farewell detection (`_detect_farewell`) and short-circuits with `continue`,
so an event with both farewell text and `interrupted=True` never reaches
farewell detection. Regression tests added:
- `test_farewell_and_interrupt_same_event_does_not_end_call`
- `test_stale_farewell_while_latched_does_not_end_call`

The ordering concern is now structurally enforced (interrupt handler returns
True → main loop skips the rest) rather than depending on inline block order.

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
