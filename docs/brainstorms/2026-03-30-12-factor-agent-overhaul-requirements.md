---
date: 2026-03-30
topic: 12-factor-agent-overhaul
---

# 12 Factor Agent Overhaul

## Problem Frame

The voice assistant has a working agentic loop (Twilio <-> Gemini Live API) but the architecture has grown organically with several concerns mixed together. `gemini_session.py` handles tool definitions, tool dispatch, audio I/O, goodbye detection, and session lifecycle in one file. Tools are added via hardcoded if/elif chains. There is no explicit call state, no error recovery, no human escalation, and no separation between transport and agent logic. This makes the system hard to extend, test, monitor, and evolve toward production readiness.

The refactor applies the [12 Factor Agents](https://github.com/humanlayer/12-factor-agents) principles to create a clean, extensible, production-ready architecture while keeping Gemini as the primary LLM provider.

## Requirements

### Tool Registry & Extensibility (Factors 4, 10)

- R1. Replace the if/elif `execute_tool()` dispatch with a tool registry that supports registering tools declaratively (name, schema, handler function) in one place
- R2. Each tool should be self-contained: its Gemini `FunctionDeclaration`, handler function, and metadata defined together (either as a class, decorated function, or registry entry)
- R3. Tool registration must automatically populate `LIVE_TOOLS` for Gemini and the dispatch table — no manual sync between declaration and dispatch
- R4. Support tool categories or tags so tools can be selectively enabled per agent configuration or call context

### Separation of Concerns (Factors 8, 11)

- R5. Extract transport layer: Twilio WebSocket handling should be isolated from agent logic so the same agent can be driven from REPL, HTTP API, or other channels without code duplication
- R6. Extract agent core: the conversation loop, tool dispatch, and state management should be independent of both the LLM provider and the transport layer
- R7. Introduce a thin LLM provider interface (protocol/ABC) that Gemini implements, making the architecture swappable without requiring immediate multi-provider support
- R8. Replace regex-based goodbye detection with an `end_call` tool that the LLM invokes to terminate calls:
  - The tool accepts a `reason` (required) and optional `farewell_message`
  - System instructions guide the agent to confirm the caller is done before ending
  - Remove all hardcoded `GOODBYE_PATTERNS` regex and `_is_goodbye()` logic
  - Add safety fallbacks: silence timeout (configurable, e.g. 30s), max call duration limit, and Twilio disconnect as hard stop
  - The `end_call` tool call triggers the `CONVERSATION → FAREWELL` state transition

### State Machine & Call Lifecycle (Factors 5, 6)

- R9. Define explicit call phases as a state machine with these phases and transitions:
  - `CONNECTING -> GREETING -> CONVERSATION -> FAREWELL -> ENDED`
  - `CONVERSATION -> ESCALATION -> TRANSFERRING -> ENDED`
  - `ESCALATION -> CONVERSATION` (fallback if transfer fails)
  - Any phase -> `ENDED` (on disconnect)
  - Phase transitions are event-driven (not turn-driven) and do not pause audio streaming
  - Invalid transitions are rejected by the state machine
- R10. Call state should be inspectable at any point — current phase, tool calls made, escalation status, duration
- R11. Design state to be serializable so calls could theoretically be paused/resumed or checkpointed (persistence implementation deferred)
- R12. Unify execution state and business state into a single `CallContext` containing:
  - Identity: call_id, caller_number, language
  - State: current phase, phase_entered_at
  - History: tool_invocations (name, args, result, duration, error), turn_count
  - Escalation: reason, transfer_target
  - Timing: started_at, ended_at
  - CallContext must NOT contain: raw audio buffers, Gemini session internals, or transport state

### Error Recovery (Factor 9)

- R13. Tool execution errors should be compacted into structured context and fed back to the LLM so it can retry or explain the failure to the caller
- R14. Add structured logging for all tool invocations (name, args, result/error, duration) for observability
- R15. Define a retry policy for transient tool failures (e.g., network errors on real API calls) with configurable max retries

### Human Escalation (Factor 7)

- R16. Add a `transfer_to_human` tool that the agent can invoke when it cannot resolve the caller's issue
- R17. The transfer tool should trigger a Twilio warm transfer or conference bridge to a configured operator number
- R18. The agent's system instructions should include guidance on when to escalate (repeated failures, explicit caller request, out-of-scope topics)

### Prompt & Context Management (Factors 2, 3)

- R19. System instructions should be composable: base instructions + language-specific + context-specific (e.g., time of day, caller history) rather than a single template string
- R20. Keep prompts as version-controlled text assets, not buried in Python code — move to a `prompts/` directory or similar
- R21. For long conversations, implement context summarization or pruning to stay within token limits (relevant when moving beyond Gemini Live's streaming model)

### Trigger Flexibility (Factor 11)

- R22. The REPL (`repl.py`) should use the same agent core as the Twilio path, not a parallel implementation with its own tool dispatch
- R23. Add a simple HTTP API endpoint that accepts text input and returns agent responses, enabling webhook-based or API-driven interactions without Twilio

### Stateless Reducer Pattern (Factor 12)

- R24. The agent's event-processing logic should be a pure function: given current `CallContext` + new event (audio, transcription, tool call, disconnect), produce updated `CallContext` + list of actions to execute
- R25. Side effects (sending audio, making API calls, transferring calls) should be executed by the orchestration layer, not inside the reducer
- R26. Events should be typed (e.g., `AudioEvent`, `TranscriptionEvent`, `ToolCallEvent`, `DisconnectEvent`) and the reducer should pattern-match on `(current_phase, event_type)` to determine transitions and actions

## Success Criteria

- Adding a new tool requires creating one file/class with no modifications to existing dispatch code
- The REPL and Twilio paths share 100% of agent logic (tool dispatch, state management, prompts)
- Call state can be serialized to JSON and inspected for debugging
- Tool errors are surfaced to the LLM and result in graceful caller-facing recovery
- Human escalation works end-to-end on a real Twilio call
- All existing tests continue to pass (with necessary updates to new interfaces)

## Scope Boundaries

- **In scope:** Architecture refactor, tool registry, state machine, error handling, human escalation, prompt organization, transport abstraction
- **Out of scope:** Multi-provider LLM implementation (only the interface boundary), persistent call storage (database), call analytics dashboard, multi-agent orchestration, authentication/authorization
- **Not changing:** Audio conversion logic (`audio.py`), Twilio provisioning script, core Gemini Live API usage pattern (streaming audio)

## Key Decisions

- **Single agent, better organized** over multi-agent composition: keeps complexity manageable while achieving clean architecture. Multi-agent can be layered on later.
- **Gemini primary, abstraction-ready**: introduce a thin provider interface but only implement Gemini. Avoids speculative abstraction while making future swaps feasible.
- **Tool registry pattern** over plugin system: tools are registered in-process (not loaded from external packages). Keeps it simple.
- **Include human escalation**: important for real customer service use cases and demonstrates Factor 7.
- **LLM-driven call termination** over regex pattern matching: the agent decides when to end calls via `end_call` tool, with safety timeouts as fallback. Eliminates false positives, works across all languages, and enables graceful farewells.

## Dependencies / Assumptions

- Twilio's conference/transfer API is available for the human escalation feature
- Gemini Live API continues to support function calling in streaming mode
- The current test suite covers tool dispatch; tests will need updating to use the new registry

## Outstanding Questions

### Resolve Before Planning

(None — all product decisions resolved)

### Deferred to Planning

- [Affects R7][Needs research] What's the minimal LLM provider interface that covers Gemini Live's streaming + tool calling + audio I/O?
- [Affects R9][Technical] What state machine library (if any) to use, or implement a simple one from scratch?
- [Affects R17][Needs research] Which Twilio API to use for warm transfer — `<Dial>` with conference, or the Transfers API?
- [Affects R20][Technical] Best format for prompt files — plain text, Jinja2 templates, or YAML with metadata?
- [Affects R15][Technical] Should retry logic live in the tool registry (decorator-based) or in the orchestration layer?

## Next Steps

-> `/ce:plan` for structured implementation planning
