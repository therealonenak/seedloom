from __future__ import annotations

from .base import Provider, ProviderError

OPENAI_COMPATIBLE_HOSTS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "lmstudio": "http://localhost:1234/v1",
    "vllm": "http://localhost:8000/v1",
    "text_generation_webui": "http://localhost:5000/v1",
}

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
    "ollama": "llama3.1",
    "groq": "llama-3.3-70b-versatile",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
    "fireworks": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek": "deepseek-chat",
    "mistral": "open-mixtral-8x22b",
    "lmstudio": "local-model",
    "vllm": "local-model",
    "text_generation_webui": "local-model",
}

NO_KEY_REQUIRED = {"ollama", "lmstudio", "vllm", "text_generation_webui"}

SUPPORTED_PROVIDERS = sorted({"anthropic", "openai", "gemini", "ollama", "openai_compatible"} | set(OPENAI_COMPATIBLE_HOSTS))


def get_provider(
    name: str,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    host: str = "",
) -> Provider:
    name = name.lower()
    model = model or DEFAULT_MODELS.get(name, "")

    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key, model=model)

    if name == "gemini":
        from .gemini_provider import GeminiProvider

        return GeminiProvider(api_key=api_key, model=model)

    if name == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(model=model, host=host or "http://localhost:11434")

    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url or None)

    if name in OPENAI_COMPATIBLE_HOSTS:
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url or OPENAI_COMPATIBLE_HOSTS[name])

    if name == "openai_compatible":
        if not base_url:
            raise ProviderError("base_url is required for provider 'openai_compatible'.")
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)

    raise ProviderError(
        f"Unknown provider '{name}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}."
    )


__all__ = [
    "Provider",
    "ProviderError",
    "get_provider",
    "OPENAI_COMPATIBLE_HOSTS",
    "DEFAULT_MODELS",
    "NO_KEY_REQUIRED",
    "SUPPORTED_PROVIDERS",
]
