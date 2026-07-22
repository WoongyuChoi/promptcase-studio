import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from promptcase_studio.providers.base import ProviderError, open_with_retry
from promptcase_studio.providers.gemini import GeminiProvider
from promptcase_studio.providers.qwen import QwenProvider, load_qwen_profile


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FakeStream:
    def __iter__(self):
        return iter(
            [
                b'data: {"choices":[{"delta":{"content":"{\\"ok\\":"},"finish_reason":null}]}\n',
                b'data: {"choices":[{"delta":{"content":"true}"},"finish_reason":"stop"}]}\n',
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

    def test_loads_repository_qwen_settings(self):
        profile = load_qwen_profile(PROJECT_ROOT / "config" / "qwen.settings.json")
        self.assertEqual(profile["model"], "qwen3.6-agent")
        self.assertEqual(profile["baseUrl"], "http://10.32.64.116:8002")
        self.assertEqual(profile["apiKey"], "")
        self.assertEqual(profile["timeoutMilliseconds"], 300000)
        provider = QwenProvider({}, PROJECT_ROOT / "config" / "qwen.settings.json")
        self.assertEqual(provider.timeout, 300)

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
