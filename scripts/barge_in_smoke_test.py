"""
Barge-in smoke test: drive ``handle_media_stream`` with real audio through
real Gemini Live, capture what it sends to a fake Twilio WebSocket, and
assert that a ``clear`` event is emitted when the caller "barges in".

This is NOT a unit test. It makes real Gemini API calls (needs
``GOOGLE_API_KEY`` in ``.env``) and costs a few cents per run. Run on
demand, not in CI.

Usage:
    uv run python scripts/barge_in_smoke_test.py

Preparation (run once on macOS):
    say -o /tmp/greeting.aiff "Hello, can you tell me the weather in Zurich please?"
    afconvert /tmp/greeting.aiff /tmp/greeting.wav -d LEI16@8000 -f WAVE -c 1
    say -o /tmp/interrupt.aiff "Wait stop, I actually want to know about Bern instead"
    afconvert /tmp/interrupt.aiff /tmp/interrupt.wav -d LEI16@8000 -f WAVE -c 1
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
import sys
import time
import wave
from pathlib import Path

# Allow running as `uv run python scripts/barge_in_smoke_test.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(name)-12s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("smoke")

GREETING_WAV = Path("/tmp/greeting.wav")
INTERRUPT_WAV = Path("/tmp/interrupt.wav")

FRAME_MS = 20
FRAME_BYTES = 8000 * FRAME_MS // 1000  # 160 bytes @ 8kHz
SILENCE_FRAME = base64.b64encode(b"\xff" * FRAME_BYTES).decode("ascii")


# ---------------------------------------------------------------------------
# Fake Twilio Media Stream WebSocket
# ---------------------------------------------------------------------------


class FakeTwilioWS:
    """Minimal stand-in for starlette's WebSocket, speaking Twilio Media
    Stream's JSON protocol. The test driver puts inbound messages on
    ``recv_queue``; everything the server sends back is captured in
    ``sent`` with a monotonic timestamp relative to ``t0``.
    """

    def __init__(self) -> None:
        self.recv_queue: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[tuple[float, dict]] = []
        self.t0 = time.monotonic()
        self._closed = asyncio.Event()

    async def accept(self) -> None:
        log.info("ws.accept() called")

    async def receive_text(self) -> str:
        return await self.recv_queue.get()

    async def send_text(self, data: str) -> None:
        t = time.monotonic() - self.t0
        msg = json.loads(data)
        self.sent.append((t, msg))
        evt = msg.get("event", "?")
        if evt == "clear":
            log.warning("[t=%5.2fs] 📤 CLEAR %s", t, msg)
        elif evt == "media":
            # Don't log every audio chunk — just sample occasionally
            media_count = sum(1 for _, m in self.sent if m.get("event") == "media")
            if media_count % 25 == 1:
                log.info("[t=%5.2fs] 📤 media (#%d)", t, media_count)
        elif evt == "mark":
            name = msg.get("mark", {}).get("name", "?")
            if name != "adk-chunk":  # per-chunk marks are too noisy
                log.info("[t=%5.2fs] 📤 mark: %s", t, name)

    async def close(self) -> None:
        self._closed.set()
        log.info("ws.close() called")


# ---------------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------------


def load_mulaw_frames_b64(wav_path: Path) -> list[str]:
    """Load a mono WAV file and return a list of 20ms base64-encoded
    mu-law frames, matching what Twilio sends in ``media`` events.
    """
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 1, f"{wav_path} must be mono"
        assert wf.getsampwidth() == 2, f"{wav_path} must be 16-bit"
        rate = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())

    if rate != 8000:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 8000, None)

    mulaw = audioop.lin2ulaw(pcm, 2)
    frames = []
    for i in range(0, len(mulaw), FRAME_BYTES):
        chunk = mulaw[i : i + FRAME_BYTES]
        if len(chunk) < FRAME_BYTES:
            chunk += b"\xff" * (FRAME_BYTES - len(chunk))
        frames.append(base64.b64encode(chunk).decode("ascii"))
    return frames


# ---------------------------------------------------------------------------
# Driver: feeds the fake WS as a real Twilio client would
# ---------------------------------------------------------------------------


async def _send_frame(ws: FakeTwilioWS, payload_b64: str) -> None:
    await ws.recv_queue.put(
        json.dumps({"event": "media", "media": {"payload": payload_b64}})
    )


async def _stream_frames(
    ws: FakeTwilioWS,
    frames: list[str],
    label: str,
) -> None:
    log.info("🎙  Streaming %d frames (%s) = %.1fs", len(frames), label, len(frames) * FRAME_MS / 1000)
    for frame in frames:
        await _send_frame(ws, frame)
        await asyncio.sleep(FRAME_MS / 1000)


async def _stream_silence(ws: FakeTwilioWS, duration_s: float, label: str) -> None:
    n = int(duration_s * 1000 / FRAME_MS)
    log.info("🤫 Streaming %.1fs of silence (%s)", duration_s, label)
    for _ in range(n):
        await _send_frame(ws, SILENCE_FRAME)
        await asyncio.sleep(FRAME_MS / 1000)


async def drive(ws: FakeTwilioWS) -> None:
    """Scripted caller behavior."""
    greeting = load_mulaw_frames_b64(GREETING_WAV)
    interrupt = load_mulaw_frames_b64(INTERRUPT_WAV)
    log.info("Loaded: greeting=%d frames, interrupt=%d frames", len(greeting), len(interrupt))

    # Initial Twilio handshake
    await ws.recv_queue.put(json.dumps({"event": "connected"}))
    await ws.recv_queue.put(json.dumps({"event": "start", "streamSid": "SM-SMOKE-TEST"}))

    # Give Gemini a moment to start its system-triggered greeting
    await _stream_silence(ws, 1.0, "initial pause")

    # Caller speaks their first utterance
    await _stream_frames(ws, greeting, "greeting")

    # Wait for the agent to process and start answering
    await _stream_silence(ws, 3.0, "waiting for agent response")

    # BARGE IN: caller speaks over the agent's answer
    log.warning("🛑 BARGE IN — injecting interrupt audio")
    await _stream_frames(ws, interrupt, "interrupt")

    # Give time for the system to react and for Gemini to respond to the new turn
    await _stream_silence(ws, 4.0, "post-interrupt")

    # End the call
    await ws.recv_queue.put(json.dumps({"event": "stop"}))
    log.info("✋ sent stop")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    if not GREETING_WAV.exists() or not INTERRUPT_WAV.exists():
        log.error(
            "Audio fixtures missing. See module docstring for how to generate them."
        )
        return 2

    # Import the system under test AFTER logging is configured, so ADK's
    # own logging respects our format.
    from voice_assistant.call_handler import handle_media_stream

    ws = FakeTwilioWS()

    log.info("Starting handle_media_stream task...")
    handler_task = asyncio.create_task(handle_media_stream(ws))
    driver_task = asyncio.create_task(drive(ws))

    try:
        await asyncio.wait_for(
            asyncio.gather(handler_task, driver_task, return_exceptions=True),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        log.error("⏰ OVERALL TIMEOUT — cancelling tasks")
        for t in (handler_task, driver_task):
            if not t.done():
                t.cancel()
        await asyncio.gather(handler_task, driver_task, return_exceptions=True)

    # ------------------------------------------------------------------ report
    print()
    print("=" * 72)
    print("RESULTS")
    print("=" * 72)

    event_counts: dict[str, int] = {}
    for _, m in ws.sent:
        evt = m.get("event", "?")
        event_counts[evt] = event_counts.get(evt, 0) + 1

    print(f"Total messages server→client: {len(ws.sent)}")
    print(f"Event type counts:            {event_counts}")

    clears = [(t, m) for t, m in ws.sent if m.get("event") == "clear"]
    media = [(t, m) for t, m in ws.sent if m.get("event") == "media"]
    marks = [(t, m) for t, m in ws.sent if m.get("event") == "mark"]

    print()
    print(f"🔊 Media events:  {len(media)}")
    if media:
        print(f"   first at t={media[0][0]:.2f}s")
        print(f"   last  at t={media[-1][0]:.2f}s")

    print(f"🏷  Mark events:   {len(marks)}")
    goodbye_marks = [t for t, m in marks if m.get("mark", {}).get("name") == "goodbye-done"]
    if goodbye_marks:
        print(f"   goodbye-done at t={goodbye_marks[0]:.2f}s")

    print(f"🛑 Clear events:  {len(clears)}")
    for t, m in clears:
        print(f"   t={t:.2f}s  {m}")

    print()
    print("=" * 72)
    if clears:
        print("✅ PASS: Twilio `clear` event was emitted — barge-in handler fired")
        return 0
    else:
        print("❌ FAIL: No `clear` event emitted — barge-in did not trigger")
        print()
        print("Possible causes:")
        print("  - Gemini Live VAD did not detect the synthesized audio as speech")
        print("  - Interrupt audio arrived after the agent finished speaking")
        print("  - ADK is not propagating event.interrupted")
        print("  - Our handler's check is wrong")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
