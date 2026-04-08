"""
Central configuration – loaded once at startup from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROMPTS_DIR = Path(__file__).parent / "prompts"


# ---------------------------------------------------------------------------
# Language profiles
# ---------------------------------------------------------------------------

LANGUAGE_PROFILES: dict[str, dict] = {
    "de-CH": {
        "display": "Swiss German",
        "voice_name": "Leda",
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

    def validate(self, *, require_twilio: bool = True) -> None:
        """Call on startup to fail early with a clear message if config is missing."""
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
        return LANGUAGE_PROFILES.get(code, LANGUAGE_PROFILES[self.default_language])

    def system_instruction(self, lang_code: str | None = None) -> str:
        profile = self.language_profile(lang_code)
        base = SYSTEM_INSTRUCTION_TEMPLATE.format(language_display=profile["display"])
        return f"{base}\n\n{_ESCALATION_PROMPT}"


# Singleton – imported everywhere
settings = Settings()


def build_instruction(lang_code: str | None = None) -> str:
    """Compose the full system instruction for a given language.

    This is the ADK-compatible replacement for Settings.system_instruction().
    Can be used as a plain function or as an ADK instruction provider.
    """
    return settings.system_instruction(lang_code)
