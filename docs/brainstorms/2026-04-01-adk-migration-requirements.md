---
date: 2026-04-01
topic: adk-migration
---

# Migrate Voice Assistant to Google ADK

## Problem Frame

The voice assistant currently uses a hand-rolled Gemini integration with manual tool dispatch, custom session management, and a custom REPL. A multi-phase "12 Factor Agent Overhaul" plan was started to address architectural issues (tool registry, state machine, transport abstraction, etc.), but Google's Agent Development Kit (ADK) provides most of these capabilities out of the box -- tool auto-registration from type hints, session/state management, built-in REPL and dev UI, an evaluation framework, and Live API streaming support.

Rather than building custom infrastructure that reimplements what ADK already provides, the project should be rebuilt on ADK as its foundation. This eliminates custom plumbing, aligns with Google's supported toolchain, and gives the project access to ADK's evaluation, deployment, and observability features for free.

## Requirements

### Agent Core

- R1. Define the customer service agent using ADK's `Agent` class with Gemini as the model
- R2. Agent instructions (system prompt) must support multi-language customer service (de-CH, de-DE, fr-CH, it-CH) with runtime language switching
- R3. Use ADK's built-in tool registration -- tools are plain Python functions with type hints and docstrings, passed to `Agent(tools=[...])`
- R4. Use ADK's session and state management (`InMemorySessionService` for dev, with path to `DatabaseSessionService` for production)
- R5. Agent must handle multi-turn conversations naturally via ADK's session/event system

### Tools

- R6. Implement `get_current_weather` tool as a plain Python function (mock data for demo)
- R7. Implement `end_call` tool that the agent invokes to terminate calls, replacing regex-based goodbye detection
- R8. Tools must return `dict` with a `"status"` key per ADK convention
- R9. Tool implementations must be independently testable (pure functions, no framework coupling)

### Local Development

- R10. Project must work with `adk run` (CLI REPL) and `adk web` (browser dev UI) for interactive testing
- R11. Agent module must export `root_agent` at module level per ADK convention
- R12. Support `--lang` configuration for testing in different languages

### Twilio Voice Integration

- R13. Maintain Twilio WebSocket media stream integration for real phone calls
- R14. Bridge Twilio's mulaw/8kHz audio to/from ADK's Live API streaming (`runner.run_live()` with `StreamingMode.BIDI`)
- R15. Preserve existing audio conversion utilities (`audio.py` mulaw/PCM functions)
- R16. FastAPI server with `/voice` webhook and `/ws/media-stream` WebSocket endpoint

### Testing

- R17. Pytest unit tests for all tool implementations (TDD -- tests written before implementation)
- R18. Pytest unit tests for audio conversion, config, and any custom bridge code
- R19. ADK evaluation tests (`.test.json` files) for agent behavior -- tool trajectory matching and response quality
- R20. Test coverage for: tool dispatch, multi-turn conversation, language switching, end_call flow
- R21. Tests must be runnable with `uv run pytest` and `adk eval`

### Code Quality

- R22. Clean Python: type hints throughout, docstrings on public functions, no unnecessary abstractions
- R23. Follow ADK's recommended project structure (`agent.py` with `root_agent`, tools as separate modules)
- R24. Minimal dependencies -- use ADK's built-in capabilities instead of adding libraries
- R25. Follow AGENTS.md conventions (uv, pytest function-based, parametrize, just as task runner)

## Success Criteria

- `adk run` starts an interactive text chat with the customer service agent
- `adk web` provides a browser-based dev UI for testing and creating eval cases
- `just dev` starts the Twilio voice flow (ngrok + FastAPI + ADK Live API)
- All tools are plain functions with no manual FunctionDeclaration boilerplate
- Agent correctly uses tools, switches languages, and terminates calls via `end_call`
- `uv run pytest` passes all unit tests
- `adk eval` passes agent behavior tests

## Scope Boundaries

- **In scope:** ADK agent core, tools, Twilio voice bridge, REPL/dev UI, pytest + ADK eval tests
- **Out of scope:** Human escalation / transfer to operator (deferred), persistent session storage (use InMemorySessionService), deployment to Vertex AI Agent Engine, multi-agent orchestration
- **Removed:** Custom tool registry (`tools/__init__.py`), custom CallContext/Phase state machine (`state.py`), custom REPL (`repl.py`), the 12 Factor Agent Overhaul plan -- all superseded by ADK
- **Preserved:** Audio conversion (`audio.py`), Twilio provisioning script, FastAPI server structure, `.env` config pattern

## Key Decisions

- **ADK over custom architecture:** ADK provides tool registration, session state, REPL, eval, and Live API streaming. Building these from scratch is wasted effort.
- **Full replacement, not incremental migration:** The ADK project structure is different enough (module with `root_agent`, `adk run`/`adk web` discovery) that layering it onto the existing code would create a hybrid mess.
- **Keep Twilio bridge as custom code:** ADK does not provide Twilio integration. The WebSocket bridge converting mulaw audio to/from ADK's Live API is the one piece of custom infrastructure needed.
- **LLM-driven call termination:** Keep the `end_call` tool approach from the previous plan. The agent decides when to end calls, with safety timeouts as fallback.
- **Both testing approaches:** Pytest for unit tests (TDD on tools and bridge code), ADK eval for agent behavior tests (trajectory + response quality).

## Dependencies / Assumptions

- `google-adk` package is stable enough for production use (it is open-source and actively maintained by Google)
- ADK's `run_live()` with `StreamingMode.BIDI` supports function calling during audio streaming (confirmed in docs)
- The Twilio mulaw/PCM bridge pattern from the current codebase transfers directly to ADK's Live API

## Outstanding Questions

### Resolve Before Planning

(None -- all product decisions resolved)

### Deferred to Planning

- [Affects R14][Needs research] Exact integration pattern for bridging Twilio WebSocket to ADK's `run_live()` / `LiveRequestQueue` -- may need to inspect ADK source or samples
- [Affects R2][Technical] How to pass runtime language config to ADK agent instructions -- likely via session state with `{language}` template variable
- [Affects R12][Technical] How to configure language for `adk run` CLI -- may need a wrapper script or env var
- [Affects R19][Needs research] ADK eval `.test.json` format details and how to test tool trajectories with mock tool responses

## Next Steps

-> `/ce:plan` for structured implementation planning
