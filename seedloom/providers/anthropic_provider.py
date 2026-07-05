from __future__ import annotations

from typing import Any

from .base import Provider, ProviderError, call_with_rate_limit_retry

try:
    import anthropic
except ImportError as e:
    raise ProviderError(
        "The 'anthropic' package is required for the anthropic provider. "
        "Install with: pip install seedloom[anthropic]"
    ) from e


class AnthropicProvider(Provider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", max_tokens: int = 4096):
        if not api_key:
            raise ProviderError("An API key is required for the anthropic provider.")
        self.client = anthropic.Anthropic(api_key=api_key)
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
            lambda: self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[
                    {
                        "name": tool_name,
                        "description": "Submit the generated seed rows for this table.",
                        "input_schema": schema,
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
            )
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input.get("rows", [])

        raise ProviderError("Anthropic response did not include the expected tool_use block.")