"""
Audio format conversion utilities.

Twilio Media Streams deliver audio as:
  - mu-law (mulaw) encoded
  - 8 000 Hz sample rate
  - mono / 8-bit samples (after mu-law decoding -> 16-bit PCM)

Gemini Live API expects:
  - Linear PCM 16-bit little-endian
  - 16 000 Hz sample rate
  - mono

For the return path (Gemini -> Twilio) we reverse the chain.
"""

from __future__ import annotations

import audioop
import base64


# ---------------------------------------------------------------------------
# Twilio -> Gemini
# ---------------------------------------------------------------------------


def twilio_mulaw_to_gemini_pcm(mulaw_b64: str) -> bytes:
    """
    Convert a base64-encoded mu-law/8kHz chunk (as sent by Twilio) to
    linear PCM 16-bit / 16 kHz bytes suitable for Gemini Live API.
    """
    mulaw_bytes = base64.b64decode(mulaw_b64)
    # mu-law -> 16-bit linear PCM at 8 kHz
    pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
    # Upsample 8 kHz -> 16 kHz
    pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
    return pcm_16k


# ---------------------------------------------------------------------------
# Gemini -> Twilio
# ---------------------------------------------------------------------------


def gemini_pcm_to_twilio_mulaw_b64(pcm_24k: bytes) -> str:
    """
    Convert raw PCM 16-bit / 24 kHz bytes (as returned by Gemini Live API)
    to a base64-encoded mu-law/8kHz string ready to be sent back to Twilio.
    """
    # Downsample 24 kHz -> 8 kHz
    pcm_8k, _ = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, None)
    # 16-bit linear PCM -> mu-law
    mulaw_bytes = audioop.lin2ulaw(pcm_8k, 2)
    return base64.b64encode(mulaw_bytes).decode("ascii")
