"""Environment-backed provider settings for the dashboard LLM router."""

import os
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from chat_backend import ChatProvider


def _enabled(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMSettings:
    groq_api_key: Optional[str]
    groq_base_url: str
    groq_models: Dict[str, str]
    local_enabled: bool
    local_api_key: str
    local_base_url: str
    local_model: str
    local_timeout_seconds: float
    provider_preferences: Dict[str, str]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None):
        env = environ if environ is not None else os.environ
        legacy_groq_model = env.get("GROQ_MODEL", "llama-3.1-8b-instant")
        return cls(
            groq_api_key=env.get("GROQ_API_KEY"),
            groq_base_url=env.get(
                "GROQ_BASE_URL",
                "https://api.groq.com/openai/v1",
            ),
            groq_models={
                "lookup": env.get("GROQ_LOOKUP_MODEL", legacy_groq_model),
                "analysis": env.get(
                    "GROQ_ANALYSIS_MODEL",
                    "llama-3.3-70b-versatile",
                ),
                "visualization": env.get(
                    "GROQ_VISUALIZATION_MODEL",
                    "openai/gpt-oss-20b",
                ),
            },
            local_enabled=_enabled(env.get("LOCAL_LLM_ENABLED")),
            local_api_key=env.get("LOCAL_LLM_API_KEY", "ollama"),
            local_base_url=env.get(
                "LOCAL_LLM_BASE_URL",
                "http://127.0.0.1:11434/v1",
            ),
            local_model=env.get("LOCAL_LLM_MODEL", "qwen3:8b"),
            local_timeout_seconds=float(
                env.get("LOCAL_LLM_TIMEOUT_SECONDS", "90")
            ),
            provider_preferences={
                "lookup": env.get("LLM_LOOKUP_PROVIDER", "groq"),
                "analysis": env.get("LLM_ANALYSIS_PROVIDER", "groq"),
                "visualization": env.get(
                    "LLM_VISUALIZATION_PROVIDER",
                    "local",
                ),
            },
        )

    def available_provider_names(self) -> tuple[str, ...]:
        providers = []
        if self.groq_api_key:
            providers.append("groq")
        if self.local_enabled and self.local_model:
            providers.append("local")
        return tuple(providers)

    def provider_order(self, selected_provider: str) -> tuple[str, ...]:
        """Try the routed provider first, then every configured alternative."""

        available = self.available_provider_names()
        ordered = []
        for provider in (selected_provider, *available):
            if provider in available and provider not in ordered:
                ordered.append(provider)
        return tuple(ordered)

    def build_provider(self, provider_name: str, intent: str) -> ChatProvider:
        if provider_name == "groq" and self.groq_api_key:
            return ChatProvider(
                name="groq",
                api_key=self.groq_api_key,
                base_url=self.groq_base_url,
                model=self.groq_models[intent],
            )
        if provider_name == "local" and self.local_enabled:
            return ChatProvider(
                name="local",
                api_key=self.local_api_key,
                base_url=self.local_base_url,
                model=self.local_model,
                timeout_seconds=self.local_timeout_seconds,
            )
        raise ValueError(f"LLM provider is not configured: {provider_name}")
