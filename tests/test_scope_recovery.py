from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from promptcase_studio.scanner import (
    _changed_diff_hunks,
    _changed_diff_lines,
    collect_changes,
)


TEMP_ROOT = Path(__file__).resolve().parent.parent / "tmp" / "tests" / "scope-recovery"


def _git(repository: Path, *args: str, authored_at: str | None = None) -> str:
    environment = os.environ.copy()
    if authored_at:
        environment["GIT_AUTHOR_DATE"] = authored_at
        environment["GIT_COMMITTER_DATE"] = authored_at
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _write(repository: Path, relative_path: str, text: str) -> None:
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repository: Path, message: str, authored_at: str) -> None:
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", message, authored_at=authored_at)


def _create_repository() -> Path:
    repository = TEMP_ROOT / uuid4().hex
    repository.mkdir(parents=True)
    _git(repository, "init")
    _git(repository, "config", "user.name", "Promptcase Test")
    _git(repository, "config", "user.email", "promptcase@example.invalid")
    return repository


def _settings() -> dict[str, object]:
    return {
        "maxCandidateFiles": 1000,
        "maxSelectedCommits": 3,
        "maxSelectedFiles": 24,
        "commitEvidenceShortlist": 12,
        "maxCommitEvidenceChars": 20000,
        "scopeRecoveryEnabled": True,
        "scopeRecoveryDays": 21,
        "scopeRecoveryCommitDistanceDays": 7,
        "scopeRecoveryMaxCommits": 80,
        "scopeRecoveryMaxCandidateFiles": 80,
        "scopeRecoveryMaxFiles": 12,
        "maxSourceScanChars": 120000,
    }


def _collect(
    repository: Path,
    manual_path: str,
    request_text: str,
    selected_date: date = date(2026, 7, 10),
) -> dict[str, object]:
    changes, _indexes, _excluded, _truncated = collect_changes(
        [repository],
        f"변경: {manual_path}",
        selected_date,
        selected_date,
        True,
        _settings(),
        request_text=request_text,
    )
    return {item.path: item for item in changes}


class ScopeRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(TEMP_ROOT, ignore_errors=True)

    def test_diff_evidence_excludes_headers_but_preserves_changed_hunk_context(self):
        diff = """diff --git a/src/PlanVo.java b/src/PlanVo.java
--- a/src/PlanVo.java
+++ b/src/PlanVo.java
@@ -10,3 +10,3 @@
 PlanVo calculate(PlanVo value) {
-    return oldRate;
+    return newRate;
 }
"""

        changed_lines = _changed_diff_lines(diff)
        changed_hunks = _changed_diff_hunks(diff)

        self.assertNotIn("src/PlanVo.java", changed_lines)
        self.assertNotIn("PlanVo", changed_lines)
        self.assertIn("return oldRate", changed_lines)
        self.assertIn("return newRate", changed_lines)
        self.assertIn("PlanVo calculate", changed_hunks)

    def test_recovers_java_service_changed_before_manually_listed_vo(self):
        repository = _create_repository()
        vo_path = "src/main/java/com/example/plan/PlanVo.java"
        service_path = "src/main/java/com/example/plan/PlanServiceImpl.java"
        _write(repository, vo_path, "package com.example.plan;\nclass PlanVo { int value; }\n")
        _write(
            repository,
            service_path,
            "package com.example.plan;\n"
            "class PlanServiceImpl {\n"
            "  int calculate(PlanVo vo) {\n"
            "    return vo.value;\n"
            "  }\n"
            "}\n",
        )
        _commit(repository, "initial plan module", "2026-07-01T09:00:00+09:00")
        _write(
            repository,
            service_path,
            "package com.example.plan;\n"
            "class PlanServiceImpl {\n"
            "  int calculate(PlanVo vo) {\n"
            "    return vo.value * 100;\n"
            "  }\n"
            "}\n",
        )
        _commit(repository, "fix plan achievement calculation", "2026-07-08T09:00:00+09:00")
        _write(
            repository,
            vo_path,
            "package com.example.plan;\nclass PlanVo { int value; int target; }\n",
        )
        _commit(repository, "change plan value object", "2026-07-10T09:00:00+09:00")

        changes = _collect(
            repository,
            vo_path,
            "사업계획 달성률 계산 변경",
            date(2026, 7, 12),
        )

        self.assertIn(service_path, changes)
        self.assertEqual(changes[service_path].source, "git-related-recovery")
        self.assertIn("diff에서 참조 식별자 확인", changes[service_path].selection_reason)
        self.assertTrue(changes[vo_path].commit)
        self.assertIn("보완 앵커", changes[vo_path].selection_reason)

    def test_does_not_promote_service_when_only_unrelated_method_changed(self):
        repository = _create_repository()
        vo_path = "src/main/java/com/example/plan/PlanVo.java"
        service_path = "src/main/java/com/example/plan/PlanServiceImpl.java"
        filler = "".join(f"  int helper{index}() {{ return {index}; }}\n" for index in range(12))
        _write(repository, vo_path, "package com.example.plan;\nclass PlanVo { int value; }\n")
        _write(
            repository,
            service_path,
            "package com.example.plan;\n"
            "class PlanServiceImpl {\n"
            "  int calculate(PlanVo vo) { return vo.value; }\n"
            f"{filler}"
            '  String audit() { return "old"; }\n'
            "}\n",
        )
        _commit(repository, "initial plan module", "2026-07-01T09:00:00+09:00")
        _write(
            repository,
            service_path,
            "package com.example.plan;\n"
            "class PlanServiceImpl {\n"
            "  int calculate(PlanVo vo) { return vo.value; }\n"
            f"{filler}"
            '  String audit() { return "new"; }\n'
            "}\n",
        )
        _commit(repository, "chore audit label", "2026-07-08T09:00:00+09:00")
        _write(
            repository,
            vo_path,
            "package com.example.plan;\nclass PlanVo { int value; int target; }\n",
        )
        _commit(repository, "change plan value object", "2026-07-10T09:00:00+09:00")

        changes = _collect(repository, vo_path, "사업계획 달성률 계산 변경")

        self.assertNotIn(service_path, changes)

    def test_does_not_promote_unchanged_related_service(self):
        repository = _create_repository()
        vo_path = "src/main/java/com/example/plan/PlanVo.java"
        service_path = "src/main/java/com/example/plan/PlanServiceImpl.java"
        _write(repository, vo_path, "package com.example.plan;\nclass PlanVo { int value; }\n")
        _write(
            repository,
            service_path,
            "package com.example.plan;\n"
            "class PlanServiceImpl { int calculate(PlanVo vo) { return vo.value; } }\n",
        )
        _commit(repository, "initial plan module", "2026-07-01T09:00:00+09:00")
        _write(
            repository,
            vo_path,
            "package com.example.plan;\nclass PlanVo { int value; int target; }\n",
        )
        _commit(repository, "change plan value object", "2026-07-10T09:00:00+09:00")

        changes = _collect(repository, vo_path, "사업계획 달성률 계산 변경")

        self.assertNotIn(service_path, changes)

    def test_recovers_explicit_dependencies_across_supported_languages(self):
        cases = (
            (
                "python",
                "app/models/order.py",
                "app/services/order_service.py",
                "class Order:\n    amount = 1\n",
                "from app.models.order import Order\n\ndef total(order: Order):\n    return order.amount\n",
                "from app.models.order import Order\n\ndef total(order: Order):\n    return order.amount * 100\n",
                "class Order:\n    amount = 1\n    target = 2\n",
            ),
            (
                "typescript",
                "src/types/order.ts",
                "src/services/orderService.ts",
                "export type Order = { amount: number };\n",
                "import { Order } from '../types/order';\n"
                "export const total = (order: Order) => order.amount;\n",
                "import { Order } from '../types/order';\n"
                "export const total = (order: Order) => order.amount * 100;\n",
                "export type Order = { amount: number; target: number };\n",
            ),
            (
                "sql",
                "db/tables/customer.sql",
                "db/views/customer_summary.sql",
                "CREATE TABLE TB_CUSTOMER (AMOUNT NUMBER);\n",
                "CREATE VIEW VW_CUSTOMER_SUMMARY AS "
                "SELECT AMOUNT FROM TB_CUSTOMER;\n",
                "CREATE VIEW VW_CUSTOMER_SUMMARY AS "
                "SELECT AMOUNT * 100 AS RATE FROM TB_CUSTOMER;\n",
                "ALTER TABLE TB_CUSTOMER ADD TARGET NUMBER;\n",
            ),
        )
        for language, anchor_path, dependent_path, anchor, dependent, changed, final_anchor in cases:
            with self.subTest(language=language):
                repository = _create_repository()
                _write(repository, anchor_path, anchor)
                _write(repository, dependent_path, dependent)
                _commit(repository, f"initial {language} module", "2026-07-01T09:00:00+09:00")
                _write(repository, dependent_path, changed)
                _commit(
                    repository,
                    f"fix {language} order calculation",
                    "2026-07-08T09:00:00+09:00",
                )
                _write(repository, anchor_path, final_anchor)
                _commit(
                    repository,
                    f"change {language} order contract",
                    "2026-07-10T09:00:00+09:00",
                )

                changes = _collect(repository, anchor_path, "주문 금액 계산 변경")

                self.assertIn(dependent_path, changes)
                self.assertEqual(
                    changes[dependent_path].source,
                    "git-related-recovery",
                )

    def test_feature_can_be_disabled_for_conservative_operation(self):
        repository = _create_repository()
        vo_path = "src/plan/PlanVo.java"
        service_path = "src/plan/PlanServiceImpl.java"
        _write(repository, vo_path, "class PlanVo { int value; }\n")
        _write(
            repository,
            service_path,
            "class PlanServiceImpl { int calculate(PlanVo vo) { return vo.value; } }\n",
        )
        _commit(repository, "initial", "2026-07-01T09:00:00+09:00")
        _write(
            repository,
            service_path,
            "class PlanServiceImpl { int calculate(PlanVo vo) { return vo.value * 100; } }\n",
        )
        _commit(repository, "fix plan calculation", "2026-07-08T09:00:00+09:00")
        _write(repository, vo_path, "class PlanVo { int value; int target; }\n")
        _commit(repository, "change plan vo", "2026-07-10T09:00:00+09:00")
        settings = _settings()
        settings["scopeRecoveryEnabled"] = False

        changes, _indexes, _excluded, _truncated = collect_changes(
            [repository],
            f"변경: {vo_path}",
            date(2026, 7, 10),
            date(2026, 7, 10),
            True,
            settings,
            request_text="사업계획 계산 변경",
        )

        self.assertNotIn(service_path, {item.path for item in changes})

    def test_pathless_input_recovers_one_coherent_multifile_commit_outside_date(self):
        repository = _create_repository()
        header_path = "src/order/OrderHeaderVo.java"
        line_path = "src/order/OrderLineVo.java"
        _write(repository, header_path, "class OrderHeaderVo { int amount; }\n")
        _write(repository, line_path, "class OrderLineVo { int amount; }\n")
        _write(repository, "src/audit/AuditLog.java", "class AuditLog {}\n")
        _commit(repository, "initialize sample project", "2026-07-01T09:00:00+09:00")
        _write(repository, header_path, "class OrderHeaderVo { int amount; int target; }\n")
        _write(repository, line_path, "class OrderLineVo { int amount; int target; }\n")
        _commit(repository, "change order value objects", "2026-07-08T09:00:00+09:00")

        changes, _indexes, _excluded, _truncated = collect_changes(
            [repository],
            "VO 2개 수정",
            date(2026, 7, 10),
            date(2026, 7, 10),
            True,
            _settings(),
            request_text="주문 VO 수정",
        )
        by_path = {item.path: item for item in changes}

        self.assertEqual(set(by_path), {header_path, line_path})
        self.assertTrue(
            all(item.source == "git-related-recovery" for item in by_path.values())
        )
        self.assertTrue(
            all("다중 파일 변경 군집" in item.selection_reason for item in by_path.values())
        )

    def test_pathless_subject_match_recovers_commit_when_paths_have_no_query_words(self):
        repository = _create_repository()
        page_path = "src/pages/MKPIM1110.tsx"
        company_page_path = "src/pages/MKPIM1111.tsx"
        utility_path = "src/utils/kpiMapSavePayload.ts"
        unrelated_path = "src/legacy/LegacyKpiMap.ts"
        _write(repository, "src/app.ts", "export const app = true;\n")
        _commit(repository, "initialize sample project", "2026-07-01T09:00:00+09:00")
        _write(
            repository,
            unrelated_path,
            "import { MKPIM1110 } from '../pages/MKPIM1110';\n"
            "import { MKPIM1111 } from '../pages/MKPIM1111';\n"
            "export const legacy = [MKPIM1110, MKPIM1111];\n",
        )
        _commit(
            repository,
            "refactor: legacy KPI map wiring",
            "2026-07-21T10:00:00+09:00",
        )
        for path in (page_path, company_page_path):
            _write(
                repository,
                path,
                "import { hasKpiMapSaveChanges } from '../utils/kpiMapSavePayload';\n"
                "if (!hasKpiMapSaveChanges()) alert('변경된 사항이 없습니다.');\n",
            )
        _write(
            repository,
            utility_path,
            "export const hasKpiMapSaveChanges = () => false;\n",
        )
        _commit(
            repository,
            "feat: 저장 시 변경된 사항이 없으면 Alert 처리",
            "2026-07-21T18:17:00+09:00",
        )
        _write(repository, "src/session/SessionProvider.ts", "export const session = true;\n")
        _commit(
            repository,
            "feat: canSave 권한 체크에 대한 Backend 구현",
            "2026-07-22T15:36:00+09:00",
        )

        changes, _indexes, _excluded, _truncated = collect_changes(
            [repository],
            "저장 시 변경된 사항이 없으면 Alert 처리",
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="사업계획관리시스템 기반사항 반영 요청",
        )
        by_path = {item.path: item for item in changes}

        self.assertEqual(
            set(by_path),
            {page_path, company_page_path, utility_path},
        )
        self.assertNotIn(unrelated_path, by_path)
        self.assertTrue(
            all(item.source == "git-related-recovery" for item in by_path.values())
        )
        self.assertTrue(
            all("커밋 문안·diff 직접 일치" in item.selection_reason for item in by_path.values())
        )

    def test_pathless_input_does_not_guess_from_single_unrelated_file(self):
        repository = _create_repository()
        vo_path = "src/order/OrderVo.java"
        _write(repository, vo_path, "class OrderVo { int amount; }\n")
        _write(repository, "src/audit/AuditLog.java", "class AuditLog { String value = \"a\"; }\n")
        _commit(repository, "initialize sample project", "2026-07-01T09:00:00+09:00")
        _write(repository, "src/audit/AuditLog.java", "class AuditLog { String value = \"b\"; }\n")
        _commit(repository, "chore audit label", "2026-07-08T09:00:00+09:00")

        changes, _indexes, _excluded, _truncated = collect_changes(
            [repository],
            "VO 수정",
            date(2026, 7, 10),
            date(2026, 7, 10),
            True,
            _settings(),
            request_text="주문 관련 수정",
        )

        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
