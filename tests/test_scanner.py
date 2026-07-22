import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from promptcase_studio.scanner import (
    _redact_sensitive_text,
    build_scan_bundle,
    collect_git_changes,
    parse_manual_changes,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_project"


class ScannerTests(unittest.TestCase):
    def test_manual_change_parser_supports_korean_and_git_status(self):
        rows = parse_manual_changes("변경: src/service/UserService.java\nD src/old/Legacy.java")
        self.assertEqual(rows[0], ("변경", "src/service/UserService.java"))
        self.assertEqual(rows[1], ("삭제", "src/old/Legacy.java"))

    def test_dynamic_context_follows_import_and_mapper_contract(self):
        bundle = build_scan_bundle(
            [FIXTURE_ROOT.resolve()],
            "변경: src/service/UserService.java",
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

    def test_redacts_common_secret_shapes_before_prompting(self):
        source = '''apiKey: "replace-with-a-real-value-123"
Authorization: Bearer abcdefghijklmnopqrstuvwxyz
<password>super-secret-password</password>'''
        redacted = _redact_sensitive_text(source)
        self.assertEqual(redacted.count("[REDACTED]"), 3)
        self.assertNotIn("replace-with-a-real-value-123", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertNotIn("super-secret-password", redacted)

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


if __name__ == "__main__":
    unittest.main()
