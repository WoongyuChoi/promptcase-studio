from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

from promptcase_studio.scanner import (
    _recover_related_git_changes,
    _recover_semantic_git_seeds,
    collect_changes,
)


TEMP_ROOT = (
    Path(__file__).resolve().parent.parent
    / "tmp"
    / "tests"
    / "scope-recovery-boundaries"
)


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


def _commit(repository: Path, message: str, authored_at: str) -> str:
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", message, authored_at=authored_at)
    return _git(repository, "rev-parse", "HEAD")


def _create_repository() -> Path:
    repository = TEMP_ROOT / uuid4().hex
    repository.mkdir(parents=True)
    _git(repository, "init")
    _git(repository, "config", "user.name", "Promptcase Test")
    _git(repository, "config", "user.email", "promptcase@example.invalid")
    return repository


def _settings(**overrides: object) -> dict[str, object]:
    settings: dict[str, object] = {
        "maxCandidateFiles": 1000,
        "maxSelectedCommits": 3,
        "maxSelectedFiles": 24,
        "commitEvidenceShortlist": 12,
        "maxCommitEvidenceChars": 20000,
        "scopeRecoveryEnabled": True,
        "scopeRecoveryDays": 21,
        "scopeRecoveryCommitDistanceDays": 7,
        "scopeRecoveryMaxCommits": 120,
        "scopeRecoveryMaxCandidateFiles": 160,
        "scopeRecoveryMaxFiles": 12,
        "maxSourceScanChars": 120000,
    }
    settings.update(overrides)
    return settings


class ScopeRecoveryBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(TEMP_ROOT, ignore_errors=True)

    def test_single_reference_does_not_promote_unrelated_changed_method(self):
        repository = _create_repository()
        vo_path = "src/types/PlanVo.ts"
        service_path = "src/services/PlanService.ts"
        filler = "".join(
            f"export const helper{index:02d} = () => {index};\n"
            for index in range(15)
        )
        _write(
            repository,
            vo_path,
            "export interface PlanVo { amount: number }\n",
        )
        _write(
            repository,
            service_path,
            "import type { PlanVo } from '../types/PlanVo';\n"
            "export const calculate = (value: PlanVo) => value.amount;\n"
            f"{filler}"
            "export const auditLabel = 'old';\n",
        )
        _commit(repository, "initialize plan module", "2026-07-01T09:00:00+09:00")
        _write(
            repository,
            service_path,
            "import type { PlanVo } from '../types/PlanVo';\n"
            "export const calculate = (value: PlanVo) => value.amount;\n"
            f"{filler}"
            "export const auditLabel = 'new';\n",
        )
        _commit(repository, "chore audit label", "2026-07-08T09:00:00+09:00")
        _write(
            repository,
            vo_path,
            "export interface PlanVo { amount: number; target: number }\n",
        )
        _commit(repository, "change plan contract", "2026-07-10T09:00:00+09:00")

        changes, _indexes, _excluded, _truncated = collect_changes(
            [repository],
            f"M {vo_path}",
            date(2026, 7, 10),
            date(2026, 7, 10),
            True,
            _settings(),
            request_text="Change the plan calculation contract.",
        )

        by_path = {item.path: item for item in changes}
        self.assertIn(vo_path, by_path)
        self.assertNotIn(
            service_path,
            by_path,
            "A direct import alone must not promote a file whose actual diff "
            "only changes an unrelated method or label.",
        )

    def test_equal_score_recovery_budget_round_robins_two_subroots(self):
        repository = _create_repository()
        roots = [repository / "frontend", repository / "backend"]
        seed_paths: dict[str, str] = {}
        for root_name in ("frontend", "backend"):
            type_name = f"{root_name.title()}PlanSeed"
            seed_path = f"{root_name}/src/shared/{type_name}.ts"
            seed_paths[root_name] = seed_path
            _write(
                repository,
                seed_path,
                f"export interface {type_name} {{ amount: number }}\n",
            )
            for index in range(6):
                _write(
                    repository,
                    f"{root_name}/src/feature/PlanFeature{index:02d}.ts",
                    (
                        f"import type {{ {type_name} }} from "
                        f"'../shared/{type_name}';\n"
                        f"export const calculate{index:02d} = "
                        f"(value: {type_name}) => value.amount;\n"
                    ),
                )
        _commit(repository, "initialize plan modules", "2026-07-01T09:00:00+09:00")

        for root_name in ("frontend", "backend"):
            type_name = f"{root_name.title()}PlanSeed"
            for index in range(6):
                _write(
                    repository,
                    f"{root_name}/src/feature/PlanFeature{index:02d}.ts",
                    (
                        f"import type {{ {type_name} }} from "
                        f"'../shared/{type_name}';\n"
                        f"export const calculate{index:02d} = "
                        f"(value: {type_name}) => value.amount + 1;\n"
                    ),
                )
        _commit(
            repository,
            "fix plan calculations",
            "2026-07-08T09:00:00+09:00",
        )

        manual_paths: list[str] = []
        for root_name, seed_path in seed_paths.items():
            type_name = f"{root_name.title()}PlanSeed"
            _write(
                repository,
                seed_path,
                (
                    f"export interface {type_name} {{ "
                    "amount: number; target: number }\n"
                ),
            )
            manual_paths.append(str((repository / seed_path).resolve()))
        _commit(repository, "change plan contracts", "2026-07-10T09:00:00+09:00")

        changes, _indexes, _excluded, _truncated = collect_changes(
            roots,
            "\n".join(f"M {path}" for path in manual_paths),
            date(2026, 7, 10),
            date(2026, 7, 10),
            True,
            _settings(scopeRecoveryMaxFiles=4),
            request_text="Change plan contracts and calculation behavior.",
        )
        recovered = [
            item for item in changes if item.source == "git-related-recovery"
        ]
        counts = Counter(Path(item.root).name for item in recovered)

        self.assertEqual(len(recovered), 4)
        self.assertEqual(set(counts), {"frontend", "backend"})
        self.assertLessEqual(
            abs(counts["frontend"] - counts["backend"]),
            1,
            "Equal-score candidates must consume a shared repository budget "
            "in round-robin order across selected subroots.",
        )

    def test_semantic_recovery_caps_large_commit_to_direct_query_matches(self):
        repository = _create_repository()
        direct_paths = {
            f"src/order/OrderCase{index:02d}Vo.java" for index in range(24)
        }
        unrelated_paths = {
            f"src/audit/AuditHelper{index:02d}.java" for index in range(24)
        }
        for index, path in enumerate(sorted(direct_paths)):
            _write(repository, path, f"class OrderCase{index:02d}Vo {{ int value = 0; }}\n")
        for index, path in enumerate(sorted(unrelated_paths)):
            _write(repository, path, f"class AuditHelper{index:02d} {{ int value = 0; }}\n")
        _commit(repository, "initialize project", "2026-07-01T09:00:00+09:00")
        for index, path in enumerate(sorted(direct_paths)):
            _write(repository, path, f"class OrderCase{index:02d}Vo {{ int value = 1; }}\n")
        for index, path in enumerate(sorted(unrelated_paths)):
            _write(repository, path, f"class AuditHelper{index:02d} {{ int value = 1; }}\n")
        _commit(
            repository,
            "update business model batch",
            "2026-07-08T09:00:00+09:00",
        )

        recovered = _recover_semantic_git_seeds(
            [repository],
            date(2026, 7, 10),
            date(2026, 7, 10),
            _settings(scopeRecoveryMaxFiles=5),
            ["Order VO update"],
            "Update order value objects.",
            None,
        )

        self.assertEqual(len(recovered), 5)
        self.assertTrue({item.path for item in recovered} <= direct_paths)
        self.assertFalse({item.path for item in recovered} & unrelated_paths)

    def test_semantic_recovery_unions_matches_from_two_subroots_of_same_repo(self):
        repository = _create_repository()
        roots = [repository / "frontend", repository / "backend"]
        expected: set[tuple[str, str]] = set()
        for root_name in ("frontend", "backend"):
            for index in range(2):
                relative_path = f"src/order/OrderCase{index:02d}Vo.ts"
                expected.add((root_name, relative_path))
                _write(
                    repository,
                    f"{root_name}/{relative_path}",
                    f"export const orderCase{index:02d}Vo = 0;\n",
                )
        _commit(repository, "initialize project", "2026-07-01T09:00:00+09:00")
        for root_name, relative_path in sorted(expected):
            index = int(relative_path.split("Case", 1)[1][:2])
            _write(
                repository,
                f"{root_name}/{relative_path}",
                f"export const orderCase{index:02d}Vo = 1;\n",
            )
        _commit(
            repository,
            "update business model batch",
            "2026-07-08T09:00:00+09:00",
        )

        recovered = _recover_semantic_git_seeds(
            roots,
            date(2026, 7, 10),
            date(2026, 7, 10),
            _settings(scopeRecoveryMaxFiles=6),
            ["Order VO update"],
            "Update order value objects.",
            None,
        )
        actual = {(Path(item.root).name, item.path) for item in recovered}

        self.assertEqual(actual, expected)
        self.assertEqual(
            {Path(item.root).name for item in recovered},
            {"frontend", "backend"},
        )

    def test_semantic_and_related_recovery_share_one_repository_budget(self):
        repository = _create_repository()
        direct_paths = [f"src/case/Case{index:02d}Vo.ts" for index in range(4)]
        related_paths = [
            f"src/case/Coordinator{index:02d}.ts" for index in range(6)
        ]
        for index, path in enumerate(direct_paths):
            _write(
                repository,
                path,
                f"export interface Case{index:02d}Vo {{ amount: number }}\n",
            )
        for index, path in enumerate(related_paths):
            _write(
                repository,
                path,
                (
                    "import type { Case00Vo } from './Case00Vo';\n"
                    "import type { Case01Vo } from './Case01Vo';\n"
                    f"export const coordinate{index:02d} = "
                    "(left: Case00Vo, right: Case01Vo) => "
                    "left.amount + right.amount;\n"
                ),
            )
        _commit(repository, "initialize project", "2026-07-01T09:00:00+09:00")

        for index, path in enumerate(direct_paths):
            _write(
                repository,
                path,
                (
                    f"export interface Case{index:02d}Vo {{ "
                    "amount: number; target: number }\n"
                ),
            )
        for index, path in enumerate(related_paths):
            _write(
                repository,
                path,
                (
                    "import type { Case00Vo } from './Case00Vo';\n"
                    "import type { Case01Vo } from './Case01Vo';\n"
                    f"export const coordinate{index:02d} = "
                    "(left: Case00Vo, right: Case01Vo) => "
                    f"left.amount + right.amount + {index + 1};\n"
                ),
            )
        _commit(
            repository,
            "adjust coordinated values",
            "2026-07-08T09:00:00+09:00",
        )

        cap = 4
        changes, _indexes, _excluded, _truncated = collect_changes(
            [repository],
            "VO 4 files",
            date(2026, 7, 10),
            date(2026, 7, 10),
            True,
            _settings(scopeRecoveryMaxFiles=cap),
            request_text="VO contract adjustment",
        )
        recovered = [
            item for item in changes if item.source == "git-related-recovery"
        ]
        semantic_direct_paths = {
            item.path for item in recovered if item.path in direct_paths
        }

        self.assertEqual(
            len(semantic_direct_paths),
            cap,
            "The fixture must exercise pathless semantic recovery before "
            "checking the shared budget.",
        )
        self.assertLessEqual(
            len(recovered),
            cap,
            "Semantic seeds and the following relation expansion must consume "
            "one shared scopeRecoveryMaxFiles budget per Git repository.",
        )
        probe_seeds = [
            replace(item, source="git-history")
            for item in recovered
            if item.path in semantic_direct_paths
        ]
        probe_logs: list[tuple[str, str]] = []
        eligible_related = _recover_related_git_changes(
            [repository],
            _indexes,
            probe_seeds,
            date(2026, 7, 10),
            date(2026, 7, 10),
            _settings(scopeRecoveryMaxFiles=cap),
            "VO 4 files\nVO contract adjustment",
            lambda level, message: probe_logs.append((level, message)),
        )
        self.assertEqual(
            len(eligible_related),
            cap,
            "The fixture must also contain at least one full budget of "
            f"high-confidence relation candidates. Seeds: "
            f"{[(item.root, item.path, item.commit) for item in probe_seeds]}; "
            f"index keys/counts: "
            f"{[(key, len(value)) for key, value in _indexes.items()]}; "
            f"logs: {probe_logs}",
        )
        self.assertTrue(
            {item.path for item in eligible_related} <= set(related_paths)
        )


if __name__ == "__main__":
    unittest.main()
