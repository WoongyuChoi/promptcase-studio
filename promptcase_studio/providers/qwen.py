from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from promptcase_studio.config import read_dotenv
from promptcase_studio.models import ChunkCallback, LogCallback
from promptcase_studio.providers.base import ProviderError, TextGenerationProvider, open_with_retry


def load_qwen_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProviderError(f"Qwen settings.json을 찾을 수 없습니다: {path}")
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    provider_type = settings.get("security", {}).get("auth", {}).get("selectedType", "openai")
    model_name = settings.get("model", {}).get("name", "")
    entries = settings.get("modelProviders", {}).get(provider_type, [])
    if not isinstance(entries, list) or not entries:
        raise ProviderError(f"Qwen provider 설정이 없습니다: {provider_type}")
    selected = next(
        (item for item in entries if item.get("name") == model_name or item.get("id") == model_name),
        entries[0],
    )
    generation_config = selected.get("generationConfig", {})
    if not isinstance(generation_config, dict):
        generation_config = {}
    env_key = str(selected.get("envKey", ""))
    api_key = os.environ.get(env_key, "") or read_dotenv().get(env_key, "")
    if not api_key:
        api_key = str(settings.get("env", {}).get(env_key, "")).strip().strip('"')
    return {
        "baseUrl": str(selected.get("baseUrl", "")).rstrip("/"),
        "model": str(selected.get("id") or selected.get("name") or model_name),
        "apiKey": api_key,
        "generationConfig": generation_config,
        "timeoutMilliseconds": generation_config.get("timeout"),
    }


class QwenProvider(TextGenerationProvider):
    def __init__(self, config: dict[str, Any], settings_path: Path):
        self.config = config
        self.profile = load_qwen_profile(settings_path)
        profile_timeout = self.profile.get("timeoutMilliseconds")
        fallback_timeout = max(1, int(float(profile_timeout) / 1000)) if profile_timeout else 300
        self.timeout = int(config.get("timeoutSeconds", fallback_timeout))
        self.max_attempts = int(config.get("maxAttempts", 3))
        self.retry_delay_seconds = float(config.get("retryDelaySeconds", 2))
        self.stream = bool(config.get("stream", True))

    def _body(self, prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.profile["model"],
            "messages": [
                {"role": "system", "content": "응답은 요청된 JSON 객체 하나만 출력한다."},
                {"role": "user", "content": prompt},
            ],
            "stream": self.stream,
        }
        generation = self.profile.get("generationConfig") or {}
        sampling = generation.get("samplingParams") if isinstance(generation, dict) else None
        if isinstance(sampling, dict):
            for key in ("temperature", "top_p", "max_tokens", "max_completion_tokens"):
                if key in sampling:
                    body[key] = sampling[key]
        if self.stream:
            body["stream_options"] = {"include_usage": True}
        return body

    def generate(
        self,
        prompt: str,
        log: LogCallback | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        base_url = self.profile["baseUrl"]
        if not base_url:
            raise ProviderError("Qwen baseUrl이 비어 있습니다.")
        endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "PromptcaseStudio/0.1"}
        if self.profile.get("apiKey"):
            headers["Authorization"] = f"Bearer {self.profile['apiKey']}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(self._body(prompt), ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        if log:
            log("API", f"Qwen {self.profile['model']}에 {len(prompt):,}자 프롬프트 전송")
        response = open_with_retry(
            request,
            self.timeout,
            "Qwen",
            self.max_attempts,
            self.retry_delay_seconds,
            log,
        )
        try:
            with response:
                if self.stream or "text/event-stream" in response.headers.get("Content-Type", ""):
                    text = self._read_stream(response, on_chunk)
                else:
                    payload = json.loads(response.read().decode("utf-8"))
                    text = self._read_json(payload)
                    if on_chunk:
                        on_chunk(text)
        except (TimeoutError, OSError) as exc:
            raise ProviderError(f"Qwen 응답 수신 중 연결이 중단되었습니다: {exc}") from exc
        if not text.strip():
            raise ProviderError("Qwen 응답이 비어 있습니다.")
        if log:
            log("RESPONSE", f"Qwen 응답 {len(text):,}자 수신")
        return text

    @staticmethod
    def _read_json(payload: dict[str, Any]) -> str:
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Qwen JSON 응답 형식 오류: {payload}") from exc

    @staticmethod
    def _read_stream(response: Any, on_chunk: ChunkCallback | None) -> str:
        chunks: list[str] = []
        terminal_seen = False
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                terminal_seen = True
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Qwen SSE JSON 파싱 실패: {exc}") from exc
            choices = payload.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta", {}).get("content", "")
            if delta:
                chunks.append(delta)
                if on_chunk:
                    on_chunk(delta)
            if choice.get("finish_reason"):
                terminal_seen = True
        if not terminal_seen:
            raise ProviderError("Qwen SSE 응답이 정상 종료되지 않았습니다.")
        return "".join(chunks)
