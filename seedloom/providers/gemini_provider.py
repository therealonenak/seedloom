from __future__ import annotations

import json
from typing import Any

from .base import Provider, ProviderError, call_with_rate_limit_retry

try:
    from google import genai
    from google.genai import types
except ImportError as e:
    raise ProviderError(
        "The 'google-genai' package is required for the gemini provider. "
        "Install with: pip install seedloom[gemini]"
    ) from e


def _simplify_schema(node: Any) -> Any:
    if isinstance(node, dict):
        cleaned = {
            k: _simplify_schema(v)
            for k, v in node.items()
            if k not in ("maxLength", "minItems", "maxItems", "format")
        }
        if "enum" in cleaned:
            cleaned["enum"] = [str(v) for v in cleaned["enum"]]
            cleaned.setdefault("type", "string")
        return cleaned
    if isinstance(node, list):
        return [_simplify_schema(v) for v in node]
    return node


class GeminiProvider(Provider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        if not api_key:
            raise ProviderError("An API key is required for the gemini provider.")
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate(
        self,
        system: str,
        user_prompt: str,
        schema: dict[str, Any],
        tool_name: str = "generate_rows",
    ) -> list[dict[str, Any]]:
        safe_schema = _simplify_schema(schema)
        response = call_with_rate_limit_retry(
            lambda: self.client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=safe_schema,
                ),
            )
        )

        if not response.text:
            raise ProviderError("Gemini returned an empty response.")

        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError as e:
            raise ProviderError(f"Could not parse Gemini response as JSON: {e}") from e

        return parsed.get("rows", [])