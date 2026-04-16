---
title: "feat: Configurable persona scoping (Velo-Händler demo)"
type: feat
status: completed
date: 2026-04-16
origin: docs/brainstorms/2026-04-16-persona-scoping-brainstorm.md
---

# feat: Configurable persona scoping (Velo-Händler demo)

## Overview

Add a YAML-based persona system so the voice assistant can be scoped to any business by swapping one config file. First persona: a fictional Swiss bike shop. The agent should answer in-scope questions, honestly decline out-of-scope ones, and never pretend to have capabilities it lacks.

## Problem Statement / Motivation

The current system prompt (`base.txt`) hard-codes a generic "Swiss company customer service" identity. Every demo feels the same. For real customer projects, each deployment needs a distinct persona — name, domain knowledge, scope boundary. There is no abstraction for this today. (see brainstorm: `docs/brainstorms/2026-04-16-persona-scoping-brainstorm.md`)

## Proposed Solution

### New files

```
voice_assistant/
  personas/
    velo_shop.yaml       # first persona — fictional bike shop
  prompts/
    base.txt             # refactored — generic scaffolding + {persona_block} slot
```

### Config flow

1. `PERSONA` env var selects the active persona (e.g. `PERSONA=velo_shop`)
2. `config.py` loads `personas/{PERSONA}.yaml` at startup, validates required fields, fails fast if missing
3. YAML fields are rendered into a `{persona_block}` section injected into `base.txt`
4. `build_instruction()` signature unchanged — existing callers unaffected
5. `agent.py` name/description derived from persona name

### YAML schema

```yaml
# Required fields
name: "Velo Züri"
tagline: "Ihr Velofachgeschäft in Zürich"
location: "Langstrasse 42, 8004 Zürich"

allowed_topics:
  - Öffnungszeiten und Standort
  - Velo-Reparatur und Service
  - Velo-Verkauf und Beratung
  - E-Bike Beratung
  - Zubehör und Ersatzteile
  - Termin vereinbaren

business_facts:
  hours: "Mo-Fr 09:00-18:30, Sa 09:00-16:00, So geschlossen"
  services:
    - Velo-Reparatur und Wartung
    - E-Bike Beratung und Verkauf
    - Kinder- und Stadtvelos
    - Zubehör (Helme, Schlösser, Lichter)
  brands:
    - Canyon
    - Trek
    - Specialized
    - Flyer (E-Bikes)
  price_range: "Stadtvelos ab CHF 500, E-Bikes ab CHF 2'500"

out_of_scope_decline: >
  Das liegt leider ausserhalb meines Bereichs — ich bin spezialisiert
  auf Velo-Themen. Kann ich Ihnen bei etwas rund ums Velo weiterhelfen?

# Optional — override the generic "Kundendienst" greeting per locale
greetings:
  de-CH: >
    Grüezi! Sie sind mit Velo Züri verbunden.
    Wie kann ich Ihnen helfen?
  fr-CH: >
    Bonjour! Vous êtes en contact avec Velo Züri.
    Comment puis-je vous aider?
```

### Prompt composition (refactored `base.txt`)

```
You are {agent_role} for {persona_name} — {persona_tagline}, located at {persona_location}.
You are speaking on the phone with a customer.

YOUR EXPERTISE:
{allowed_topics_formatted}

BUSINESS INFORMATION:
{business_facts_formatted}

SCOPE RULES:
- If the customer asks about something NOT in your expertise, respond with:
  "{out_of_scope_decline}"
- If the customer asks about something in your expertise but you lack specific
  data (e.g. current stock, specific pricing), say so honestly and offer to
  take a note or connect them with a colleague.
- NEVER pretend to look things up or claim capabilities you do not have.

IMPORTANT RULES:
- RESPOND IN {language_display}. ...
[rest of existing rules: language switching, conversation flow, ending the call]
```

`escalation.txt` stays unchanged — it's generic and complementary (not conflicting) with persona scope rules.

## Technical Considerations

### Startup validation

`config.py` validates the persona YAML at import time:
- `PERSONA` env var selects a persona by name; when unset, the first available persona YAML file is auto-selected
- File must exist at `voice_assistant/personas/{PERSONA}.yaml`
- Required fields: `name`, `allowed_topics`, `out_of_scope_decline`
- Fail fast with `EnvironmentError` listing what's wrong (matches existing `Settings.validate()` pattern)

### Language switching + persona

The decline template and business facts are written in the persona's primary language. When a caller switches language, Gemini translates on-the-fly — the prompt already instructs "switch to that language immediately." The decline template is guidance, not a literal script. This is sufficient for the demo; per-language decline templates can be added later if needed.

### Greeting override

SpecFlow analysis identified that the existing greeting ("Kundendienst") breaks immersion for a bike shop. The persona YAML has an optional `greetings` dict keyed by locale. If present, `language_profile()` uses it instead of the default. If absent, falls back to existing `LANGUAGE_PROFILES` greeting — backward compatible.

### Escalation vs. decline

These are distinct flows:
- **Decline** (out-of-scope): "Das ist nicht mein Bereich" → redirect to allowed topics
- **Escalation** (in-scope, beyond capability): "Ich kann das leider nicht nachschauen — soll ich Sie mit einem Kollegen verbinden?"

`escalation.txt` handles the second. The persona's `out_of_scope_decline` handles the first. No conflict.

## Acceptance Criteria

- [x] `voice_assistant/personas/velo_shop.yaml` exists with all required fields
- [x] `config.py` loads persona YAML at startup, validates required fields, fails fast if invalid
- [x] `PERSONA` env var selects the persona file
- [x] `base.txt` refactored with `{persona_block}` — persona fields injected into system instruction
- [x] `build_instruction()` output contains persona name, allowed topics, and decline template
- [x] `agent.py` name/description reflect active persona
- [x] Out-of-scope questions → graceful decline with persona-specific redirect
- [x] In-scope questions without data → honest "no live access" + escalation offer
- [x] Optional `greetings` override works per locale; falls back to `LANGUAGE_PROFILES` if absent
- [x] Unit tests: YAML loading, validation (missing file, missing fields), prompt composition with persona
- [x] Existing `test_config.py` tests still pass (language substitution, escalation inclusion, honesty guidance)
- [ ] Manual test: 3 in-scope + 3 out-of-scope questions behave correctly

## Implementation Steps

### Step 1: Persona YAML + loader (`config.py`)

- Add `PERSONA` field to `Settings` dataclass (default from env var, no fallback)
- Add `_PERSONAS_DIR = Path(__file__).parent / "personas"`
- Write `_load_persona(name: str) -> dict` — reads YAML, validates required keys, returns dict
- Call at module level alongside existing prompt loading
- Add `pyyaml` dependency via `uv add pyyaml`

Files: `voice_assistant/config.py`, `pyproject.toml`

### Step 2: Create `velo_shop.yaml`

- Write the fictional Velo Züri persona with all fields from schema above
- Place in `voice_assistant/personas/velo_shop.yaml`

Files: `voice_assistant/personas/velo_shop.yaml`

### Step 3: Refactor `base.txt`

- Replace hard-coded "Swiss company" identity with `{persona_block}` placeholder
- Add `SCOPE RULES` section with `{out_of_scope_decline}` slot
- Keep existing rules (language, conversation flow, ending call) unchanged
- Update `Settings.system_instruction()` to format persona fields into the template

Files: `voice_assistant/prompts/base.txt`, `voice_assistant/config.py`

### Step 4: Greeting override

- In `Settings.language_profile()`, check if persona has `greetings.{lang_code}` and override the greeting field
- Fallback to existing `LANGUAGE_PROFILES` greeting if persona doesn't specify one

Files: `voice_assistant/config.py`

### Step 5: Update `agent.py`

- Derive agent `name` and `description` from persona (e.g. `name="velo_zueri"`, `description="Velo Züri voice assistant"`)

Files: `voice_assistant/agent.py`

### Step 6: Unit tests

- Test YAML loading succeeds for valid persona
- Test validation fails for missing file, missing required fields
- Test `build_instruction()` output contains persona name, scope rules, decline template
- Test greeting override works per locale
- Test greeting fallback when persona has no greetings
- Verify existing `test_config.py` tests pass with `PERSONA` set

Files: `tests/unit/test_persona.py`, `tests/unit/test_config.py` (may need `PERSONA` env fixture)

### Step 7: Manual testing

- Set `PERSONA=velo_shop` in `.env`
- Run `just adk` or `just repl`
- Test 3 in-scope: Öffnungszeiten, E-Bike Beratung, Reparatur-Termin
- Test 3 out-of-scope: Wetter, Pizza bestellen, Aktienkurs
- Verify decline is natural, not robotic

## Dependencies & Risks

- **New dependency:** `pyyaml` — standard, no risk
- **Breaking change:** `PERSONA` env var becomes required. Existing `.env` files need updating. Mitigate: clear error message at startup
- **Existing tests:** `test_config.py` tests call `build_instruction()` against real files. Once `base.txt` gains `{persona_block}`, these tests need `PERSONA` env set. Use a pytest fixture or conftest to set it.
- **Deploy:** Cloud Run `just deploy` recipe needs `PERSONA` added to `--set-env-vars`

## Sources & References

- **Origin brainstorm:** [docs/brainstorms/2026-04-16-persona-scoping-brainstorm.md](docs/brainstorms/2026-04-16-persona-scoping-brainstorm.md) — key decisions: YAML per persona, env var selection, no voice override in persona, honest+escalation for missing facts
- Related issue: #9
- Closely related: #11 (no hallucinated capabilities — persona scope rules reinforce this)
- Current prompt: `voice_assistant/prompts/base.txt:1-22`
- Config assembly: `voice_assistant/config.py:100-182`
- Agent wiring: `voice_assistant/agent.py:41-53`
- Existing tests: `tests/unit/test_config.py`
