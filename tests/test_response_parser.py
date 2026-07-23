import json
import unittest

from promptcase_studio.response_parser import ResponseValidationError, parse_structured_response


def valid_payload():
    return {
        "documentTitle": "사용자관리시스템",
        "testCase": {
            "name": "사용자 조회 단위테스트",
            "procedure": [
                "사용자 조회 기능에 접근해 기준 결과를 확인한다",
                "활성 상태의 사용자 식별자로 조회를 실행한다",
                "조회 결과의 사용자 정보와 상태를 확인한다",
            ],
            "targetIds": ["USR1000"],
            "targetNames": ["사용자 조회"],
            "preconditions": [
                "조회 권한이 있는 계정으로 로그인되어 있어야 한다",
                "활성 상태의 사용자 데이터가 준비되어 있어야 한다",
                "조회 결과를 비교할 기준 정보가 준비되어 있어야 한다",
            ],
            "testData": "활성 사용자 데이터를 사용한다",
            "expectedResult": "활성 사용자만 정상 조회된다",
            "notes": "",
        },
        "testResult": {
            "processingDetails": [{"title": "조회 조건 변경", "detail": "활성 상태 조건 반영"}],
            "testDetails": [
                "사용자 조회 기능의 기준 결과가 표시되는지 확인한다",
                "활성 상태 조건에 맞는 사용자만 조회되는지 확인한다",
                "조회된 사용자 정보와 상태가 일치하는지 확인한다",
            ],
            "resultChecks": ["활성 사용자 조회 결과 확인"],
        },
    }


class ResponseParserTests(unittest.TestCase):
    def test_accepts_bom_and_whitespace_around_the_single_json_object(self):
        raw = "\ufeff  \n" + json.dumps(valid_payload(), ensure_ascii=False) + "\n  "
        result = parse_structured_response(raw)
        self.assertEqual(result["testCase"]["name"], "사용자 조회 단위테스트")

    def test_rejects_json_code_fence_and_surrounding_explanation(self):
        raw = "```json\n" + json.dumps(valid_payload(), ensure_ascii=False) + "\n```"
        with self.assertRaisesRegex(ResponseValidationError, "코드 펜스"):
            parse_structured_response(raw)
        with self.assertRaisesRegex(ResponseValidationError, "앞뒤에 설명"):
            parse_structured_response(
                "작성 결과입니다\n" + json.dumps(valid_payload(), ensure_ascii=False)
            )

    def test_accepts_one_to_five_steps_and_matching_test_details(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = ["활성 사용자 식별자로 조회를 실행한다"]
        payload["testCase"]["preconditions"] = [
            "조회 권한이 있는 계정으로 로그인되어 있어야 한다"
        ]
        payload["testResult"]["testDetails"] = [
            "활성 상태 조건에 맞는 사용자만 조회되는지 확인한다"
        ]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(result["testCase"]["procedure"]), 1)

        payload = valid_payload()
        payload["testCase"]["procedure"] = [
            "조회 메뉴에 접근해 기준 목록을 확인한다",
            "활성 상태를 조회조건으로 선택한다",
            "선택한 조회조건으로 사용자 조회를 실행한다",
            "조회 목록에서 비활성 사용자가 제외되었는지 확인한다",
            "조회된 사용자 정보와 상태값을 비교한다",
        ]
        payload["testCase"]["preconditions"] = [
            "조회 권한이 있는 계정으로 로그인되어 있어야 한다",
            "활성 상태의 사용자 데이터가 준비되어 있어야 한다",
            "비활성 상태의 사용자 데이터가 준비되어 있어야 한다",
            "조회 결과를 비교할 기준 정보가 준비되어 있어야 한다",
            "사용자 상태별 조회가 가능한 환경이어야 한다",
        ]
        payload["testResult"]["testDetails"] = [
            "사용자 조회 기능의 기준 목록이 표시되는지 확인한다",
            "활성 상태 조회조건이 선택되는지 확인한다",
            "선택한 조건으로 사용자 조회가 실행되는지 확인한다",
            "조회 목록에서 비활성 사용자가 제외되는지 확인한다",
            "조회된 사용자 정보와 상태값이 일치하는지 확인한다",
        ]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(result["testCase"]["procedure"]), 5)

    def test_rejects_zero_six_and_mismatched_step_counts(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = []
        with self.assertRaisesRegex(ResponseValidationError, "1~5개"):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

        payload = valid_payload()
        payload["testCase"]["procedure"] = [
            f"사용자 조회 조건 {index}로 조회를 실행한다" for index in range(1, 7)
        ]
        with self.assertRaisesRegex(ResponseValidationError, "1~5개"):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

        payload = valid_payload()
        payload["testResult"]["testDetails"] = payload["testResult"]["testDetails"][:2]
        with self.assertRaisesRegex(ResponseValidationError, "같은 항목 수"):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

    def test_accepts_natural_commas_inside_test_data(self):
        payload = valid_payload()
        payload["testCase"]["testData"] = (
            "기준년도 2026, 세션 조직코드 92886000, 전사 조직코드 90124000을 사용한다"
        )
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertIn(",", result["testCase"]["testData"])

    def test_accepts_natural_complete_sentences_that_end_in_da(self):
        payload = valid_payload()
        payload["testCase"]["procedure"][2] = (
            "카드 정보를 수정한 후 저장 버튼을 누른다"
        )
        payload["testCase"]["preconditions"][0] = (
            "비교 기준 데이터가 준비되어 있다"
        )

        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(
            result["testCase"]["procedure"][2],
            "카드 정보를 수정한 후 저장 버튼을 누른다",
        )
        self.assertEqual(
            result["testCase"]["preconditions"][0],
            "비교 기준 데이터가 준비되어 있다",
        )

    def test_processing_details_accepts_five_and_rejects_six(self):
        payload = valid_payload()
        payload["testResult"]["processingDetails"] = [
            {"title": f"조회 조건 변경 {index}", "detail": f"사용자 조회 조건 {index} 반영"}
            for index in range(1, 6)
        ]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(result["testResult"]["processingDetails"]), 5)

        payload["testResult"]["processingDetails"].append(
            {"title": "조회 조건 변경 6", "detail": "사용자 조회 조건 6 반영"}
        )
        with self.assertRaisesRegex(ResponseValidationError, "1~5개"):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

    def test_document_title_is_optional_for_existing_responses(self):
        payload = valid_payload()
        del payload["documentTitle"]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(result["documentTitle"], "")

    def test_rejects_decorative_characters_and_numbered_items(self):
        for invalid in (
            "사용자 조회·상태 확인을 수행한다",
            "○ 사용자 조회 상태를 확인한다",
            "사용자 조회 조건: 활성 상태를 확인한다",
            "사용자 조회 조건; 활성 상태를 확인한다",
            "사용자 조회 조건： 활성 상태를 확인한다",
            "사용자 조회 조건； 활성 상태를 확인한다",
            "사용자 조회ㆍ상태를 확인한다",
            "사용자 조회‧상태를 확인한다",
            "사용자 조회∙상태를 확인한다",
            "사용자 “조회” 상태를 확인한다",
            "사용자 ‘조회’ 상태를 확인한다",
            "사용자 「조회」 상태를 확인한다",
            "사용자 *조회* 상태를 확인한다",
            "사용자 | 조회 상태를 확인한다",
            "사용자 \\ 조회 상태를 확인한다",
            "1. 사용자 조회 상태를 확인한다",
            "사용자 조회 상태를 확인한다.",
        ):
            with self.subTest(invalid=invalid):
                payload = valid_payload()
                payload["testCase"]["procedure"][0] = invalid
                with self.assertRaises(ResponseValidationError):
                    parse_structured_response(json.dumps(payload, ensure_ascii=False))

        payload = valid_payload()
        payload["testResult"]["processingDetails"][0]["detail"] = "활성 상태 조건을 반영했다."
        with self.assertRaises(ResponseValidationError):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

    def test_rejects_duplicate_and_generic_quality_failures(self):
        payload = valid_payload()
        payload["testResult"]["testDetails"][1] = payload["testResult"]["testDetails"][0]
        with self.assertRaises(ResponseValidationError):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

        payload = valid_payload()
        payload["testCase"]["expectedResult"] = "기능이 정상 동작한다"
        with self.assertRaises(ResponseValidationError):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

    def test_optional_evidence_gate_rejects_invented_target(self):
        payload = valid_payload()
        with self.assertRaises(ResponseValidationError):
            parse_structured_response(
                json.dumps(payload, ensure_ascii=False),
                evidence_text="사용자 조회 화면만 확인되며 식별자는 제공되지 않았다",
            )

    def test_reports_independent_title_and_grounding_errors_together(self):
        evidence = json.dumps(valid_payload(), ensure_ascii=False)
        payload = valid_payload()
        payload["documentTitle"] = "재무관리시스템"
        payload["testCase"]["testData"] = "INACTIVE 상태의 사용자 데이터를 사용한다"

        with self.assertRaises(ResponseValidationError) as caught:
            parse_structured_response(
                json.dumps(payload, ensure_ascii=False),
                evidence_text=evidence,
            )

        self.assertEqual(len(caught.exception.errors), 2)
        self.assertTrue(any("documentTitle" in error and "재무관리시스템" in error for error in caught.exception.errors))
        self.assertTrue(any("INACTIVE" in error for error in caught.exception.errors))
        self.assertIn("응답 계약 오류 2건", str(caught.exception))

    def test_reports_independent_field_quality_errors_together(self):
        payload = valid_payload()
        payload["testCase"]["procedure"][0] = "사용자 조회 조건: 활성 상태를 확인한다"
        payload["testCase"]["expectedResult"] = "기능이 정상 동작한다"

        with self.assertRaises(ResponseValidationError) as caught:
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

        self.assertTrue(any("testCase.procedure[0]" in error for error in caught.exception.errors))
        self.assertTrue(any("testCase.expectedResult" in error for error in caught.exception.errors))

    def test_non_object_test_case_still_collects_test_result_errors(self):
        payload = valid_payload()
        payload["testCase"] = None
        payload["testResult"] = {"processingDetails": []}

        with self.assertRaises(ResponseValidationError) as caught:
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

        errors = caught.exception.errors
        self.assertIn("testCase는 JSON 객체여야 합니다.", errors)
        self.assertTrue(
            any(
                "testResult 필수 필드가 없습니다" in error
                and "testDetails" in error
                and "resultChecks" in error
                for error in errors
            )
        )
        self.assertIn("testResult.processingDetails 항목 수는 1~5개여야 합니다.", errors)
        self.assertFalse(any(error.startswith("testCase.") for error in errors))

    def test_evidence_gate_rejects_invented_codes_inside_narrative_fields(self):
        for token in (
            "UNSEEN_ACCOUNT_9999",
            "KpiMapBogus",
            "kpiMapBogus",
            "SessionProvider",
            "testuser",
            "testuser1",
            "Spring",
            "스프링",
        ):
            with self.subTest(token=token):
                payload = valid_payload()
                payload["documentTitle"] = ""
                payload["testCase"]["targetIds"] = []
                payload["testCase"]["targetNames"] = []
                payload["testCase"]["testData"] = f"{token} 조건 데이터를 사용한다"
                with self.assertRaisesRegex(ResponseValidationError, token):
                    parse_structured_response(
                        json.dumps(payload, ensure_ascii=False),
                        evidence_text="활성 사용자 조회 조건과 기준 데이터를 확인한다",
                    )

    def test_evidence_gate_rejects_invented_privileged_role(self):
        payload = valid_payload()
        payload["documentTitle"] = ""
        payload["testCase"]["targetIds"] = []
        payload["testCase"]["targetNames"] = []
        payload["testCase"]["preconditions"][0] = "최고관리자 계정으로 로그인되어 있어야 한다"
        with self.assertRaisesRegex(ResponseValidationError, "최고관리자"):
            parse_structured_response(
                json.dumps(payload, ensure_ascii=False),
                evidence_text="사용자 조회 조건과 기준 데이터를 확인한다",
            )

    def test_document_title_rejects_formatting_and_timestamp_fragments(self):
        for title in (
            "사용자관리시스템(신규)",
            "사용자관리시스템 20260722",
            "사용자관리시스템 174617",
            "사용자관리시스템 단위테스트",
        ):
            with self.subTest(title=title):
                payload = valid_payload()
                payload["documentTitle"] = title
                with self.assertRaises(ResponseValidationError):
                    parse_structured_response(json.dumps(payload, ensure_ascii=False))

    def test_target_id_rejects_colon(self):
        payload = valid_payload()
        payload["testCase"]["targetIds"] = ["SCREEN:USR1000"]
        with self.assertRaises(ResponseValidationError):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

    def test_rejects_fields_outside_the_contract(self):
        payload = valid_payload()
        payload["analysis"] = "추가 설명"
        with self.assertRaises(ResponseValidationError):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
