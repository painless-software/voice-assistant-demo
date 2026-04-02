---
title: "refactor: Migrate Voice Assistant to Google ADK"
type: refactor
status: active
date: 2026-04-01
origin: docs/brainstorms/2026-04-01-adk-migration-requirements.md
---

# refactor: Migrate Voice Assistant to Google ADK

## Overview

Replace the hand-rolled Gemini integration with Google's Agent Development Kit (ADK). ADK provides tool auto-registration, session/state management, a built-in REPL and dev UI, an evaluation framework, and Live API streaming support -- eliminating the need for the custom tool registry, state machine, REPL, and adapter code that was planned in the previous "12 Factor Agent Overhaul."

## Problem Statement

The current codebase uses raw `google-genai` SDK calls with manually-written `FunctionDeclaration` objects, a custom `ToolRegistry` with auto-discovery, a custom `CallContext` state machine, a custom REPL, and a hand-written receive loop. Google's ADK provides all of these as tested, maintained framework features. Building them from scratch is wasted effort when a first-party framework exists.

(see origin: `docs/brainstorms/2026-04-01-adk-migration-requirements.md`)

## Proposed Solution

Rebuild the project on ADK's `Agent` + `Runner` architecture. The agent is defined declaratively with tools as plain Python functions. ADK handles tool dispatch, session state, and the conversation loop. The only custom code is the Twilio WebSocket bridge that converts mulaw audio to/from ADK's Live API streaming.

### New File Structure

```
src/voice_assistant/
├── __init__.py
├── agent.py                 # ADK root_agent definition (Agent + tools + instructions)
├── tools/
│   ├── __init__.py          # Tool imports for clean Agent(tools=[...]) wiring
│   ├── weather.py           # get_current_weather (plain function)
│   └── end_call.py          # end_call (plain function, returns status dict)
├── prompts/
│   ├── base.txt             # System instruction template with {language} placeholder
│   └── escalation.txt       # Escalation guidelines
├── audio.py                 # mulaw/PCM conversion (preserved from current code)
├── config.py                # Settings, language profiles (simplified -- no genai client)
├── server.py                # FastAPI app with /voice webhook + /ws/media-stream
└── twilio_bridge.py         # Twilio WS <-> ADK run_live() bridge

tests/
├── __init__.py
├── test_tools.py            # Unit tests for tool functions (TDD)
├── test_audio.py            # Unit tests for audio conversion
├── test_config.py           # Unit tests for settings and instruction composition
├── test_bridge.py           # Unit tests for Twilio bridge with mocked run_live()
├── test_server.py           # FastAPI endpoint tests
└── evals/
    ├── greeting.evalset.json        # Agent greets in correct language
    ├── weather_tool.evalset.json    # Agent uses weather tool correctly
    ├── end_call.evalset.json        # Agent terminates call on goodbye
    └── language_switch.evalset.json # Agent switches language mid-conversation

justfile                     # Updated with adk run, adk web, adk eval commands
pyproject.toml               # google-adk replaces google-genai as primary dependency
```

### What Is Removed

| File | Reason |
|------|--------|
| `gemini_session.py` | Replaced by ADK's Agent + Runner |
| `call_handler.py` | Replaced by `twilio_bridge.py` |
| `repl.py` | Replaced by `adk run` / `adk web` |
| `tools/__init__.py` (registry) | Replaced by ADK's built-in tool registration |
| `state.py` | Replaced by ADK's session state |
| `__main__.py` | Replaced by `server.py` (direct uvicorn) |
| `test_registry.py` | Registry no longer exists |
| `test_state.py` | State machine no longer exists |

### What Is Preserved

| File | Notes |
|------|-------|
| `audio.py` | Pure mulaw/PCM conversion functions, no framework coupling |
| `prompts/base.txt`, `prompts/escalation.txt` | Prompt text files |
| `config.py` | Language profiles and settings (simplified) |
| `scripts/provision_twilio.py` | Twilio number provisioning |
| `start.sh` | Dev launcher (ngrok + server) |

## Key Architectural Decisions

Carried forward from origin document:

1. **ADK over custom architecture** -- ADK provides tool registration, session state, REPL, eval, and Live API streaming. Building these from scratch is wasted effort. (see origin)
2. **Full replacement, not incremental migration** -- The ADK project structure is different enough that layering it onto existing code would create a hybrid mess. (see origin)
3. **Keep Twilio bridge as custom code** -- ADK does not provide Twilio integration. The WebSocket bridge is the one piece of custom infrastructure needed. (see origin)
4. **LLM-driven call termination** via `end_call` tool. (see origin)
5. **Both testing approaches** -- Pytest for unit tests (TDD), ADK eval for agent behavior. (see origin)

New decisions made during planning:

6. **`end_call` is a pure function** -- Returns `{"status": "call_ended", "reason": reason}`. The bridge detects `end_call` by inspecting events yielded by `run_live()` for function-call actions. No side effects in the tool itself.
7. **Language via ADK instruction provider** -- Use a callable `instruction` on the Agent that reads `{language}` from session state, enabling runtime language switching without agent reconstruction.
8. **Greeting via synthetic message** -- Send `"Greet the customer now."` through `LiveRequestQueue` on connection, same pattern as current code.
9. **Safety timeout** -- 5-minute max call duration enforced by the bridge via `asyncio.wait_for`. On timeout, close the `LiveRequestQueue` to terminate the live session gracefully.
10. **`audioop-lts` for Python 3.13+** -- Already in dependencies. No change needed.

## Technical Approach

### Implementation Phases

#### Phase 1: Agent Core + Tools (TDD)

**Goal:** Define the ADK agent with tools, working via `adk run` and `adk web`. No Twilio yet.

**Tasks:**

- [ ] **P1.1** Add `google-adk` dependency, update pyproject.toml
  - `uv add google-adk`
  - Keep `google-genai` (ADK depends on it), remove if redundant
  - Ensure `.env` has `GOOGLE_API_KEY`
- [ ] **P1.2** Write tests for `end_call` tool (TDD -- test first)
  - Test: returns `{"status": "call_ended", "reason": <reason>}`
  - Test: reason parameter is required
  - Test: farewell_message parameter is optional
  - File: `tests/test_tools.py`
- [ ] **P1.3** Implement `end_call` tool
  - File: `src/voice_assistant/tools/end_call.py`
  - Plain function with type hints and docstring
  - ```python
    def end_call(reason: str, farewell_message: str = "") -> dict:
        """End the current call. Use when the customer wants to hang up."""
        return {"status": "call_ended", "reason": reason, "farewell_message": farewell_message}
    ```
- [ ] **P1.4** Write tests for `get_current_weather` tool (TDD)
  - Port existing parametrized tests from `test_tools.py`
  - Test: returns expected keys for various cities
  - Test: returns sensible value types
  - Remove `@tool` decorator, use bare function
- [ ] **P1.5** Implement `get_current_weather` tool
  - File: `src/voice_assistant/tools/weather.py`
  - Same mock data, but plain function (no decorator)
  - ADK convention: return `{"status": "success", ...}`
- [ ] **P1.6** Write tests for config/instruction composition
  - Test: `build_instruction("de-CH")` returns instruction containing "Swiss German"
  - Test: `build_instruction("fr-CH")` returns instruction containing "Swiss French"
  - Test: escalation guidelines are appended
- [ ] **P1.7** Simplify `config.py`
  - Keep: `Settings`, `LANGUAGE_PROFILES`, `validate()`, prompt file loading
  - Remove: `build_genai_client()`, `GEMINI_LIVE_MODEL`
  - Add: `build_instruction(lang_code) -> str` that composes base + escalation with language
- [ ] **P1.8** Create `tools/__init__.py` with clean imports
  - ```python
    from .weather import get_current_weather
    from .end_call import end_call
    ALL_TOOLS = [get_current_weather, end_call]
    ```
- [ ] **P1.9** Create `agent.py` with ADK agent definition
  - ```python
    from google.adk.agents import Agent
    from .tools import ALL_TOOLS
    from .config import build_instruction

    root_agent = Agent(
        name="customer_service",
        model="gemini-2.0-flash",
        instruction=build_instruction,  # callable for dynamic language
        tools=ALL_TOOLS,
    )
    ```
  - Instruction provider receives `ReadonlyContext`, reads `language` from state
- [ ] **P1.10** Verify `adk run voice_assistant` and `adk web` work
- [ ] **P1.11** Update justfile with ADK commands
  - `adk-run`: `uv run adk run voice_assistant`
  - `adk-web`: `uv run adk web --port 8000`
  - `adk-eval`: `uv run adk eval voice_assistant tests/evals/`

**Success criteria:**
- `adk run voice_assistant` starts interactive chat, agent greets, answers weather questions, responds to goodbye with end_call
- `adk web` provides browser dev UI
- All pytest unit tests pass
- No custom tool registry code -- ADK handles tool dispatch

**Execution note:** Test-first for P1.2, P1.4, P1.6. Implement after tests are written and failing.

---

#### Phase 2: ADK Evaluation Tests

**Goal:** Create `.evalset.json` files for agent behavior testing.

**Tasks:**

- [ ] **P2.1** Create `tests/evals/greeting.evalset.json`
  - Test: agent greets in the default language when prompted
  - Verify: no tool calls during greeting
- [ ] **P2.2** Create `tests/evals/weather_tool.evalset.json`
  - Test: user asks "What's the weather in Zürich?"
  - Verify: agent calls `get_current_weather` with `{"city": "Zürich"}`
  - Verify: response mentions the weather data
- [ ] **P2.3** Create `tests/evals/end_call.evalset.json`
  - Test: user says "That's all, goodbye"
  - Verify: agent calls `end_call` tool
  - Verify: response includes a farewell
- [ ] **P2.4** Create `tests/evals/language_switch.evalset.json`
  - Test: user asks "Parlez-vous français?" in a de-CH session
  - Verify: agent switches to French in response
- [ ] **P2.5** Verify `adk eval voice_assistant tests/evals/` passes

**Success criteria:**
- All eval tests pass with `tool_trajectory_avg_score >= 1.0` and `response_match_score >= 0.6`
- Eval tests are runnable via `just adk-eval`

**Execution note:** Create eval tests interactively using `adk web` Eval tab, then export as `.evalset.json`.

---

#### Phase 3: Twilio Voice Bridge (TDD)

**Goal:** Bridge Twilio WebSocket media streams to ADK's `run_live()` with bidirectional audio.

**Tasks:**

- [ ] **P3.1** Research spike: run ADK's live streaming sample
  - Confirm: event structure from `run_live()`, audio format, `LiveRequestQueue` API
  - Confirm: how tool call events surface (function name, args, result)
  - Confirm: audio sample rates (16kHz in, 24kHz out expected)
  - Document findings in a comment at top of `twilio_bridge.py`
- [ ] **P3.2** Write tests for audio.py (TDD -- ensure existing functions work)
  - Test: `twilio_mulaw_to_gemini_pcm` round-trips correctly
  - Test: `gemini_pcm_to_twilio_mulaw_b64` produces valid base64 mulaw
  - Test: empty input handling
- [ ] **P3.3** Write tests for `twilio_bridge.py` with mocked `run_live()` (TDD)
  - Mock `runner.run_live()` as an async generator yielding fake events
  - Test: Twilio audio -> PCM -> `LiveRequestQueue.send_realtime()`
  - Test: Audio event from `run_live()` -> mulaw -> Twilio WS JSON
  - Test: `end_call` tool event detected -> Twilio WS closed
  - Test: Twilio WS disconnect -> `LiveRequestQueue.close()`
  - Test: greeting message sent on connection
  - Test: safety timeout (5 min) triggers graceful shutdown
- [ ] **P3.4** Implement `twilio_bridge.py`
  - `async def handle_media_stream(websocket)` -- main entry point
  - Creates `InMemoryRunner` with `root_agent`
  - Creates `LiveRequestQueue` and `RunConfig` with `StreamingMode.BIDI`
  - Two concurrent tasks:
    - `_twilio_to_adk`: reads Twilio WS JSON, converts mulaw -> PCM, sends to queue
    - `_adk_to_twilio`: consumes `run_live()` events, extracts audio, converts PCM -> mulaw, sends to Twilio WS. Detects `end_call` events.
  - Safety timeout wraps the whole bridge with `asyncio.wait_for(5 * 60)`
  - Greeting: sends synthetic text through queue on start
- [ ] **P3.5** Write tests for FastAPI server endpoints (TDD)
  - Test: `GET /health` returns 200
  - Test: `POST /voice` returns TwiML XML with correct WebSocket URL
  - Test: `WS /ws/media-stream` accepts connection (integration with bridge)
- [ ] **P3.6** Implement `server.py`
  - FastAPI app with `/health`, `/voice`, `/ws/media-stream`
  - `/voice` generates TwiML pointing to the WebSocket
  - `/ws/media-stream` delegates to `twilio_bridge.handle_media_stream()`
- [ ] **P3.7** Update `start.sh` and justfile for the new entry point
  - `just serve`: `uv run uvicorn voice_assistant.server:app --host 0.0.0.0 --port 8080`
  - `just dev`: ngrok + serve
- [ ] **P3.8** Delete old files: `gemini_session.py`, `call_handler.py`, `repl.py`, `__main__.py`, `state.py`, `tools/__init__.py` (old registry)
- [ ] **P3.9** Delete old tests: `test_registry.py`, `test_state.py`, update `test_tools.py`
- [ ] **P3.10** End-to-end test with real Twilio call

**Success criteria:**
- `just dev` starts ngrok + FastAPI + ADK live streaming
- Real phone call: agent greets, answers weather questions, says goodbye via `end_call`
- All pytest tests pass
- Old files deleted, no dead code

**Execution note:** P3.1 (research spike) must complete before writing bridge tests. Test-first for P3.2, P3.3, P3.5.

---

#### Phase 4: Polish and Documentation

**Goal:** Clean up, update docs, verify all success criteria.

**Tasks:**

- [ ] **P4.1** Update README.md
  - New architecture diagram (ADK-based)
  - Updated setup instructions (`adk run`, `adk web`, `adk eval`)
  - Updated dev workflow
- [ ] **P4.2** Update AGENTS.md if needed
- [ ] **P4.3** Verify all success criteria from origin document:
  - [ ] `adk run` starts interactive text chat
  - [ ] `adk web` provides browser dev UI
  - [ ] `just dev` starts Twilio voice flow
  - [ ] All tools are plain functions, no FunctionDeclaration boilerplate
  - [ ] Agent correctly uses tools, switches languages, terminates calls
  - [ ] `uv run pytest` passes all tests
  - [ ] `adk eval` passes behavior tests
- [ ] **P4.4** Clean up any remaining references to old code in comments/docs
- [ ] **P4.5** Final `uv run pytest && uv run adk eval voice_assistant tests/evals/`

**Success criteria:**
- All origin document success criteria met
- README reflects new ADK architecture
- Clean repo with no dead code or stale references

---

## Alternative Approaches Considered

1. **Incremental migration (keep old code, add ADK alongside)** -- Rejected. ADK's project structure (`root_agent` module-level export, `adk run` discovery) is fundamentally different from the current architecture. A hybrid would be confusing. (see origin)

2. **ADK for text only, keep raw GenAI SDK for voice** -- Rejected. ADK supports `run_live()` with `StreamingMode.BIDI`, so both text and voice can use the same framework. Using two different patterns for the same agent creates maintenance burden.

3. **Keep custom state machine alongside ADK** -- Rejected. ADK's session state (`InMemorySessionService`) handles conversation state. The custom `Phase` enum and `CallContext` add complexity without value when ADK manages the conversation loop. Business rules (e.g., "don't end call without farewell") are better expressed as agent instructions.

## System-Wide Impact

### Interaction Graph

Twilio WebSocket -> `twilio_bridge.py` converts mulaw -> PCM -> `LiveRequestQueue.send_realtime()` -> ADK `Runner.run_live()` -> Gemini Live API -> ADK yields `Event`s -> bridge extracts audio -> PCM -> mulaw -> Twilio WebSocket. Tool calls are handled entirely within ADK's event loop -- the bridge only observes them for lifecycle signals (`end_call`).

### Error & Failure Propagation

- Tool errors: ADK catches exceptions and feeds error context back to the LLM automatically
- Gemini disconnects: `run_live()` async generator terminates -> bridge closes Twilio WS
- Twilio disconnects: bridge closes `LiveRequestQueue` -> `run_live()` terminates
- Safety timeout: `asyncio.wait_for` cancels both tasks after 5 minutes

### Integration Test Scenarios

1. Full voice call: Twilio -> bridge -> ADK -> weather tool -> audio response -> Twilio (requires real Twilio)
2. End call flow: user says goodbye -> ADK calls `end_call` -> bridge detects -> WS closed
3. Disconnect: caller hangs up -> Twilio WS closes -> bridge cleans up ADK session
4. Timeout: call exceeds 5 minutes -> bridge terminates gracefully

## Acceptance Criteria

### Functional Requirements

- [ ] `adk run voice_assistant` starts interactive text chat with customer service agent
- [ ] `adk web` provides browser-based dev UI at localhost:8000
- [ ] `just dev` starts Twilio voice flow (ngrok + FastAPI + ADK Live API)
- [ ] Agent greets in configured language on call start
- [ ] Agent uses `get_current_weather` tool when asked about weather
- [ ] Agent calls `end_call` tool when customer indicates goodbye
- [ ] Agent switches language mid-conversation when requested
- [ ] Safety timeout terminates calls after 5 minutes

### Non-Functional Requirements

- [ ] All tools are plain Python functions with type hints and docstrings -- no framework coupling
- [ ] No custom tool registry, state machine, or REPL code -- ADK handles these
- [ ] `uv run pytest` passes all unit tests
- [ ] `adk eval` passes all behavior eval tests

### Quality Gates

- [ ] Each phase passes `uv run pytest` before proceeding
- [ ] Each phase gets a separate commit for incremental review
- [ ] `adk run` verified working after Phase 1, `just dev` after Phase 3

## Dependencies & Prerequisites

- **`google-adk` package** -- primary new dependency
- **`audioop-lts`** -- already in dependencies for Python 3.13+ mulaw conversion
- **Twilio account** -- for Phase 3 end-to-end testing
- **GOOGLE_API_KEY** -- for Gemini model access via ADK

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ADK `run_live()` event model differs from expectations | Medium | High | Phase 3 starts with research spike (P3.1) before writing bridge code |
| `end_call` detection mechanism unclear in live events | Medium | High | Research spike + prototype in P3.1 |
| Audio sample rate mismatch between ADK and current code | Low | High | Verify in P3.1; `audio.py` functions are easy to adjust |
| ADK breaking changes (active development) | Low | Medium | Pin `google-adk` version in pyproject.toml |
| Concurrent live sessions exhausting Gemini connections | Low | Medium | Out of scope (InMemorySessionService for dev); document limitation |

## Outstanding Questions

### Resolved During Planning

- **`end_call` signal mechanism** -> Bridge inspects events from `run_live()` for tool-call actions with `name == "end_call"`. Pure function, no side effects.
- **Language switching** -> ADK instruction provider (callable) reads language from session state. `{language}` template variable.
- **Greeting trigger** -> Synthetic message through `LiveRequestQueue` on connection.
- **Safety timeout** -> 5-minute `asyncio.wait_for` in bridge. Closes queue on expiry.
- **State machine removal** -> ADK session state replaces CallContext. Business rules (farewell before end) move to agent instructions.

### Deferred to Implementation

- [Affects P3.1] Exact ADK `run_live()` event structure for audio and tool calls -- must be confirmed by running a sample
- [Affects P3.4] Whether `LiveRequestQueue.close()` cleanly terminates `run_live()` -- verify in spike
- [Affects P1.9] Exact `ReadonlyContext` API for instruction provider -- may need ADK source inspection
- [Affects P2] ADK eval `.evalset.json` format details for multi-turn conversations with tool calls

## Sources & References

### Origin

- **Origin document:** [docs/brainstorms/2026-04-01-adk-migration-requirements.md](docs/brainstorms/2026-04-01-adk-migration-requirements.md) -- Key decisions: ADK over custom architecture, full replacement, Twilio bridge as custom code, both testing approaches.

### Internal References

- Current Twilio bridge: `src/voice_assistant/call_handler.py` (pattern to adapt for ADK)
- Audio conversion: `src/voice_assistant/audio.py` (preserved)
- System prompts: `src/voice_assistant/prompts/` (preserved)
- Language profiles: `src/voice_assistant/config.py` (simplified)

### External References

- [Google ADK Docs](https://google.github.io/adk-docs/) -- framework documentation
- [ADK Get Started (Python)](https://google.github.io/adk-docs/get-started/python/) -- quickstart
- [ADK Function Tools](https://google.github.io/adk-docs/tools-custom/function-tools/) -- tool patterns
- [ADK Session State](https://google.github.io/adk-docs/sessions/state/) -- state management
- [ADK Streaming](https://google.github.io/adk-docs/streaming/) -- Live API integration
- [ADK Evaluation](https://google.github.io/adk-docs/evaluate/) -- eval framework
- [ADK Samples](https://github.com/google/adk-samples) -- reference implementations
- [ADK Python Source](https://github.com/google/adk-python) -- framework source
