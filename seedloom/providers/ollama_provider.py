from __future__ import annotations

import json
from typing import Any

from .base import Provider, ProviderError

try:
    import requests
except ImportError as e:
    raise ProviderError(
        "The 'requests' package is required for the ollama provider. "
        "Install with: pip install seedloom[ollama]"
    ) from e


class OllamaProvider(Provider):
    def __init__(self, model: str = "llama3.1", host: str = "http://localhost:11434", timeout: int = 120):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def generate(
        self,
        system: str,
        user_prompt: str,
        schema: dict[str, Any],
        tool_name: str = "generate_rows",
    ) -> list[dict[str, Any]]:
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "format": schema,
                    "stream": False,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise ProviderError(
                f"Could not reach Ollama at {self.host}. Is 'ollama serve' running? ({e})"
            ) from e

        if response.status_code != 200:
            raise ProviderError(f"Ollama request failed ({response.status_code}): {response.text}")

        content = response.json().get("message", {}).get("content", "")
        if not content:
            raise ProviderError("Ollama returned an empty response.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise ProviderError(f"Could not parse Ollama response as JSON: {e}") from e

        return parsed.get("rows", [])
