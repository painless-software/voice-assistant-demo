---
status: pending
priority: p1
issue_id: security-001
tags: [security, pre-existing, billing-abuse, dos, scope-out-of-pr]
dependencies: []
---

# PRE-EXISTING: `/voice` and `/ws/media-stream` have zero authentication

## Problem Statement

**Out of scope for `feat/barge-in-support` but uncovered during its security review.**

`voice_assistant/app.py:107-109` — the `/ws/media-stream` WebSocket endpoint calls `websocket.accept()` with no signature check, no token, no origin validation, no IP allowlist.

`voice_assistant/app.py:56-80` — the `/voice` HTTP webhook does not verify Twilio's `X-Twilio-Signature` header even though `twilio_auth_token` is loaded in `config.py:112`.

## Attack Path

1. Attacker discovers `PUBLIC_URL` (e.g., from public GitHub Actions logs, Cloud Run service URL)
2. Opens a direct WS to `wss://<host>/ws/media-stream`
3. Sends a synthetic `start` event with attacker-controlled `streamSid` (`call_handler.py:151` blindly trusts `msg["streamSid"]`)
4. Streams arbitrary PCM into `live_queue.send_realtime()` (`call_handler.py:157`), **burning Gemini Live API quota on the operator's account**
5. Holds the connection for `MAX_CALL_DURATION = 300s` (`call_handler.py:33`), no concurrent-connection cap

**Direct path to billing abuse + DoS.** The barge-in PR makes this slightly worse by adding a new write amplification path (Twilio `clear` per interrupted event), but the underlying gap exists today.

## Findings

- `voice_assistant/app.py:107-109` — unauth WebSocket
- `voice_assistant/app.py:56-80` — no Twilio signature validation
- `voice_assistant/call_handler.py:33` — `MAX_CALL_DURATION = 300`, no per-IP/per-call rate limit
- `voice_assistant/call_handler.py:151, 157` — blindly forwards caller-controlled data
- `voice_assistant/config.py:112` — `twilio_auth_token` is already loaded but unused for validation
- Source: security-sentinel review

## Proposed Solutions

### Option A — Validate `X-Twilio-Signature` on `/voice` + signed token on WS (recommended)
1. Use `twilio.request_validator.RequestValidator` on `/voice`
2. Have `/voice` mint a short-lived (60s) signed token, embed it in the WSS URL passed to `<Stream url="...">` 
3. Validate the token on WS connect before `accept()`
- Pros: industry standard, defense in depth
- Cons: requires JWT or HMAC implementation; needs Twilio relay testing
- Effort: Medium

### Option B — Validate `accountSid` from first `start` event
After receiving Twilio's `start` event, check `msg.get("accountSid")` against `settings.twilio_account_sid` before forwarding any audio. Lighter weight.
- Pros: no token plumbing
- Cons: not cryptographically authenticated; only verifies SID claim

### Option C — IP allowlist on `/voice` + WS
Twilio publishes its IP ranges. Allowlist + reject everything else.
- Pros: zero code in the request path
- Cons: requires keeping IP list current, blocks legit testing tools

## Recommended Action
**Open a separate GitHub issue for this — do NOT bundle into the barge-in PR.** This is pre-existing scope and should land in its own focused PR.

## Acceptance Criteria
- [ ] Separate GitHub issue created with `security` label
- [ ] `/voice` validates `X-Twilio-Signature` (or equivalent)
- [ ] `/ws/media-stream` rejects unauthenticated connections

## Work Log
- 2026-04-09: Finding raised by security-sentinel during barge-in review
- Status: documented; **not blocking** this PR
