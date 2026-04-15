---
title: "feat: Add ElevenLabs as alternative voice backend"
type: feat
status: active
date: 2026-04-15
origin: https://github.com/painless-software/voice-assistant-demo/issues/17
---

# feat: Add ElevenLabs as alternative voice backend (issue #17)

## Context

The demo currently uses Gemini's native-audio model as a monolithic STT+LLM+TTS pipeline. We want to add ElevenLabs as an alternative TTS backend so operators can compare voice quality, latency, and cost. When ElevenLabs is selected, Gemini still handles STT and LLM (via its Live API in text mode), but TTS is delegated to ElevenLabs' streaming WebSocket API.

## Architecture

**Gemini path (default, unchanged):**
```
Caller audio → Gemini Live native-audio (STT+LLM+TTS) → audio → Twilio
```

**ElevenLabs path (new):**
```
Caller audio → Gemini Live text mode (STT+LLM) → text → ElevenLabs TTS → audio → Twilio
```

Key difference: with ElevenLabs, `response_modalities=["TEXT"]` and we use the standard `gemini-2.5-flash` model (not native-audio) for the Live API. ADK events carry text in `event.content.parts[].text` instead of audio in `event.content.parts[].inline_data`. That text is streamed to ElevenLabs which returns PCM audio chunks.

## Implementation steps

### 1. `voice_assistant/config.py` — add settings and profile fields

- Add to `Settings`: `voice_backend` (str, default `"gemini"`, from `VOICE_BACKEND`), `elevenlabs_api_key` (from `ELEVENLABS_API_KEY`), `elevenlabs_model_id` (default `"eleven_turbo_v2_5"`, from `ELEVENLABS_MODEL_ID`)
- Add `elevenlabs_voice_id` to each language profile (ElevenLabs voice IDs per language)
- Extend `validate()`: when `voice_backend == "elevenlabs"`, require `elevenlabs_api_key`

### 2. `voice_assistant/elevenlabs_tts.py` — new file, streaming TTS client

Async WebSocket client wrapping ElevenLabs' text-to-speech streaming API (`wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`). ~80-100 lines.

- `ElevenLabsTTS` class with:
  - `connect(voice_id, model_id, api_key, output_format)` — opens WebSocket, sends BOS (beginning-of-stream) config
  - `send_text(text)` — streams a text chunk
  - `flush()` — sends empty string to signal end of input, triggering final audio generation
  - `receive_audio()` — async generator yielding raw PCM audio chunks (decoded from base64 in the response JSON)
  - `interrupt()` — closes the WebSocket to abort generation
- Uses `websockets` library (already a transitive dep via google-adk, add explicitly to pyproject.toml)
- Output format: `pcm_24000` (16-bit PCM@24kHz) — matches Gemini's output, so existing `gemini_pcm_to_twilio_mulaw_b64()` works unchanged

### 3. `voice_assistant/agent.py` — conditional live model

When `voice_backend == "elevenlabs"`, the live model should be the standard text model (not native-audio), since we only need STT+LLM from Gemini:

```python
class _DualModelGemini(Gemini):
    live_model: str = (
        GEMINI_MODEL if settings.voice_backend == "elevenlabs" else GEMINI_LIVE_MODEL
    )
```

### 4. `voice_assistant/call_handler.py` — branch on backend

**In `handle_media_stream()`:**
- When `voice_backend == "gemini"`: current RunConfig with `response_modalities=["AUDIO"]` and `speech_config`
- When `voice_backend == "elevenlabs"`: RunConfig with `response_modalities=["TEXT"]`, no speech_config

**In `_adk_to_twilio()`:**
- Add an `ElevenLabsTTS` instance (created per call) when backend is elevenlabs
- New helper `_stream_text_to_tts(event, tts)` — extracts text from `event.content.parts[].text`, calls `tts.send_text()`
- Spawn a background task `_tts_audio_to_twilio(tts, ws, sid_holder)` that reads from `tts.receive_audio()` and forwards converted mulaw to Twilio
- Farewell detection: use `event.content.parts[].text` directly (since `output_transcription` may not be available in text mode)
- On interrupt: call `tts.interrupt()` in addition to sending Twilio `clear`
- On flush (end of agent turn): call `tts.flush()`

**Barge-in with ElevenLabs:**
1. Gemini detects caller speech → `event.interrupted = True`
2. Send Twilio `clear` (same as now)
3. Call `tts.interrupt()` — closes WebSocket, stops audio generation
4. Set `interrupt_latched` (same as now) — suppresses stale text events
5. On next user turn: latch clears, new TTS WebSocket opened for next agent response

### 5. `voice_assistant/audio.py` — no changes

ElevenLabs outputs PCM@24kHz (via `pcm_24000` format), same as Gemini. The existing `gemini_pcm_to_twilio_mulaw_b64()` works as-is.

### 6. `pyproject.toml` — add dependency

Run `uv add websockets` to add the dependency.

### 7. `.env.example` — document new variables

Add a `Voice Backend` section with `VOICE_BACKEND`, `ELEVENLABS_API_KEY`, `ELEVENLABS_MODEL_ID`.

### 8. Tests

- **`tests/unit/test_elevenlabs_tts.py`** (new) — test `send_text`, `flush`, `receive_audio`, `interrupt` with a mock WebSocket
- **`tests/unit/test_call_handler.py`** — add tests for elevenlabs path: text events streamed to TTS, barge-in calls `tts.interrupt()`, farewell detection from text content
- **`tests/unit/test_config.py`** — test new settings fields, validation when `voice_backend == "elevenlabs"`

## Files to modify/create

| File | Action |
|---|---|
| `voice_assistant/config.py` | Modify — add settings + profile fields |
| `voice_assistant/elevenlabs_tts.py` | **Create** — streaming TTS client |
| `voice_assistant/agent.py` | Modify — conditional live model (~2 lines) |
| `voice_assistant/call_handler.py` | Modify — branch on backend, TTS integration |
| `voice_assistant/audio.py` | No changes |
| `pyproject.toml` | Modify via `uv add websockets` |
| `.env.example` | Modify — document new env vars |
| `tests/unit/test_elevenlabs_tts.py` | **Create** — TTS client tests |
| `tests/unit/test_call_handler.py` | Modify — add elevenlabs path tests |
| `tests/unit/test_config.py` | Modify — test new settings |

## Verification

1. `just pytest` — all existing + new tests pass
2. `just fmt` — formatting clean
3. Set `VOICE_BACKEND=gemini` (or unset) — existing behavior unchanged
4. Manual test with `VOICE_BACKEND=elevenlabs` + `ELEVENLABS_API_KEY` — caller hears ElevenLabs voice
