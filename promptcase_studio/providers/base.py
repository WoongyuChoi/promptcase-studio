from __future__ import annotations

import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from promptcase_studio.models import ChunkCallback, LogCallback


class ProviderError(RuntimeError):
    pass


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
            detail = exc.read().decode("utf-8", errors="replace")[:1500]
            error = ProviderError(f"{provider_name} HTTP {exc.code}: {detail}")
            retryable = exc.code in RETRYABLE_HTTP_STATUS
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = ProviderError(f"{provider_name} 연결 실패: {exc}")
            retryable = True

        if not retryable or attempt >= attempts:
            raise error
        wait_seconds = delay * attempt
        if log:
            log(
                "RETRY",
                f"{provider_name} 연결 재시도 {attempt + 1}/{attempts} - {wait_seconds:g}초 후 재시도",
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
