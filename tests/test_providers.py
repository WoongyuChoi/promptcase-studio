import io
import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from promptcase_studio.providers.base import (
    ProviderError,
    ProviderRateLimitError,
    open_with_retry,
    split_prompt_sections,
)
from promptcase_studio.providers.gemini import GeminiProvider
from promptcase_studio.gemini_models import (
    gemini_model_sequence,
    normalize_gemini_model_id,
)
from promptcase_studio.providers.qwen import QwenProvider, load_qwen_profile
from promptcase_studio.response_parser import parse_structured_response
from tests.test_response_parser import valid_payload


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FakeStream:
    def __iter__(self):
        return iter(
            [
                b'data: {"choices":[{"delta":{"content":"{\\"ok\\":"},"finish_reason":null}]}\n',
                b'data: {"choices":[{"delta":{"content":"true}"},"finish_reason":"stop"}]}\n',
                b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":5,"total_tokens":17}}\n',
                b'data: [DONE]\n',
            ]
        )


class FinishReasonThenUsageStream:
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"done"},"finish_reason":"stop"}]}\n'
        yield b'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":2,"total_tokens":9}}\n'
        yield b'data: [DONE]\n'


class InterleavedChoiceStream:
    def __iter__(self):
        return iter(
            [
                b'data: {"choices":[{"index":1,"delta":{"content":"WRONG"},"finish_reason":"stop"}]}\n',
                b'data: {"choices":[{"index":0,"delta":{"content":"RIGHT"},"finish_reason":"stop"}]}\n',
                b'data: [DONE]\n',
            ]
        )


class ReadTimeoutResponse:
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        raise TimeoutError("response read timeout")


class JsonResponse:
    headers = {"Content-Type": "application/json; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return (
            b'{"choices":[{"index":0,"message":{"content":"{\\"ok\\":true}"},'
            b'"finish_reason":"stop"}],"usage":{"prompt_tokens":3,'
            b'"completion_tokens":4,"total_tokens":7}}'
        )


class StaticResponse:
    def __init__(self, payload, content_type="application/json; charset=utf-8", lines=None):
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload

    def __iter__(self):
        return iter(self.lines)


class ProviderParsingTests(unittest.TestCase):
    def test_extracts_gemini_text(self):
        text = GeminiProvider.extract_text(
            {"candidates": [{"content": {"parts": [{"text": "{\"ok\":true}"}]}}]}
        )
        self.assertEqual(text, '{"ok":true}')

    def test_rejects_empty_gemini_candidate(self):
        with self.assertRaises(ProviderError):
            GeminiProvider.extract_text({"candidates": []})

    def test_reads_qwen_sse_chunks(self):
        chunks = []
        text = QwenProvider._read_stream(FakeStream(), chunks.append)
        self.assertEqual(text, '{"ok":true}')
        self.assertEqual("".join(chunks), text)

    def test_qwen_sse_reads_usage_after_finish_reason_until_done(self):
        text, diagnostics = QwenProvider._parse_stream(FinishReasonThenUsageStream(), None)
        self.assertEqual(text, "done")
        self.assertEqual(diagnostics.finish_reason, "stop")
        self.assertEqual(diagnostics.prompt_tokens, 7)
        self.assertEqual(diagnostics.completion_tokens, 2)
        self.assertEqual(diagnostics.total_tokens, 9)

    def test_qwen_reads_only_primary_choice_index_zero(self):
        self.assertEqual(QwenProvider._read_stream(InterleavedChoiceStream(), None), "RIGHT")
        self.assertEqual(
            QwenProvider._read_json(
                {
                    "choices": [
                        {"index": 1, "message": {"content": "WRONG"}},
                        {
                            "index": 0,
                            "message": {"content": "RIGHT"},
                            "finish_reason": "stop",
                        },
                    ]
                }
            ),
            "RIGHT",
        )

    def test_qwen_applies_full_generation_config_to_headers_and_body(self):
        provider = QwenProvider.__new__(QwenProvider)
        provider.stream = True
        provider.profile = {
            "model": "fixture-model",
            "apiKey": "fixture-key",
            "generationConfig": {
                "customHeaders": {
                    "user-agent": "FixtureAgent/1.0",
                    "X-Trace-Mode": "qa",
                },
                "samplingParams": {
                    "temperature": 0.2,
                    "stop": ["STOP_ONE", "STOP_TWO"],
                },
                "extra_body": {
                    "temperature": 0.1,
                    "top_k": 40,
                    "stream": False,
                },
            },
        }

        body = provider._body("fixture prompt")
        headers = provider._headers()

        self.assertEqual(body["temperature"], 0.1)
        self.assertEqual(body["stop"], ["STOP_ONE", "STOP_TWO"])
        self.assertEqual(body["top_k"], 40)
        self.assertFalse(body["stream"])
        self.assertNotIn("stream_options", body)
        self.assertNotIn("User-Agent", headers)
        self.assertEqual(headers["user-agent"], "FixtureAgent/1.0")
        self.assertEqual(headers["X-Trace-Mode"], "qa")
        self.assertEqual(headers["Authorization"], "Bearer fixture-key")

    def test_qwen_applies_configured_output_budget_only_when_profile_has_none(self):
        provider = QwenProvider.__new__(QwenProvider)
        provider.stream = False
        provider.max_output_tokens = 16384
        provider.profile = {
            "model": "fixture-model",
            "generationConfig": {"samplingParams": {"temperature": 0.1}},
        }
        self.assertEqual(provider._body("fixture prompt")["max_tokens"], 16384)

        provider.profile["generationConfig"]["samplingParams"]["max_completion_tokens"] = 8192
        body = provider._body("fixture prompt")
        self.assertEqual(body["max_completion_tokens"], 8192)
        self.assertNotIn("max_tokens", body)

        provider.profile["generationConfig"] = {"max_tokens": 4096}
        body = provider._body("fixture prompt")
        self.assertEqual(body["max_tokens"], 4096)
        self.assertNotIn("max_completion_tokens", body)

    def test_qwen_rejects_unsafe_custom_header(self):
        provider = QwenProvider.__new__(QwenProvider)
        provider.profile = {
            "apiKey": "",
            "generationConfig": {"customHeaders": {"X-Trace": "value\r\ninjected: yes"}},
        }
        with self.assertRaisesRegex(ProviderError, "줄바꿈"):
            provider._headers()

    def test_gemini_and_qwen_json_envelopes_share_the_same_output_contract(self):
        response_text = json.dumps(valid_payload(), ensure_ascii=False)
        gemini_text = GeminiProvider.extract_text(
            {"candidates": [{"content": {"parts": [{"text": response_text}]}}]}
        )
        qwen_text = QwenProvider._read_json(
            {
                "choices": [
                    {"message": {"content": response_text}, "finish_reason": "stop"}
                ]
            }
        )

        self.assertEqual(
            parse_structured_response(gemini_text),
            parse_structured_response(qwen_text),
        )

    def test_prompt_split_uses_minimal_system_rule_without_delimiter(self):
        system_prompt, user_prompt = split_prompt_sections("plain fixture prompt")
        self.assertEqual(system_prompt, "응답은 요청된 JSON 객체 하나만 출력한다.")
        self.assertEqual(user_prompt, "plain fixture prompt")

    def test_gemini_model_catalog_normalizes_latest_alias_and_deduplicates(self):
        self.assertEqual(normalize_gemini_model_id("gemini-flash-latest"), "auto")
        self.assertEqual(
            gemini_model_sequence(
                "gemini-flash-latest",
                ["gemini-3.5-flash-lite", "gemini-3.5-flash-lite"],
            ),
            ("gemini-3.6-flash", "gemini-3.5-flash-lite"),
        )

    @patch("promptcase_studio.providers.gemini.open_with_retry")
    def test_gemini_daily_quota_falls_back_and_reuses_successful_model(self, open_retry):
        response_payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "{\"ok\":true}"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        open_retry.side_effect = [
            ProviderRateLimitError(
                "Gemini",
                daily_quota=True,
                free_tier=True,
                quota_value="20",
                model="gemini-3.6-flash",
            ),
            StaticResponse(response_payload),
            StaticResponse(response_payload),
        ]
        provider = GeminiProvider(
            {
                "apiBase": "https://example.invalid",
                "model": "gemini-3.6-flash",
                "fallbackOnDailyQuota": True,
                "fallbackModels": ["gemini-3.5-flash-lite"],
            },
            "fixture-key",
        )
        logs = []

        self.assertEqual(
            provider.generate("first", log=lambda level, message: logs.append((level, message))),
            '{"ok":true}',
        )
        self.assertEqual(provider.generate("second"), '{"ok":true}')

        requested_urls = [call.args[0].full_url for call in open_retry.call_args_list]
        self.assertIn("gemini-3.6-flash:generateContent", requested_urls[0])
        self.assertIn("gemini-3.5-flash-lite:generateContent", requested_urls[1])
        self.assertIn("gemini-3.5-flash-lite:generateContent", requested_urls[2])
        self.assertEqual(provider.model, "gemini-3.5-flash-lite")
        self.assertTrue(any(level == "FALLBACK" for level, _message in logs))

    @patch("promptcase_studio.providers.gemini.open_with_retry")
    def test_gemini_auto_switches_after_transient_rate_limit_retries_are_exhausted(
        self, open_retry
    ):
        response_payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "{\"ok\":true}"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        open_retry.side_effect = [
            ProviderRateLimitError(
                "Gemini",
                retry_after_seconds=30,
                daily_quota=False,
            ),
            StaticResponse(response_payload),
        ]
        provider = GeminiProvider(
            {
                "apiBase": "https://example.invalid",
                "model": "auto",
                "fallbackModels": ["gemini-3.5-flash-lite"],
            },
            "fixture-key",
        )
        logs = []

        result = provider.generate(
            "fixture prompt",
            log=lambda level, message: logs.append((level, message)),
        )

        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(open_retry.call_count, 2)
        self.assertEqual(provider.model, "gemini-3.5-flash-lite")
        self.assertTrue(any(level == "FALLBACK" for level, _message in logs))
        self.assertTrue(any("요청 한도 재시도 소진" in message for _level, message in logs))

    @patch("promptcase_studio.providers.gemini.open_with_retry")
    def test_fixed_gemini_model_does_not_fall_back_on_daily_quota(self, open_retry):
        open_retry.side_effect = ProviderRateLimitError(
            "Gemini",
            daily_quota=True,
            model="gemini-3.5-flash-lite",
        )
        provider = GeminiProvider(
            {
                "apiBase": "https://example.invalid",
                "model": "gemini-3.5-flash-lite",
                "fallbackModels": ["gemini-3.1-flash-lite"],
            },
            "fixture-key",
        )

        with self.assertRaises(ProviderRateLimitError):
            provider.generate("fixture prompt")

        self.assertEqual(open_retry.call_count, 1)
        self.assertFalse(provider.auto_model_selection)
        self.assertEqual(provider.models, ("gemini-3.5-flash-lite",))

    @patch("promptcase_studio.providers.gemini.open_with_retry")
    def test_gemini_reports_quota_after_all_configured_models_are_exhausted(self, open_retry):
        open_retry.side_effect = [
            ProviderRateLimitError(
                "Gemini",
                daily_quota=True,
                model="gemini-3.6-flash",
            ),
            ProviderRateLimitError(
                "Gemini",
                daily_quota=True,
                model="gemini-3.5-flash-lite",
            ),
        ]
        provider = GeminiProvider(
            {
                "apiBase": "https://example.invalid",
                "model": "auto",
                "fallbackModels": ["gemini-3.5-flash-lite"],
            },
            "fixture-key",
        )
        logs = []

        with self.assertRaises(ProviderRateLimitError):
            provider.generate(
                "fixture prompt",
                log=lambda level, message: logs.append((level, message)),
            )

        self.assertEqual(open_retry.call_count, 2)
        self.assertTrue(any(level == "FALLBACK" for level, _message in logs))
        self.assertTrue(any(level == "QUOTA" for level, _message in logs))

    def test_provider_bodies_keep_unsplit_prompt_as_user_content(self):
        response = StaticResponse(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "{\"ok\":true}"}]},
                        "finishReason": "STOP",
                    }
                ]
            }
        )
        gemini = GeminiProvider(
            {"apiBase": "https://example.invalid", "model": "fixture-model"},
            "fixture-key",
        )
        with patch(
            "promptcase_studio.providers.gemini.open_with_retry",
            return_value=response,
        ) as gemini_open:
            gemini.generate("plain fixture prompt")
        gemini_body = json.loads(gemini_open.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(
            gemini_body["system_instruction"]["parts"][0]["text"],
            "응답은 요청된 JSON 객체 하나만 출력한다.",
        )
        self.assertEqual(
            gemini_body["contents"][0]["parts"][0]["text"],
            "plain fixture prompt",
        )

        qwen = QwenProvider(
            {"stream": False},
            PROJECT_ROOT / "config" / "qwen.settings.json",
        )
        qwen_body = qwen._body("plain fixture prompt")
        self.assertEqual(
            qwen_body["messages"][0]["content"],
            "응답은 요청된 JSON 객체 하나만 출력한다.",
        )
        self.assertEqual(qwen_body["messages"][1]["content"], "plain fixture prompt")

    def test_gemini_rejects_abnormal_finish_reasons_and_keeps_usage(self):
        for finish_reason, expected_message in (
            ("MAX_TOKENS", "출력 토큰 한도"),
            ("SAFETY", "안전 정책"),
            ("OTHER", "정상 종료되지"),
        ):
            with self.subTest(finish_reason=finish_reason):
                provider = GeminiProvider(
                    {"apiBase": "https://example.invalid", "model": "fixture-model"},
                    "fixture-key",
                )
                response = StaticResponse(
                    {
                        "candidates": [
                            {
                                "content": {"parts": [{"text": "{\"partial\":true}"}]},
                                "finishReason": finish_reason,
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 50,
                            "candidatesTokenCount": 25,
                            "totalTokenCount": 75,
                        },
                    }
                )
                logs = []
                with (
                    patch(
                        "promptcase_studio.providers.gemini.open_with_retry",
                        return_value=response,
                    ),
                    self.assertRaisesRegex(ProviderError, expected_message),
                ):
                    provider.generate(
                        "fixture prompt",
                        log=lambda level, message: logs.append((level, message)),
                    )
                self.assertEqual(provider.last_diagnostics.finish_reason, finish_reason)
                self.assertEqual(provider.last_diagnostics.total_tokens, 75)
                self.assertTrue(any(finish_reason in message for _level, message in logs))

    def test_qwen_json_rejects_abnormal_finish_reasons_and_keeps_usage(self):
        for finish_reason, expected_message in (
            ("length", "출력 토큰 한도"),
            ("content_filter", "안전 정책"),
            ("tool_calls", "정상 종료되지"),
        ):
            with self.subTest(finish_reason=finish_reason):
                provider = QwenProvider(
                    {"stream": False},
                    PROJECT_ROOT / "config" / "qwen.settings.json",
                )
                response = StaticResponse(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "message": {"content": "{\"partial\":true}"},
                                "finish_reason": finish_reason,
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 40,
                            "completion_tokens": 20,
                            "total_tokens": 60,
                        },
                    }
                )
                with (
                    patch(
                        "promptcase_studio.providers.qwen.open_with_retry",
                        return_value=response,
                    ),
                    self.assertRaisesRegex(ProviderError, expected_message),
                ):
                    provider.generate("fixture prompt")
                self.assertEqual(provider.last_diagnostics.finish_reason, finish_reason)
                self.assertEqual(provider.last_diagnostics.total_tokens, 60)

    def test_qwen_sse_rejects_length_after_collecting_usage(self):
        lines = [
            b'data: {"choices":[{"index":0,"delta":{"content":"partial"},"finish_reason":"length"}]}\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":30,"completion_tokens":10,"total_tokens":40}}\n',
            b"data: [DONE]\n",
        ]
        provider = QwenProvider(
            {"stream": True},
            PROJECT_ROOT / "config" / "qwen.settings.json",
        )
        response = StaticResponse({}, content_type="text/event-stream", lines=lines)
        chunks = []
        with (
            patch(
                "promptcase_studio.providers.qwen.open_with_retry",
                return_value=response,
            ),
            self.assertRaisesRegex(ProviderError, "출력 토큰 한도"),
        ):
            provider.generate("fixture prompt", on_chunk=chunks.append)
        self.assertEqual("".join(chunks), "partial")
        self.assertEqual(provider.last_diagnostics.finish_reason, "length")
        self.assertEqual(provider.last_diagnostics.total_tokens, 40)

    def test_provider_generate_paths_preserve_the_full_structured_contract(self):
        response_text = json.dumps(valid_payload(), ensure_ascii=False)
        gemini_response = StaticResponse(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": response_text}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 40,
                    "totalTokenCount": 140,
                },
            }
        )
        gemini = GeminiProvider(
            {
                "apiBase": "https://example.invalid",
                "model": "fixture-model",
                "timeoutSeconds": 300,
                "maxAttempts": 3,
                "maxOutputTokens": 16384,
            },
            "fixture-key",
        )
        with patch(
            "promptcase_studio.providers.gemini.open_with_retry",
            return_value=gemini_response,
        ) as gemini_open:
            gemini_text = gemini.generate("system contract\n\n---\n\nfixture prompt")
        gemini_request = gemini_open.call_args.args[0]
        gemini_body = json.loads(gemini_request.data.decode("utf-8"))
        self.assertEqual(gemini_body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(gemini_body["generationConfig"]["maxOutputTokens"], 16384)
        self.assertNotIn("temperature", gemini_body["generationConfig"])
        self.assertEqual(gemini_body["system_instruction"]["parts"][0]["text"], "system contract")
        self.assertEqual(gemini_body["contents"][0]["parts"][0]["text"], "fixture prompt")
        self.assertEqual(gemini.last_diagnostics.finish_reason, "STOP")
        self.assertEqual(gemini.last_diagnostics.prompt_tokens, 100)
        self.assertEqual(gemini.last_diagnostics.completion_tokens, 40)
        self.assertEqual(gemini.last_diagnostics.total_tokens, 140)

        qwen_json_response = StaticResponse(
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {"content": response_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 90, "completion_tokens": 30, "total_tokens": 120},
            }
        )
        qwen = QwenProvider(
            {"stream": True, "maxOutputTokens": 16384},
            PROJECT_ROOT / "config" / "qwen.settings.json",
        )
        with patch(
            "promptcase_studio.providers.qwen.open_with_retry",
            return_value=qwen_json_response,
        ) as qwen_open:
            qwen_json_text = qwen.generate("system contract\n\n---\n\nfixture prompt")
        qwen_request = qwen_open.call_args.args[0]
        qwen_body = json.loads(qwen_request.data.decode("utf-8"))
        self.assertTrue(qwen_body["stream"])
        self.assertEqual([message["role"] for message in qwen_body["messages"]], ["system", "user"])
        self.assertEqual(qwen_body["messages"][0]["content"], "system contract")
        self.assertEqual(qwen_body["messages"][1]["content"], "fixture prompt")
        self.assertEqual(qwen_body["max_tokens"], 16384)
        self.assertEqual(qwen.last_diagnostics.finish_reason, "stop")
        self.assertEqual(qwen.last_diagnostics.total_tokens, 120)

        midpoint = len(response_text) // 2
        sse_lines = [
            (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {"delta": {"content": response_text[:midpoint]}, "finish_reason": None}
                        ]
                    },
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8"),
            (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {"delta": {"content": response_text[midpoint:]}, "finish_reason": "stop"}
                        ]
                    },
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8"),
            (
                "data: "
                + json.dumps(
                    {
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 91,
                            "completion_tokens": 31,
                            "total_tokens": 122,
                        },
                    }
                )
                + "\n"
            ).encode("utf-8"),
            b"data: [DONE]\n",
        ]
        qwen_sse_response = StaticResponse(
            {},
            content_type="text/event-stream; charset=utf-8",
            lines=sse_lines,
        )
        with patch(
            "promptcase_studio.providers.qwen.open_with_retry",
            return_value=qwen_sse_response,
        ):
            qwen_sse_text = qwen.generate("fixture prompt")
        self.assertEqual(qwen.last_diagnostics.finish_reason, "stop")
        self.assertEqual(qwen.last_diagnostics.prompt_tokens, 91)
        self.assertEqual(qwen.last_diagnostics.completion_tokens, 31)
        self.assertEqual(qwen.last_diagnostics.total_tokens, 122)

        expected = parse_structured_response(response_text)
        self.assertEqual(parse_structured_response(gemini_text), expected)
        self.assertEqual(parse_structured_response(qwen_json_text), expected)
        self.assertEqual(parse_structured_response(qwen_sse_text), expected)

    def test_loads_repository_qwen_settings(self):
        profile = load_qwen_profile(PROJECT_ROOT / "config" / "qwen.settings.json")
        self.assertEqual(profile["model"], "qwen3.6-agent")
        self.assertEqual(profile["baseUrl"], "http://10.32.64.116:8002")
        self.assertEqual(profile["apiKey"], "")
        self.assertEqual(profile["timeoutMilliseconds"], 300000)
        provider = QwenProvider({}, PROJECT_ROOT / "config" / "qwen.settings.json")
        self.assertEqual(provider.timeout, 300)

    @patch("promptcase_studio.providers.qwen.open_with_retry", return_value=JsonResponse())
    def test_qwen_accepts_json_response_when_stream_was_requested(self, _open):
        provider = QwenProvider(
            {"stream": True},
            PROJECT_ROOT / "config" / "qwen.settings.json",
        )
        self.assertEqual(provider.generate("test prompt"), '{"ok":true}')

    @patch("promptcase_studio.providers.base.time.sleep")
    @patch("promptcase_studio.providers.base.urllib.request.urlopen")
    def test_retries_pre_response_connection_failure_three_times(self, urlopen, sleep):
        response = object()
        urlopen.side_effect = [
            urllib.error.URLError("temporary-1"),
            urllib.error.URLError("temporary-2"),
            response,
        ]
        logs = []
        result = open_with_retry(
            urllib.request.Request("https://example.invalid"),
            timeout=300,
            provider_name="Test",
            max_attempts=3,
            retry_delay_seconds=2,
            log=lambda level, message: logs.append((level, message)),
        )
        self.assertIs(result, response)
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])
        self.assertEqual([level for level, _ in logs], ["RETRY", "RETRY"])

    @patch("promptcase_studio.providers.base.time.sleep")
    @patch("promptcase_studio.providers.base.urllib.request.urlopen")
    def test_daily_gemini_quota_stops_without_pointless_retry(self, urlopen, sleep):
        payload = {
            "error": {
                "code": 429,
                "message": (
                    "Quota exceeded for daily requests. Please retry in 50.154492449s."
                ),
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaMetric": "generate_content_free_tier_requests",
                                "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                "quotaDimensions": {"model": "gemini-3.6-flash"},
                                "quotaValue": "20",
                            }
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "50s",
                    },
                ],
            }
        }
        urlopen.side_effect = urllib.error.HTTPError(
            "https://example.invalid",
            429,
            "RESOURCE_EXHAUSTED",
            {},
            io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

        with self.assertRaises(ProviderRateLimitError) as raised:
            open_with_retry(
                urllib.request.Request("https://example.invalid"),
                timeout=300,
                provider_name="Gemini",
                max_attempts=3,
                retry_delay_seconds=2,
            )

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()
        self.assertTrue(raised.exception.daily_quota)
        self.assertTrue(raised.exception.free_tier)
        self.assertEqual(raised.exception.quota_value, "20")
        self.assertEqual(raised.exception.model, "gemini-3.6-flash")
        self.assertAlmostEqual(raised.exception.retry_after_seconds or 0, 50.154492449)
        self.assertIn("20건을 모두", str(raised.exception))
        self.assertNotIn("20건를", str(raised.exception))

    @patch("promptcase_studio.providers.base.time.sleep")
    @patch("promptcase_studio.providers.base.urllib.request.urlopen")
    def test_transient_rate_limit_honors_server_retry_delay(self, urlopen, sleep):
        payload = {
            "error": {
                "code": 429,
                "message": "Requests per minute exceeded.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "11.5s",
                    }
                ],
            }
        }
        rate_error = urllib.error.HTTPError(
            "https://example.invalid",
            429,
            "RESOURCE_EXHAUSTED",
            {},
            io.BytesIO(json.dumps(payload).encode("utf-8")),
        )
        response = object()
        urlopen.side_effect = [rate_error, response]
        logs = []

        result = open_with_retry(
            urllib.request.Request("https://example.invalid"),
            timeout=300,
            provider_name="Gemini",
            max_attempts=3,
            retry_delay_seconds=2,
            log=lambda level, message: logs.append((level, message)),
        )

        self.assertIs(result, response)
        sleep.assert_called_once_with(11.5)
        self.assertIn("요청 제한 재시도", logs[0][1])

    @patch("promptcase_studio.providers.base.urllib.request.urlopen")
    def test_does_not_retry_after_response_read_has_started(self, urlopen):
        urlopen.return_value = ReadTimeoutResponse()
        provider = GeminiProvider(
            {
                "apiBase": "https://example.invalid",
                "model": "test-model",
                "timeoutSeconds": 300,
                "maxAttempts": 3,
                "retryDelaySeconds": 0,
            },
            "local-test-key",
        )
        with self.assertRaisesRegex(ProviderError, "응답 수신 중"):
            provider.generate("test prompt")
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
