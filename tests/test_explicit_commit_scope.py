from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from promptcase_studio.scanner import (
    build_scan_bundle,
    collect_changes,
    parse_explicit_commit_refs,
)


TEMP_ROOT = (
    Path(__file__).resolve().parent.parent
    / "tmp"
    / "tests"
    / f"explicit-commit-scope-{os.getpid()}"
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


def _settings() -> dict[str, object]:
    # Keep every fuzzy/recovery limit deliberately generous. The tests prove
    # that an explicit commit scope bypasses those heuristics rather than being
    # correct merely because a low limit happened to discard unrelated files.
    return {
        "maxCandidateFiles": 2000,
        "maxSelectedCommits": 5,
        "maxSelectedFiles": 100,
        "commitEvidenceShortlist": 20,
        "maxCommitEvidenceChars": 40000,
        "scopeRecoveryEnabled": True,
        "scopeRecoveryDays": 21,
        "scopeRecoveryCommitDistanceDays": 7,
        "scopeRecoveryMaxCommits": 120,
        "scopeRecoveryMaxCandidateFiles": 200,
        "scopeRecoveryMaxFiles": 40,
        "maxSourceScanChars": 120000,
    }


def _absolute_paths(changes: list[object]) -> set[Path]:
    return {
        (Path(item.root) / Path(item.path)).resolve(strict=False)
        for item in changes
    }


def _commit_url(commit: str, label: str = "change") -> str:
    return f"[{label}](https://github.com/example/promptcase-fixture/commit/{commit})"


class ExplicitCommitScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(TEMP_ROOT, ignore_errors=True)

    def test_markdown_commit_url_is_exact_across_two_subroots(self):
        repository = _create_repository()
        frontend_root = repository / "frontend" / "src"
        backend_root = repository / "backend" / "src"
        target_frontend = frontend_root / "features" / "permission" / "canSave.ts"
        target_backend = (
            backend_root
            / "main"
            / "java"
            / "com"
            / "example"
            / "permission"
            / "PermissionServiceImpl.java"
        )
        outside_roots = repository / "docs" / "can-save-release.md"

        _write(repository, "frontend/src/app.ts", "export const app = true;\n")
        _write(repository, "backend/src/main/java/com/example/App.java", "class App {}\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")

        noisy_paths: set[Path] = set()
        for index in range(12):
            relative_path = (
                f"frontend/src/features/permission/legacyCanSave{index}.ts"
                if index % 2 == 0
                else (
                    "backend/src/main/java/com/example/permission/"
                    f"LegacyCanSaveService{index}.java"
                )
            )
            _write(
                repository,
                relative_path,
                f"// canSave permission related high-fanout change {index}\n",
            )
            noisy_paths.add((repository / relative_path).resolve())
        _commit(
            repository,
            "feat: canSave permission preliminary implementation",
            "2026-07-23T09:00:00+09:00",
        )

        _write(
            repository,
            "frontend/src/features/permission/canSave.ts",
            "export const canSave = (allowed: boolean) => allowed;\n",
        )
        _write(
            repository,
            "backend/src/main/java/com/example/permission/PermissionServiceImpl.java",
            "class PermissionServiceImpl { boolean canSave() { return true; } }\n",
        )
        _write(
            repository,
            "docs/can-save-release.md",
            "# canSave permission release\n",
        )
        target_commit = _commit(
            repository,
            "feat: canSave permission backend implementation",
            "2026-07-24T09:00:00+09:00",
        )
        dirty_working_tree = frontend_root / "features" / "permission" / "draftRule.ts"
        _write(
            repository,
            "frontend/src/features/permission/draftRule.ts",
            "export const draftRule = 'not part of the explicit commit';\n",
        )

        changes, _indexes, _excluded, _truncated = collect_changes(
            [frontend_root, backend_root],
            _commit_url(
                target_commit,
                "feat: canSave 권한 체크에 대한 Backend 구현",
            ),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="canSave 권한 체크 Backend 구현",
        )

        selected = _absolute_paths(changes)
        self.assertEqual(selected, {target_frontend.resolve(), target_backend.resolve()})
        self.assertNotIn(outside_roots.resolve(), selected)
        self.assertNotIn(dirty_working_tree.resolve(), selected)
        self.assertTrue(selected.isdisjoint(noisy_paths))
        self.assertTrue(changes)
        self.assertTrue(
            all(
                target_commit in item.commit.split(", ")
                for item in changes
            )
        )

    def test_explicit_commit_is_selected_even_when_date_range_misses_it(self):
        repository = _create_repository()
        root = repository / "backend" / "src"
        target = (
            root
            / "main"
            / "java"
            / "com"
            / "example"
            / "permission"
            / "AuthorizationService.java"
        )
        in_range_but_unrelated = (
            root
            / "main"
            / "java"
            / "com"
            / "example"
            / "permission"
            / "CanSavePermissionService.java"
        )

        _write(repository, "backend/src/main/java/com/example/App.java", "class App {}\n")
        _commit(repository, "initial project", "2026-07-01T09:00:00+09:00")
        _write(
            repository,
            "backend/src/main/java/com/example/permission/AuthorizationService.java",
            "class AuthorizationService { boolean canSave() { return true; } }\n",
        )
        explicit_commit = _commit(
            repository,
            "feat: implement canSave authorization",
            "2026-07-10T09:00:00+09:00",
        )
        _write(
            repository,
            "backend/src/main/java/com/example/permission/CanSavePermissionService.java",
            "class CanSavePermissionService { boolean canSave() { return false; } }\n",
        )
        _commit(
            repository,
            "feat: canSave permission follow-up",
            "2026-07-25T09:00:00+09:00",
        )

        changes, _indexes, _excluded, _truncated = collect_changes(
            [root],
            _commit_url(explicit_commit, "canSave 권한 구현"),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="canSave 권한 체크 Backend 구현",
        )

        self.assertEqual(_absolute_paths(changes), {target.resolve()})
        self.assertNotIn(in_range_but_unrelated.resolve(), _absolute_paths(changes))
        self.assertEqual({item.commit for item in changes}, {explicit_commit})

    def test_unknown_explicit_commit_fails_without_fuzzy_fallback(self):
        repository = _create_repository()
        root = repository / "backend" / "src"
        _write(
            repository,
            "backend/src/main/java/com/example/permission/CanSaveService.java",
            "class CanSaveService { boolean canSave() { return true; } }\n",
        )
        _commit(
            repository,
            "feat: canSave permission backend implementation",
            "2026-07-24T09:00:00+09:00",
        )
        unknown_commit = "f" * 40

        with self.assertRaises(ValueError) as raised:
            collect_changes(
                [root],
                _commit_url(unknown_commit, "canSave 권한 구현"),
                date(2026, 7, 22),
                date(2026, 7, 27),
                True,
                _settings(),
                request_text="canSave 권한 체크 Backend 구현",
            )

        message = str(raised.exception)
        self.assertIn(unknown_commit[:8], message)
        self.assertRegex(message.casefold(), r"(commit|커밋)")

    def test_multiple_explicit_commit_urls_produce_the_exact_union(self):
        repository = _create_repository()
        frontend_root = repository / "frontend" / "src"
        backend_root = repository / "backend" / "src"
        frontend_target = frontend_root / "permission" / "canSave.ts"
        backend_target = (
            backend_root
            / "main"
            / "java"
            / "com"
            / "example"
            / "permission"
            / "CanSaveService.java"
        )

        _write(repository, "frontend/src/app.ts", "export const app = true;\n")
        _write(repository, "backend/src/main/java/com/example/App.java", "class App {}\n")
        _commit(repository, "initial project", "2026-07-01T09:00:00+09:00")

        _write(
            repository,
            "frontend/src/permission/canSave.ts",
            "export const canSave = (allowed: boolean) => allowed;\n",
        )
        frontend_commit = _commit(
            repository,
            "feat: add canSave frontend contract",
            "2026-07-08T09:00:00+09:00",
        )
        _write(
            repository,
            "backend/src/main/java/com/example/permission/CanSaveService.java",
            "class CanSaveService { boolean canSave() { return true; } }\n",
        )
        _write(repository, "docs/backend-release.md", "# outside selected roots\n")
        backend_commit = _commit(
            repository,
            "feat: implement canSave backend permission",
            "2026-07-10T09:00:00+09:00",
        )

        manual_text = "\n".join(
            (
                _commit_url(frontend_commit, "frontend canSave"),
                _commit_url(backend_commit, "backend canSave"),
            )
        )
        changes, _indexes, _excluded, _truncated = collect_changes(
            [frontend_root, backend_root],
            manual_text,
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="canSave 권한 체크 구현",
        )

        self.assertEqual(
            _absolute_paths(changes),
            {frontend_target.resolve(), backend_target.resolve()},
        )
        self.assertEqual(
            {item.commit for item in changes},
            {frontend_commit, backend_commit},
        )

    def test_conventional_commit_subject_does_not_expand_to_adjacent_history(self):
        repository = _create_repository()
        root = repository / "src"
        target = root / "permission" / "CanSaveRequest.ts"
        old_related = root / "legacy" / "LegacyPermissionService.ts"

        _write(repository, "src/app.ts", "export const app = true;\n")
        _commit(repository, "initial project", "2026-07-01T09:00:00+09:00")
        _write(
            repository,
            "src/legacy/LegacyPermissionService.ts",
            "import type { CanSaveRequest } from '../permission/CanSaveRequest';\n"
            "export const legacy = (value: CanSaveRequest) => value.allowed;\n",
        )
        _commit(
            repository,
            "feat: initialize permission infrastructure",
            "2026-07-21T09:00:00+09:00",
        )
        _write(
            repository,
            "src/permission/CanSaveRequest.ts",
            "export interface CanSaveRequest { allowed: boolean }\n",
        )
        target_commit = _commit(
            repository,
            "feat: implement backend canSave permission check",
            "2026-07-23T09:00:00+09:00",
        )

        changes, _indexes, _excluded, _truncated = collect_changes(
            [root],
            "feat: implement backend canSave permission check",
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="Implement the backend canSave permission check.",
        )

        self.assertEqual(_absolute_paths(changes), {target.resolve()})
        self.assertNotIn(old_related.resolve(), _absolute_paths(changes))
        self.assertEqual({item.commit for item in changes}, {target_commit})

    def test_parser_supports_github_and_gitlab_commit_urls(self):
        github_commit = "0123456789abcdef0123456789abcdef01234567"
        gitlab_commit = "fedcba9876543210fedcba9876543210fedcba98"
        text = "\n".join(
            (
                (
                    "[GitHub 변경]"
                    "(https://github.com/example/project/commit/"
                    f"{github_commit})"
                ),
                (
                    "GitLab 변경: "
                    "https://gitlab.example.com/group/project/-/commit/"
                    f"{gitlab_commit}?view=parallel"
                ),
                f"commit: {github_commit}",
            )
        )

        self.assertEqual(
            parse_explicit_commit_refs(text),
            [github_commit, gitlab_commit],
        )

    def test_parser_does_not_treat_business_hex_values_as_commit_selectors(self):
        business_hash = "abcdef0123456789abcdef0123456789abcdef01"
        text = "\n".join(
            (
                f"요청 추적 ID: {business_hash}",
                f'{{"payloadHash": "{business_hash}"}}',
                f"SHA-256 체크섬: {business_hash}{business_hash[:24]}",
                f"커밋 여부 확인 대상 데이터: {business_hash}",
                f"https://example.invalid/audit/commits/{business_hash}",
            )
        )

        self.assertEqual(parse_explicit_commit_refs(text), [])

    def test_parser_does_not_treat_relative_application_path_as_commit_url(self):
        self.assertEqual(
            parse_explicit_commit_refs(
                "라우팅 경로 /commit/deadbee 에서 승인 화면을 연다."
            ),
            [],
        )

    def test_parser_accepts_standalone_short_sha_but_ignores_numeric_business_id(self):
        short_sha = "deadbee"
        numeric_business_id = "123456789012345678901234567890123456789"

        self.assertEqual(
            parse_explicit_commit_refs(
                f"{short_sha}\n{numeric_business_id}"
            ),
            [short_sha],
        )

    def test_digits_only_short_sha_requires_an_explicit_commit_label(self):
        digits_only_sha = "1234567"

        self.assertEqual(parse_explicit_commit_refs(digits_only_sha), [])
        self.assertEqual(
            parse_explicit_commit_refs(f"commit: {digits_only_sha}"),
            [digits_only_sha],
        )

    def test_explicit_merge_commit_uses_first_parent_diff(self):
        repository = _create_repository()
        root = repository / "src"

        _write(repository, "src/app.ts", "export const app = true;\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")
        main_branch = _git(repository, "branch", "--show-current")

        _git(repository, "checkout", "-b", "feature/can-save")
        _write(
            repository,
            "src/permission/CanSaveService.ts",
            "export const canSave = (allowed: boolean) => allowed;\n",
        )
        _commit(
            repository,
            "feat: add canSave service",
            "2026-07-22T09:00:00+09:00",
        )

        _git(repository, "checkout", main_branch)
        _write(repository, "README.md", "# fixture\n")
        _commit(repository, "docs: update readme", "2026-07-23T09:00:00+09:00")
        _git(
            repository,
            "merge",
            "--no-ff",
            "feature/can-save",
            "-m",
            "merge: canSave service",
            authored_at="2026-07-24T09:00:00+09:00",
        )
        merge_commit = _git(repository, "rev-parse", "HEAD")

        changes, _indexes, _excluded, _truncated = collect_changes(
            [root],
            _commit_url(merge_commit, "merge canSave"),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="canSave 서비스를 반영한다.",
        )

        self.assertEqual(
            {item.path for item in changes},
            {"permission/CanSaveService.ts"},
        )
        self.assertEqual({item.commit for item in changes}, {merge_commit})

    def test_explicit_historical_bundle_uses_selected_commit_snapshot_only(self):
        repository = _create_repository()
        root = repository / "src"
        target_path = "src/permission/CanSaveService.ts"

        _write(repository, "src/app.ts", "export const app = true;\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")
        _write(
            repository,
            target_path,
            "export const selectedSnapshotToken = 'can-save-release';\n",
        )
        selected_commit = _commit(
            repository,
            "feat: add canSave release behavior",
            "2026-07-22T09:00:00+09:00",
        )

        _write(
            repository,
            target_path,
            "export const laterCheckoutOnlyToken = 'unrelated-follow-up';\n",
        )
        _write(
            repository,
            "src/permission/CurrentRelatedConsumer.ts",
            "import { laterCheckoutOnlyToken } from './CanSaveService';\n"
            "export const currentOnly = laterCheckoutOnlyToken;\n",
        )
        _commit(
            repository,
            "refactor: unrelated later checkout state",
            "2026-07-25T09:00:00+09:00",
        )

        bundle = build_scan_bundle(
            [root],
            _commit_url(selected_commit, "canSave release"),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="canSave release behavior",
        )

        self.assertEqual(
            [context.path for context in bundle.contexts],
            ["permission/CanSaveService.ts"],
        )
        evidence = "\n".join(context.excerpt for context in bundle.contexts)
        self.assertIn("[선택 커밋 소스]", evidence)
        self.assertIn("selectedSnapshotToken", evidence)
        self.assertNotIn("laterCheckoutOnlyToken", evidence)
        self.assertNotIn("CurrentRelatedConsumer.ts", evidence)

    def test_explicit_rename_outside_selected_root_preserves_old_path(self):
        repository = _create_repository()
        root = repository / "src"

        _write(
            repository,
            "src/domain/LegacyPermissionService.ts",
            "export const legacyPermission = true;\n",
        )
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")
        (repository / "archive").mkdir()
        _git(
            repository,
            "mv",
            "src/domain/LegacyPermissionService.ts",
            "archive/LegacyPermissionService.ts",
        )
        moved_commit = _commit(
            repository,
            "refactor: archive legacy permission service",
            "2026-07-24T09:00:00+09:00",
        )

        changes, _indexes, _excluded, _truncated = collect_changes(
            [root],
            _commit_url(moved_commit, "archive legacy service"),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="legacy permission service 이동",
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, "domain/LegacyPermissionService.ts")
        self.assertFalse(changes[0].exists)
        self.assertIn("archive/LegacyPermissionService.ts", changes[0].note)

    def test_sensitive_explicit_file_keeps_metadata_without_body_or_diff(self):
        repository = _create_repository()
        root = repository / "app"
        secret = "PROMPTCASE_TEST_SECRET_DO_NOT_EXPOSE_72b9"

        _write(repository, "app/main.py", "print('ready')\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")
        _write(repository, "app/.env", f"GEMINI_API_KEY={secret}\n")
        sensitive_commit = _commit(
            repository,
            "chore: configure private runtime",
            "2026-07-24T09:00:00+09:00",
        )

        bundle = build_scan_bundle(
            [root],
            _commit_url(sensitive_commit, "private runtime"),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="private runtime configuration",
        )

        self.assertEqual([change.path for change in bundle.changes], [".env"])
        self.assertEqual([context.path for context in bundle.contexts], [".env"])
        evidence = "\n".join(context.excerpt for context in bundle.contexts)
        self.assertIn(".env", evidence)
        self.assertNotIn(secret, evidence)
        self.assertNotIn("GEMINI_API_KEY", evidence)
        self.assertNotIn("[Git diff]", evidence)

    def test_sensitive_rename_to_plain_name_remains_metadata_only(self):
        repository = _create_repository()
        root = repository / "app"
        old_secret = "PROMPTCASE_OLD_RENAME_SECRET_38cf"
        new_secret = "PROMPTCASE_NEW_RENAME_SECRET_d722"
        common_lines = "".join(
            f"COMMON_SETTING_{index:02d}=value-{index}\n"
            for index in range(30)
        )

        _write(
            repository,
            "app/.env",
            common_lines + f"GEMINI_API_KEY={old_secret}\n",
        )
        _commit(repository, "initial private configuration", "2026-07-20T09:00:00+09:00")
        _git(repository, "mv", "app/.env", "app/config.txt")
        _write(
            repository,
            "app/config.txt",
            common_lines + f"GEMINI_API_KEY={new_secret}\n",
        )
        rename_commit = _commit(
            repository,
            "chore: rename private configuration",
            "2026-07-24T09:00:00+09:00",
        )

        bundle = build_scan_bundle(
            [root],
            _commit_url(rename_commit, "rename private configuration"),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="private configuration rename",
        )

        self.assertEqual([change.path for change in bundle.changes], ["config.txt"])
        self.assertIn(".env", bundle.changes[0].note)
        self.assertEqual([context.path for context in bundle.contexts], ["config.txt"])
        evidence = bundle.contexts[0].excerpt
        self.assertIn("config.txt", evidence)
        self.assertNotIn(old_secret, evidence)
        self.assertNotIn(new_secret, evidence)
        self.assertNotIn("GEMINI_API_KEY", evidence)
        self.assertNotIn("[Git diff]", evidence)
        self.assertNotIn("[선택 커밋 소스]", evidence)

    def test_multiple_explicit_commits_use_descendant_snapshot_not_input_order(self):
        repository = _create_repository()
        root = repository / "src"
        target_path = "src/domain/policy.py"
        oldest_token = "oldest_selected_snapshot_04bd"
        newest_token = "newest_descendant_snapshot_91e7"

        _write(repository, "src/app.py", "print('ready')\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")
        _write(repository, target_path, f"policy_value = '{oldest_token}'\n")
        oldest_commit = _commit(
            repository,
            "feat: add policy",
            "2026-07-22T09:00:00+09:00",
        )
        _write(repository, target_path, f"policy_value = '{newest_token}'\n")
        newest_commit = _commit(
            repository,
            "fix: update policy",
            "2026-07-24T09:00:00+09:00",
        )

        bundle = build_scan_bundle(
            [root],
            "\n".join(
                (
                    _commit_url(newest_commit, "newest policy"),
                    _commit_url(oldest_commit, "oldest policy"),
                )
            ),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="policy behavior",
        )

        self.assertEqual([change.path for change in bundle.changes], ["domain/policy.py"])
        evidence = bundle.contexts[0].excerpt
        self.assertIn("[선택 커밋 소스]", evidence)
        selected_source = evidence.split("[선택 커밋 소스]", 1)[1]
        self.assertIn(newest_token, selected_source)
        self.assertNotIn(oldest_token, selected_source)

    def test_incomparable_explicit_commits_omit_ambiguous_snapshot(self):
        repository = _create_repository()
        root = repository / "src"
        target_path = "src/domain/shared_policy.py"

        _write(repository, target_path, "policy_value = 'base'\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")
        main_branch = _git(repository, "branch", "--show-current")

        _git(repository, "checkout", "-b", "feature/left-policy")
        _write(repository, target_path, "policy_value = 'left_branch_value'\n")
        left_commit = _commit(
            repository,
            "feat: left policy",
            "2026-07-22T09:00:00+09:00",
        )

        _git(repository, "checkout", main_branch)
        _git(repository, "checkout", "-b", "feature/right-policy")
        _write(repository, target_path, "policy_value = 'right_branch_value'\n")
        right_commit = _commit(
            repository,
            "feat: right policy",
            "2026-07-24T09:00:00+09:00",
        )

        bundle = build_scan_bundle(
            [root],
            "\n".join(
                (
                    _commit_url(left_commit, "left policy"),
                    _commit_url(right_commit, "right policy"),
                )
            ),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="shared policy",
        )

        self.assertEqual([change.path for change in bundle.changes], ["domain/shared_policy.py"])
        self.assertIn(left_commit, bundle.changes[0].commit)
        self.assertIn(right_commit, bundle.changes[0].commit)
        evidence = bundle.contexts[0].excerpt
        self.assertIn("[Git diff]", evidence)
        self.assertNotIn("[선택 커밋 소스]", evidence)

    def test_detailed_context_limit_is_fair_across_selected_roots(self):
        repository = _create_repository()
        root_a = repository / "frontend"
        root_b = repository / "backend"

        _write(repository, "frontend/bootstrap.py", "READY = True\n")
        _write(repository, "backend/bootstrap.py", "READY = True\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")
        for index in range(121):
            _write(
                repository,
                f"frontend/generated/change_{index:03d}.py",
                f"VALUE = {index}\n",
            )
        for index in range(3):
            _write(
                repository,
                f"backend/important/change_{index:03d}.py",
                f"VALUE = {index}\n",
            )
        selected_commit = _commit(
            repository,
            "feat: update frontend and backend scope",
            "2026-07-24T09:00:00+09:00",
        )
        settings = {
            **_settings(),
            "maxDetailedChangedFiles": 120,
            "maxChangedFileChars": 400,
            "maxContextChars": 140000,
        }

        with (
            patch(
                "promptcase_studio.scanner._git_file_snapshot",
                side_effect=lambda _root, _commits, path, _maximum: (
                    f"DETAIL_SOURCE = '{path}'\n"
                ),
            ),
            patch(
                "promptcase_studio.scanner._git_selected_commit_diff",
                side_effect=lambda _root, _commits, path, _maximum: (
                    f"@@ -0,0 +1 @@\n+DETAIL_DIFF = '{path}'"
                ),
            ),
        ):
            bundle = build_scan_bundle(
                [root_a, root_b],
                _commit_url(selected_commit, "frontend and backend scope"),
                date(2026, 7, 22),
                date(2026, 7, 27),
                True,
                settings,
                request_text="frontend backend scope",
            )

        self.assertEqual(len(bundle.changes), 124)
        detailed_contexts = [
            context for context in bundle.contexts if context.mode != "metadata"
        ]
        self.assertEqual(len(detailed_contexts), 120)
        detailed_roots = {Path(context.root).resolve() for context in detailed_contexts}
        self.assertIn(root_a.resolve(), detailed_roots)
        self.assertIn(root_b.resolve(), detailed_roots)
        self.assertTrue(
            any(
                Path(context.root).resolve() == root_b.resolve()
                and "[Git diff]" in context.excerpt
                for context in detailed_contexts
            )
        )

    def test_many_explicit_commits_follow_latest_descendant_state_and_diff(self):
        repository = _create_repository()
        root = repository / "src"
        target_path = "src/domain/release_policy.py"
        latest_token = "LATEST_SIXTH_DESCENDANT_EVIDENCE_5f21"

        _write(repository, "src/app.py", "print('ready')\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")

        commits: list[str] = []
        _write(repository, target_path, "POLICY_VALUE = 'first'\n")
        commits.append(
            _commit(repository, "feat: add policy", "2026-07-21T09:00:00+09:00")
        )
        _write(repository, target_path, "POLICY_VALUE = 'second'\n")
        commits.append(
            _commit(repository, "fix: update policy", "2026-07-22T09:00:00+09:00")
        )
        _git(repository, "rm", target_path)
        commits.append(
            _commit(repository, "refactor: remove policy", "2026-07-23T09:00:00+09:00")
        )
        _write(repository, target_path, "POLICY_VALUE = 'readded'\n")
        commits.append(
            _commit(repository, "feat: re-add policy", "2026-07-24T09:00:00+09:00")
        )
        _write(repository, target_path, "POLICY_VALUE = 'fifth'\n")
        commits.append(
            _commit(repository, "fix: refine policy", "2026-07-25T09:00:00+09:00")
        )
        _write(repository, target_path, f"POLICY_VALUE = '{latest_token}'\n")
        commits.append(
            _commit(repository, "fix: finalize policy", "2026-07-26T09:00:00+09:00")
        )

        adversarial_order = [
            commits[2],
            commits[0],
            commits[3],
            commits[1],
            commits[4],
            commits[5],
        ]
        bundle = build_scan_bundle(
            [root],
            "\n".join(
                _commit_url(commit, f"policy change {index}")
                for index, commit in enumerate(adversarial_order, start=1)
            ),
            date(2026, 7, 21),
            date(2026, 7, 27),
            True,
            _settings(),
            request_text="release policy",
        )

        self.assertEqual([change.path for change in bundle.changes], ["domain/release_policy.py"])
        change = bundle.changes[0]
        self.assertEqual(change.change_type, "변경")
        self.assertTrue(change.exists)
        self.assertTrue(all(commit in change.commit for commit in commits))

        evidence = bundle.contexts[0].excerpt
        self.assertIn("[선택 커밋 소스]", evidence)
        diff_evidence, selected_source = evidence.split("[선택 커밋 소스]", 1)
        self.assertIn(f"[commit {commits[5][:8]}]", diff_evidence)
        self.assertIn(latest_token, diff_evidence)
        self.assertIn(latest_token, selected_source)

    def test_oversized_historical_blob_keeps_metadata_and_bounded_diff(self):
        repository = _create_repository()
        root = repository / "src"
        oversized_tail = "OVERSIZED_SNAPSHOT_TAIL_MUST_NOT_BE_LOADED_91ac"

        _write(repository, "src/app.py", "print('ready')\n")
        _commit(repository, "initial project", "2026-07-20T09:00:00+09:00")
        _write(
            repository,
            "src/domain/large_policy.py",
            "policy_data = '" + ("x" * 5000) + oversized_tail + "'\n",
        )
        selected_commit = _commit(
            repository,
            "feat: add large policy source",
            "2026-07-24T09:00:00+09:00",
        )
        settings = {
            **_settings(),
            "maxChangedFileChars": 400,
            "maxSourceScanChars": 400,
            "maxDiffChars": 500,
        }

        bundle = build_scan_bundle(
            [root],
            _commit_url(selected_commit, "large policy source"),
            date(2026, 7, 22),
            date(2026, 7, 27),
            True,
            settings,
            request_text="large policy source",
        )

        self.assertEqual([change.path for change in bundle.changes], ["domain/large_policy.py"])
        self.assertEqual(bundle.changes[0].source, "git-explicit-commit")
        self.assertEqual(bundle.changes[0].commit, selected_commit)
        self.assertEqual([context.path for context in bundle.contexts], ["domain/large_policy.py"])
        evidence = bundle.contexts[0].excerpt
        self.assertIn("domain/large_policy.py", evidence)
        self.assertIn("[Git diff]", evidence)
        self.assertNotIn("[선택 커밋 소스]", evidence)
        self.assertNotIn(oversized_tail, evidence)
        self.assertTrue(
            any(
                "크기 제한" in warning or "문자 상한" in warning
                for warning in bundle.warnings
            ),
            bundle.warnings,
        )


if __name__ == "__main__":
    unittest.main()
