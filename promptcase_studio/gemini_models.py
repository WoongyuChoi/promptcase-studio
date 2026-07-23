from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class GeminiTextModel:
    model_id: str
    display_name: str
    profile: str
    input_token_limit: int = 1_048_576
    output_token_limit: int = 65_536

    @property
    def choice_label(self) -> str:
        return self.display_name


# Stable text-output models that support structured JSON and a 1M-token input
# window. Preview, image, audio, and deprecated model IDs are intentionally
# excluded from automatic fallback.
GEMINI_TEXT_MODELS = (
    GeminiTextModel("gemini-3.6-flash", "Gemini 3.6 Flash", "품질 우선"),
    GeminiTextModel("gemini-3.5-flash", "Gemini 3.5 Flash", "코드 분석"),
    GeminiTextModel("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "처리량 우선"),
    GeminiTextModel("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "호환 대체"),
)

DEFAULT_GEMINI_MODEL = GEMINI_TEXT_MODELS[0].model_id
AUTO_GEMINI_MODEL = "auto"
DEFAULT_GEMINI_FALLBACK_MODELS = tuple(model.model_id for model in GEMINI_TEXT_MODELS[1:])
LEGACY_GEMINI_MODEL_ALIASES = {
    "gemini-flash-latest": AUTO_GEMINI_MODEL,
}


def normalize_gemini_model_id(value: Any) -> str:
    model_id = str(value or "").strip()
    if not model_id:
        return AUTO_GEMINI_MODEL
    if model_id.casefold() == AUTO_GEMINI_MODEL:
        return AUTO_GEMINI_MODEL
    return LEGACY_GEMINI_MODEL_ALIASES.get(model_id, model_id)


def _model_values(values: Any) -> Iterable[Any]:
    if isinstance(values, str):
        return values.split(",")
    if isinstance(values, (list, tuple)):
        return values
    return ()


def gemini_model_sequence(primary: Any, fallback_models: Any) -> tuple[str, ...]:
    selected = normalize_gemini_model_id(primary)
    ordered = [DEFAULT_GEMINI_MODEL] if selected == AUTO_GEMINI_MODEL else [selected]
    ordered.extend(normalize_gemini_model_id(value) for value in _model_values(fallback_models))
    return tuple(dict.fromkeys(model for model in ordered if model))


def gemini_model_label(model_id: str) -> str:
    normalized = normalize_gemini_model_id(model_id)
    if normalized == AUTO_GEMINI_MODEL:
        return "Auto"
    for model in GEMINI_TEXT_MODELS:
        if model.model_id == normalized:
            return model.choice_label
    return normalized
