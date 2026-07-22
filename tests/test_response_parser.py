import json
import unittest

from promptcase_studio.response_parser import ResponseValidationError, parse_structured_response


def valid_payload():
    return {
        "testCase": {
            "name": "사용자 조회 단위테스트",
            "procedure": ["화면에 진입한다", "사용자를 조회한다", "결과를 확인한다"],
            "targetIds": ["USR1000"],
            "targetNames": ["사용자 조회"],
            "preconditions": ["로그인 상태다", "사용자가 존재한다", "조회 권한이 있다"],
            "testData": "활성 사용자 데이터를 사용한다",
            "expectedResult": "활성 사용자만 정상 조회된다",
            "notes": "",
        },
        "testResult": {
            "processingDetails": [{"title": "조회 조건 변경", "detail": "활성 상태 조건 반영"}],
            "testDetails": ["진입 확인", "조회 확인", "결과 확인"],
            "resultChecks": ["활성 사용자 조회 결과 확인"],
        },
    }


class ResponseParserTests(unittest.TestCase):
    def test_parses_json_code_fence(self):
        raw = "```json\n" + json.dumps(valid_payload(), ensure_ascii=False) + "\n```"
        result = parse_structured_response(raw)
        self.assertEqual(result["testCase"]["name"], "사용자 조회 단위테스트")
        self.assertEqual(len(result["testCase"]["procedure"]), 3)

    def test_rejects_short_procedure(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = ["한 단계만 확인한다"]
        with self.assertRaises(ResponseValidationError):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()

