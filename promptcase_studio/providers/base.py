from __future__ import annotations

import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from promptcase_studio.models import ChunkCallback, LogCallback


class ProviderError(RuntimeError):
    pass


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
    @abstractmethod
    def generate(
        self,
        prompt: str,
        log: LogCallback | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        raise NotImplementedError
