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
from collections.abc import AsyncIterator

from google import genai
from google.genai import types

from .config import settings, GEMINI_LIVE_MODEL

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool declarations
# ---------------------------------------------------------------------------

TOOL_GET_WEATHER = types.FunctionDeclaration(
    name="get_current_weather",
    description="Get the current weather for a given city.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "city": types.Schema(
                type=types.Type.STRING,
                description="City name, e.g. 'Zürich'",
            ),
        },
        required=["city"],
    ),
)

LIVE_TOOLS = [types.Tool(function_declarations=[TOOL_GET_WEATHER])]


# ---------------------------------------------------------------------------
# Mock tool implementations (replace with real APIs as needed)
# ---------------------------------------------------------------------------


def _mock_get_weather(city: str) -> dict:
    """Return fake weather data for demo purposes."""
    return {
        "city": city,
        "temperature_celsius": 18,
        "condition": "partly cloudy",
        "humidity_percent": 65,
    }


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
        self._client = self._build_client()
        self._session = None
        self._response_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._receiver_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> genai.Client:
        if settings.use_vertex_ai():
            return genai.Client(
                vertexai=True,
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
            )
        return genai.Client(api_key=settings.google_api_key)

    def _build_config(self) -> types.LiveConnectConfig:
        speech_cfg = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=self._profile["voice_name"],
                )
            ),
            language_code=self._profile["gemini_language_code"],
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
        self._cm = self._client.aio.live.connect(
            model=GEMINI_LIVE_MODEL,
            config=config,
        )
        self._session = await self._cm.__aenter__()
        log.info("Gemini Live session opened [lang=%s]", self._lang_code)

        # Send greeting as the first model turn so Gemini speaks it aloud
        greeting = self._profile["greeting"]
        await self._session.send_client_content(
            turns=[
                types.Content(
                    role="user",
                    parts=[types.Part(text="[SYSTEM] Greet the customer now.")],
                )
            ],
            turn_complete=True,
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

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    @staticmethod
    def _execute_tool(name: str, args: dict) -> dict:
        """Dispatch a tool call to its mock implementation."""
        if name == "get_current_weather":
            return _mock_get_weather(args.get("city", "Unknown"))
        return {"error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Internal receiver loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        try:
            async for response in self._session.receive():
                if response.data:
                    # response.data contains raw PCM audio bytes
                    await self._response_queue.put(response.data)
                elif response.tool_call:
                    await self._handle_tool_call(response.tool_call)
                elif response.text:
                    log.debug("Gemini text: %s", response.text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.error("Gemini receive loop error: %s", exc)
        finally:
            await self._response_queue.put(None)

    async def _handle_tool_call(self, tool_call) -> None:
        """Execute each function call and send results back to Gemini."""
        function_responses = []
        for fc in tool_call.function_calls:
            log.info("Tool call: %s(%s)", fc.name, fc.args)
            result = self._execute_tool(fc.name, fc.args)
            function_responses.append(
                types.FunctionResponse(name=fc.name, response=result)
            )
        await self._session.send_tool_response(
            function_responses=function_responses,
        )
