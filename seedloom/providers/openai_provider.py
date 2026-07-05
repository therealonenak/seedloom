from __future__ import annotations

import json
from typing import Any

from .base import Provider, ProviderError, call_with_rate_limit_retry

try:
    from openai import OpenAI
except ImportError as e:
    raise ProviderError(
        "The 'openai' package is required for this provider. "
        "Install with: pip install seedloom[openai]"
    ) from e


class OpenAIProvider(Provider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_tokens: int = 4096,
    ):
        if not api_key and not base_url:
            raise ProviderError("An API key is required for this provider.")
        self.client = OpenAI(api_key=api_key or "not-needed", base_url=base_url)
        self.model = model
        self.max_tokens = max_tokens

    def generate(
        self,
        system: str,
        user_prompt: str,
        schema: dict[str, Any],
        tool_name: str = "generate_rows",
    ) -> list[dict[str, Any]]:
        response = call_with_rate_limit_retry(
            lambda: self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": "Submit the generated seed rows for this table.",
                            "parameters": schema,
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
        )

        message = response.choices[0].message
        if not message.tool_calls:
            raise ProviderError("Response did not include the expected tool call.")

        arguments = message.tool_calls[0].function.arguments
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as e:
            raise ProviderError(f"Could not parse tool call arguments as JSON: {e}") from e

        return parsed.get("rows", [])