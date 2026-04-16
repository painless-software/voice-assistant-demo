# Brainstorm: Constrain Agent Persona to Specific Use Case

**Issue:** #9
**Date:** 2026-04-16
**Status:** Ready for planning

## What We're Building

A configurable persona system so the voice assistant can be re-pointed to any business demo by swapping a single YAML file. First demo: fictional Swiss bike shop ("Velo-Händler").

The persona constrains the agent's identity, domain knowledge, and scope — off-topic requests are declined gracefully, in-scope questions without data are handled honestly via escalation.

## Why This Approach

**Audience is real customers.** This is not a throwaway demo — it becomes the template for actual paid projects. The abstraction must be clean enough to hand to a new customer onboarding.

**YAML per persona chosen over plain-text or Python modules** because:
- Structured fields (identity, scope, decline template) are easier to edit for non-developers
- Scales to many demos without code changes
- `.env` variable `PERSONA=velo_shop` selects the active persona
- Per-locale greeting overrides live in the persona YAML (`greetings:` key), applied on top of `LANGUAGE_PROFILES` at runtime

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Config format | One YAML file per persona, selected via `PERSONA` env var | Structured, non-dev friendly, scales |
| Persona fields | Identity + business facts, allowed topics, out-of-scope decline template | Covers all needs without overreach |
| Voice/greeting | Stay in LANGUAGE_PROFILES, not persona | Persona is about content/scope, not TTS config |
| Missing facts behavior | Honestly say "no live access", offer note or escalation | Aligns with #11 (no hallucinated capabilities), leverages existing escalation prompt |
| First iteration scope | Velo persona only | Smallest diff, prove abstraction works |
| Decline style | Friendly, persona-specific redirect line in YAML | Not robotic boilerplate — each persona can customize |

## Persona YAML Shape (Sketch)

```yaml
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
```

## How It Plugs In

1. `config.py` loads `personas/<PERSONA>.yaml` at startup
2. `base.txt` gets `{persona_block}` placeholder — persona fields rendered into structured prompt section
3. Existing escalation prompt stays unchanged (already handles "connect to specialist")
4. `agent.py` name/description derived from persona name

## Resolved Questions

- **Scope of first iteration?** Velo only. No second stub persona needed.
- **Voice overrides in persona?** No. Stay in LANGUAGE_PROFILES.
- **Agent behavior for missing facts?** Honest + escalation. Not improvisation.

## Open Questions

None — ready for planning.
