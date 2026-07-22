from __future__ import annotations

import json
import urllib.request
from typing import Any

from promptcase_studio.models import ChunkCallback, LogCallback
from promptcase_studio.providers.base import ProviderError, TextGenerationProvider, open_with_retry


class GeminiProvider(TextGenerationProvider):
    def __init__(self, config: dict[str, Any], api_key: str):
        self.api_base = str(config.get("apiBase", "")).rstrip("/")
        self.model = str(config.get("model", "gemini-flash-latest"))
        self.timeout = int(config.get("timeoutSeconds", 300))
        self.max_attempts = int(config.get("maxAttempts", 3))
        self.retry_delay_seconds = float(config.get("retryDelaySeconds", 2))
        self.api_key = api_key

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

    def generate(
        self,
        prompt: str,
        log: LogCallback | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY가 없습니다. 환경설정 또는 .env를 확인해 주세요.")
        url = f"{self.api_base}/models/{self.model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        if log:
            log("API", f"Gemini {self.model}에 {len(prompt):,}자 프롬프트 전송")
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
            text = self.extract_text(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Gemini JSON 응답 파싱 실패: {exc}") from exc
        if on_chunk:
            on_chunk(text)
        if log:
            log("RESPONSE", f"Gemini 응답 {len(text):,}자 수신")
        return text
