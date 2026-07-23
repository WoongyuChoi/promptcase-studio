import json
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import patch

from promptcase_studio.config import load_settings
from promptcase_studio.models import AnalysisRequest, ChangeItem, ContextFile, ScanBundle
from promptcase_studio.pipeline import (
    PipelinePausedError,
    _document_title,
    _program_category,
    _program_info,
    _quality_sources_for_bundle,
    run_pipeline,
)
from promptcase_studio.providers.mock import MockProvider
from promptcase_studio.providers.base import (
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from promptcase_studio.response_parser import ResponseValidationError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_project"
TEMP_ROOT = PROJECT_ROOT / "tmp" / "tests"


class PipelineTests(unittest.TestCase):
    def test_quality_sources_require_primary_diff_support_for_broad_request_scenarios(self):
        root = str(FIXTURE_ROOT.resolve())
        bundle = ScanBundle(
            changes=[
                ChangeItem(
                    root,
                    "src/pages/MKPIM1110.tsx",
                    "변경",
                    "git-history",
                    True,
                    commit="target123",
                    relevance_score=80,
                )
            ],
            contexts=[
                ContextFile(
                    root,
                    "src/pages/MKPIM1110.tsx",
                    "diff",
                    "선택 커밋",
                    1000,
                    "if (!hasChanges) alert('저장할 변경 사항이 없습니다')",
                )
            ],
            change_notes=["feat: 저장 시 변경된 사항이 없으면 Alert 처리"],
        )
        request = (
            "사업계획관리시스템 구축을 위한 기반사항 반영 요청\n"
            "권한, 메뉴, 사용자 기반 사항 변경 요청\n"
            "저장할 변경 사항이 없을 때 Alert 처리 요청"
        )

        sources = _quality_sources_for_bundle(request, bundle)

        self.assertIn(bundle.change_notes[0], sources)
        self.assertTrue(any("Alert 처리" in source for source in sources))
        self.assertFalse(any("권한" in source for source in sources))

    def test_pipeline_rejects_incomplete_or_reversed_date_range_before_creating_a_run(self):
        settings = deepcopy(load_settings())
        settings["runDirectory"] = str(TEMP_ROOT / "invalid-date-range" / "runs")
        base = dict(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )

        with self.assertRaisesRegex(ValueError, "시작일과 종료일"):
            run_pipeline(
                AnalysisRequest(**base, date_from=date(2026, 7, 1), date_to=None),
                settings,
            )
        with self.assertRaisesRegex(ValueError, "종료일은 시작일보다"):
            run_pipeline(
                AnalysisRequest(
                    **base,
                    date_from=date(2026, 7, 22),
                    date_to=date(2026, 7, 1),
                ),
                settings,
            )

    def test_document_title_prefers_structured_value_and_falls_back_to_request_title(self):
        request = AnalysisRequest(
            project_roots=[Path("C:/Project/sample/src")],
            manual_changes="",
            request_text=(
                "요청제목\n"
                "사업계획관리시스템 구축을 위한 기반사항 반영 요청\n\n"
                "요청내용\n기반 사항 변경"
            ),
            environment="online",
        )
        self.assertEqual(_document_title({"documentTitle": "KPI 관리 포털"}, request), "KPI_관리_포털")
        self.assertEqual(_document_title({"documentTitle": ""}, request), "사업계획관리시스템")
        self.assertEqual(
            _document_title({"documentTitle": "사업계획관리시스템 20260722"}, request),
            "사업계획관리시스템",
        )

    def test_program_project_labels_use_selected_analysis_root_project_name(self):
        changes = [
            ChangeItem(
                "C:/Project/product/poswrk-backend-api",
                "src/main/java/com/sample/base/web/LocalSessionProvider.java",
                "변경",
                "manual",
                True,
            ),
            ChangeItem(
                "C:/Project/product/poswrk-backend-api",
                "README.md",
                "변경",
                "manual",
                True,
            ),
            ChangeItem(
                "C:/Project/ui-vibe-lab-publishing-02/src",
                ".env.local",
                "변경",
                "manual",
                False,
            ),
            ChangeItem(
                "C:/Project/ui-vibe-lab-publishing-02/src",
                "pages/PlanPage.tsx",
                "변경",
                "manual",
                True,
            ),
        ]
        rows = _program_info(changes)
        labels = {row["program"]: row["project"] for row in rows}

        self.assertEqual(labels["LocalSessionProvider.java"], "poswrk-backend-api")
        self.assertEqual(labels["README.md"], "poswrk-backend-api")
        self.assertEqual(labels[".env.local"], "ui-vibe-lab-publishing-02")
        self.assertEqual(labels["PlanPage.tsx"], "ui-vibe-lab-publishing-02")

    def test_program_project_labels_are_independent_per_root_and_handle_drive_root(self):
        changes = [
            ChangeItem(
                "C:/Project/alpha/src",
                "pages/Alpha.tsx",
                "변경",
                "manual",
                True,
            ),
            ChangeItem(
                "C:/Project/beta-api",
                "src/main/java/Beta.java",
                "변경",
                "manual",
                True,
            ),
            ChangeItem(
                "C:/",
                "orphan.txt",
                "변경",
                "manual",
                True,
            ),
        ]

        rows = _program_info(changes)
        labels = {row["program"]: row["project"] for row in rows}

        self.assertEqual(labels["Alpha.tsx"], "alpha")
        self.assertEqual(labels["Beta.java"], "beta-api")
        self.assertEqual(labels["orphan.txt"], "프로젝트")
        self.assertTrue(all(" - Backend" not in label for label in labels.values()))
        self.assertTrue(all(" - Frontend" not in label for label in labels.values()))

    def test_program_project_label_walks_up_from_deep_source_folder(self):
        rows = _program_info(
            [
                ChangeItem(
                    "C:/Project/product/poswrk-backend-api/src/main/java",
                    "com/sample/UserService.java",
                    "변경",
                    "manual",
                    True,
                ),
                ChangeItem(
                    "C:/Project/ui-vibe-lab-publishing-02/src/pages",
                    "kpi/MKPIM1111.tsx",
                    "신규",
                    "manual",
                    True,
                ),
            ]
        )

        labels = {row["program"]: row["project"] for row in rows}
        self.assertEqual(labels["UserService.java"], "poswrk-backend-api")
        self.assertEqual(labels["MKPIM1111.tsx"], "ui-vibe-lab-publishing-02")

    def test_program_project_label_does_not_escape_selected_standalone_root(self):
        rows = _program_info(
            [
                ChangeItem(
                    str(FIXTURE_ROOT.resolve()),
                    "src/service/UserService.java",
                    "변경",
                    "manual",
                    True,
                )
            ]
        )

        self.assertEqual(rows[0]["project"], "sample_project")

    def test_program_info_dynamically_classifies_sql_and_work_content(self):
        rows = _program_info(
            [
                ChangeItem(
                    "C:/Project/accounting",
                    "src/main/java/BalanceService.java",
                    "변경",
                    "manual",
                    True,
                ),
                ChangeItem(
                    "C:/Project/accounting",
                    "src/main/resources/mapper/BalanceMapper.xml",
                    "신규",
                    "manual",
                    True,
                ),
                ChangeItem(
                    "C:/Project/accounting",
                    "db/drop_legacy_view.sql",
                    "삭제",
                    "manual",
                    False,
                ),
            ],
            "통합정산시스템",
        )

        self.assertEqual(rows[0]["category"], "통합정산시스템")
        self.assertEqual(rows[0]["detailCategory"], "Program")
        self.assertEqual(
            rows[0]["workContent"],
            "요건 변경에 따른 개발 프로그램 수정",
        )
        self.assertEqual(rows[1]["detailCategory"], "SQL")
        self.assertEqual(
            rows[1]["workContent"],
            "요건 변경에 따른 신규 SQL 추가",
        )
        self.assertEqual(rows[2]["detailCategory"], "SQL")
        self.assertEqual(
            rows[2]["workContent"],
            "요건 변경에 따른 불필요 SQL 삭제",
        )

    def test_program_category_uses_document_system_and_keeps_legacy_default(self):
        request = AnalysisRequest(
            project_roots=[Path("C:/Project/sample")],
            manual_changes="",
            request_text="사용자 조회 조건을 변경한다",
            environment="online",
        )

        self.assertEqual(
            _program_category({"documentTitle": "인사관리시스템"}, request),
            "인사관리시스템",
        )
        self.assertEqual(
            _program_category({"documentTitle": ""}, request),
            "채산관리시스템",
        )

    def test_mock_pipeline_runs_without_network_and_generates_xlsx(self):
        case_directory = TEMP_ROOT / "pipeline"
        case_directory.mkdir(parents=True, exist_ok=True)
        settings = deepcopy(load_settings())
        settings["mockMode"] = True
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        settings["outputDirectory"] = str(case_directory / "outputs")
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            date_from=None,
            date_to=None,
            include_git=False,
        )
        logs = []
        result = run_pipeline(request, settings, log=lambda level, message: logs.append((level, message)))
        self.assertTrue(result.document_path.exists())
        self.assertEqual(result.document_path.parent, result.run_directory)
        self.assertEqual(result.document_path.name, "unit-test-preview.xlsx")
        self.assertRegex(result.suggested_filename, r"^sample_project_단위테스트_\d{8}_\d{6}\.xlsx$")
        self.assertTrue((result.run_directory / "change_manifest.json").exists())
        self.assertTrue((result.run_directory / "context_bundle.md").exists())
        self.assertTrue((result.run_directory / "evidence.txt").exists())
        self.assertTrue((result.run_directory / "quality-review.json").exists())
        self.assertTrue((result.run_directory / "prompt.quality-review.md").exists())
        self.assertTrue((result.run_directory / "prompt.release-note.md").exists())
        self.assertTrue((result.run_directory / "release-note.json").exists())
        self.assertTrue((result.run_directory / "release-note.txt").exists())
        self.assertEqual(
            result.release_note_path,
            result.run_directory / "release-note.txt",
        )
        self.assertTrue(result.release_note_subject)
        self.assertTrue(result.release_note_body.startswith("안녕하세요"))
        self.assertTrue(result.release_note_body.endswith("감사합니다."))
        self.assertTrue((result.run_directory / "scope_decision.json").exists())
        self.assertTrue((result.run_directory / "pipeline.log").exists())
        document = json.loads((result.run_directory / "document.json").read_text(encoding="utf-8"))
        self.assertEqual(document["programInfo"][0]["project"], "sample_project")
        self.assertIn("[CONTEXT]", (result.run_directory / "pipeline.log").read_text(encoding="utf-8"))
        self.assertTrue(any(level == "MOCK" for level, _ in logs))
        self.assertTrue(any(level == "CONTEXT" for level, _ in logs))
        self.assertTrue(any(level == "TRACE" and "응답 미리보기" in message for level, message in logs))

    def test_invalid_structured_response_is_reprompted_and_preserved(self):
        class InvalidThenValidProvider:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, log=None, on_chunk=None):
                self.calls += 1
                if self.calls == 1:
                    return '{"unexpected": true}'
                return MockProvider().generate(prompt, log=log, on_chunk=on_chunk)

        case_directory = TEMP_ROOT / "pipeline-validation-retry"
        case_directory.mkdir(parents=True, exist_ok=True)
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = False
        settings["responseValidationAttempts"] = 1
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        provider = InvalidThenValidProvider()
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )
        logs = []
        with patch("promptcase_studio.pipeline.create_provider", return_value=provider):
            result = run_pipeline(request, settings, log=lambda level, message: logs.append((level, message)))
        self.assertEqual(provider.calls, 3)
        self.assertTrue((result.run_directory / "response.attempt-1.invalid.txt").exists())
        self.assertTrue(any(level == "RETRY" and "계약 오류" in message for level, message in logs))

    def test_required_user_scenario_is_blocked_even_when_ai_review_is_disabled(self):
        class MissingRequiredScenarioProvider:
            def generate(self, prompt, log=None, on_chunk=None):
                payload = json.loads(MockProvider().generate(prompt, log=log, on_chunk=on_chunk))
                payload["testCase"]["procedure"] = [
                    "활성 상태 조건을 선택해 사용자 조회를 실행한다"
                ]
                payload["testCase"]["preconditions"] = [
                    "활성 상태의 사용자 데이터가 준비되어 있어야 한다"
                ]
                payload["testCase"]["testData"] = "활성 상태 사용자 데이터를 사용한다"
                payload["testCase"]["expectedResult"] = "활성 사용자가 조회 결과에 표시된다"
                payload["testResult"]["testDetails"] = [
                    "활성 상태 사용자가 조회 결과에 표시되는지 확인한다"
                ]
                payload["testResult"]["resultChecks"] = ["활성 상태 사용자 조회 결과 확인"]
                return json.dumps(payload, ensure_ascii=False)

        case_directory = TEMP_ROOT / "pipeline-required-scenario-without-review"
        case_directory.mkdir(parents=True, exist_ok=True)
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = False
        settings["qualityGateMode"] = "strict"
        settings["responseValidationAttempts"] = 1
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="비활성 사용자는 조회 결과에서 제외되는지 확인한다",
            environment="online",
            include_git=False,
        )

        with (
            patch(
                "promptcase_studio.pipeline.create_provider",
                return_value=MissingRequiredScenarioProvider(),
            ),
            self.assertRaises(ResponseValidationError),
        ):
            run_pipeline(request, settings)

    def test_retry_prompt_includes_all_independent_validation_errors(self):
        class MultipleErrorsThenValidProvider:
            def __init__(self):
                self.prompts = []

            def generate(self, prompt, log=None, on_chunk=None):
                self.prompts.append(prompt)
                valid_response = MockProvider().generate(prompt, log=log, on_chunk=on_chunk)
                if len(self.prompts) > 1:
                    return valid_response
                payload = json.loads(valid_response)
                payload["documentTitle"] = "재무관리시스템"
                payload["testCase"]["testData"] = "INACTIVE 상태의 사용자 데이터를 사용한다"
                return json.dumps(payload, ensure_ascii=False)

        case_directory = TEMP_ROOT / "pipeline-aggregate-validation-retry"
        case_directory.mkdir(parents=True, exist_ok=True)
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = False
        settings["responseValidationAttempts"] = 2
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        provider = MultipleErrorsThenValidProvider()
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )
        with patch("promptcase_studio.pipeline.create_provider", return_value=provider):
            run_pipeline(request, settings)

        self.assertEqual(len(provider.prompts), 3)
        correction_prompt = provider.prompts[1]
        self.assertIn("응답 계약 오류 2건", correction_prompt)
        self.assertIn("documentTitle 값이 입력 근거에서 확인되지 않습니다: 재무관리시스템", correction_prompt)
        self.assertIn("문안의 기술 식별자 또는 코드값이 입력 근거에서 확인되지 않습니다: INACTIVE", correction_prompt)

    def test_quality_review_replaces_implementation_precondition_with_better_draft(self):
        class QualityImprovingProvider:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, log=None, on_chunk=None):
                self.calls += 1
                payload = json.loads(MockProvider().generate(prompt, log=log, on_chunk=on_chunk))
                if self.calls == 1:
                    payload["testCase"]["preconditions"][0] = (
                        "UserService 서비스 객체가 생성되어 있어야 한다"
                    )
                return json.dumps(payload, ensure_ascii=False)

        case_directory = TEMP_ROOT / "pipeline-quality-review"
        case_directory.mkdir(parents=True, exist_ok=True)
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = True
        settings["qualityReviewValidationAttempts"] = 1
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        provider = QualityImprovingProvider()
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )
        logs = []
        with patch("promptcase_studio.pipeline.create_provider", return_value=provider):
            result = run_pipeline(
                request,
                settings,
                log=lambda level, message: logs.append((level, message)),
            )

        quality = json.loads(
            (result.run_directory / "quality-review.json").read_text(encoding="utf-8")
        )
        document = json.loads((result.run_directory / "document.json").read_text(encoding="utf-8"))
        self.assertEqual(provider.calls, 3)
        self.assertEqual(quality["selected"], "review")
        self.assertNotIn("서비스 객체", " ".join(document["testCase"]["preconditions"]))
        self.assertTrue(any(level == "REVIEW" for level, _message in logs))

    def test_daily_quota_during_review_preserves_draft_and_quality_diagnostics(self):
        class QuotaAfterDraftProvider:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, log=None, on_chunk=None):
                self.calls += 1
                if self.calls > 1:
                    raise ProviderRateLimitError(
                        "Gemini",
                        retry_after_seconds=50,
                        daily_quota=True,
                        free_tier=True,
                        quota_value="20",
                        model="gemini-3.6-flash",
                    )
                payload = json.loads(MockProvider().generate(prompt, log=log, on_chunk=on_chunk))
                payload["testCase"]["preconditions"][0] = (
                    "UserService 서비스 객체가 생성되어 있어야 한다"
                )
                return json.dumps(payload, ensure_ascii=False)

        case_directory = TEMP_ROOT / "pipeline-quality-review-quota"
        run_root = case_directory / "runs"
        case_directory.mkdir(parents=True, exist_ok=True)
        before = set(run_root.iterdir()) if run_root.exists() else set()
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = True
        settings["qualityReviewPasses"] = 1
        settings["qualityReviewValidationAttempts"] = 1
        settings["qualityGateMode"] = "strict"
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(run_root)
        provider = QuotaAfterDraftProvider()
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )
        logs = []

        with (
            patch("promptcase_studio.pipeline.create_provider", return_value=provider),
            self.assertRaisesRegex(PipelinePausedError, "일일 요청 한도"),
        ):
            run_pipeline(
                request,
                settings,
                log=lambda level, message: logs.append((level, message)),
            )

        created = set(run_root.iterdir()) - before
        self.assertEqual(len(created), 1)
        run_directory = created.pop()
        quality = json.loads(
            (run_directory / "quality-review.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provider.calls, 2)
        self.assertTrue((run_directory / "response.draft.txt").exists())
        self.assertTrue(quality["interruption"]["dailyQuota"])
        self.assertTrue(any(level == "QUOTA" for level, _message in logs))
        self.assertTrue(any(level == "PAUSED" for level, _message in logs))
        self.assertFalse(any(level == "ERROR" for level, _message in logs))

    def test_best_effort_gate_exports_draft_when_review_hits_quota(self):
        class QuotaAfterDraftProvider:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, log=None, on_chunk=None):
                self.calls += 1
                if self.calls > 1:
                    raise ProviderRateLimitError(
                        "Gemini",
                        daily_quota=True,
                        model="gemini-3.6-flash",
                    )
                payload = json.loads(MockProvider().generate(prompt, log=log, on_chunk=on_chunk))
                payload["testCase"]["preconditions"][0] = (
                    "UserService 서비스 객체가 생성되어 있어야 한다"
                )
                return json.dumps(payload, ensure_ascii=False)

        case_directory = TEMP_ROOT / "pipeline-quality-quota-best-effort"
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = True
        settings["qualityReviewPasses"] = 1
        settings["qualityReviewValidationAttempts"] = 1
        settings["qualityGateMode"] = "best_effort"
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        provider = QuotaAfterDraftProvider()
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )
        logs = []

        with patch("promptcase_studio.pipeline.create_provider", return_value=provider):
            result = run_pipeline(
                request,
                settings,
                log=lambda level, message: logs.append((level, message)),
            )

        quality = json.loads(
            (result.run_directory / "quality-review.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result.quality_status, "review_required")
        self.assertTrue(result.document_path.exists())
        self.assertTrue(quality["interruption"]["dailyQuota"])
        self.assertTrue(any(level == "QUOTA" for level, _message in logs))
        self.assertTrue(any(level == "DONE" for level, _message in logs))
        self.assertFalse(any(level in {"ERROR", "PAUSED"} for level, _message in logs))

    def test_best_effort_gate_exports_draft_when_review_hits_503(self):
        class UnavailableAfterDraftProvider:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, log=None, on_chunk=None):
                self.calls += 1
                if self.calls > 1:
                    raise ProviderUnavailableError(
                        "Gemini",
                        status_code=503,
                        detail="This model is currently experiencing high demand.",
                    )
                return MockProvider().generate(prompt, log=log, on_chunk=on_chunk)

        case_directory = TEMP_ROOT / "pipeline-quality-503-best-effort"
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = True
        settings["qualityReviewPasses"] = 1
        settings["qualityReviewValidationAttempts"] = 1
        settings["qualityGateMode"] = "best_effort"
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        provider = UnavailableAfterDraftProvider()
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경 src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )
        logs = []

        with patch("promptcase_studio.pipeline.create_provider", return_value=provider):
            result = run_pipeline(
                request,
                settings,
                log=lambda level, message: logs.append((level, message)),
            )

        quality = json.loads(
            (result.run_directory / "quality-review.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provider.calls, 2)
        self.assertTrue(result.document_path.exists())
        self.assertEqual(quality["selected"], "draft")
        self.assertEqual(quality["interruption"]["type"], "unavailable")
        self.assertTrue(any(level == "WARN" and "현재 최선의 초안" in message for level, message in logs))
        self.assertTrue(any(level == "DONE" for level, _message in logs))
        self.assertFalse(any(level == "ERROR" for level, _message in logs))

    def test_best_effort_gate_exports_valid_draft_when_review_contract_fails(self):
        class InvalidReviewAfterDraftProvider:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, log=None, on_chunk=None):
                self.calls += 1
                payload = json.loads(MockProvider().generate(prompt, log=log, on_chunk=on_chunk))
                payload["testCase"]["preconditions"][0] = (
                    "UserService 서비스 객체가 생성되어 있어야 한다"
                )
                if self.calls > 1:
                    payload["testCase"]["procedure"][0] = "저장 버튼 선택"
                return json.dumps(payload, ensure_ascii=False)

        case_directory = TEMP_ROOT / "pipeline-quality-best-effort"
        run_root = case_directory / "runs"
        case_directory.mkdir(parents=True, exist_ok=True)
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = True
        settings["qualityReviewPasses"] = 2
        settings["qualityReviewValidationAttempts"] = 1
        settings["qualityGateMode"] = "best_effort"
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(run_root)
        provider = InvalidReviewAfterDraftProvider()
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )
        logs = []

        with patch("promptcase_studio.pipeline.create_provider", return_value=provider):
            result = run_pipeline(
                request,
                settings,
                log=lambda level, message: logs.append((level, message)),
            )

        quality = json.loads(
            (result.run_directory / "quality-review.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provider.calls, 3)
        self.assertEqual(result.quality_status, "review_required")
        self.assertGreater(result.quality_critical_count, 0)
        self.assertTrue(result.document_path.exists())
        self.assertEqual(quality["gateMode"], "best_effort")
        self.assertTrue(any(level == "WARN" for level, _message in logs))
        self.assertTrue(any(level == "DONE" for level, _message in logs))
        self.assertFalse(any(level == "ERROR" for level, _message in logs))

    def test_quality_review_retries_when_explicit_user_scenario_is_still_missing(self):
        class ScenarioImprovingProvider:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, log=None, on_chunk=None):
                self.calls += 1
                payload = json.loads(MockProvider().generate(prompt, log=log, on_chunk=on_chunk))
                if self.calls <= 2:
                    payload["testCase"]["procedure"] = [
                        "활성 상태 조건을 선택해 사용자 조회를 실행한다"
                    ]
                    payload["testCase"]["preconditions"] = [
                        "활성 상태의 사용자 데이터가 준비되어 있어야 한다"
                    ]
                    payload["testCase"]["testData"] = "활성 상태 사용자 데이터를 사용한다"
                    payload["testCase"]["expectedResult"] = "활성 사용자가 조회 결과에 표시된다"
                    payload["testResult"]["testDetails"] = [
                        "활성 상태 사용자가 조회 결과에 표시되는지 확인한다"
                    ]
                    payload["testResult"]["resultChecks"] = [
                        "활성 상태 사용자 조회 결과 확인"
                    ]
                return json.dumps(payload, ensure_ascii=False)

        case_directory = TEMP_ROOT / "pipeline-quality-scenario-retry"
        case_directory.mkdir(parents=True, exist_ok=True)
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["qualityReviewEnabled"] = True
        settings["qualityReviewPasses"] = 2
        settings["qualityReviewValidationAttempts"] = 1
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "unittest_template.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        provider = ScenarioImprovingProvider()
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 상태와 비활성 상태 조회조건을 각각 검증한다",
            environment="online",
            include_git=False,
        )

        with patch("promptcase_studio.pipeline.create_provider", return_value=provider):
            result = run_pipeline(request, settings)

        quality = json.loads(
            (result.run_directory / "quality-review.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provider.calls, 4)
        self.assertEqual(quality["selected"], "review-2")
        self.assertEqual(quality["selectedReport"]["soft_gate"]["blocking"], False)
        self.assertTrue((result.run_directory / "prompt.quality-review-2.md").exists())

    def test_provider_failure_is_recorded_in_the_run_log(self):
        class FailingProvider:
            def generate(self, *_args, **_kwargs):
                raise ProviderError("synthetic provider failure")

        case_directory = TEMP_ROOT / "pipeline-provider-failure"
        case_directory.mkdir(parents=True, exist_ok=True)
        run_root = case_directory / "runs"
        before = set(run_root.iterdir()) if run_root.exists() else set()
        settings = deepcopy(load_settings())
        settings["mockMode"] = False
        settings["runDirectory"] = str(run_root)
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            include_git=False,
        )
        with (
            patch("promptcase_studio.pipeline.create_provider", return_value=FailingProvider()),
            self.assertRaisesRegex(ProviderError, "synthetic provider failure"),
        ):
            run_pipeline(request, settings)

        created = set(run_root.iterdir()) - before
        self.assertEqual(len(created), 1)
        log_text = (created.pop() / "pipeline.log").read_text(encoding="utf-8")
        self.assertIn("[ERROR] AI 응답 생성 또는 검증 실패", log_text)
        self.assertIn("synthetic provider failure", log_text)


if __name__ == "__main__":
    unittest.main()
