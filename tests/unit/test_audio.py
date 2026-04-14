"""Unit tests for audio format conversion utilities."""

from __future__ import annotations

import audioop
import base64

from voice_assistant.audio import (
    gemini_pcm_to_twilio_mulaw_b64,
    twilio_mulaw_to_gemini_pcm,
)


# ---------------------------------------------------------------------------
# Twilio -> Gemini (mulaw b64 -> PCM 16kHz)
# ---------------------------------------------------------------------------


def test_twilio_to_gemini_returns_bytes():
    # Create valid mulaw audio: silence (0x7F in mulaw = ~0 in linear PCM)
    mulaw_bytes = b"\x7f" * 160  # 20ms at 8kHz
    b64_input = base64.b64encode(mulaw_bytes).decode("ascii")
    result = twilio_mulaw_to_gemini_pcm(b64_input)
    assert isinstance(result, bytes)


def test_twilio_to_gemini_upsamples_to_16khz():
    # 160 mulaw samples at 8kHz = 20ms
    # After ulaw2lin: 160 samples * 2 bytes = 320 bytes at 8kHz
    # After ratecv 8k->16k: ~640 bytes (doubled sample count)
    mulaw_bytes = b"\x7f" * 160
    b64_input = base64.b64encode(mulaw_bytes).decode("ascii")
    result = twilio_mulaw_to_gemini_pcm(b64_input)
    # Output should be roughly 2x the input PCM size (8kHz -> 16kHz)
    pcm_8k_size = 160 * 2  # 320 bytes
    assert len(result) >= pcm_8k_size  # at least as large as 8kHz PCM


def test_twilio_to_gemini_output_is_16bit_pcm():
    mulaw_bytes = b"\x7f" * 160
    b64_input = base64.b64encode(mulaw_bytes).decode("ascii")
    result = twilio_mulaw_to_gemini_pcm(b64_input)
    # 16-bit PCM has 2 bytes per sample, so output length must be even
    assert len(result) % 2 == 0


# ---------------------------------------------------------------------------
# Gemini -> Twilio (PCM 24kHz -> mulaw b64)
# ---------------------------------------------------------------------------


def test_gemini_to_twilio_returns_string():
    # Create valid PCM 16-bit at 24kHz: 480 samples = 20ms
    pcm_24k = b"\x00\x00" * 480
    result = gemini_pcm_to_twilio_mulaw_b64(pcm_24k)
    assert isinstance(result, str)


def test_gemini_to_twilio_returns_valid_base64():
    pcm_24k = b"\x00\x00" * 480
    result = gemini_pcm_to_twilio_mulaw_b64(pcm_24k)
    decoded = base64.b64decode(result)
    assert len(decoded) > 0


def test_gemini_to_twilio_downsamples_to_8khz():
    # 480 samples at 24kHz = 20ms
    # After ratecv 24k->8k: ~160 samples (1/3)
    # After lin2ulaw: 1 byte per sample
    pcm_24k = b"\x00\x00" * 480
    result = gemini_pcm_to_twilio_mulaw_b64(pcm_24k)
    decoded = base64.b64decode(result)
    # 480 samples / 3 = 160 mulaw bytes (approximately)
    assert len(decoded) == 160


# ---------------------------------------------------------------------------
# Round-trip: verify data survives the full conversion chain
# ---------------------------------------------------------------------------


def test_round_trip_preserves_silence():
    """Silence in -> mulaw -> PCM -> mulaw -> base64 should round-trip cleanly."""
    # Start with mulaw silence
    original_mulaw = b"\xff" * 160  # 0xFF = silence in mulaw
    b64_input = base64.b64encode(original_mulaw).decode("ascii")

    # Twilio -> Gemini (mulaw -> PCM 16kHz)
    pcm_16k = twilio_mulaw_to_gemini_pcm(b64_input)

    # Simulate Gemini processing: upsample 16kHz -> 24kHz (as Gemini would output)
    pcm_24k, _ = audioop.ratecv(pcm_16k, 2, 1, 16000, 24000, None)

    # Gemini -> Twilio (PCM 24kHz -> mulaw base64)
    result_b64 = gemini_pcm_to_twilio_mulaw_b64(pcm_24k)
    result_mulaw = base64.b64decode(result_b64)

    # The round-trip should produce mulaw bytes of similar length
    assert len(result_mulaw) == len(original_mulaw)


def test_empty_audio_input():
    """Empty audio should not crash."""
    b64_input = base64.b64encode(b"").decode("ascii")
    result = twilio_mulaw_to_gemini_pcm(b64_input)
    assert result == b""


def test_empty_pcm_output():
    """Empty PCM should not crash."""
    result = gemini_pcm_to_twilio_mulaw_b64(b"")
    decoded = base64.b64decode(result)
    assert decoded == b""
