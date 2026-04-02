---
title: "refactor: 12 Factor Agent Overhaul"
type: refactor
status: active
date: 2026-03-31
origin: docs/brainstorms/2026-03-30-12-factor-agent-overhaul-requirements.md
---

# refactor: 12 Factor Agent Overhaul

## Overview

Decompose the voice assistant's monolithic `gemini_session.py` into a clean, extensible architecture following the [12 Factor Agents](https://github.com/humanlayer/12-factor-agents) principles. The current system mixes tool definitions, tool dispatch, audio I/O, goodbye detection, and session lifecycle in one file. The refactor introduces a tool registry, explicit call state machine, transport/agent/LLM separation, error recovery, human escalation, and a stateless reducer pattern -- while keeping Gemini as the primary LLM provider.

## Problem Statement

The voice assistant works end-to-end (Twilio <-> Gemini Live API) but has grown organically:

- **Tool dispatch** is an if/elif chain in `execute_tool()` with manually synced `FunctionDeclaration` objects
- **Goodbye detection** uses 20+ regex patterns across 5 languages, producing false positives
- **No explicit call state** -- `_call_end_requested` boolean is the only lifecycle tracking
- **REPL reimplements agent logic** -- uses a different Gemini model (`gemini-2.5-flash` chat API) with its own tool dispatch loop, violating DRY
- **Transport and agent logic are entangled** -- `call_handler.py` directly imports `GeminiSession` and manipulates Twilio JSON
- **No error recovery** -- tool failures crash the call; no retry, no LLM feedback
- **No human escalation** path

(see origin: `docs/brainstorms/2026-03-30-12-factor-agent-overhaul-requirements.md`)

## Proposed Solution

A layered architecture with clear boundaries:

```
┌─────────────────────────────────────────────────────┐
│  Transport Layer (Twilio WS, REPL, HTTP API)        │
│  - Converts transport events to AgentEvents         │
│  - Executes Actions (send audio, transfer call)     │
├─────────────────────────────────────────────────────┤
│  Agent Core (stateless reducer)                     │
│  - step(CallContext, AgentEvent) -> (CallContext,    │
│    [Action])                                        │
│  - Pure function, no I/O                            │
├─────────────────────────────────────────────────────┤
│  Tool Registry                                      │
│  - Decorator-based, auto-generates FunctionDecls    │
│  - Self-contained: schema + handler in one place    │
├─────────────────────────────────────────────────────┤
│  LLM Adapter (Gemini Live, Gemini Chat)             │
│  - Translates LLM events to/from AgentEvents        │
│  - Protocol-based interface for swappability         │
├─────────────────────────────────────────────────────┤
│  CallContext + State Machine                        │
│  - Serializable call state                          │
│  - Phase enum with validated transitions            │
└─────────────────────────────────────────────────────┘
```

## Key Architectural Decisions

These decisions were made during brainstorming (see origin) and validated by research:

1. **Single agent, better organized** over multi-agent composition. Multi-agent can layer on later.
2. **Gemini primary, abstraction-ready**: thin provider protocol, only Gemini implemented now.
3. **Decorator-based tool registry** over plugin system. Tools register in-process via `@tool` decorator that auto-generates Gemini `FunctionDeclaration` from type hints. (Pattern from FastMCP; see research.)
4. **LLM-driven call termination** via `end_call` tool, replacing regex `GOODBYE_PATTERNS`. Safety timeouts as fallback.
5. **Conference-based warm transfer** for human escalation. Twilio has no dedicated Transfers API; Conference is the canonical mechanism. AI stays on call until human joins, then disconnects. (See research on Twilio warm transfer.)
6. **Hand-rolled state machine** with a `Phase` enum. The state space is small (8 phases including ERROR); a library adds dependency for little gain. The reducer pattern subsumes most state machine concerns.
7. **Two LLM adapters with separate Protocols** -- `StreamingAdapter` for Live API (audio I/O, turn-based) and `ChatAdapter` for Chat API (text request-response). They share only the output type (`AgentEvent`) and a minimal base (`connect`, `receive_events`, `disconnect`). The executor knows which adapter type it has via the transport. The "100% shared agent logic" criterion applies to business logic (tools, state, prompts), not LLM interaction code.
8. **Prompts as plain text files** with f-string substitution. No template engine dependency.
9. **Two-layer retry**: tenacity decorators on tool handlers for transient I/O failures; error compaction in the event stream for LLM self-healing (12FA Factor 9).

## Technical Approach

### Architecture

#### New File Structure

```
src/voice_assistant/
├── __init__.py
├── __main__.py              # Entry point (existing, minimal changes)
├── app.py                   # FastAPI routes (existing, add HTTP API endpoint)
├── audio.py                 # mulaw/PCM conversion (unchanged)
├── config.py                # Settings + build_genai_client (existing, extract prompts)
├── tools/
│   ├── __init__.py          # Registry: @tool decorator, get_declarations(), execute()
│   ├── weather.py           # get_current_weather tool
│   ├── end_call.py          # end_call tool
│   └── transfer.py          # transfer_to_human tool
├── prompts/
│   ├── base.txt             # Core agent instructions
│   ├── language_de-CH.txt   # Swiss German specifics
│   ├── language_fr-CH.txt   # French specifics
│   ├── language_it-CH.txt   # Italian specifics
│   └── escalation.txt       # When/how to escalate
├── state.py                 # Phase enum, CallContext dataclass, transition validation
├── events.py                # Typed AgentEvent classes (AudioReceived, ToolCallRequested, etc.)
├── reducer.py               # step(CallContext, AgentEvent) -> (CallContext, [Action])
├── actions.py               # Action types (SendAudio, ExecuteTool, EndCall, TransferCall)
├── adapters/
│   ├── __init__.py
│   ├── protocol.py          # LLMAdapter Protocol (abstract interface)
│   ├── gemini_live.py       # Live API adapter (streaming audio) -- extracted from gemini_session.py
│   └── gemini_chat.py       # Chat API adapter (text) -- extracted from repl.py
├── transports/
│   ├── __init__.py
│   ├── twilio_ws.py         # Twilio WebSocket handler (extracted from call_handler.py)
│   ├── repl.py              # Interactive text REPL
│   └── http_api.py          # Simple HTTP text endpoint
└── executor.py              # Orchestration loop: transport events -> reducer -> action execution
```

### Implementation Phases

#### Phase 1: Foundation (Tool Registry + CallContext + Prompts)

**Goal:** Establish the building blocks without changing runtime behavior. All existing tests continue to pass.

**Tasks:**

- [ ] **P1.1** Create `src/voice_assistant/tools/__init__.py` -- decorator-based tool registry
  - `@tool` decorator auto-generates `types.FunctionDeclaration` from function name, docstring, and `Annotated` type hints
  - Registry provides `get_declarations() -> list[types.Tool]` and `execute(name, args) -> dict`
  - Tags/categories support via decorator kwarg: `@tool(tags={"voice", "repl"})`
  - Note: Gemini uses `types.Schema` objects (not raw JSON Schema). The decorator must map Python type hints -> `types.Schema` with correct `type_` enum values (`STRING`, `NUMBER`, etc.)
- [ ] **P1.2** Create `src/voice_assistant/tools/weather.py` -- migrate `mock_get_weather` as `@tool`-decorated function
- [ ] **P1.3** Create `src/voice_assistant/state.py` -- `Phase` enum and `CallContext` frozen dataclass
  - Phases: `CONNECTING`, `GREETING`, `CONVERSATION`, `FAREWELL`, `ESCALATION`, `TRANSFERRING`, `ERROR`, `ENDED`
  - Add `ERROR` phase (identified gap: Gemini crash while caller is still on line)
  - `CallContext` fields: `call_id`, `caller_number`, `language`, `phase`, `phase_entered_at`, `tool_invocations` (tuple, not list -- frozen dataclass), `turn_count`, `escalation_reason`, `transfer_target`, `started_at`, `ended_at`, `consecutive_errors`
  - Use `tuple` for collection fields to preserve the frozen invariant; the reducer returns new CallContext instances via `dataclasses.replace()`
  - Transition validator: `can_transition(from_phase, to_phase) -> bool`
  - Add transitions missing from origin spec: `CONNECTING -> ERROR`, `CONNECTING -> ENDED`, `TRANSFERRING -> ERROR`, `ERROR -> ENDED`, `ERROR -> CONVERSATION` (recovery)
- [ ] **P1.4** Extract prompts to `src/voice_assistant/prompts/` as plain text files
  - Move `SYSTEM_INSTRUCTION_TEMPLATE` from `config.py` into `prompts/base.txt`
  - Split language-specific sections into `prompts/language_{code}.txt`
  - Add `prompts/escalation.txt` with guidance on when to escalate
  - Add `Settings.system_instruction()` method that composes: base + language + escalation + context
- [ ] **P1.5** Add structured logging for tool invocations (R14)
  - Log: tool name, args (sanitized), result/error, duration_ms
  - Use stdlib `logging` with structured format
- [ ] **P1.6** Update existing tests to use new registry; add tests for registry, CallContext, transitions
- [ ] **P1.7** Wire registry into existing `gemini_session.py` and `repl.py` as a drop-in replacement
  - `LIVE_TOOLS` becomes `tools.get_declarations()`
  - `execute_tool()` calls become `tools.execute()`
  - Verify no behavior change

**Success criteria:**
- All existing tests pass with updated imports
- New tests cover: tool registration, declaration generation, dispatch, CallContext creation/serialization, phase transitions (valid and invalid)
- `just repl` and `just dev` work identically to before

**Estimated effort:** ~2 sessions

---

#### Phase 2: Typed Events, Actions, and Reducer Core

**Goal:** Introduce the event/action types and the stateless reducer function. Not yet wired to real transport -- tested with pure unit tests.

**Tasks:**

- [ ] **P2.1** Create `src/voice_assistant/events.py` -- typed event classes
  - `CallStarted(call_id, caller_number, language)`
  - `AudioReceived(audio_data: bytes)` -- represents a batch of audio forwarded to LLM, NOT every PCM chunk
  - `TranscriptionReceived(text, is_input: bool)`
  - `ToolCallRequested(id, name, args)`
  - `ToolCallResult(id, name, result, duration_ms)`
  - `ToolCallError(id, name, error_message, consecutive_count)`
  - `LLMResponseAudio(audio_data: bytes)`
  - `LLMResponseText(text: str)`
  - `EndCallRequested(reason, farewell_message)`
  - `TransferRequested(reason, target)`
  - `TransferSucceeded()`
  - `TransferFailed(error)`
  - `SilenceTimeout(duration_seconds)`
  - `MaxDurationTimeout(duration_seconds)`
  - `Disconnected(source: str)` -- "caller", "gemini", "timeout"
  - `GeminiSessionFailed(error_message)`
- [ ] **P2.2** Create `src/voice_assistant/actions.py` -- action types
  - `SendAudioToTransport(audio_data: bytes)`
  - `SendAudioToLLM(audio_data: bytes)`
  - `SendTextToLLM(text: str)`
  - `ExecuteTool(id, name, args)`
  - `SendToolResult(id, name, result)`
  - `EndCall(farewell_message: str | None)`
  - `InitiateTransfer(target, reason, context_summary)`
  - `PlayErrorMessage(message: str)`
  - `ReconnectLLM()`
  - Note: logging is a side effect of the executor, not an action type. The executor logs tool invocations, phase transitions, and errors as it processes actions.
- [ ] **P2.3** Create `src/voice_assistant/reducer.py` -- the core pure function
  - `step(ctx: CallContext, event: AgentEvent) -> tuple[CallContext, list[Action]]`
  - Pattern match on `(ctx.phase, type(event))`
  - Key transitions:
    - `(CONNECTING, CallStarted)` -> `GREETING` + `SendTextToLLM("Greet the customer")`
    - `(GREETING, LLMResponseAudio)` -> `CONVERSATION` + `SendAudioToTransport`
    - `(CONVERSATION, ToolCallRequested)` -> stays `CONVERSATION` + `ExecuteTool`
    - `(CONVERSATION, ToolCallResult)` -> stays `CONVERSATION` + `SendToolResult`
    - `(CONVERSATION, ToolCallError)` -> if consecutive < 3: stays `CONVERSATION` + compact error; else `ERROR`
    - `(CONVERSATION, EndCallRequested)` -> `FAREWELL` + `SendAudioToTransport(farewell)`
    - `(CONVERSATION, TransferRequested)` -> `ESCALATION` + `InitiateTransfer`
    - `(ESCALATION, TransferSucceeded)` -> `TRANSFERRING`
    - `(ESCALATION, TransferFailed)` -> `CONVERSATION` + `SendTextToLLM("Transfer failed, inform caller")`
    - `(TRANSFERRING, Disconnected)` -> `ENDED`
    - `(*, Disconnected)` -> `ENDED`
    - `(*, GeminiSessionFailed)` -> `ERROR` + `ReconnectLLM` or `PlayErrorMessage` + `EndCall`
    - `(*, SilenceTimeout)` -> `SendTextToLLM("Ask if caller is still there")`; second timeout -> `FAREWELL`
    - `(*, MaxDurationTimeout)` -> `FAREWELL` + `EndCall`
  - Reducer NEVER performs I/O -- pure function
- [ ] **P2.4** Comprehensive unit tests for the reducer
  - Test every `(phase, event)` combination
  - Test error escalation (1, 2, 3 consecutive errors)
  - Test state serialization round-trip (CallContext -> JSON -> CallContext)
  - Test invalid transitions are rejected

**Success criteria:**
- Reducer is 100% covered by pure unit tests (no mocks needed)
- CallContext serializes to/from JSON
- Every phase transition in the state diagram is tested

**Estimated effort:** ~2 sessions

---

#### Phase 3: LLM Adapters and Transport Abstraction

**Goal:** Extract the Gemini-specific code into adapters behind a Protocol. Extract Twilio-specific code into a transport module. Wire everything through an executor.

**Tasks:**

- [ ] **P3.1** Create `src/voice_assistant/adapters/protocol.py` -- two adapter Protocols
  ```python
  class BaseAdapter(Protocol):
      """Shared surface -- both adapters implement these."""
      async def connect(self, config: AdapterConfig) -> None: ...
      async def receive_events(self) -> AsyncIterator[AgentEvent]: ...
      async def send_tool_result(self, responses: list) -> None: ...
      async def disconnect(self) -> None: ...

  class StreamingAdapter(BaseAdapter, Protocol):
      """Live API: bidirectional audio streaming."""
      async def send_audio(self, audio: bytes) -> None: ...
      async def send_realtime_text(self, text: str) -> None: ...

  class ChatAdapter(BaseAdapter, Protocol):
      """Chat API: text request-response."""
      async def send_message(self, text: str) -> AsyncIterator[AgentEvent]: ...
  ```
  - Separate Protocols avoid dead methods (`send_audio` on a text adapter)
  - The executor knows its adapter type via the transport that created it
- [ ] **P3.2** Create `src/voice_assistant/adapters/gemini_live.py` -- extract from `gemini_session.py`
  - Implements `StreamingAdapter` for Live API (streaming audio)
  - The `_receive_loop` logic becomes `receive_events()` yielding typed `AgentEvent`s
  - No tool dispatch, no state management, no goodbye detection -- just LLM I/O
- [ ] **P3.3** Create `src/voice_assistant/adapters/gemini_chat.py` -- extract from `repl.py`
  - Implements `ChatAdapter` for Chat API (text)
  - Same event output -- `ToolCallRequested`, `LLMResponseText`, etc.
- [ ] **P3.4** Create `src/voice_assistant/transports/twilio_ws.py` -- extract from `call_handler.py`
  - Reads Twilio WS JSON, emits `AgentEvent`s (AudioReceived, Disconnected)
  - Consumes `Action`s (SendAudioToTransport -> Twilio media JSON)
  - Handles stream SID, mulaw conversion (delegates to `audio.py`)
- [ ] **P3.5** Create `src/voice_assistant/transports/repl.py` -- refactored REPL
  - stdin/stdout transport
  - Emits `AgentEvent`s, consumes `Action`s
  - Uses `gemini_chat` adapter
- [ ] **P3.6** Create `src/voice_assistant/executor.py` -- the orchestration loop
  ```python
  async def run(transport: Transport, adapter: BaseAdapter, tools: ToolRegistry):
      ctx = CallContext(...)
      async for event in merge(transport.events(), adapter.receive_events()):
          ctx, actions = step(ctx, event)
          for action in actions:
              await execute_action(action, transport, adapter, tools)
  ```
  - The ONLY place where side effects happen
  - Handles tool execution with tenacity retry for transient failures
  - Feeds tool results/errors back through the reducer as events
- [ ] **P3.7** Create `src/voice_assistant/tools/end_call.py` -- `end_call` tool
  - Accepts `reason` (required) and `farewell_message` (optional)
  - Returns structured result: `{"action": "end_call", "reason": ..., "farewell_message": ...}`
  - **Tool-to-event flow:** the executor inspects tool results after execution. When a tool result contains `"action": "end_call"`, the executor emits an `EndCallRequested` event into the reducer (same pattern for `transfer_to_human` -> `TransferRequested`). This keeps the reducer pure -- it never sees raw tool results, only typed events.
  - Remove `GOODBYE_PATTERNS` and `_is_goodbye()` from old code
- [ ] **P3.8** Update `app.py` to use new transport + executor for the WS endpoint
- [ ] **P3.9** Update `__main__.py` REPL entry point to use new transport + executor
- [ ] **P3.10** Delete old `gemini_session.py`, `call_handler.py`, old `repl.py`
- [ ] **P3.11** Update and expand test suite
  - Adapter tests (mock the SDK, verify event translation)
  - Transport tests (mock WebSocket, verify event/action mapping)
  - Integration test: executor with mock adapter + mock transport

**Success criteria:**
- `just dev` works with real Twilio calls (end-to-end voice)
- `just repl` works with text chat
- Old `gemini_session.py` and `call_handler.py` are deleted
- REPL and Twilio paths share: tool registry, reducer, CallContext, prompts
- Each layer is independently testable

**Estimated effort:** ~3-4 sessions

---

#### Phase 4: Error Recovery and Resilience

**Goal:** Add production-grade error handling following 12FA Factor 9.

**Tasks:**

- [ ] **P4.1** Add tenacity retry decorators to tool handlers
  - Configurable max retries (default 3), exponential backoff
  - Only retry on transient exceptions (network, timeout)
  - Tool-level timeout (default 5s) to prevent blocking
- [ ] **P4.2** Implement error compaction in the reducer
  - `ToolCallError` events include a compact, LLM-readable error message
  - After 3 consecutive errors, transition to `ERROR` phase
  - In `ERROR` phase: attempt one LLM reconnection, play apology message if that fails, then `ENDED`
- [ ] **P4.3** Add safety timeouts to the executor
  - Silence timeout: configurable (default 30s). First timeout: "Are you still there?" Second: end call.
  - Max call duration: configurable (default 15min). Triggers `FAREWELL`.
  - Both emit events into the reducer, not handled as special cases.
- [ ] **P4.4** Handle Gemini session failures
  - `go_away` event from Live API triggers graceful session migration
  - Unexpected disconnect triggers `GeminiSessionFailed` event -> `ERROR` phase -> reconnect attempt
- [ ] **P4.5** Add tool execution timeout
  - If a tool handler exceeds timeout, cancel it and emit `ToolCallError`
  - Prevents indefinite audio silence during slow tool execution
- [ ] **P4.6** Tests for all error scenarios

**Success criteria:**
- Tool errors are fed back to LLM as context; LLM can retry or explain to caller
- 3 consecutive failures trigger error recovery
- Silence and duration timeouts work
- Gemini disconnect triggers reconnection attempt

**Estimated effort:** ~1-2 sessions

---

#### Phase 5: Human Escalation

**Goal:** Implement `transfer_to_human` tool with Twilio conference-based warm transfer.

**Tasks:**

- [ ] **P5.1** Create `src/voice_assistant/tools/transfer.py` -- `transfer_to_human` tool
  - Accepts `reason` (required), `target` (optional, defaults to configured operator number)
  - Returns structured result; reducer handles phase transition to `ESCALATION`
- [ ] **P5.2** Implement conference-based transfer in `transports/twilio_ws.py`
  - On `InitiateTransfer` action:
    1. Current call is already in a conference (or move it to one)
    2. Add human operator as conference participant via Twilio REST API
    3. AI stays on call, keeps talking ("I'm connecting you with a colleague...")
    4. On human join (status callback): remove AI participant
    5. On human no-answer/busy: emit `TransferFailed` event
  - Add `OPERATOR_PHONE_NUMBER` to `config.py`
- [ ] **P5.3** Add escalation guidance to system prompt (`prompts/escalation.txt`)
  - When to escalate: repeated tool failures, explicit caller request, out-of-scope topics
  - How to escalate: confirm with caller first, then invoke tool
- [ ] **P5.4** Handle transport-specific tool availability
  - `transfer_to_human` only available in voice transport (has Twilio)
  - REPL/HTTP: tool returns `{"status": "escalation_needed", "reason": "..."}` -- informational only
  - Use R4 tag filtering: `@tool(tags={"voice"})` excluded from REPL declarations
- [ ] **P5.5** Add Twilio conference status callback endpoint to `app.py`
- [ ] **P5.6** Tests (unit tests for reducer transitions; integration test with mocked Twilio API)

**Success criteria:**
- Human escalation works end-to-end on a real Twilio call
- AI stays on call during transfer, speaks naturally while human is being connected
- Failed transfers fall back to CONVERSATION with LLM-generated explanation
- REPL gracefully handles escalation (prints message, continues)

**Estimated effort:** ~2-3 sessions

---

#### Phase 6: HTTP API and Polish

**Goal:** Add the HTTP text endpoint, clean up, and verify all success criteria.

**Tasks:**

- [ ] **P6.1** Create `src/voice_assistant/transports/http_api.py` -- simple HTTP text endpoint
  - `POST /api/chat` accepts `{"message": "...", "session_id": "...", "language": "de-CH"}`
  - Stateless per-request (session_id for optional future statefulness)
  - Uses `gemini_chat` adapter through the same executor
  - Returns `{"response": "...", "tool_calls": [...], "escalation": null}`
- [ ] **P6.2** Add route to `app.py`
- [ ] **P6.3** Verify all success criteria from origin document:
  - [ ] Adding a new tool requires creating one file with no modifications to existing dispatch code
  - [ ] REPL and Twilio paths share 100% of business logic (tool dispatch, state management, prompts)
  - [ ] Call state serializes to JSON for debugging
  - [ ] Tool errors surfaced to LLM, result in graceful recovery
  - [ ] Human escalation works end-to-end
  - [ ] All tests pass
- [ ] **P6.4** Update README.md with new architecture docs
- [ ] **P6.5** Update justfile with any new commands

**Success criteria:**
- HTTP API endpoint works for text-based interactions
- All origin document success criteria met
- README reflects new architecture

**Estimated effort:** ~1 session

## Alternative Approaches Considered

1. **State machine library (python-statemachine v3)** -- Considered for R9. Rejected because the state space is small (8 phases) and the reducer pattern already handles transitions. Adding a library would create two sources of truth for state logic.

2. **Single LLM adapter Protocol** for both Live and Chat APIs -- Rejected because streaming audio (turn-based, VAD-driven, bidirectional) and request-response text are fundamentally different interaction models. A single Protocol would require dead methods (`send_audio` on Chat, `send_message` on Live). Instead: `BaseAdapter` with shared surface + `StreamingAdapter`/`ChatAdapter` sub-protocols.

3. **Class-based tool registry** -- Considered (Strands Agents pattern). Rejected in favor of decorator-based registry for simplicity: tools in this project are stateless functions, not lifecycle-managed objects.

4. **Jinja2 templates for prompts** -- Rejected as over-engineered. Plain text with f-string substitution is sufficient given the current prompt complexity. Can upgrade later if needed.

## System-Wide Impact

### Interaction Graph

Incoming Twilio WebSocket -> `twilio_ws.py` emits `AgentEvent` -> `executor.py` calls `step()` -> produces `Action`s -> executor dispatches to transport (send audio) or adapter (send to LLM) or tool registry (execute tool). Tool results feed back as events. The reducer is the single decision-maker.

### Error & Failure Propagation

- Tool errors: handler raises -> tenacity retries transient -> if exhausted, `ToolCallError` event -> reducer increments `consecutive_errors` -> after 3, transitions to `ERROR`
- LLM errors: adapter catches SDK exceptions -> emits `GeminiSessionFailed` -> reducer transitions to `ERROR` -> executor attempts reconnect
- Transport errors: Twilio WS closes -> `Disconnected` event -> reducer transitions to `ENDED`

### State Lifecycle Risks

- **Partial tool execution on disconnect**: Caller hangs up while tool is in-flight. The executor cancels pending tool tasks on `Disconnected` event. No orphaned state because CallContext is in-memory only (persistence deferred per scope).
- **Conference participant leak**: If AI is not properly removed after transfer, it stays in the conference consuming resources. The status callback must reliably trigger AI removal. Fallback: max duration timeout on the AI call leg.

### API Surface Parity

After refactor, three entry points use the same agent core:
- `WS /ws/media-stream` (Twilio voice) via `twilio_ws` transport + `gemini_live` adapter
- `just repl` via `repl` transport + `gemini_chat` adapter
- `POST /api/chat` via `http_api` transport + `gemini_chat` adapter

All share: tool registry, reducer, CallContext, prompts. Only the adapter and transport differ.

## Acceptance Criteria

### Functional Requirements

- [ ] Adding a new tool requires only creating a new `@tool`-decorated function in `tools/` -- no modifications to dispatch, declarations, or imports elsewhere
- [ ] `just repl` and Twilio voice path share tool registry, reducer, state management, and prompts
- [ ] `end_call` tool replaces all regex-based goodbye detection
- [ ] `transfer_to_human` tool triggers Twilio conference-based warm transfer
- [ ] Safety timeouts (silence 30s, max duration 15min) end calls gracefully
- [ ] Tool errors are compacted and fed back to LLM; 3 consecutive errors trigger error recovery
- [ ] HTTP API endpoint accepts text and returns agent responses

### Non-Functional Requirements

- [ ] CallContext serializes to JSON for debugging/inspection
- [ ] All tool invocations are structurally logged (name, args, result/error, duration)
- [ ] No new runtime dependencies beyond what's in pyproject.toml (tenacity is the one addition for retry)
- [ ] All existing tests pass (updated for new interfaces)
- [ ] New test coverage for: tool registry, state machine, reducer, adapters, transports

### Quality Gates

- [ ] Each phase passes `uv run pytest` before proceeding to the next
- [ ] Each phase gets a separate PR for incremental review
- [ ] `just repl` and `just dev` verified working after each phase

## Dependencies & Prerequisites

- **Twilio Conference API** for human escalation (Phase 5). Requires real Twilio account for integration testing.
- **`tenacity` package** -- add as runtime dependency for tool retry. (`uv add tenacity`)
- **Gemini Live API** stability -- the model `gemini-3.1-flash-live-preview` is in preview. Function calling is sequential-only (model blocks until tool response arrives, no audio during tool execution). If this changes, adapters need updating.
- **No blocking external dependencies** for Phases 1-4.

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Gemini Live API behavior changes (preview model) | Medium | High | LLM adapter abstraction isolates changes to one file |
| Conference-based transfer is complex to test | High | Medium | Mock Twilio API in tests; manual E2E test with real calls |
| Reducer pattern adds indirection, harder to debug | Medium | Low | Comprehensive logging; CallContext JSON dump on errors |
| REPL/Chat adapter event model diverges from Live adapter | Low | Medium | Shared `AgentEvent` types enforced by type checker |

## Outstanding Questions

### Resolved During Planning

- **State machine library?** -> Hand-rolled Phase enum + reducer. Library is overkill for 8 states.
- **Twilio transfer mechanism?** -> Conference-based warm transfer. Only viable option.
- **Prompt file format?** -> Plain text with f-string substitution.
- **Retry location?** -> Two layers: tenacity on tools (transient), error compaction in reducer (semantic).
- **LLM provider interface shape?** -> Two adapter protocols (streaming + request-response), shared event output.

### Deferred to Implementation

- Exact `AdapterConfig` fields for the LLM Protocol (will emerge during Phase 3)
- Whether to add `session_resumption` support to the Live adapter (nice-to-have for production)
- Context summarization strategy for long Chat API conversations (R21 -- only relevant for non-Live paths)

## Sources & References

### Origin

- **Origin document:** [docs/brainstorms/2026-03-30-12-factor-agent-overhaul-requirements.md](docs/brainstorms/2026-03-30-12-factor-agent-overhaul-requirements.md) -- Key decisions carried forward: decorator-based tool registry, LLM-driven call termination, conference-based warm transfer, single agent architecture.

### Internal References

- Current monolith: `src/voice_assistant/gemini_session.py` (321 lines, target for decomposition)
- Current transport coupling: `src/voice_assistant/call_handler.py:1-173`
- Current REPL (parallel implementation): `src/voice_assistant/repl.py:1-130`
- Existing tests: `tests/test_tools.py` (21 tests, covers tool dispatch and receive loop)
- Agent conventions: `AGENTS.md` (uv, pytest, just)

### External References

- [12 Factor Agents](https://github.com/humanlayer/12-factor-agents) -- architectural principles
- [FastMCP Tools](https://gofastmcp.com/servers/tools) -- decorator-based tool registry pattern
- [Twilio Warm Transfer Tutorial](https://www.twilio.com/docs/voice/tutorials/warm-transfer) -- conference-based transfer
- [Twilio Warm Transfer from AI (OpenAI)](https://www.twilio.com/en-us/blog/developers/tutorials/product/warm-transfer-openai-realtime-programmable-sip) -- closest analogue
- [Gemini Live API](https://ai.google.dev/gemini-api/docs/live-api) -- streaming audio + function calling
- [Gemini Live API Tool Use](https://ai.google.dev/gemini-api/docs/live-tools) -- function calling in live mode
- [Tenacity](https://tenacity.readthedocs.io/) -- retry library
- [python-statemachine](https://github.com/fgmacedo/python-statemachine) -- evaluated, not selected
