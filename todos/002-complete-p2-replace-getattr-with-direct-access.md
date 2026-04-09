---
status: pending
priority: p2
issue_id: barge-in-002
tags: [code-review, python, idiom, consistency]
dependencies: []
---

# Replace `getattr(event, "interrupted", None)` with `event.interrupted`

## Problem Statement

`voice_assistant/call_handler.py:248` uses `getattr(event, "interrupted", None)` to read the interrupted flag, but `google.adk.events.Event` inherits `interrupted: Optional[bool] = None` from `LlmResponse` as a real pydantic field — it is **always** present. The defensive `getattr` with a default is misleading and inconsistent with surrounding code.

## Findings

- `voice_assistant/call_handler.py:248` — `if getattr(event, "interrupted", None):`
- `voice_assistant/call_handler.py:261` — `if event.content and event.content.parts:` uses direct attribute access on the same Event object
- `voice_assistant/call_handler.py:213, 215, 225, 227` — earlier code uses `hasattr(...)` (also defensive); the file is internally inconsistent
- Confirmed via `inspect.getsource(LlmResponse)`: `interrupted: Optional[bool] = None`

Flagged independently by **3 reviewers**: kieran-python-reviewer, code-simplicity-reviewer, performance-oracle.

## Proposed Solutions

### Option A — Direct attribute access (recommended)
```python
if event.interrupted:
```
- Pros: matches the pydantic contract, consistent with `event.content` access at :261, removes ~50ns/event of overhead
- Cons: none
- Effort: Small (1 LOC change)
- Risk: zero — test fixtures already set `interrupted=...` explicitly via `_make_event`

### Option B — Keep as-is
Defensive `getattr` is harmless but inconsistent.
- Pros: none
- Cons: confusing, inconsistent

## Recommended Action
_(filled during triage)_

## Acceptance Criteria
- [ ] `voice_assistant/call_handler.py:248` uses `if event.interrupted:`
- [ ] All existing tests still pass
- [ ] (Optional) Audit other `hasattr` / `getattr` calls in the same loop for the same simplification

## Work Log
- 2026-04-09: Finding raised by 3 parallel reviewers
