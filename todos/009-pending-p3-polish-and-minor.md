---
status: pending
priority: p3
issue_id: barge-in-polish
tags: [code-review, polish, nice-to-have]
dependencies: []
---

# Barge-in PR — minor polish items

## Problem Statement

A handful of minor polish suggestions from the multi-agent review that don't individually warrant their own todos.

## Findings

### F1 — Drop redundant second log line
`voice_assistant/call_handler.py:255` — `log.info("Interrupted during goodbye — cancelling drain")` adds nothing operators need on top of the first log at `:249`. Replace lines 254-256 with unconditional `draining = False`.
Source: code-simplicity-reviewer

### F2 — Inline `stream_sid` local variable
`voice_assistant/call_handler.py:250-253` — local `stream_sid = sid_holder[0]` exists only to branch on truthiness. Collapse to `if sid_holder[0]: await ws.send_text(json.dumps({"event": "clear", "streamSid": sid_holder[0]}))`. Saves 2 lines, matches terse style at `:294-301`.
Source: code-simplicity-reviewer

### F3 — Move barge-in branch to top of loop body
`voice_assistant/call_handler.py:213-257` — barge-in is "flush and skip"; nothing else on the event should be honored. Moving the check to the top of the loop body avoids running farewell detection on a stale utterance. Tension with todo 006 (current ordering is load-bearing for combined farewell+interrupt) — only do this if we add an explicit comment that the farewell+interrupt case is handled differently.
Source: kieran-python-reviewer

### F4 — Add explicit "interrupt when not draining" test
`tests/test_call_handler.py:385-466` — current tests don't pin down that interrupt without an active drain doesn't accidentally touch any state. One small parametrized assertion would lock the branch structure.
Source: kieran-python-reviewer

### F5 — Demote logs to DEBUG
`voice_assistant/call_handler.py:249, 255` — be consistent with other per-chunk logging at `:231` which is DEBUG. **Tension** with security-sentinel which says INFO is valuable for production debugging. Decision: keep at INFO unless flooding becomes a real problem (see todo 004 for the rate-limit fix).
Source: kieran-python-reviewer (rejected by security-sentinel)

### F6 — Document this PR as the first entry in `docs/solutions/`
After landing, write up the `interrupted` → Twilio `clear` mapping as a learning. The repo has `docs/brainstorms/` and `docs/plans/` but no `docs/solutions/` directory yet — this would be the first entry.
Source: learnings-researcher

## Recommended Action
_(triage these individually — most are subjective polish)_

## Acceptance Criteria
- [ ] Each finding triaged and either applied or explicitly rejected with reason

## Work Log
- 2026-04-09: Findings collected from multi-agent review
