---
status: pending
priority: p2
issue_id: barge-in-005
tags: [code-review, simplicity, polish]
dependencies: []
---

# 6-line comment block is verbose for the 7 lines of code it documents

## Problem Statement

`voice_assistant/call_handler.py:241-247` is a 6-line prose comment explaining the barge-in handler. The rest of the file uses 1-2 line comments (see `:212`, `:219-220`, `:232-234`, `:290-291`). The block is internally inconsistent with the file's comment style.

## Findings

- `voice_assistant/call_handler.py:241-247` — 6 lines of comment for 10 lines of code
- Source: code-simplicity-reviewer

## Proposed Solutions

### Option A — One-line comment (recommended)
Replace lines 241-247 with:
```python
# -- Barge-in: flush buffered Twilio audio and drop this event's audio --
```
- Pros: matches surrounding style
- Cons: loses the explanation of *why* (server-side VAD, Twilio buffer semantics)

### Option B — 2-line comment
```python
# -- Barge-in: Gemini's server-side VAD flagged caller speech mid-utterance.
# Flush Twilio's outbound buffer with `clear` and drop any audio on this event.
```
- Pros: keeps the *why*, matches style
- Cons: still longer than typical inline comments here

### Option C — Keep as-is
The detailed *why* is genuinely useful for a non-obvious protocol concern.
- Pros: best for new maintainers
- Cons: stylistically inconsistent

## Recommended Action
_(filled during triage)_

## Acceptance Criteria
- [ ] Comment block at `voice_assistant/call_handler.py:241-247` is reduced (1-2 lines) OR keeps current form with explicit decision documented in PR

## Work Log
- 2026-04-09: Finding raised by code-simplicity-reviewer
