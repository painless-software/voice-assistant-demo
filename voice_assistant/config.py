"""
Central configuration – loaded once at startup from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PERSONAS_DIR = Path(__file__).parent / "personas"

_PERSONA_REQUIRED_FIELDS = ("name", "allowed_topics", "out_of_scope_decline")


# ---------------------------------------------------------------------------
# Language profiles
# ---------------------------------------------------------------------------

LANGUAGE_PROFILES: dict[str, dict] = {
    "de-CH": {
        "display": "Swiss German",
        "voice_name": "Leda",
        "elevenlabs_voice_id": "onwK4e9ZLuTAKqWW03F9",  # Daniel
        "greeting": (
            "Grüezi! Sie sind mit dem Kundendienst verbunden. "
            "Wie kann ich Ihnen heute helfen?"
        ),
        "fallback_reply": (
            "Entschuldigung, ich habe Sie leider nicht verstanden. "
            "Könnten Sie das bitte wiederholen?"
        ),
    },
    "de-DE": {
        "display": "Standard German",
        "voice_name": "Leda",
        "elevenlabs_voice_id": "onwK4e9ZLuTAKqWW03F9",  # Daniel
        "greeting": (
            "Hallo! Sie sind mit dem Kundendienst verbunden. Wie kann ich Ihnen helfen?"
        ),
        "fallback_reply": (
            "Entschuldigung, ich habe Sie leider nicht verstanden. "
            "Könnten Sie das bitte wiederholen?"
        ),
    },
    "fr-CH": {
        "display": "Swiss French",
        "voice_name": "Aoede",
        "elevenlabs_voice_id": "TX3LPaxmHKxFdv7VOQHJ",  # Liam
        "greeting": (
            "Bonjour! Vous êtes en contact avec notre service clientèle. "
            "Comment puis-je vous aider aujourd'hui?"
        ),
        "fallback_reply": (
            "Je suis désolé, je n'ai pas bien compris. "
            "Pourriez-vous répéter, s'il vous plaît?"
        ),
    },
    "it-CH": {
        "display": "Swiss Italian",
        "voice_name": "Zephyr",
        "elevenlabs_voice_id": "bIHbv24MWmeRgasZH58o",  # Will
        "greeting": (
            "Buongiorno! Benvenuto al servizio clienti. Come posso aiutarla oggi?"
        ),
        "fallback_reply": (
            "Mi dispiace, non ho capito bene. Potrebbe ripetere per favore?"
        ),
    },
}

# Common farewell substrings the agent might use, across all supported
# languages.  Matched case-insensitively against the agent's output
# transcription to detect that the call is ending.  Keep these broad —
# the agent is steered by the prompt but may improvise.
FAREWELL_PHRASES = [
    # German
    "wiederhören",
    "wiedersehen",
    "tschüss",
    "tschüs",
    "ade",
    "adé",
    # French
    "au revoir",
    "à bientôt",
    "bonne journée",
    # Italian
    "arrivederci",
    "arrivederla",
    # English (language switching)
    "goodbye",
    "bye bye",
    "bye",
]

# Text/general model (generateContent) -- used by ADK web UI and non-live flows
GEMINI_MODEL = "gemini-2.5-flash"
# Live-only model (bidiGenerateContent) -- used for real-time phone calls
GEMINI_LIVE_MODEL = "gemini-2.5-flash-native-audio-latest"

# System instruction injected into every Gemini Live session.
# Loaded from prompts/ text files and composed at runtime.
SYSTEM_INSTRUCTION_TEMPLATE = (_PROMPTS_DIR / "base.txt").read_text()
_ESCALATION_PROMPT = (_PROMPTS_DIR / "escalation.txt").read_text()


# ---------------------------------------------------------------------------
# Persona loading
# ---------------------------------------------------------------------------


def _load_persona(name: str) -> dict:
    """Load and validate a persona YAML file by name."""
    path = _PERSONAS_DIR / f"{name}.yaml"
    if not path.exists():
        raise EnvironmentError(
            f"Persona file not found: {path}\n"
            f"Set PERSONA to a valid persona name "
            f"(available: {', '.join(p.stem for p in _PERSONAS_DIR.glob('*.yaml'))})"
        )
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise EnvironmentError(
            f"Persona '{name}' must be a YAML mapping with fields: "
            f"{', '.join(_PERSONA_REQUIRED_FIELDS)}"
        )
    missing = [f for f in _PERSONA_REQUIRED_FIELDS if f not in data]
    if missing:
        raise EnvironmentError(
            f"Persona '{name}' is missing required fields: {', '.join(missing)}"
        )
    return data


def _render_persona_block(persona: dict) -> str:
    """Render persona data into a prompt section."""
    topics = "\n".join(f"- {t}" for t in persona["allowed_topics"])

    facts_lines = []
    for key, value in persona.get("business_facts", {}).items():
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            facts_lines.append(f"- {label}: {', '.join(value)}")
        else:
            facts_lines.append(f"- {label}: {value}")
    facts = "\n".join(facts_lines) if facts_lines else "No additional facts available."

    decline = persona["out_of_scope_decline"].strip()

    return (
        f"You are a friendly and professional representative for "
        f"{persona['name']}.\n"
        f"{persona.get('tagline', '')}\n"
        f"Located at: {persona.get('location', 'N/A')}\n"
        f"\n"
        f"YOUR EXPERTISE:\n{topics}\n"
        f"\n"
        f"BUSINESS INFORMATION:\n{facts}\n"
        f"\n"
        f"SCOPE RULES:\n"
        f"- If the customer asks about something NOT listed under YOUR EXPERTISE, "
        f"respond approximately like this:\n"
        f'  "{decline}"\n'
        f"- If the customer asks about something in your expertise but you lack "
        f"specific data (e.g. current stock, exact pricing for a model), say so "
        f"honestly and offer to take a note or connect them with a colleague.\n"
        f"- NEVER pretend to look things up or claim capabilities you do not have."
    )


def load_all_personas() -> dict[str, dict]:
    """Load and validate all persona YAML files from the personas directory."""
    personas = {}
    for path in sorted(_PERSONAS_DIR.glob("*.yaml")):
        personas[path.stem] = _load_persona(path.stem)
    return personas


def build_instruction_for_persona(persona: dict, lang_code: str | None = None) -> str:
    """Build the full system instruction for a specific persona and language."""
    lang = lang_code or settings.default_language
    profile = LANGUAGE_PROFILES.get(lang, LANGUAGE_PROFILES[settings.default_language])
    block = _render_persona_block(persona)
    base = SYSTEM_INSTRUCTION_TEMPLATE.format(
        persona_block=block,
        language_display=profile["display"],
    )
    return f"{base}\n\n{_ESCALATION_PROMPT}"


def _default_persona_name() -> str:
    """Return PERSONA env var, or the first available persona file."""
    name = os.getenv("PERSONA", "")
    if name:
        return name
    available = sorted(p.stem for p in _PERSONAS_DIR.glob("*.yaml"))
    if available:
        return available[0]
    return ""


_PERSONA_NAME = _default_persona_name()
PERSONA: dict = _load_persona(_PERSONA_NAME) if _PERSONA_NAME else {}
PERSONA_BLOCK: str = _render_persona_block(PERSONA) if PERSONA else ""


@dataclass
class Settings:
    # Twilio – required at runtime, read lazily so imports work without .env
    twilio_account_sid: str = field(
        default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID", "")
    )
    twilio_auth_token: str = field(
        default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", "")
    )
    twilio_phone_number: str = field(
        default_factory=lambda: os.getenv("TWILIO_PHONE_NUMBER", "")
    )

    # Google
    google_api_key: str | None = field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY")
    )
    google_cloud_project: str | None = field(
        default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT")
    )
    google_cloud_location: str = field(
        default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    )

    # Server
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", ""))

    # Language
    default_language: str = field(
        default_factory=lambda: os.getenv("DEFAULT_LANGUAGE", "de-CH")
    )

    # Voice backend: "gemini" (default) or "elevenlabs"
    voice_backend: str = field(
        default_factory=lambda: os.getenv("VOICE_BACKEND", "gemini")
    )

    # ElevenLabs (required when voice_backend == "elevenlabs")
    elevenlabs_api_key: str = field(
        default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", "")
    )
    elevenlabs_model_id: str = field(
        default_factory=lambda: os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")
    )

    # Persona
    persona: str = field(default_factory=lambda: os.getenv("PERSONA", ""))

    _VALID_VOICE_BACKENDS = {"gemini", "elevenlabs"}

    def validate(self, *, require_twilio: bool = True) -> None:
        """Call on startup to fail early with a clear message if config is missing."""
        if self.voice_backend not in self._VALID_VOICE_BACKENDS:
            raise EnvironmentError(
                f"VOICE_BACKEND={self.voice_backend!r} is not valid. "
                f"Choose one of: {', '.join(sorted(self._VALID_VOICE_BACKENDS))}"
            )
        missing = []
        if require_twilio:
            if not self.twilio_account_sid:
                missing.append("TWILIO_ACCOUNT_SID")
            if not self.twilio_auth_token:
                missing.append("TWILIO_AUTH_TOKEN")
            if not self.twilio_phone_number:
                missing.append("TWILIO_PHONE_NUMBER")
        if not self.google_api_key and not self.google_cloud_project:
            missing.append("GOOGLE_API_KEY (or GOOGLE_CLOUD_PROJECT for Vertex AI)")
        if self.voice_backend == "elevenlabs" and not self.elevenlabs_api_key:
            missing.append("ELEVENLABS_API_KEY")
        if missing:
            raise EnvironmentError(
                "Missing required environment variables:\n  "
                + "\n  ".join(missing)
                + "\n\nCopy .env.example to .env and fill in your values."
            )

    def use_vertex_ai(self) -> bool:
        """Return True when Vertex AI credentials are configured."""
        return bool(self.google_cloud_project) and not self.google_api_key

    def language_profile(self, lang_code: str | None = None) -> dict:
        code = lang_code or self.default_language
        profile = LANGUAGE_PROFILES.get(code, LANGUAGE_PROFILES[self.default_language])
        persona_greeting = PERSONA.get("greetings", {}).get(code)
        if persona_greeting:
            profile = {**profile, "greeting": persona_greeting.strip()}
        return profile

    def system_instruction(self, lang_code: str | None = None) -> str:
        profile = self.language_profile(lang_code)
        base = SYSTEM_INSTRUCTION_TEMPLATE.format(
            persona_block=PERSONA_BLOCK,
            language_display=profile["display"],
        )
        return f"{base}\n\n{_ESCALATION_PROMPT}"


# Singleton – imported everywhere
settings = Settings()


def build_instruction(lang_code: str | None = None) -> str:
    """Compose the full system instruction for a given language.

    This is the ADK-compatible replacement for Settings.system_instruction().
    Can be used as a plain function or as an ADK instruction provider.
    """
    return settings.system_instruction(lang_code)
