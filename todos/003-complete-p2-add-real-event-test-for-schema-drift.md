---
status: pending
priority: p2
issue_id: barge-in-003
tags: [code-review, testing, schema-drift]
dependencies: []
---

# Test fixture uses `SimpleNamespace`, not real ADK `Event` — schema drift risk

## Problem Statement

`tests/test_call_handler.py:34-65` (`_make_event` helper) builds `SimpleNamespace`-based fakes for ADK events. This is fast and convenient but provides zero schema fidelity:

- If ADK renames `interrupted` (or any other field), tests keep passing
- The real `Event.content` is `Optional[Content]` defaulting to `None`, but the helper always builds `SimpleNamespace(parts=[])`, so the `if event.content and event.content.parts:` guard at `voice_assistant/call_handler.py:261` is never exercised for the `content is None` case

## Findings

- `tests/test_call_handler.py:34-65` — `_make_event` returns `SimpleNamespace(...)`
- `voice_assistant/call_handler.py:261` — guards on `event.content is not None`, untested for None case
- Source: kieran-python-reviewer

## Proposed Solutions

### Option A — Add ONE real-Event test (recommended)
Add a single test that constructs `google.adk.events.Event(invocation_id="t", author="model", interrupted=True)` and runs it through `_run_adk`. Two lines, gives a schema contract check for free.

### Option B — Replace all `_make_event` calls with real Event construction
Higher fidelity but verbose; pydantic Event has many required fields.
- Effort: Medium

### Option C — Generate fixture via `Event.model_validate(dict)`
Cleaner middle ground. Use a dict literal that pydantic validates against the real schema.
- Effort: Small-Medium

## Recommended Action
_(filled during triage)_

## Acceptance Criteria
- [ ] At least one test in `tests/test_call_handler.py` constructs a real `google.adk.events.Event` (not `SimpleNamespace`) and exercises the barge-in path
- [ ] If ADK renames `interrupted`, the test fails

## Work Log
- 2026-04-09: Finding raised by kieran-python-reviewer
