"""Configuration loading: env vars + optional .env file, no external deps."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .providers import NO_KEY_REQUIRED, SUPPORTED_PROVIDERS

_PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
}


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader - avoids pulling in python-dotenv as a dependency."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Config:
    database_url: str
    provider: str = "anthropic"
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    host: str = ""

    @classmethod
    def load(cls, provider_override: str = "", require_provider: bool = True) -> "Config":
        _load_dotenv()
        db_url = os.environ.get("DATABASE_URL", "")
        provider = (provider_override or os.environ.get("SEEDLOOM_PROVIDER", "anthropic")).lower()
        model = os.environ.get("SEEDLOOM_MODEL", "")
        base_url = os.environ.get("SEEDLOOM_BASE_URL", "")
        host = os.environ.get("SEEDLOOM_HOST", "")

        missing = []
        if not db_url:
            missing.append("DATABASE_URL")

        if provider not in SUPPORTED_PROVIDERS:
            raise EnvironmentError(
                f"Unknown provider '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}."
            )

        api_key = ""
        if require_provider and provider not in NO_KEY_REQUIRED:
            key_env = _PROVIDER_KEY_ENV.get(provider, f"{provider.upper()}_API_KEY")
            api_key = os.environ.get(key_env, "")
            if not api_key:
                missing.append(key_env)

        if missing:
            raise EnvironmentError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set them in your shell or in a .env file in the current directory."
            )

        return cls(
            database_url=db_url,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            host=host,
        )
