from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from promptcase_studio import __version__
from promptcase_studio.config import read_dotenv
from promptcase_studio.models import ChunkCallback, LogCallback
from promptcase_studio.providers.base import (
    GenerationDiagnostics,
    ProviderError,
    TextGenerationProvider,
    log_generation_diagnostics,
    open_with_retry,
    split_prompt_sections,
    token_count,
)


def select_qwen_provider_entry(
    entries: Any,
    model_name: object,
) -> dict[str, Any] | None:
    """Select the configured model provider, or the first valid entry."""

    if not isinstance(entries, list):
        return None
    candidates = [item for item in entries if isinstance(item, dict)]
    if not candidates:
        return None
    selected_model = str(model_name or "")
    return next(
        (
            item
            for item in candidates
            if item.get("name") == selected_model or item.get("id") == selected_model
        ),
        candidates[0],
    )


def load_qwen_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProviderError(f"Qwen settings.json을 찾을 수 없습니다: {path}")
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    provider_type = settings.get("security", {}).get("auth", {}).get("selectedType", "openai")
    model_name = settings.get("model", {}).get("name", "")
    entries = settings.get("modelProviders", {}).get(provider_type, [])
    if not isinstance(entries, list) or not entries:
        raise ProviderError(f"Qwen provider 설정이 없습니다: {provider_type}")
    selected = select_qwen_provider_entry(entries, model_name)
    if selected is None:
        raise ProviderError(f"Qwen provider 설정이 없습니다: {provider_type}")
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
        self.max_output_tokens = int(config.get("maxOutputTokens", 0) or 0)
        self.last_diagnostics: GenerationDiagnostics | None = None

    def _body(self, prompt: str) -> dict[str, Any]:
        system_prompt, user_prompt = split_prompt_sections(prompt)
        body: dict[str, Any] = {
            "model": self.profile["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": self.stream,
        }
        generation = self.profile.get("generationConfig") or {}
        sampling = generation.get("samplingParams") if isinstance(generation, dict) else None
        if sampling is not None and not isinstance(sampling, dict):
            raise ProviderError("Qwen generationConfig.samplingParams는 JSON 객체여야 합니다.")
        if isinstance(generation, dict):
            for token_key in ("max_tokens", "max_completion_tokens"):
                if token_key in generation:
                    body[token_key] = generation[token_key]
        if isinstance(sampling, dict):
            body.update(sampling)
        extra_body = generation.get("extra_body") if isinstance(generation, dict) else None
        if extra_body is not None and not isinstance(extra_body, dict):
            raise ProviderError("Qwen generationConfig.extra_body는 JSON 객체여야 합니다.")
        if isinstance(extra_body, dict):
            body.update(extra_body)
        if "max_tokens" in body and "max_completion_tokens" in body:
            raise ProviderError(
                "Qwen 요청에는 max_tokens와 max_completion_tokens 중 하나만 설정해야 합니다."
            )
        if (
            "max_tokens" not in body
            and "max_completion_tokens" not in body
            and getattr(self, "max_output_tokens", 0) > 0
        ):
            body["max_tokens"] = self.max_output_tokens
        if not isinstance(body.get("stream"), bool):
            raise ProviderError("Qwen 요청의 stream 값은 true 또는 false여야 합니다.")
        if body["stream"]:
            body.setdefault("stream_options", {"include_usage": True})
        else:
            body.pop("stream_options", None)
        return body

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"PromptcaseStudio/{__version__}",
        }
        if self.profile.get("apiKey"):
            headers["Authorization"] = f"Bearer {self.profile['apiKey']}"

        generation = self.profile.get("generationConfig") or {}
        custom_headers = generation.get("customHeaders") if isinstance(generation, dict) else None
        if custom_headers is not None and not isinstance(custom_headers, dict):
            raise ProviderError("Qwen generationConfig.customHeaders는 JSON 객체여야 합니다.")
        for name, value in (custom_headers or {}).items():
            header_name = str(name)
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header_name):
                raise ProviderError(f"Qwen customHeaders에 유효하지 않은 이름이 있습니다: {header_name}")
            if header_name.casefold() in {"content-length", "transfer-encoding"}:
                raise ProviderError(f"Qwen customHeaders에서 전송 관리 헤더를 지정할 수 없습니다: {header_name}")
            if value is None:
                continue
            if not isinstance(value, (str, int, float, bool)):
                raise ProviderError(f"Qwen customHeaders 값은 단일 값이어야 합니다: {header_name}")
            header_value = str(value)
            if "\r" in header_value or "\n" in header_value:
                raise ProviderError(f"Qwen customHeaders 값에 줄바꿈을 넣을 수 없습니다: {header_name}")
            for existing_name in list(headers):
                if existing_name.casefold() == header_name.casefold():
                    del headers[existing_name]
            headers[header_name] = header_value
        return headers

    def generate(
        self,
        prompt: str,
        log: LogCallback | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        self.last_diagnostics = None
        base_url = self.profile["baseUrl"]
        if not base_url:
            raise ProviderError("Qwen baseUrl이 비어 있습니다.")
        endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(self._body(prompt), ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
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
                content_type = response.headers.get("Content-Type", "").casefold()
                if "text/event-stream" in content_type:
                    text, diagnostics = self._parse_stream(response, on_chunk)
                else:
                    payload = json.loads(response.read().decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ProviderError("Qwen JSON 응답의 최상위 값은 객체여야 합니다.")
                    text, diagnostics = self._parse_json(payload)
            self.last_diagnostics = diagnostics
            log_generation_diagnostics("Qwen", diagnostics, log)
            self._raise_for_finish_reason(diagnostics)
            if "text/event-stream" not in content_type and on_chunk:
                on_chunk(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Qwen JSON 응답 파싱 실패: {exc}") from exc
        except (TimeoutError, OSError) as exc:
            raise ProviderError(f"Qwen 응답 수신 중 연결이 중단되었습니다: {exc}") from exc
        if not text.strip():
            raise ProviderError("Qwen 응답이 비어 있습니다.")
        if log:
            log("RESPONSE", f"Qwen 응답 {len(text):,}자 수신")
        return text

    @staticmethod
    def _diagnostics(finish_reason: Any, usage: Any) -> GenerationDiagnostics:
        usage_payload = usage if isinstance(usage, dict) else {}
        return GenerationDiagnostics(
            finish_reason=str(finish_reason or "MISSING").strip(),
            prompt_tokens=token_count(
                usage_payload.get("prompt_tokens", usage_payload.get("input_tokens"))
            ),
            completion_tokens=token_count(
                usage_payload.get("completion_tokens", usage_payload.get("output_tokens"))
            ),
            total_tokens=token_count(usage_payload.get("total_tokens")),
        )

    @staticmethod
    def _raise_for_finish_reason(diagnostics: GenerationDiagnostics) -> None:
        reason = diagnostics.finish_reason.casefold()
        if reason == "stop":
            return
        if reason == "length":
            raise ProviderError(
                "Qwen 응답이 출력 토큰 한도 length에 도달하여 잘렸습니다. "
                "maxOutputTokens 설정을 늘린 뒤 다시 시도해 주세요."
            )
        if reason in {"content_filter", "safety"}:
            raise ProviderError(f"Qwen 응답이 안전 정책에 의해 종료되었습니다: {diagnostics.finish_reason}")
        raise ProviderError(f"Qwen 응답이 정상 종료되지 않았습니다: {diagnostics.finish_reason}")

    @staticmethod
    def _primary_choice(choices: Any) -> dict[str, Any]:
        if not isinstance(choices, list):
            raise ProviderError("Qwen 응답 choices는 배열이어야 합니다.")
        primary = next(
            (
                choice
                for choice in choices
                if isinstance(choice, dict) and choice.get("index") == 0
            ),
            None,
        )
        if primary is None:
            primary = next(
                (
                    choice
                    for choice in choices
                    if isinstance(choice, dict) and "index" not in choice
                ),
                None,
            )
        if primary is None:
            raise ProviderError("Qwen 응답에 primary choice index 0이 없습니다.")
        return primary

    @classmethod
    def _parse_json(cls, payload: dict[str, Any]) -> tuple[str, GenerationDiagnostics]:
        try:
            primary = cls._primary_choice(payload["choices"])
            message = primary.get("message") or {}
            if not isinstance(message, dict):
                raise TypeError("choice message is not an object")
            content = message.get("content", "")
            if not isinstance(content, str):
                raise TypeError("choice content is not text")
            diagnostics = cls._diagnostics(primary.get("finish_reason"), payload.get("usage"))
            return content, diagnostics
        except (KeyError, TypeError) as exc:
            raise ProviderError(f"Qwen JSON 응답 형식 오류: {payload}") from exc

    @classmethod
    def _read_json(cls, payload: dict[str, Any]) -> str:
        text, diagnostics = cls._parse_json(payload)
        cls._raise_for_finish_reason(diagnostics)
        return text

    @classmethod
    def _parse_stream(
        cls,
        response: Any,
        on_chunk: ChunkCallback | None,
    ) -> tuple[str, GenerationDiagnostics]:
        chunks: list[str] = []
        finish_reason = ""
        usage: dict[str, Any] = {}
        done_seen = False
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done_seen = True
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Qwen SSE JSON 파싱 실패: {exc}") from exc
            if not isinstance(payload, dict):
                raise ProviderError("Qwen SSE 이벤트는 JSON 객체여야 합니다.")
            if isinstance(payload.get("usage"), dict):
                usage = payload["usage"]
            choices = payload.get("choices", [])
            if not choices:
                continue
            if not isinstance(choices, list):
                raise ProviderError("Qwen SSE choices는 배열이어야 합니다.")
            try:
                choice = cls._primary_choice(choices)
            except ProviderError:
                continue
            delta_object = choice.get("delta") or {}
            if not isinstance(delta_object, dict):
                raise ProviderError("Qwen SSE delta는 JSON 객체여야 합니다.")
            delta = delta_object.get("content", "")
            if delta:
                if not isinstance(delta, str):
                    raise ProviderError("Qwen SSE 응답 content가 문자열이 아닙니다.")
                chunks.append(delta)
                if on_chunk:
                    on_chunk(delta)
            reason = choice.get("finish_reason")
            if reason:
                finish_reason = str(reason)
        if not done_seen and not finish_reason:
            raise ProviderError("Qwen SSE 응답이 정상 종료되지 않았습니다.")
        return "".join(chunks), cls._diagnostics(finish_reason, usage)

    @classmethod
    def _read_stream(cls, response: Any, on_chunk: ChunkCallback | None) -> str:
        text, diagnostics = cls._parse_stream(response, on_chunk)
        cls._raise_for_finish_reason(diagnostics)
        return text
