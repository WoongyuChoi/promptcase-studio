import codecs
import shutil
import unittest
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from promptcase_studio.models import ChangeItem
from promptcase_studio.scanner import (
    ChangedProfile,
    IndexedFile,
    _business_family,
    _candidate_relation,
    _extract_reference_signals,
    _extract_terms,
    _file_role,
    _focused_excerpt,
    _redact_sensitive_text,
    _read_text,
    _git_diff,
    build_scan_bundle,
    collect_changes,
    collect_date_changes,
    collect_git_changes,
    parse_manual_changes,
    parse_manual_notes,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_project"
MULTI_ROOT_FIXTURE = Path(__file__).parent / "fixtures" / "multi_root"
TEMP_ROOT = Path(__file__).resolve().parent.parent / "tmp" / "tests" / "scanner"


@contextmanager
def workspace_temporary_directory():
    """Use normal inherited ACLs; Python 3.13 TemporaryDirectory uses 0700 on Windows."""

    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEMP_ROOT / f"case-{uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


class ScannerTests(unittest.TestCase):
    def test_reads_bom_declared_utf8_and_cp949_sources_without_replacement(self):
        samples = {
            "utf8-bom.xml": codecs.BOM_UTF8
            + "<mapper>한글 UTF8 근거</mapper>".encode("utf-8"),
            "utf16-le.xml": codecs.BOM_UTF16_LE
            + "<mapper>한글 UTF16 LE 근거</mapper>".encode("utf-16-le"),
            "utf16-be.xml": codecs.BOM_UTF16_BE
            + "<mapper>한글 UTF16 BE 근거</mapper>".encode("utf-16-be"),
            "declared-latin1.xml": (
                '<?xml version="1.0" encoding="iso-8859-1"?><mapper>caf\u00e9</mapper>'
            ).encode("iso-8859-1"),
            "strict-utf8.java": "class Utf8Sample { String label = \"한글 근거\"; }".encode(
                "utf-8"
            ),
            "legacy-cp949.java": "class LegacySample { String label = \"주문확정상태\"; }".encode(
                "cp949"
            ),
        }
        expected = {
            "utf8-bom.xml": "한글 UTF8 근거",
            "utf16-le.xml": "한글 UTF16 LE 근거",
            "utf16-be.xml": "한글 UTF16 BE 근거",
            "declared-latin1.xml": "café",
            "strict-utf8.java": "한글 근거",
            "legacy-cp949.java": "주문확정상태",
        }

        with workspace_temporary_directory() as temporary:
            root = Path(temporary)
            for name, payload in samples.items():
                with self.subTest(name=name):
                    path = root / name
                    path.write_bytes(payload)
                    text = _read_text(path)
                    self.assertIn(expected[name], text)
                    self.assertNotIn("\ufffd", text)

            bounded_path = root / "bounded-utf8.txt"
            bounded_path.write_bytes("가나다".encode("utf-8"))
            self.assertEqual(_read_text(bounded_path, 2), "가나")

    def test_mybatis_placeholders_are_data_fields_only_inside_mapper_xml(self):
        tsx_signals = _extract_reference_signals(
            Path("KpiMapHeader.tsx"),
            "const style = `${GRAYSCALE}-${opacity}`;",
        )
        plain_xml_signals = _extract_reference_signals(
            Path("runtime.xml"),
            "<configuration><value>${runtimeValue}</value></configuration>",
        )
        mapper_signals = _extract_reference_signals(
            Path("UserMapper.xml"),
            '<mapper namespace="UserMapper"><select id="find">'
            "SELECT * FROM USERS WHERE USER_ID = #{userId} AND TYPE = ${typeName}"
            "</select></mapper>",
        )

        self.assertFalse(any(signal.kind == "data-field" for signal in tsx_signals))
        self.assertFalse(any(signal.kind == "data-field" for signal in plain_xml_signals))
        mapper_fields = {
            signal.value for signal in mapper_signals if signal.kind == "data-field"
        }
        self.assertEqual(mapper_fields, {"userId", "typeName"})

    def test_file_roles_distinguish_frontend_and_backend_layers(self):
        expected = {
            "api/com/sessionApi.ts": "frontend-api",
            "hook/kpi/useKpiMapTaskList.ts": "frontend-hook",
            "store/session.ts": "frontend-store",
            "app/providers/SessionProvider.tsx": "frontend-provider",
            "src/main/java/com/sample/UserController.java": "backend-controller",
            "src/main/java/com/sample/UserServiceImpl.java": "backend-service",
            "src/main/resources/mapper/UserMapper.xml": "backend-mapper",
            "src/main/java/com/sample/UserResponseDto.java": "backend-dto",
        }
        for path, role in expected.items():
            with self.subTest(path=path):
                self.assertEqual(_file_role(Path(path)), role)

    def test_endpoint_signal_connects_frontend_api_to_spring_controller_across_roots(self):
        with workspace_temporary_directory() as temporary:
            workspace = Path(temporary)
            frontend = workspace / "frontend"
            backend = workspace / "backend"
            frontend_file = frontend / "src" / "api" / "userApi.ts"
            backend_file = (
                backend
                / "src"
                / "main"
                / "java"
                / "com"
                / "sample"
                / "UserController.java"
            )
            frontend_file.parent.mkdir(parents=True)
            backend_file.parent.mkdir(parents=True)
            frontend_file.write_text(
                'import sessionApi from "./client";\n'
                "export const loadUser = (userId: string) => "
                "sessionApi.get<User>(`${API_BASE_URL}/api/users/${userId}?active=true`);\n",
                encoding="utf-8",
            )
            backend_file.write_text(
                "package com.sample;\n"
                "@RestController\n"
                '@RequestMapping(value = "/api/users", produces = "application/json")\n'
                "public class UserController {\n"
                '  @GetMapping(path = "/{id}", produces = "application/json", '
                'headers = "X-Mode=active")\n'
                "  public UserDto findUser(String id) { return service.findUser(id); }\n"
                "}\n",
                encoding="utf-8",
            )

            frontend_endpoints = {
                signal.value
                for signal in _extract_reference_signals(
                    frontend_file,
                    frontend_file.read_text(encoding="utf-8"),
                )
                if signal.kind == "endpoint"
            }
            backend_endpoints = {
                signal.value
                for signal in _extract_reference_signals(
                    backend_file,
                    backend_file.read_text(encoding="utf-8"),
                )
                if signal.kind == "endpoint"
            }
            self.assertEqual(frontend_endpoints, {"/api/users/{}"})
            self.assertEqual(backend_endpoints, {"/api/users/{}"})

            bundle = build_scan_bundle(
                [frontend, backend],
                "변경: src/api/userApi.ts",
                None,
                None,
                False,
                {
                    "maxCandidateFiles": 100,
                    "maxChangedFileChars": 4000,
                    "maxRelatedFiles": 4,
                    "maxRelatedFileChars": 3000,
                    "maxContextChars": 10000,
                },
            )
            related = next(
                item
                for item in bundle.contexts
                if item.path.endswith("UserController.java")
            )
            self.assertIn("공통 endpoint", related.reason)
            self.assertIn("/api/users/{}", related.reason)
            self.assertIn("frontend-api와 backend-controller 계층 연결", related.reason)

    def test_focused_excerpt_stratifies_diff_condition_sql_identifier_and_call(self):
        source_lines = [f"const repeatedStatus = value{index};" for index in range(35)]
        source_lines.extend(
            [
                "const fillerBeforeCondition = true;",
                "if (hasPendingChanges) {",
                '  throw new Error("pending change");',
                "}",
                *(f"const conditionGap{index} = {index};" for index in range(12)),
                "SELECT USER_ID FROM TB_USER WHERE ACTIVE_YN = 'Y'",
                *(f"const sqlGap{index} = {index};" for index in range(12)),
                "submitKpiMap(payload);",
                *(f"const callGap{index} = {index};" for index in range(12)),
                "+const diffSentinel = changedValue;",
            ]
        )
        excerpt = _focused_excerpt(
            "\n".join(source_lines),
            ["repeatedStatus"],
            2400,
        )

        self.assertIn("diffSentinel", excerpt)
        self.assertIn("hasPendingChanges", excerpt)
        self.assertIn("SELECT USER_ID", excerpt)
        self.assertIn("repeatedStatus", excerpt)
        self.assertIn("submitKpiMap", excerpt)

    def test_overlapping_roots_do_not_duplicate_the_same_physical_file(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        nested_source = (frontend / "src").resolve()
        changes, _indexes, _excluded, _truncated = collect_changes(
            [frontend, nested_source],
            "",
            date(2000, 1, 1),
            None,
            False,
            {"maxCandidateFiles": 100},
        )
        matching = [item for item in changes if item.path.endswith("PlanPage.tsx")]
        self.assertEqual(len(matching), 1)

    def test_related_context_can_follow_an_exact_reference_across_roots(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        backend = (MULTI_ROOT_FIXTURE / "backend").resolve()
        bundle = build_scan_bundle(
            [frontend, backend],
            "변경: src/components/PlanPage.tsx",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 5000,
                "maxRelatedFiles": 4,
                "maxRelatedFileChars": 3000,
                "maxContextChars": 12000,
            },
        )
        related = [
            item
            for item in bundle.contexts
            if item.path.endswith("PlanService.java") and Path(item.root) == backend
        ]
        self.assertEqual(len(related), 1)
        self.assertIn("import", related[0].reason)

    def test_generic_import_name_does_not_create_a_cross_root_relation(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        backend = (MULTI_ROOT_FIXTURE / "backend").resolve()
        bundle = build_scan_bundle(
            [frontend, backend],
            "변경: src/main/resources/db/h2/data.sql",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 5000,
                "maxRelatedFiles": 4,
                "maxRelatedFileChars": 3000,
                "maxContextChars": 12000,
            },
        )
        related_paths = {item.path for item in bundle.contexts[1:]}
        self.assertNotIn("src/layout/SideMenuLayout.tsx", related_paths)

    def test_generic_import_name_does_not_cross_roots_during_expansion(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        backend = (MULTI_ROOT_FIXTURE / "backend").resolve()
        bundle = build_scan_bundle(
            [frontend, backend],
            "변경: src/components/PlanPage.tsx",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 5000,
                "maxRelatedFiles": 8,
                "maxRelatedFileChars": 3000,
                "maxContextChars": 18000,
            },
        )
        related_paths = {item.path for item in bundle.contexts[1:]}
        self.assertNotIn("src/data.ts", related_paths)

    def test_manual_change_parser_supports_korean_and_git_status(self):
        text = (
            "feat: 저장 시 변경된 사항이 없으면 Alert 처리\n"
            "변경: src/service/UserService.java\n"
            "D src/old/Legacy.java\n"
            "M .env.local\n"
            "refactor: node 삭제에 대한 edge 처리 대응"
        )
        rows = parse_manual_changes(text)
        self.assertEqual(rows[0], ("변경", "src/service/UserService.java"))
        self.assertEqual(rows[1], ("삭제", "src/old/Legacy.java"))
        self.assertEqual(rows[2], ("변경", ".env.local"))
        self.assertEqual(
            parse_manual_notes(text),
            [
                "feat: 저장 시 변경된 사항이 없으면 Alert 처리",
                "refactor: node 삭제에 대한 edge 처리 대응",
            ],
        )

    def test_manual_paths_resolve_globally_and_retain_missing_metadata(self):
        frontend = (MULTI_ROOT_FIXTURE / "frontend").resolve()
        backend = (MULTI_ROOT_FIXTURE / "backend").resolve()
        changes, _indexes, _excluded, _truncated = collect_changes(
            [frontend, backend],
            "\n".join(
                (
                    "변경: src/main/java/com/sample/PlanService.java",
                    "삭제: src/main/java/com/sample/LegacyPlanService.java",
                    "변경: src/main/java/com/sample/MissingPlanService.java",
                )
            ),
            None,
            None,
            False,
            {"maxCandidateFiles": 100},
        )
        by_path = {item.path: item for item in changes}
        self.assertEqual(len(changes), 3)
        self.assertEqual(Path(by_path["src/main/java/com/sample/PlanService.java"].root), backend)
        self.assertEqual(Path(by_path["src/main/java/com/sample/LegacyPlanService.java"].root), backend)
        self.assertFalse(by_path["src/main/java/com/sample/LegacyPlanService.java"].exists)
        self.assertEqual(
            Path(by_path["src/main/java/com/sample/MissingPlanService.java"].root), backend
        )
        self.assertFalse(by_path["src/main/java/com/sample/MissingPlanService.java"].exists)
        self.assertFalse(any(Path(item.root) == frontend for item in changes))

    def test_manual_path_cannot_escape_selected_project_root(self):
        root = FIXTURE_ROOT.resolve()
        logs = []
        changes, _indexes, _excluded, _truncated = collect_changes(
            [root],
            "M ../outside/CHANGELOG.md\nM C:/outside/CHANGELOG.md",
            None,
            None,
            False,
            {"maxCandidateFiles": 100},
            lambda level, message: logs.append((level, message)),
        )
        self.assertEqual(changes, [])
        self.assertEqual(sum(level == "WARN" for level, _message in logs), 2)
        self.assertTrue(all("프로젝트 루트 밖" in message for level, message in logs if level == "WARN"))

    def test_sensitive_manual_file_is_kept_as_metadata_without_body(self):
        missing_changes, _indexes, _excluded, _truncated = collect_changes(
            [FIXTURE_ROOT.resolve()],
            "M .env.local",
            None,
            None,
            False,
            {"maxCandidateFiles": 100},
        )
        self.assertEqual(missing_changes[0].path, ".env.local")
        self.assertFalse(missing_changes[0].exists)

        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "M src/api-credentials.json",
            None,
            None,
            False,
            {"maxCandidateFiles": 100, "maxRelatedFiles": 0, "maxContextChars": 3000},
        )
        self.assertEqual(bundle.contexts[0].mode, "metadata")
        self.assertNotIn("do-not-send-this-value", bundle.contexts[0].excerpt)
        self.assertTrue(any("민감정보 파일 규칙" in warning for warning in bundle.warnings))

    def test_request_terms_prioritize_changed_logic_over_long_import_header(self):
        source = "\n".join(
            [*(f'import Module{index} from "./module{index}";' for index in range(80)),
             "export function saveKpiMap(hasChanges: boolean) {",
             "  if (!hasChanges) {",
             '    alert("저장할 변경 사항이 없습니다");',
             "    return;",
             "  }",
             "  persistKpiMap();",
             "}"]
        )
        excerpt = _focused_excerpt(
            source,
            ["Module", "saveKpiMap", "persistKpiMap"],
            700,
            ["저장", "hasChanges", "alert"],
        )
        self.assertIn("저장할 변경 사항이 없습니다", excerpt)
        self.assertIn("hasChanges", excerpt)

    def test_modern_javascript_module_extensions_are_supported(self):
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: scripts/generate-seed.mjs",
            None,
            None,
            False,
            {"maxCandidateFiles": 100, "maxRelatedFiles": 0, "maxContextChars": 3000},
        )
        self.assertIn("generateSeed", bundle.contexts[0].excerpt)
        self.assertFalse(any("지원하지 않는 확장자" in warning for warning in bundle.warnings))

    def test_dynamic_context_follows_import_and_mapper_contract(self):
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: src/service/UserService.java",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 12000,
                "maxRelatedFiles": 8,
                "maxRelatedFileChars": 5000,
                "maxContextChars": 30000,
            },
        )
        paths = [item.path for item in bundle.contexts]
        self.assertIn("src/service/UserService.java", paths)
        self.assertTrue(any(path.endswith("UserMapper.java") for path in paths))
        self.assertTrue(any(path.endswith("UserDto.java") for path in paths))
        mapper_context = next(item for item in bundle.contexts if item.path.endswith("UserMapper.java"))
        self.assertIn("import", mapper_context.reason)

    def test_reference_graph_expands_controller_to_service_mapper_and_dto(self):
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: src/controller/UserController.java",
            None,
            None,
            False,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 8000,
                "maxRelatedFiles": 6,
                "maxRelatedFileChars": 3000,
                "maxContextChars": 20000,
            },
        )
        related = {item.path: item for item in bundle.contexts}
        self.assertIn("src/service/UserService.java", related)
        self.assertIn("src/mapper/UserMapper.java", related)
        self.assertIn("src/dto/UserDto.java", related)
        self.assertIn("정확한 참조를 한 단계 확장", related["src/mapper/UserMapper.java"].reason)

    def test_related_selection_prefers_exact_layer_links_over_nearby_noise(self):
        root = FIXTURE_ROOT.resolve()
        service = root / "src" / "service" / "UserService.java"
        source = service.read_text(encoding="utf-8")
        change = ChangeItem(str(root), "src/service/UserService.java", "변경", "manual", True)
        profile = ChangedProfile(
            change=change,
            path=service,
            role=_file_role(Path(change.path)),
            family=_business_family(Path(change.path)),
            signals=_extract_reference_signals(service, source),
            terms=_extract_terms(service, source),
        )
        mapper_path = root / "src" / "mapper" / "UserMapper.java"
        mapper = IndexedFile(root, mapper_path, "src/mapper/UserMapper.java", 100, 0)
        mapper_relation = _candidate_relation(
            mapper,
            mapper_path.read_text(encoding="utf-8"),
            profile,
        )
        noise_path = root / "src" / "service" / "AuditService.java"
        noise = IndexedFile(root, noise_path, "src/service/AuditService.java", 100, 0)
        noise_relation = _candidate_relation(noise, "class AuditService { void auditLog() {} }", profile)
        self.assertIsNotNone(mapper_relation)
        self.assertTrue(mapper_relation.explicit)
        self.assertIsNone(noise_relation)

    @patch("promptcase_studio.scanner.is_git_repository", return_value=True)
    @patch("promptcase_studio.scanner._git_diff")
    def test_diff_is_preserved_before_current_source_and_for_deleted_files(self, git_diff, _is_repo):
        git_diff.return_value = "@@ -1 +1 @@\n-old condition\n+new condition"
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: src/service/UserService.java\n삭제: src/legacy/LegacyService.java",
            None,
            None,
            True,
            {
                "maxCandidateFiles": 100,
                "maxChangedFileChars": 3000,
                "maxDiffChars": 1500,
                "maxRelatedFiles": 0,
                "maxContextChars": 7000,
            },
        )
        existing = next(item for item in bundle.contexts if item.path.endswith("UserService.java"))
        deleted = next(item for item in bundle.contexts if item.path.endswith("LegacyService.java"))
        self.assertLess(existing.excerpt.index("[Git diff]"), existing.excerpt.index("[현재 소스]"))
        self.assertIn("diff", existing.mode)
        self.assertIn("[Git diff]", deleted.excerpt)

    def test_large_change_set_keeps_every_change_within_context_budget(self):
        root = FIXTURE_ROOT.resolve()
        changes = []
        for index in range(72):
            layer = "frontend" if index % 2 == 0 else "backend"
            suffix = "tsx" if layer == "frontend" else "java"
            changes.append(
                ChangeItem(
                    str(root),
                    f"src/{layer}/PlanBase{index:02d}.{suffix}",
                    "변경",
                    "git-working-tree",
                    False,
                )
            )
        with (
            patch(
                "promptcase_studio.scanner.collect_changes",
                return_value=(changes, {str(root): []}, 0, False),
            ),
            patch("promptcase_studio.scanner.is_git_repository", return_value=True),
            patch(
                "promptcase_studio.scanner._git_diff",
                return_value="@@ -1 +1 @@\n-old base plan\n+new base plan\n" * 100,
            ),
        ):
            bundle = build_scan_bundle(
                [root],
                "",
                None,
                None,
                True,
                {
                    "maxCandidateFiles": 200,
                    "maxChangedFileChars": 2000,
                    "maxRelatedFiles": 0,
                    "maxContextChars": 18000,
                },
            )
            self.assertEqual(len(bundle.changes), 72)
            self.assertEqual(len(bundle.contexts), 72)
            self.assertLessEqual(sum(len(item.excerpt) for item in bundle.contexts), 18000)
            self.assertTrue(all(item.excerpt for item in bundle.contexts))
            self.assertTrue(any("예산" in warning for warning in bundle.warnings))

    def test_redacts_common_secret_shapes_before_prompting(self):
        source = '''apiKey: "replace-with-a-real-value-123"
GEMINI_API_KEY=gemini-prefixed-secret-value
OPENAI_API_KEY=openai-prefixed-secret-value
DB_PASSWORD=database-prefixed-secret-value
AWS_SECRET_ACCESS_KEY=aws-secret-access-value
JWT_SECRET=jwt-secret-value
GITHUB_TOKEN=github-token-value
privateKey: private-key-value
DATABASE_URL=postgres://sample:secret@localhost/app
Authorization: Bearer abcdefghijklmnopqrstuvwxyz
<password>super-secret-password</password>'''
        redacted = _redact_sensitive_text(source)
        self.assertEqual(redacted.count("[REDACTED]"), 11)
        self.assertNotIn("replace-with-a-real-value-123", redacted)
        self.assertNotIn("gemini-prefixed-secret-value", redacted)
        self.assertNotIn("openai-prefixed-secret-value", redacted)
        self.assertNotIn("database-prefixed-secret-value", redacted)
        self.assertNotIn("aws-secret-access-value", redacted)
        self.assertNotIn("jwt-secret-value", redacted)
        self.assertNotIn("github-token-value", redacted)
        self.assertNotIn("private-key-value", redacted)
        self.assertNotIn("postgres://sample:secret@localhost/app", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertNotIn("super-secret-password", redacted)

    def test_bounded_text_reader_does_not_load_the_entire_file(self):
        class TrackingBytesIO(BytesIO):
            requested_size = None

            def read(self, size=-1):
                self.requested_size = size
                return super().read(size)

        stream = TrackingBytesIO(("가나다라마바사" * 1000).encode("utf-8"))
        with patch.object(Path, "open", return_value=stream):
            text = _read_text(Path("large.sql"), 25)
        self.assertEqual(stream.requested_size, 100)
        self.assertLessEqual(len(text), 25)

    @patch("promptcase_studio.scanner.is_git_repository", return_value=True)
    @patch("promptcase_studio.scanner._run_git")
    def test_git_changes_merge_working_tree_and_history(self, run_git, _is_repo):
        def fake_git(_root, args):
            if "--show-toplevel" in args:
                return str(FIXTURE_ROOT.resolve())
            if "status" in args:
                return " M src/service/UserService.java\n?? src/service/NewService.java\n"
            if "log" in args:
                return "D\tsrc/service/LegacyService.java\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        changes = collect_git_changes(FIXTURE_ROOT.resolve(), date(2026, 6, 1))
        by_path = {item.path: item for item in changes}
        self.assertEqual(by_path["src/service/UserService.java"].change_type, "변경")
        self.assertEqual(by_path["src/service/NewService.java"].change_type, "신규")
        self.assertEqual(by_path["src/service/LegacyService.java"].change_type, "삭제")

    @patch("promptcase_studio.scanner._run_git")
    def test_git_diff_combines_committed_and_working_changes_from_date_base(self, run_git):
        def fake_git(_root, args):
            if args[:2] == ["rev-list", "-1"]:
                return "base-commit\n"
            if args[:6] == [
                "diff",
                "--find-renames",
                "--no-ext-diff",
                "--unified=4",
                "base-commit",
                "--",
            ]:
                return "@@ -1 +1 @@\n-old committed value\n+new working value\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        diff = _git_diff(
            FIXTURE_ROOT.resolve(),
            "src/service/UserService.java",
            date(2026, 7, 1),
            date.today(),
        )
        self.assertIn("old committed value", diff)
        self.assertIn("new working value", diff)
        self.assertEqual(run_git.call_count, 2)

    @patch("promptcase_studio.scanner._run_git")
    def test_git_diff_uses_empty_tree_when_repository_started_after_date(self, run_git):
        def fake_git(_root, args):
            if args[:2] == ["rev-list", "-1"]:
                return ""
            if args == ["rev-parse", "--verify", "HEAD"]:
                return "first-commit\n"
            if args[0] == "diff" and "4b825dc642cb6eb9a060e54bf8d69288fbee4904" in args:
                return "@@ -0,0 +1 @@\n+initial content\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        diff = _git_diff(
            FIXTURE_ROOT.resolve(),
            "README.md",
            date(2026, 7, 1),
            date.today(),
        )
        self.assertIn("initial content", diff)
        self.assertEqual(run_git.call_count, 3)

    def test_modified_date_range_includes_both_boundary_dates(self):
        root = FIXTURE_ROOT.resolve()
        date_from = date(2026, 7, 1)
        date_to = date(2026, 7, 3)
        start = datetime.combine(date_from, time.min).timestamp()
        end = datetime.combine(date_to, time.max).timestamp()
        next_midnight = datetime.combine(date_to + timedelta(days=1), time.min).timestamp()
        index = [
            IndexedFile(root, root / "before.java", "before.java", 1, start - 0.001),
            IndexedFile(root, root / "start.java", "start.java", 1, start),
            IndexedFile(root, root / "end.java", "end.java", 1, end),
            IndexedFile(
                root,
                root / "next-midnight.java",
                "next-midnight.java",
                1,
                next_midnight,
            ),
        ]

        changes = collect_date_changes(index, date_from, date_to)

        self.assertEqual([item.path for item in changes], ["start.java", "end.java"])

    def test_reversed_date_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "시작일은 종료일보다 늦을 수 없습니다"):
            collect_date_changes([], date(2026, 7, 3), date(2026, 7, 1))

    @patch("promptcase_studio.scanner.is_git_repository", return_value=True)
    @patch("promptcase_studio.scanner._run_git")
    def test_git_history_uses_inclusive_start_and_end_of_day(self, run_git, _is_repo):
        date_from = date.today().replace(day=1)
        date_to = date.today()

        def fake_git(_root, args):
            if "--show-toplevel" in args:
                return str(FIXTURE_ROOT.resolve())
            if "status" in args:
                return ""
            if "log" in args:
                return "M\tsrc/service/UserService.java\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        changes = collect_git_changes(FIXTURE_ROOT.resolve(), date_from, date_to)
        log_args = next(call.args[1] for call in run_git.call_args_list if "log" in call.args[1])

        self.assertIn(f"--since={date_from.isoformat()}T00:00:00", log_args)
        self.assertIn(f"--until={date_to.isoformat()}T23:59:59", log_args)
        self.assertEqual(changes[0].path, "src/service/UserService.java")

    @patch("promptcase_studio.scanner._run_git")
    def test_historical_git_diff_stops_at_selected_end_date(self, run_git):
        date_to = date.today() - timedelta(days=2)
        date_from = date_to - timedelta(days=2)
        next_midnight = (date_to + timedelta(days=1)).isoformat()

        def fake_git(_root, args):
            if args[:2] == ["rev-list", "-1"]:
                if f"--before={date_from.isoformat()}T00:00:00" in args:
                    return "base-commit\n"
                if f"--before={next_midnight}T00:00:00" in args:
                    return "end-commit\n"
            if args[0] == "diff" and "base-commit" in args and "end-commit" in args:
                return "@@ -1 +1 @@\n-old range value\n+new range value\n"
            raise AssertionError(args)

        run_git.side_effect = fake_git
        diff = _git_diff(
            FIXTURE_ROOT.resolve(),
            "src/service/UserService.java",
            date_from,
            date_to,
        )

        self.assertIn("new range value", diff)
        self.assertEqual(run_git.call_count, 3)


if __name__ == "__main__":
    unittest.main()
