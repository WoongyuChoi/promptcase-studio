from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from promptcase_studio.scanner import collect_changes


TEMP_ROOT = (
    Path(__file__).resolve().parent.parent / "tmp" / "tests" / "manifest-scope-limits"
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
        # This is an AI evidence/context bound, not a change-manifest bound.
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


class ManifestScopeLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(TEMP_ROOT, ignore_errors=True)

    def test_explicit_commit_keeps_every_changed_file_beyond_context_limit(self):
        repository = _create_repository()
        expected_paths = {
            f"src/permission/CanSaveRule{index:02d}.java" for index in range(31)
        }
        for index, relative_path in enumerate(sorted(expected_paths)):
            _write(
                repository,
                relative_path,
                (
                    "package permission;\n"
                    f"class CanSaveRule{index:02d} {{\n"
                    "  boolean canSave() { return true; }\n"
                    "}\n"
                ),
            )
        subject = "feat: implement backend canSave permission check"
        commit = _commit(repository, subject, "2026-07-23T10:00:00+09:00")
        commit_url = (
            "https://github.com/example/promptcase-fixture/commit/"
            f"{commit}"
        )

        changes, _indexes, _excluded, _truncated = collect_changes(
            [repository],
            f"[{subject}]({commit_url})",
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(scopeRecoveryEnabled=False),
            request_text="Implement the backend canSave permission check.",
        )

        self.assertEqual({item.path for item in changes}, expected_paths)
        self.assertEqual(len(changes), 31)
        self.assertTrue(all(item.commit == commit for item in changes))

    def test_recovery_budget_is_global_for_two_subroots_of_one_git_repository(self):
        repository = _create_repository()
        roots = [repository / "frontend", repository / "backend"]
        seed_paths = {
            "frontend": "src/shared/FrontendPlanSeed.ts",
            "backend": "src/shared/BackendPlanSeed.ts",
        }

        for root_name, seed_path in seed_paths.items():
            type_name = "FrontendPlanSeed" if root_name == "frontend" else "BackendPlanSeed"
            _write(
                repository,
                f"{root_name}/{seed_path}",
                f"export interface {type_name} {{ amount: number }}\n",
            )
            for index in range(13):
                _write(
                    repository,
                    f"{root_name}/src/feature/PlanFeature{index:02d}.ts",
                    (
                        f"import type {{ {type_name} }} from '../shared/{type_name}';\n"
                        f"export const calculate{index:02d} = (value: {type_name}) => "
                        "value.amount;\n"
                    ),
                )
        _commit(repository, "initialize plan modules", "2026-07-01T09:00:00+09:00")

        for root_name in seed_paths:
            type_name = "FrontendPlanSeed" if root_name == "frontend" else "BackendPlanSeed"
            for index in range(13):
                _write(
                    repository,
                    f"{root_name}/src/feature/PlanFeature{index:02d}.ts",
                    (
                        f"import type {{ {type_name} }} from '../shared/{type_name}';\n"
                        f"export const calculate{index:02d} = (value: {type_name}) => "
                        f"value.amount + {index + 1};\n"
                    ),
                )
        _commit(
            repository,
            "fix plan feature calculations",
            "2026-07-08T09:00:00+09:00",
        )

        manual_paths: list[str] = []
        for root_name, seed_path in seed_paths.items():
            type_name = "FrontendPlanSeed" if root_name == "frontend" else "BackendPlanSeed"
            _write(
                repository,
                f"{root_name}/{seed_path}",
                (
                    f"export interface {type_name} {{ "
                    "amount: number; target: number }\n"
                ),
            )
            manual_paths.append(str((repository / root_name / seed_path).resolve()))
        _commit(repository, "change plan contracts", "2026-07-10T09:00:00+09:00")

        changes, _indexes, _excluded, _truncated = collect_changes(
            roots,
            "\n".join(f"M {path}" for path in manual_paths),
            date(2026, 7, 10),
            date(2026, 7, 10),
            True,
            _settings(scopeRecoveryMaxFiles=12),
            request_text="Change plan contracts and calculation behavior.",
        )
        recovered = [
            item for item in changes if item.source == "git-related-recovery"
        ]

        self.assertGreater(len(recovered), 0)
        self.assertLessEqual(
            len(recovered),
            12,
            "One Git repository must receive one recovery budget even when "
            "its frontend and backend subdirectories are supplied as separate roots.",
        )
        self.assertEqual(
            len([item for item in changes if item.source == "manual"]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
