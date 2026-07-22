from __future__ import annotations

from pathlib import Path
from typing import Any

from promptcase_studio.config import get_secret, resolve_project_path
from promptcase_studio.providers.base import TextGenerationProvider
from promptcase_studio.providers.gemini import GeminiProvider
from promptcase_studio.providers.mock import MockProvider
from promptcase_studio.providers.qwen import QwenProvider


def create_provider(settings: dict[str, Any], environment: str) -> TextGenerationProvider:
    if settings.get("mockMode"):
        return MockProvider()
    provider_config = settings.get("providers", {}).get(environment, {})
    provider_type = provider_config.get("type")
    if provider_type == "gemini":
        key_name = str(provider_config.get("apiKeyEnv", "GEMINI_API_KEY"))
        return GeminiProvider(provider_config, get_secret(key_name))
    if provider_type == "qwen":
        settings_path = resolve_project_path(str(provider_config.get("settingsPath", "")))
        return QwenProvider(provider_config, settings_path)
    raise ValueError(f"지원하지 않는 provider type: {provider_type}")

