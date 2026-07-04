"""Configuration loading: env vars + optional .env file, no external deps."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader — avoids pulling in python-dotenv as a dependency."""
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
    anthropic_api_key: str
    model: str = "claude-sonnet-4-6"

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv()
        db_url = os.environ.get("DATABASE_URL", "")
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = os.environ.get("SEEDAGENT_MODEL", "claude-sonnet-4-6")

        missing = []
        if not db_url:
            missing.append("DATABASE_URL")
        if not api_key:
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set them in your shell or in a .env file in the current directory."
            )
        return cls(database_url=db_url, anthropic_api_key=api_key, model=model)
