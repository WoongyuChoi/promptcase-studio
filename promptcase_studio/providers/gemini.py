from __future__ import annotations

import json
import urllib.request
from typing import Any

from promptcase_studio.models import ChunkCallback, LogCallback
from promptcase_studio.providers.base import (
    GenerationDiagnostics,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    TextGenerationProvider,
    log_generation_diagnostics,
    open_with_retry,
    split_prompt_sections,
    token_count,
)
from promptcase_studio.gemini_models import (
    AUTO_GEMINI_MODEL,
    DEFAULT_GEMINI_FALLBACK_MODELS,
    DEFAULT_GEMINI_MODEL,
    gemini_model_sequence,
    normalize_gemini_model_id,
)


class GeminiProvider(TextGenerationProvider):
    def __init__(self, config: dict[str, Any], api_key: str):
        self.api_base = str(config.get("apiBase", "")).rstrip("/")
        selected_model = normalize_gemini_model_id(config.get("model", AUTO_GEMINI_MODEL))
        legacy_auto = config.get("fallbackOnDailyQuota") is True
        self.auto_model_selection = selected_model == AUTO_GEMINI_MODEL or legacy_auto
        if self.auto_model_selection:
            self.models = gemini_model_sequence(
                selected_model,
                config.get("fallbackModels", DEFAULT_GEMINI_FALLBACK_MODELS),
            )
        else:
            self.models = (selected_model,)
        self.model = self.models[0] if self.models else DEFAULT_GEMINI_MODEL
        self.auto_fallback_enabled = self.auto_model_selection
        self._active_model_index = 0
        self._failed_models: set[str] = set()
        self.timeout = int(config.get("timeoutSeconds", 300))
        self.max_attempts = int(config.get("maxAttempts", 3))
        self.retry_delay_seconds = float(config.get("retryDelaySeconds", 2))
        self.max_output_tokens = int(config.get("maxOutputTokens", 0) or 0)
        self.api_key = api_key
        self.last_diagnostics: GenerationDiagnostics | None = None

    @staticmethod
    def extract_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = payload.get("promptFeedback") or payload
            raise ProviderError(f"Gemini 응답에 candidate가 없습니다: {feedback}")
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text.strip():
            raise ProviderError("Gemini 응답에 텍스트가 없습니다.")
        return text

    @staticmethod
    def response_diagnostics(payload: dict[str, Any]) -> GenerationDiagnostics:
        candidates = payload.get("candidates")
        primary = candidates[0] if isinstance(candidates, list) and candidates else {}
        finish_reason = str(primary.get("finishReason", "")).strip()
        if not finish_reason:
            feedback = payload.get("promptFeedback")
            if isinstance(feedback, dict):
                finish_reason = str(feedback.get("blockReason", "")).strip()
        usage = payload.get("usageMetadata")
        if not isinstance(usage, dict):
            usage = {}
        return GenerationDiagnostics(
            finish_reason=finish_reason or "MISSING",
            prompt_tokens=token_count(usage.get("promptTokenCount")),
            completion_tokens=token_count(usage.get("candidatesTokenCount")),
            total_tokens=token_count(usage.get("totalTokenCount")),
        )

    @staticmethod
    def _raise_for_finish_reason(diagnostics: GenerationDiagnostics) -> None:
        reason = diagnostics.finish_reason.upper()
        if reason == "STOP":
            return
        if reason == "MAX_TOKENS":
            raise ProviderError(
                "Gemini 응답이 출력 토큰 한도 MAX_TOKENS에 도달하여 잘렸습니다. "
                "maxOutputTokens 설정을 늘린 뒤 다시 시도해 주세요."
            )
        if reason in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
            raise ProviderError(f"Gemini 응답이 안전 정책에 의해 종료되었습니다: {reason}")
        raise ProviderError(f"Gemini 응답이 정상 종료되지 않았습니다: {reason}")

    def generate(
        self,
        prompt: str,
        log: LogCallback | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        self.last_diagnostics = None
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY가 없습니다. 환경설정 또는 .env를 확인해 주세요.")
        last_fallback_error: ProviderError | None = None
        for model_index in range(self._active_model_index, len(self.models)):
            model = self.models[model_index]
            if model in self._failed_models:
                continue
            try:
                result = self._generate_with_model(model, prompt, log, on_chunk)
            except (ProviderRateLimitError, ProviderUnavailableError) as exc:
                if not self.auto_fallback_enabled:
                    raise
                self._failed_models.add(model)
                last_fallback_error = exc
                next_model = next(
                    (
                        candidate
                        for candidate in self.models[model_index + 1 :]
                        if candidate not in self._failed_models
                    ),
                    None,
                )
                if not next_model:
                    break
                if isinstance(exc, ProviderUnavailableError):
                    if log:
                        log(
                            "FALLBACK",
                            f"Gemini {model} 서버 과부하 또는 일시 장애, "
                            f"다음 대체 모델 {next_model}로 전환",
                        )
                    continue
                if log:
                    reason = "일일 한도 소진" if exc.daily_quota else "요청 한도 재시도 소진"
                    log(
                        "FALLBACK",
                        f"Gemini {model} {reason}, 다음 안정 모델 {next_model}로 전환",
                    )
                continue
            self._active_model_index = model_index
            self.model = model
            return result

        if last_fallback_error is not None:
            if isinstance(last_fallback_error, ProviderUnavailableError):
                if log:
                    exhausted = ", ".join(self._failed_models)
                    log(
                        "WARN",
                        f"Gemini 자동 대체 모델을 모두 시도했지만 일시 장애가 "
                        f"계속되었습니다: {exhausted}",
                    )
                raise last_fallback_error
            if log:
                exhausted = ", ".join(self._failed_models)
                log("QUOTA", f"Gemini 자동 대체 모델의 요청 한도까지 소진됨: {exhausted}")
            raise last_fallback_error
        raise ProviderError("사용 가능한 Gemini 텍스트 출력 모델이 없습니다.")

    def _generate_with_model(
        self,
        model: str,
        prompt: str,
        log: LogCallback | None,
        on_chunk: ChunkCallback | None,
    ) -> str:
        url = f"{self.api_base}/models/{model}:generateContent"
        system_prompt, user_prompt = split_prompt_sections(prompt)
        generation_config: dict[str, Any] = {
            "responseMimeType": "application/json",
        }
        if self.max_output_tokens > 0:
            generation_config["maxOutputTokens"] = self.max_output_tokens
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": generation_config,
        }
        if log:
            log("API", f"Gemini {model}에 {len(prompt):,}자 프롬프트 전송")
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-goog-api-key": self.api_key,
                "User-Agent": "PromptcaseStudio/0.1",
            },
            method="POST",
        )
        response = open_with_retry(
            request,
            self.timeout,
            "Gemini",
            self.max_attempts,
            self.retry_delay_seconds,
            log,
        )
        try:
            with response:
                raw = response.read().decode("utf-8")
        except (TimeoutError, OSError) as exc:
            raise ProviderError(f"Gemini 응답 수신 중 연결이 중단되었습니다: {exc}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Gemini JSON 응답 파싱 실패: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Gemini JSON 응답의 최상위 값은 객체여야 합니다.")
        diagnostics = self.response_diagnostics(payload)
        self.last_diagnostics = diagnostics
        log_generation_diagnostics("Gemini", diagnostics, log)
        self._raise_for_finish_reason(diagnostics)
        text = self.extract_text(payload)
        if on_chunk:
            on_chunk(text)
        if log:
            log("RESPONSE", f"Gemini 응답 {len(text):,}자 수신")
        return text
