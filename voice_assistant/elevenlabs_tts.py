"""
Async streaming TTS client for ElevenLabs WebSocket API.

Opens a WebSocket to ElevenLabs' ``stream-input`` endpoint, streams text
chunks in, and yields raw PCM audio chunks back.  Output format is
``pcm_24000`` (16-bit LE mono @ 24 kHz) — the same format Gemini Live
produces, so the existing ``gemini_pcm_to_twilio_mulaw_b64()`` converter
works unchanged.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncGenerator

import websockets

log = logging.getLogger(__name__)

_BASE_URL = "wss://api.elevenlabs.io/v1/text-to-speech"
_OUTPUT_FORMAT = "pcm_24000"


class ElevenLabsTTS:
    """One-shot streaming TTS session.

    Typical lifecycle::

        tts = ElevenLabsTTS()
        await tts.connect(voice_id, model_id, api_key)
        await tts.send_text("Hello ")
        await tts.send_text("world!")
        await tts.flush()
        async for pcm_chunk in tts.receive_audio():
            ...  # forward to Twilio
    """

    def __init__(self) -> None:
        self._ws: websockets.ClientConnection | None = None

    async def connect(
        self,
        voice_id: str,
        model_id: str,
        api_key: str,
    ) -> None:
        """Open the WebSocket and send the BOS (beginning-of-stream) message."""
        url = (
            f"{_BASE_URL}/{voice_id}/stream-input"
            f"?model_id={model_id}&output_format={_OUTPUT_FORMAT}"
        )
        self._ws = await websockets.connect(
            url, additional_headers={"xi-api-key": api_key}
        )
        bos = {
            "text": " ",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            "generation_config": {"chunk_length_schedule": [50]},
        }
        await self._ws.send(json.dumps(bos))
        log.debug("ElevenLabs TTS session opened [voice=%s]", voice_id)

    async def send_text(self, text: str) -> None:
        """Stream a text chunk to ElevenLabs for synthesis."""
        if self._ws is None:
            return
        await self._ws.send(json.dumps({"text": text, "try_trigger_generation": True}))

    async def flush(self) -> None:
        """Signal end of text input — triggers generation of remaining audio."""
        if self._ws is None:
            return
        await self._ws.send(json.dumps({"text": ""}))

    async def receive_audio(self) -> AsyncGenerator[bytes]:
        """Yield raw PCM audio chunks (24 kHz, 16-bit LE) as they arrive."""
        if self._ws is None:
            return
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("isFinal"):
                    break
                audio_b64 = msg.get("audio")
                if audio_b64:
                    yield base64.b64decode(audio_b64)
        except websockets.ConnectionClosed:
            log.debug("ElevenLabs WebSocket closed during receive")

    async def interrupt(self) -> None:
        """Abort the current TTS session (used for barge-in)."""
        if self._ws is None:
            return
        try:
            await self._ws.close()
        except Exception:
            pass
        finally:
            self._ws = None
            log.debug("ElevenLabs TTS session interrupted")
