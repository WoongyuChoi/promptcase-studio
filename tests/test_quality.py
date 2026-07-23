import json
import unittest

from promptcase_studio.models import ChangeItem
from promptcase_studio.quality import (
    build_quality_report,
    extract_change_anchors,
    find_implementation_preconditions,
    find_non_actionable_test_steps,
    find_overloaded_expected_result,
    find_scope_inflation,
    find_semantic_duplicates,
    find_unnatural_test_data,
    quality_report_markdown,
)
from tests.test_response_parser import valid_payload


class QualityTests(unittest.TestCase):
    def test_finds_korean_and_english_semantic_duplicates(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = [
            "사용자 조회 기능에서 조회 결과를 확인한다",
            "사용자 조회 기능에서 표시 결과를 확인한다",
            "활성 상태의 사용자 식별자로 조회를 실행한다",
        ]
        payload["testResult"]["resultChecks"] = [
            "Verify active user query returns only active records",
            "Confirm active user query returns active records only",
        ]

        issues = find_semantic_duplicates(payload)

        fields = [tuple(issue["fields"]) for issue in issues]
        self.assertIn(
            ("testCase.procedure[0]", "testCase.procedure[1]"),
            fields,
        )
        self.assertIn(
            ("testResult.resultChecks[0]", "testResult.resultChecks[1]"),
            fields,
        )
        self.assertNotIn(
            ("testCase.procedure[1]", "testCase.procedure[2]"),
            fields,
        )

    def test_does_not_flag_sentences_that_only_share_generic_test_words(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = [
            "조직 변경 권한으로 세션 정보를 갱신한다",
            "KPI 노드 삭제 후 연결선 정리를 실행한다",
            "저장할 내용이 없을 때 알림 표시를 확인한다",
        ]

        self.assertEqual(find_semantic_duplicates(payload), [])

    def test_distinct_status_and_missing_data_branches_are_not_duplicates(self):
        payload = valid_payload()
        payload["testResult"]["resultChecks"] = [
            "ACTIVE 상태가 아닌 사용자 조회 시 null 반환 확인",
            "미존재 사용자 조회 시 null 반환 확인",
        ]

        self.assertEqual(find_semantic_duplicates(payload), [])

    def test_active_and_inactive_branches_are_not_duplicates(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = [
            "활성 상태 조건을 선택해 사용자 조회를 실행한다",
            "비활성 상태 조건을 선택해 사용자 조회를 다시 실행한다",
        ]
        payload["testResult"]["testDetails"] = [
            "활성 상태 사용자가 조회 결과에 표시되는지 확인한다",
            "비활성 상태 사용자가 조회 결과에서 제외되는지 확인한다",
        ]

        self.assertEqual(find_semantic_duplicates(payload), [])

    def test_finds_implementation_existence_preconditions_only(self):
        payload = valid_payload()
        payload["testCase"]["preconditions"] = [
            "UserMapper 매퍼 파일의 selectActiveUser 쿼리가 작성되어 있어야 한다",
            "UserService 서비스 객체가 정상적으로 생성되어 있어야 한다",
            "활성 상태의 사용자 데이터가 준비되어 있어야 한다",
        ]

        issues = find_implementation_preconditions(payload)

        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0]["fields"], ["testCase.preconditions[0]"])
        self.assertEqual(issues[1]["fields"], ["testCase.preconditions[1]"])

    def test_business_status_code_definition_can_be_a_data_precondition(self):
        payload = valid_payload()
        payload["testCase"]["preconditions"] = [
            "사용자 상태값 식별을 위한 ACTIVE 상태 코드가 정의되어 있어야 한다",
            "활성 상태의 사용자 데이터가 준비되어 있어야 한다",
            "조회 결과를 비교할 기준 정보가 준비되어 있어야 한다",
        ]

        self.assertEqual(find_implementation_preconditions(payload), [])

    def test_flags_vague_confirmation_but_accepts_real_operations_and_outcomes(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = [
            "사용자 조회 기능을 확인한다",
            "활성 상태를 조회조건으로 선택해 조회를 실행한다",
        ]
        payload["testResult"]["testDetails"] = [
            "변경 사항을 확인한다",
            "조회 목록에서 비활성 사용자가 제외되는지 확인한다",
        ]

        issues = find_non_actionable_test_steps(payload)

        fields = [issue["fields"][0] for issue in issues]
        self.assertIn("testCase.procedure[0]", fields)
        self.assertIn("testResult.testDetails[0]", fields)
        self.assertNotIn("testCase.procedure[1]", fields)
        self.assertNotIn("testResult.testDetails[1]", fields)

    def test_flags_keyword_like_test_data_and_accepts_natural_separators(self):
        payload = valid_payload()
        payload["testCase"]["testData"] = (
            "기준년도 2026 세션 조직코드 92886000 전사 조직코드 90124000을 사용한다"
        )
        issues = find_unnatural_test_data(payload)
        self.assertEqual(issues[0]["code"], "keyword_like_test_data")

        payload["testCase"]["testData"] = (
            "기준년도 2026, 세션 조직코드 92886000, 전사 조직코드 90124000을 사용한다"
        )
        self.assertEqual(find_unnatural_test_data(payload), [])

    def test_expected_result_is_limited_to_two_observable_outcomes(self):
        payload = valid_payload()
        payload["testCase"]["expectedResult"] = (
            "저장값이 반영되고, 조회 목록이 갱신되며, 완료 알림이 표시된다"
        )
        issues = find_overloaded_expected_result(payload)
        self.assertEqual(issues[0]["code"], "overloaded_expected_result")

        payload["testCase"]["expectedResult"] = (
            "저장값이 반영되고, 완료 알림이 표시된다"
        )
        self.assertEqual(find_overloaded_expected_result(payload), [])

    def test_semantic_duplicate_scan_includes_processing_topics(self):
        payload = valid_payload()
        payload["testResult"]["processingDetails"] = [
            {"title": "조회 조건 반영", "detail": "활성 사용자 조회 조건을 적용"},
            {"title": "조회 조건 적용", "detail": "활성 사용자 조회 조건을 적용"},
        ]

        fields = [tuple(issue["fields"]) for issue in find_semantic_duplicates(payload)]

        self.assertIn(
            (
                "testResult.processingDetails[0]",
                "testResult.processingDetails[1]",
            ),
            fields,
        )

    def test_flags_inflated_rows_only_for_a_single_simple_change(self):
        payload = valid_payload()
        payload["testCase"]["procedure"].append(
            "조회 목록의 사용자 수를 기준 정보와 비교한다"
        )
        payload["testCase"]["preconditions"].append(
            "사용자 수를 비교할 기준 정보가 준비되어 있어야 한다"
        )
        payload["testResult"]["testDetails"].append(
            "조회 목록의 사용자 수가 기준 정보와 일치하는지 확인한다"
        )
        payload["testResult"]["processingDetails"] = [
            {"title": f"조회 변경 {index}", "detail": f"조회 처리 {index} 반영"}
            for index in range(1, 5)
        ]
        changes = [
            ChangeItem("C:/front", "api/UserApi.ts", "변경", "manual", True),
        ]

        issues = find_scope_inflation(payload, changes, ["조회 조건 변경"])

        self.assertEqual(issues[0]["code"], "overexpanded_simple_change")
        self.assertIn("testCase.procedure", issues[0]["fields"])
        self.assertEqual(
            find_scope_inflation(
                payload,
                [
                    *changes,
                    ChangeItem("C:/back", "service/UserService.java", "변경", "manual", True),
                ],
                ["조회 조건 변경"],
            ),
            [],
        )

    def test_extracts_compact_note_and_cross_layer_file_family_anchors(self):
        changes = [
            ChangeItem("C:/front", "component/kpi/KpiMapCanvas.tsx", "변경", "manual", True),
            ChangeItem("C:/front", "component/kpi/KpiMapHeader.tsx", "변경", "manual", True),
            ChangeItem("C:/back", "service/KpiMapServiceImpl.java", "변경", "manual", True),
            ChangeItem("C:/front", "api/kpi/orgSelectApi.ts", "삭제", "manual", False),
            ChangeItem("C:/front", "data/index.ts", "변경", "manual", True),
        ]

        anchors = extract_change_anchors(
            changes,
            ["feat: 저장 시 변경된 사항이 없으면 Alert 처리"],
        )

        note_anchor = next(anchor for anchor in anchors if anchor["source"] == "change_note")
        self.assertIn("save", note_anchor["terms"])
        self.assertIn("alert", note_anchor["terms"])
        kpi_anchor = next(anchor for anchor in anchors if anchor["id"] == "family-kpi-map")
        self.assertEqual(len(kpi_anchor["paths"]), 3)
        self.assertFalse(any(anchor["label"].casefold() == "index" for anchor in anchors))
        deleted = next(
            anchor
            for anchor in anchors
            if "api/kpi/orgSelectApi.ts" in anchor["paths"]
        )
        self.assertIn("deletion", deleted["categories"])
        self.assertEqual(deleted["weight"], 3)

    def test_report_exposes_coverage_categories_score_and_json_contract(self):
        payload = valid_payload()
        payload["documentTitle"] = ""
        payload["testCase"]["procedure"] = [
            "사용자 권한으로 KPI Map 메뉴에 접근한다",
            "저장할 변경 사항이 없을 때 알림 표시를 확인한다",
            "KPI Map 조회 결과와 세션 조직 정보를 확인한다",
        ]
        payload["testCase"]["preconditions"] = [
            "KPI Map 권한이 있는 계정으로 로그인되어 있어야 한다",
            "세션 조직 정보가 준비되어 있어야 한다",
            "조회 가능한 KPI 데이터가 준비되어 있어야 한다",
        ]
        payload["testCase"]["testData"] = "저장 변경 사항이 없는 KPI Map 데이터를 사용한다"
        payload["testCase"]["expectedResult"] = "변경 사항이 없으면 알림이 표시되고 저장되지 않는다"
        payload["testCase"]["targetIds"] = []
        payload["testCase"]["targetNames"] = ["KPI Map"]
        changes = [
            ChangeItem("C:/front", "component/kpi/KpiMapHeader.tsx", "변경", "manual", True),
            ChangeItem("C:/front", "api/kpi/orgSelectApi.ts", "삭제", "manual", False),
            ChangeItem("C:/front", "api/kpi/MKPIM1110.ts", "이름변경", "manual", True),
        ]
        notes = [
            "feat: 저장 시 변경된 사항이 없으면 Alert 처리",
            "변경: 권한이 없는 사용자의 저장 요청 거부",
            "변경: 최대 100개 노드 입력 제한",
        ]

        report = build_quality_report(payload, changes, notes)

        self.assertIsInstance(report["score"], int)
        self.assertTrue(report["soft_gate"]["blocking"])
        self.assertTrue(report["scenario_categories"]["normal"]["covered"])
        self.assertTrue(report["scenario_categories"]["negative"]["covered"])
        self.assertTrue(report["scenario_categories"]["permission"]["covered"])
        self.assertTrue(report["scenario_categories"]["error"]["covered"])
        self.assertFalse(report["scenario_categories"]["boundary"]["covered"])
        self.assertFalse(report["scenario_categories"]["deletion"]["covered"])
        self.assertFalse(report["scenario_categories"]["regression"]["covered"])
        self.assertGreater(len(report["covered_anchors"]), 0)
        self.assertGreater(len(report["uncovered_anchors"]), 0)
        json.dumps(report, ensure_ascii=False)

        markdown = quality_report_markdown(report, max_items=4)
        self.assertIn("자동 품질 검토", markdown)
        self.assertIn("품질 점수", markdown)
        self.assertIn("경계값: 검토 필요", markdown)
        self.assertIn("미커버 변경 앵커", markdown)

    def test_program_info_file_listing_does_not_count_as_scenario_coverage(self):
        payload = valid_payload()
        payload["programInfo"] = [
            {"program": "RemovedApi.ts", "changeType": "삭제"},
        ]
        changes = [
            ChangeItem("C:/front", "api/RemovedApi.ts", "삭제", "manual", False),
        ]

        report = build_quality_report(payload, changes)

        self.assertTrue(report["scenario_categories"]["deletion"]["detected"])
        self.assertFalse(report["scenario_categories"]["deletion"]["covered"])

    def test_each_explicit_user_condition_requires_its_own_coverage(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = [
            "변경 사항이 없는 상태에서 저장 버튼을 선택한다",
        ]
        payload["testCase"]["preconditions"] = [
            "비활성 사용자 데이터가 준비되어 있어야 한다",
        ]
        payload["testCase"]["testData"] = "변경 사항이 없는 비활성 사용자 데이터를 사용한다"
        payload["testCase"]["expectedResult"] = "변경 사항 없음 알림이 표시된다"
        payload["testResult"]["processingDetails"] = [
            {"title": "변경 없음 처리", "detail": "저장 요청을 차단하고 알림을 표시"},
        ]
        payload["testResult"]["testDetails"] = [
            "변경 사항 없음 알림이 표시되는지 확인한다",
        ]
        payload["testResult"]["resultChecks"] = ["변경 사항 없음 알림 확인"]

        report = build_quality_report(
            payload,
            change_notes=[
                "저장 시 변경된 사항이 없으면 알림 처리",
                "비활성 사용자는 조회 결과에서 제외",
            ],
        )

        inactive_issues = [
            issue
            for issue in report["issues"]
            if issue.get("code") == "uncovered_explicit_scenario"
            and issue.get("scenario") == "inactive"
        ]
        self.assertEqual(len(inactive_issues), 1)
        self.assertEqual(inactive_issues[0]["severity"], "required")
        self.assertTrue(report["soft_gate"]["blocking"])

    def test_explicit_condition_is_not_covered_by_an_unrelated_generic_outcome(self):
        payload = valid_payload()
        payload["testCase"]["procedure"] = [
            "비활성 상태 조건을 선택해 사용자 조회를 실행한다",
        ]
        payload["testCase"]["preconditions"] = [
            "비활성 사용자 데이터가 준비되어 있어야 한다",
        ]
        payload["testCase"]["expectedResult"] = "삭제된 메뉴가 탐색 목록에서 제외된다"
        payload["testResult"]["testDetails"] = [
            "삭제된 메뉴가 탐색 목록에서 제외되는지 확인한다",
        ]
        payload["testResult"]["resultChecks"] = ["삭제 메뉴 제외 결과 확인"]

        report = build_quality_report(
            payload,
            change_notes=["비활성 사용자는 조회 결과에서 제외"],
        )

        self.assertFalse(report["explicit_scenarios"]["inactive"]["covered"])
        self.assertTrue(
            any(
                issue.get("code") == "uncovered_explicit_scenario"
                and issue.get("scenario") == "inactive"
                for issue in report["issues"]
            )
        )

    def test_manifest_only_file_path_signal_is_not_a_required_scenario(self):
        for note in (
            "삭제: api/kpi/orgSelectApi.ts",
            "삭제 C:\\Project Folder\\api\\orgSelectApi.ts",
        ):
            with self.subTest(note=note):
                report = build_quality_report(valid_payload(), change_notes=[note])

                self.assertTrue(report["scenario_categories"]["deletion"]["detected"])
                self.assertFalse(report["scenario_categories"]["deletion"]["required"])
                self.assertFalse(
                    any(
                        issue.get("severity") == "required"
                        for issue in report["issues"]
                        if issue.get("code")
                        in {"uncovered_scenario_category", "uncovered_explicit_scenario"}
                    )
                )
                self.assertFalse(report["soft_gate"]["blocking"])

    def test_clean_payload_without_change_signals_can_pass_soft_gate(self):
        report = build_quality_report(valid_payload())

        self.assertEqual(report["score"], 100)
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["soft_gate"]["status"], "pass")
        self.assertEqual(report["covered_anchors"], [])
        self.assertEqual(report["uncovered_anchors"], [])


if __name__ == "__main__":
    unittest.main()
