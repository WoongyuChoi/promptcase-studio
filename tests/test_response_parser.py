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

    def test_accepts_single_json_inside_code_fence_or_surrounding_explanation(self):
        raw = "```json\n" + json.dumps(valid_payload(), ensure_ascii=False) + "\n```"
        fenced = parse_structured_response(raw)
        explained = parse_structured_response(
            "작성 결과입니다\n"
            + json.dumps(valid_payload(), ensure_ascii=False)
            + "\n검토해 주세요"
        )
        self.assertEqual(fenced["testCase"]["name"], "사용자 조회 단위테스트")
        self.assertEqual(explained["testCase"]["name"], "사용자 조회 단위테스트")

    def test_rejects_multiple_json_objects_even_with_surrounding_text(self):
        raw = (
            json.dumps(valid_payload(), ensure_ascii=False)
            + "\n"
            + json.dumps(valid_payload(), ensure_ascii=False)
        )
        with self.assertRaisesRegex(ResponseValidationError, "여러 개"):
            parse_structured_response(raw)

    def test_repairs_one_missing_or_duplicate_closing_brace(self):
        payload = json.dumps(valid_payload(), ensure_ascii=False)

        missing = parse_structured_response(payload[:-1])
        duplicate = parse_structured_response(payload + "}")

        self.assertEqual(missing["testCase"]["name"], "사용자 조회 단위테스트")
        self.assertEqual(duplicate["testCase"]["name"], "사용자 조회 단위테스트")

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

    def test_rejects_zero_and_six_steps_but_accepts_mismatched_result_count(self):
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

        payload["testCase"]["procedure"][-1] = payload["testCase"]["procedure"][0]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(result["testCase"]["procedure"]), 5)

        payload = valid_payload()
        payload["testResult"]["testDetails"] = payload["testResult"]["testDetails"][:2]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(result["testCase"]["procedure"]), 3)
        self.assertEqual(len(result["testResult"]["testDetails"]), 2)

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
        payload["testCase"]["expectedResult"] = (
            "대표 실적이 반영되고 저장 후 모든 팝업이 닫힌다"
        )
        payload["testCase"]["testData"] = "활성 상태의 사용자 데이터를 준비한다"
        payload["testResult"]["testDetails"][0] = (
            "사용자 조회 기능의 기준 결과가 화면에 표시된다"
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
        self.assertEqual(
            result["testCase"]["expectedResult"],
            "대표 실적이 반영되고 저장 후 모든 팝업이 닫힌다",
        )
        self.assertEqual(
            result["testResult"]["testDetails"][0],
            "사용자 조회 기능의 기준 결과가 화면에 표시된다",
        )

    def test_accepts_empty_preconditions_and_test_data(self):
        payload = valid_payload()
        payload["testCase"]["preconditions"] = []
        payload["testCase"]["testData"] = ""

        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(result["testCase"]["preconditions"], [])
        self.assertEqual(result["testCase"]["testData"], "")

    def test_normalizes_missing_or_spaced_unit_test_name_suffix(self):
        for supplied in ("사용자 조회", "사용자 조회 단위 테스트"):
            with self.subTest(supplied=supplied):
                payload = valid_payload()
                payload["testCase"]["name"] = supplied
                result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
                self.assertEqual(result["testCase"]["name"], "사용자 조회 단위테스트")

    def test_accepts_procedure_and_test_detail_overlap_for_soft_review(self):
        payload = valid_payload()
        payload["testResult"]["testDetails"][0] = payload["testCase"]["procedure"][0]

        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(
            result["testResult"]["testDetails"][0],
            result["testCase"]["procedure"][0],
        )

    def test_normalizes_harmless_human_text_formatting(self):
        payload = valid_payload()
        payload["testCase"]["procedure"][0] = (
            "1.  사용자 조회 조건을 선택하고\n검색 버튼을 누른다."
        )

        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(
            result["testCase"]["procedure"][0],
            "사용자 조회 조건을 선택하고 검색 버튼을 누른다",
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

        payload["testResult"]["processingDetails"][-1] = payload["testResult"][
            "processingDetails"
        ][0]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(result["testResult"]["processingDetails"]), 5)

    def test_document_title_is_optional_for_existing_responses(self):
        payload = valid_payload()
        del payload["documentTitle"]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(result["documentTitle"], "")

    def test_accepts_harmless_decorative_characters_and_strips_leading_markers(self):
        for supplied in (
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
        ):
            with self.subTest(supplied=supplied):
                payload = valid_payload()
                payload["testCase"]["procedure"][0] = supplied
                result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
                self.assertTrue(result["testCase"]["procedure"][0].endswith("다"))
                self.assertFalse(result["testCase"]["procedure"][0].startswith("○"))

        payload = valid_payload()
        payload["testResult"]["processingDetails"][0]["detail"] = "활성 상태 조건을 반영했다."
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(
            result["testResult"]["processingDetails"][0]["detail"],
            "활성 상태 조건을 반영했다",
        )

    def test_normalizes_exact_duplicates_but_rejects_generic_quality_failure(self):
        payload = valid_payload()
        payload["testResult"]["testDetails"][1] = payload["testResult"]["testDetails"][0]
        result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(len(result["testResult"]["testDetails"]), 2)

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

    def test_drops_ungrounded_optional_title_without_rejecting_sample_data_token(self):
        evidence = json.dumps(valid_payload(), ensure_ascii=False)
        payload = valid_payload()
        payload["documentTitle"] = "재무관리시스템"
        payload["testCase"]["testData"] = "INACTIVE 상태의 사용자 데이터를 사용한다"

        parsed = parse_structured_response(
            json.dumps(payload, ensure_ascii=False),
            evidence_text=evidence,
        )
        self.assertEqual(parsed["documentTitle"], "")
        self.assertEqual(
            parsed["testCase"]["testData"],
            "INACTIVE 상태의 사용자 데이터를 사용한다",
        )

    def test_filters_ungrounded_optional_target_names(self):
        payload = valid_payload()
        payload["documentTitle"] = ""
        payload["testCase"]["targetIds"] = []
        payload["testCase"]["targetNames"] = ["사용자 조회", "근거 없는 검색 화면"]
        evidence = "사용자 조회 기능과 활성 사용자 데이터를 확인한다"

        result = parse_structured_response(
            json.dumps(payload, ensure_ascii=False),
            evidence_text=evidence,
        )

        self.assertEqual(result["testCase"]["targetNames"], ["사용자 조회"])

    def test_style_punctuation_does_not_hide_a_semantic_quality_error(self):
        payload = valid_payload()
        payload["testCase"]["procedure"][0] = "사용자 조회 조건: 활성 상태를 확인한다"
        payload["testCase"]["expectedResult"] = "기능이 정상 동작한다"

        with self.assertRaises(ResponseValidationError) as caught:
            parse_structured_response(json.dumps(payload, ensure_ascii=False))

        self.assertTrue(any("testCase.expectedResult" in error for error in caught.exception.errors))
        self.assertFalse(any("testCase.procedure[0]" in error for error in caught.exception.errors))

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

    def test_narrative_identifiers_do_not_fail_the_response_contract(self):
        for token in (
            "92886000",
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
                result = parse_structured_response(
                    json.dumps(payload, ensure_ascii=False),
                    evidence_text="활성 사용자 조회 조건과 기준 데이터를 확인한다",
                )
                self.assertEqual(
                    result["testCase"]["testData"],
                    f"{token} 조건 데이터를 사용한다",
                )

    def test_narrative_role_does_not_fail_the_response_contract(self):
        payload = valid_payload()
        payload["documentTitle"] = ""
        payload["testCase"]["targetIds"] = []
        payload["testCase"]["targetNames"] = []
        payload["testCase"]["preconditions"][0] = "최고관리자 계정으로 로그인되어 있어야 한다"
        result = parse_structured_response(
            json.dumps(payload, ensure_ascii=False),
            evidence_text="사용자 조회 조건과 기준 데이터를 확인한다",
        )
        self.assertEqual(
            result["testCase"]["preconditions"][0],
            "최고관리자 계정으로 로그인되어 있어야 한다",
        )

    def test_document_title_drops_formatting_and_timestamp_fragments(self):
        for title in (
            "사용자관리시스템(신규)",
            "사용자관리시스템 20260722",
            "사용자관리시스템 174617",
            "사용자관리시스템 단위테스트",
        ):
            with self.subTest(title=title):
                payload = valid_payload()
                payload["documentTitle"] = title
                result = parse_structured_response(json.dumps(payload, ensure_ascii=False))
                self.assertEqual(result["documentTitle"], "")

    def test_accepts_grounded_cross_platform_target_id_formats(self):
        for target_id in (
            "SCREEN:USR1000",
            "ZCL_USER=>READ",
            "ZIF_USER~READ",
            "UserService#findActiveUser",
            "App\\Service\\UserService",
            "[dbo].[TB_USER]",
        ):
            with self.subTest(target_id=target_id):
                payload = valid_payload()
                payload["documentTitle"] = ""
                payload["testCase"]["targetIds"] = [target_id]
                payload["testCase"]["targetNames"] = []
                evidence = f"실행 대상은 {target_id}이며 활성 사용자 데이터를 조회한다"
                result = parse_structured_response(
                    json.dumps(payload, ensure_ascii=False),
                    evidence_text=evidence,
                )
                self.assertEqual(result["testCase"]["targetIds"], [target_id])

    def test_rejects_fields_outside_the_contract(self):
        payload = valid_payload()
        payload["analysis"] = "추가 설명"
        with self.assertRaises(ResponseValidationError):
            parse_structured_response(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
