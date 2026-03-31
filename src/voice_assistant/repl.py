"""
Interactive text REPL for testing the voice assistant agent locally.

Uses the standard Gemini chat API with the same system prompt and tools
as the live voice session.  No Twilio or ngrok needed — just GOOGLE_API_KEY.

Usage:
    uv run python -m voice_assistant.repl
    uv run python -m voice_assistant.repl --lang fr-CH
    uv run python -m voice_assistant.repl --verbose
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from google.genai import errors as genai_errors, types

from .config import settings, build_genai_client, LANGUAGE_PROFILES
from .tools import registry as tool_registry

# Standard (non-live) model for the text REPL
GEMINI_CHAT_MODEL = "gemini-2.5-flash"


async def send_message(chat, text: str) -> str:
    """Send user text, handle tool calls automatically, return final text."""
    response = await chat.send_message(text)

    while response.function_calls:
        parts = []
        for fc in response.function_calls:
            print(f"  [tool] {fc.name}({json.dumps(fc.args)})")
            result = tool_registry.execute(fc.name, fc.args)
            parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name, response=result
                    )
                )
            )
        response = await chat.send_message(parts)

    return response.text or "(no response)"


async def repl(lang_code: str) -> None:
    profile = settings.language_profile(lang_code)
    print(f"Connecting to Gemini [{GEMINI_CHAT_MODEL}] as {profile['display']}...")
    print("Type your messages. Ctrl+C or 'quit' to exit.\n")

    # Client must be created inside the async context (aiohttp event loop binding)
    client = build_genai_client()
    chat = client.aio.chats.create(
        model=GEMINI_CHAT_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=settings.system_instruction(lang_code),
            tools=tool_registry.get_declarations(),
        ),
    )

    # Trigger the greeting (same as the voice flow)
    try:
        response = await send_message(chat, "Greet the customer now.")
        print(f"Assistant: {response}\n")
    except genai_errors.APIError as e:
        print(f"  [API error] {e}\n")

    loop = asyncio.get_running_loop()
    while True:
        try:
            user_input = await loop.run_in_executor(None, lambda: input("You: "))
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        if not user_input.strip():
            continue

        try:
            response = await send_message(chat, user_input)
        except genai_errors.APIError as e:
            print(f"  [API error] {e}")
            continue
        print(f"Assistant: {response}\n")


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    lang_code = settings.default_language

    # Simple arg parsing: --lang <code> or --verbose
    args = sys.argv[1:]
    if "--verbose" in args or "-v" in args:
        logging.getLogger().setLevel(logging.DEBUG)
        args = [a for a in args if a not in ("--verbose", "-v")]
    if "--lang" in args:
        idx = args.index("--lang")
        if idx + 1 >= len(args):
            print("Error: --lang requires a language code (e.g., de-CH)")
            sys.exit(1)
        lang_code = args[idx + 1]
        if lang_code not in LANGUAGE_PROFILES:
            available = ", ".join(LANGUAGE_PROFILES.keys())
            print(f"Unknown language '{lang_code}'. Available: {available}")
            sys.exit(1)

    # Only need Google credentials, not Twilio
    settings.validate(require_twilio=False)

    try:
        asyncio.run(repl(lang_code))
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
