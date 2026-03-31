"""
Manages a single Gemini Live API session for one phone call.

Each incoming call gets its own GeminiSession instance.
The session bridges:
  caller audio  →  Gemini Live API  →  synthesised speech back to caller

Audio format contract
  Input  to Gemini:  PCM 16-bit LE / 16 kHz / mono   (mime: audio/pcm;rate=16000)
  Output from Gemini: PCM 16-bit LE / 24 kHz / mono
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator

from google.genai import types

from .config import settings, build_genai_client, GEMINI_LIVE_MODEL
from .tools import registry as tool_registry

# Ensure tools are registered by importing the tools package
import voice_assistant.tools.weather  # noqa: F401

log = logging.getLogger(__name__)

GOODBYE_PATTERNS = [
    re.compile(r"\bgoodbye\b", re.IGNORECASE),
    re.compile(r"\bno\s+need\s+to\s+continue\b", re.IGNORECASE),
    re.compile(r"\bno\s+need\s+for\b", re.IGNORECASE),
    re.compile(r"\bthat('s| is) all\b", re.IGNORECASE),
    re.compile(r"\bthat('s| is) it\b", re.IGNORECASE),
    re.compile(r"\bthat('s| is) everything\b", re.IGNORECASE),
    re.compile(r"\bcall\s+you\s+later\b", re.IGNORECASE),
    re.compile(r"\bsee\s+you\s+(later|again|soon)\b", re.IGNORECASE),
    re.compile(r"\bhave\s+a\s+(nice|good|great)\s+day\b", re.IGNORECASE),
    re.compile(r"\bbye\b", re.IGNORECASE),
    re.compile(r"\bthanks?\s+(for\s+calling|you\s+help)\b", re.IGNORECASE),
    re.compile(r"\btschüss(i)?\b", re.IGNORECASE),
    re.compile(r"\btschüß(i)?\b", re.IGNORECASE),
    re.compile(r"\bauf\s+wieder(s)?hören\b", re.IGNORECASE),
    re.compile(r"\bad[eéèêë](r)?\b", re.IGNORECASE),
    re.compile(r"\bciao\b", re.IGNORECASE),
    re.compile(r"\barrivederci\b", re.IGNORECASE),
    re.compile(r"\bmerci(\s+(beaucoup|tant))?\b", re.IGNORECASE),
    re.compile(r"\bdanke(\s+(schön|sehr))?\b", re.IGNORECASE),
    re.compile(r"\bgracias?\b", re.IGNORECASE),
    re.compile(r"\ba\s+rever\b", re.IGNORECASE),
    re.compile(r"\bnão\s+preciso\s+mais\b", re.IGNORECASE),
    re.compile(r"\bestá\s+bem(\s+assim)?\b", re.IGNORECASE),
]


def _is_goodbye(transcription: str) -> bool:
    """Return True if the transcription indicates the caller wants to end."""
    if not transcription:
        return False
    cleaned = transcription.strip().rstrip('.,!?;:"').lower()
    if any(pattern.search(cleaned) for pattern in GOODBYE_PATTERNS):
        return True
    if any(pattern.search(transcription.lower()) for pattern in GOODBYE_PATTERNS):
        return True
    return False


# ---------------------------------------------------------------------------
# Tool declarations & dispatch -- delegated to the tool registry
# ---------------------------------------------------------------------------

LIVE_TOOLS = tool_registry.get_declarations()

# Backwards-compatible aliases (used by existing tests and repl.py)
TOOL_GET_WEATHER = LIVE_TOOLS[0].function_declarations[0] if LIVE_TOOLS else None

from .tools.weather import get_current_weather as mock_get_weather  # noqa: E402


def execute_tool(name: str, args: dict) -> dict:
    """Dispatch a tool call via the registry."""
    return tool_registry.execute(name, args)


class GeminiSession:
    """
    Wraps a single google-genai Live session.

    Usage
    -----
    async with GeminiSession(lang_code="de-CH") as session:
        await session.send_audio(pcm_bytes)
        async for chunk in session.receive_audio():
            ...
    """

    def __init__(self, lang_code: str | None = None) -> None:
        self._lang_code = lang_code or settings.default_language
        self._profile = settings.language_profile(self._lang_code)
        self._client = build_genai_client()
        self._session = None
        self._response_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._receiver_task: asyncio.Task | None = None
        self._last_input_transcription: str = ""
        self._call_end_requested: bool = False

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _build_config(self) -> types.LiveConnectConfig:
        """
        Native audio models (gemini-3.1-flash-live-*) handle language
        switching automatically; language is guided via system instructions.
        """
        speech_cfg = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=self._profile["voice_name"],
                )
            ),
        )
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=speech_cfg,
            system_instruction=types.Content(
                parts=[types.Part(text=settings.system_instruction(self._lang_code))]
            ),
            tools=LIVE_TOOLS,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "GeminiSession":
        config = self._build_config()
        log.debug(
            "Connecting to Gemini Live [model=%s, lang=%s]",
            GEMINI_LIVE_MODEL,
            self._lang_code,
        )
        log.debug("LiveConnectConfig: %s", config)
        self._cm = self._client.aio.live.connect(
            model=GEMINI_LIVE_MODEL,
            config=config,
        )
        try:
            self._session = await self._cm.__aenter__()
        except Exception as exc:
            log.error("Failed to open Gemini Live session: %s", exc)
            log.debug("Connection failure details", exc_info=True)
            raise
        log.info("Gemini Live session opened [lang=%s]", self._lang_code)

        # Prompt Gemini to speak the greeting aloud.
        # Native audio models (gemini-3.1-flash-live-*) require
        # send_realtime_input for all user messages; send_client_content
        # is only valid for seeding initial context history.
        await self._session.send_realtime_input(
            text="[SYSTEM] Greet the customer now.",
        )

        # Start background receiver
        self._receiver_task = asyncio.create_task(self._receive_loop())
        return self

    async def __aexit__(self, *exc) -> None:
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
        if self._cm and self._session:
            await self._cm.__aexit__(*exc)
        log.info("Gemini Live session closed [lang=%s]", self._lang_code)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def send_audio(self, pcm_16k: bytes) -> None:
        """Send a chunk of caller audio (PCM 16-bit / 16 kHz) to Gemini."""
        if self._session is None:
            raise RuntimeError("Session not open – use 'async with GeminiSession()'")
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
        )

    async def receive_audio(self) -> AsyncIterator[bytes]:
        """
        Async generator that yields PCM 24 kHz audio chunks
        as Gemini produces them.
        Yields None sentinel when the stream ends.
        """
        while True:
            chunk = await self._response_queue.get()
            if chunk is None:
                return
            yield chunk

    @property
    def last_input_transcription(self) -> str:
        """Return the most recent input transcription from the caller."""
        return self._last_input_transcription

    @property
    def call_end_requested(self) -> bool:
        """Return True if the caller has indicated they want to end the call."""
        return self._call_end_requested

    # ------------------------------------------------------------------
    # Internal receiver loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Process events from Gemini for the lifetime of the session.

        The SDK's ``receive()`` yields events for **one model turn**
        and then returns (it breaks internally on ``turn_complete``).
        We therefore call ``receive()`` in an outer ``while True`` so
        we keep listening across all turns of the conversation.

        The ``None`` sentinel that signals "no more audio" to
        :meth:`receive_audio` is only pushed when the loop truly exits
        (cancellation or fatal error).

        Each event may carry several fields simultaneously (audio data,
        transcription, turn-complete flag, tool call, …).  We inspect
        all relevant fields per event rather than using ``elif``.
        """
        try:
            while True:
                async for response in self._session.receive():
                    # -- Audio data (PCM 24 kHz) -----------------
                    if response.data:
                        await self._response_queue.put(response.data)
                    elif response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if part.inline_data:
                                await self._response_queue.put(part.inline_data.data)

                    # -- Tool calls ------------------------------
                    if response.tool_call:
                        await self._handle_tool_call(response.tool_call)

                    # -- Transcriptions (useful for debugging) ---
                    if response.server_content:
                        sc = response.server_content
                        if sc.input_transcription:
                            self._last_input_transcription = sc.input_transcription.text
                            log.info("User said: %s", sc.input_transcription.text)
                            if _is_goodbye(sc.input_transcription.text):
                                self._call_end_requested = True
                                log.warning(
                                    "Caller indicated end of conversation: %s",
                                    sc.input_transcription.text,
                                )
                        if sc.output_transcription:
                            log.debug(
                                "Gemini said: %s",
                                sc.output_transcription.text,
                            )
                        if sc.interrupted:
                            log.debug("Model interrupted by user")

                    # -- Text-only response (fallback) -----------
                    if response.text:
                        log.debug("Gemini text: %s", response.text)

                # receive() returned after turn_complete – loop
                # back to listen for the next turn.
                log.debug("Model turn complete, waiting for next turn")

        except asyncio.CancelledError:
            log.debug("Receive loop cancelled (session closing)")
        except Exception as exc:
            log.error("Gemini receive loop error: %s", exc)
            log.debug("Receive loop error details", exc_info=True)
        finally:
            # Signal the consumer that no more audio will arrive.
            await self._response_queue.put(None)

    async def _handle_tool_call(self, tool_call) -> None:
        """Execute each function call and send results back to Gemini."""
        function_responses = []
        for fc in tool_call.function_calls:
            log.debug("Tool call: %s(%s)", fc.name, fc.args)
            result = execute_tool(fc.name, fc.args)
            function_responses.append(
                types.FunctionResponse(id=fc.id, name=fc.name, response=result)
            )
        await self._session.send_tool_response(
            function_responses=function_responses,
        )
