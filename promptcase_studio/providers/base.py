from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from promptcase_studio.models import ChunkCallback, LogCallback


class ProviderError(RuntimeError):
    pass


class ProviderRateLimitError(ProviderError):
    """A structured 429 error that callers can handle without parsing text."""

    def __init__(
        self,
        provider_name: str,
        *,
        retry_after_seconds: float | None = None,
        daily_quota: bool = False,
        free_tier: bool = False,
        quota_value: str = "",
        model: str = "",
    ) -> None:
        self.provider_name = provider_name
        self.retry_after_seconds = retry_after_seconds
        self.daily_quota = daily_quota
        self.free_tier = free_tier
        self.quota_value = quota_value
        self.model = model

        tier = "무료 등급 " if free_tier else ""
        model_text = f" {model}" if model else ""
        if daily_quota:
            limit_text = (
                f"일일 요청 한도 {quota_value}건을"
                if quota_value
                else "일일 요청 한도를"
            )
            quota_help = (
                "Google AI Studio에서 사용량과 결제 등급을 확인하거나"
                if provider_name.casefold() == "gemini"
                else "서비스 관리자에게 사용량 한도를 확인하거나"
            )
            message = (
                f"{provider_name} {tier}모델{model_text}의 {limit_text} 모두 사용했습니다. "
                f"짧게 재시도해도 해결되지 않습니다. {quota_help} "
                "일일 한도가 갱신된 뒤 다시 시도해 주세요."
            )
        else:
            wait_text = (
                f" 서버 권장 대기시간은 {retry_after_seconds:g}초입니다."
                if retry_after_seconds is not None
                else ""
            )
            message = f"{provider_name} 요청 한도를 초과했습니다.{wait_text}"
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "rate_limit",
            "provider": self.provider_name,
            "dailyQuota": self.daily_quota,
            "freeTier": self.free_tier,
            "quotaValue": self.quota_value,
            "model": self.model,
            "retryAfterSeconds": self.retry_after_seconds,
            "message": str(self),
        }


PROMPT_SECTION_DELIMITER = "\n\n---\n\n"
MINIMAL_SYSTEM_INSTRUCTION = "응답은 요청된 JSON 객체 하나만 출력한다."


@dataclass(frozen=True)
class GenerationDiagnostics:
    """Non-sensitive metadata reported by a text-generation provider."""

    finish_reason: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


def split_prompt_sections(prompt: str) -> tuple[str, str]:
    """Split the composed prompt into provider-native system and user parts.

    Promptcase Studio joins its versioned system prompt and task with one
    explicit delimiter. Ad-hoc callers without that delimiter keep the full
    prompt as user content and receive only the minimal JSON system rule.
    """

    if PROMPT_SECTION_DELIMITER not in prompt:
        return MINIMAL_SYSTEM_INSTRUCTION, prompt
    system_prompt, user_prompt = prompt.split(PROMPT_SECTION_DELIMITER, 1)
    return system_prompt.strip() or MINIMAL_SYSTEM_INSTRUCTION, user_prompt.strip()


def token_count(value: Any) -> int | None:
    """Return a non-negative provider token count without accepting booleans."""

    if isinstance(value, bool) or value is None:
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def log_generation_diagnostics(
    provider_name: str,
    diagnostics: GenerationDiagnostics,
    log: LogCallback | None,
) -> None:
    if not log:
        return
    fields = [f"종료 사유 {diagnostics.finish_reason or '없음'}"]
    if diagnostics.prompt_tokens is not None:
        fields.append(f"입력 {diagnostics.prompt_tokens:,} 토큰")
    if diagnostics.completion_tokens is not None:
        fields.append(f"출력 {diagnostics.completion_tokens:,} 토큰")
    if diagnostics.total_tokens is not None:
        fields.append(f"합계 {diagnostics.total_tokens:,} 토큰")
    log("RESPONSE", f"{provider_name} " + ", ".join(fields))


RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _duration_seconds(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", value)
    if not match:
        return None
    return float(match.group(1))


def _retry_after_header_seconds(headers: Any) -> float | None:
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(str(value))
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _rate_limit_error(
    provider_name: str,
    detail: str,
    headers: Any,
) -> ProviderRateLimitError:
    retry_candidates = [_retry_after_header_seconds(headers)]
    quota_ids: list[str] = []
    quota_metrics: list[str] = []
    quota_value = ""
    model = ""
    message = detail
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        payload = {}
    error_payload = payload.get("error", payload) if isinstance(payload, dict) else {}
    if isinstance(error_payload, dict):
        message = str(error_payload.get("message", detail))
        details = error_payload.get("details", [])
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                retry_candidates.append(_duration_seconds(item.get("retryDelay")))
                violations = item.get("violations", [])
                if not isinstance(violations, list):
                    continue
                for violation in violations:
                    if not isinstance(violation, dict):
                        continue
                    quota_ids.append(str(violation.get("quotaId", "")))
                    quota_metrics.append(str(violation.get("quotaMetric", "")))
                    quota_value = quota_value or str(violation.get("quotaValue", ""))
                    dimensions = violation.get("quotaDimensions", {})
                    if isinstance(dimensions, dict):
                        model = model or str(dimensions.get("model", ""))

    message_retry = re.search(r"retry\s+in\s+(\d+(?:\.\d+)?)s", message, re.IGNORECASE)
    if message_retry:
        retry_candidates.append(float(message_retry.group(1)))
    retry_values = [value for value in retry_candidates if value is not None]
    retry_after = max(retry_values) if retry_values else None

    quota_text = " ".join([*quota_ids, *quota_metrics, message]).casefold()
    normalized_quota = re.sub(r"[^a-z0-9]+", "", quota_text)
    daily_quota = "perday" in normalized_quota or "daily" in normalized_quota
    free_tier = "freetier" in normalized_quota or "free tier" in quota_text
    return ProviderRateLimitError(
        provider_name,
        retry_after_seconds=retry_after,
        daily_quota=daily_quota,
        free_tier=free_tier,
        quota_value=quota_value,
        model=model,
    )


def open_with_retry(
    request: urllib.request.Request,
    timeout: int,
    provider_name: str,
    max_attempts: int,
    retry_delay_seconds: float,
    log: LogCallback | None = None,
) -> Any:
    attempts = max(1, min(int(max_attempts), 10))
    delay = max(0.0, float(retry_delay_seconds))
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                error = _rate_limit_error(provider_name, detail[:32768], exc.headers)
                retryable = not error.daily_quota
            else:
                error = ProviderError(f"{provider_name} HTTP {exc.code}: {detail[:1500]}")
                retryable = exc.code in RETRYABLE_HTTP_STATUS
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = ProviderError(f"{provider_name} 연결 실패: {exc}")
            retryable = True

        if not retryable or attempt >= attempts:
            raise error
        backoff_seconds = delay * (2 ** (attempt - 1))
        server_wait = (
            error.retry_after_seconds
            if isinstance(error, ProviderRateLimitError)
            else None
        )
        wait_seconds = max(backoff_seconds, server_wait or 0.0)
        wait_seconds = min(wait_seconds, max(1.0, float(timeout)))
        if log:
            reason = "요청 제한" if isinstance(error, ProviderRateLimitError) else "연결 오류"
            log(
                "RETRY",
                f"{provider_name} {reason} 재시도 {attempt + 1}/{attempts} - "
                f"{wait_seconds:g}초 후 재시도",
            )
        if wait_seconds:
            time.sleep(wait_seconds)

    raise ProviderError(f"{provider_name} 연결 재시도가 종료되었습니다.")


class TextGenerationProvider(ABC):
    last_diagnostics: GenerationDiagnostics | None = None

    @abstractmethod
    def generate(
        self,
        prompt: str,
        log: LogCallback | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        raise NotImplementedError
