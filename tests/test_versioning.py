import json
import re
import unittest

from promptcase_studio import __version__
from promptcase_studio.config import PROJECT_ROOT


class VersioningTests(unittest.TestCase):
    def test_product_version_is_semver(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_product_and_prompt_bundle_versions_match(self):
        manifest = json.loads(
            (PROJECT_ROOT / "prompts" / "manifest.json").read_text(
                encoding="utf-8-sig"
            )
        )

        self.assertEqual(manifest["bundleVersion"], __version__)

    def test_response_schema_id_matches_manifest_policy_version(self):
        manifest = json.loads(
            (PROJECT_ROOT / "prompts" / "manifest.json").read_text(encoding="utf-8-sig")
        )
        schema = json.loads(
            (PROJECT_ROOT / "schemas" / "test_case_response.schema.json").read_text(
                encoding="utf-8-sig"
            )
        )

        self.assertTrue(
            schema["$id"].endswith(
                f"test_case_response-{manifest['responseSchemaVersion']}.json"
            )
        )

    def test_response_schema_accepts_cross_platform_target_ids(self):
        schema = json.loads(
            (PROJECT_ROOT / "schemas" / "test_case_response.schema.json").read_text(
                encoding="utf-8-sig"
            )
        )
        pattern = re.compile(
            schema["properties"]["testCase"]["properties"]["targetIds"]["items"][
                "pattern"
            ]
        )

        for value in (
            "ZCL_USER=>READ",
            "ZIF_USER~READ",
            "App\\Service\\UserService",
            "UserService#findActiveUser",
            "[dbo].[TB_USER]",
        ):
            with self.subTest(value=value):
                self.assertIsNotNone(pattern.fullmatch(value))

    def test_pyinstaller_uses_the_product_version_resource(self):
        spec = (PROJECT_ROOT / "promptcase-studio.spec").read_text(encoding="utf-8")

        self.assertRegex(spec, re.compile(r"version\s*=\s*version_resource"))

    def test_windows_onefile_build_uses_cleanup_fixed_pyinstaller(self):
        requirements = (PROJECT_ROOT / "requirements-build.txt").read_text(
            encoding="utf-8"
        )
        spec = (PROJECT_ROOT / "promptcase-studio.spec").read_text(encoding="utf-8")

        self.assertIn("PyInstaller==6.21.0", requirements)
        self.assertRegex(spec, re.compile(r"upx\s*=\s*False"))

    def test_onedir_fallback_reuses_spec_without_replacing_onefile_output(self):
        spec = (PROJECT_ROOT / "promptcase-studio.spec").read_text(encoding="utf-8")
        onefile_script = (PROJECT_ROOT / "build-exe.bat").read_text(encoding="utf-8")
        folder_script = (PROJECT_ROOT / "build-folder.bat").read_text(
            encoding="utf-8"
        )
        private_folder_script = (
            PROJECT_ROOT / "build-private-folder.bat"
        ).read_text(encoding="utf-8")
        private_onefile_script = (
            PROJECT_ROOT / "build-private-exe.bat"
        ).read_text(encoding="utf-8")

        self.assertIn('os.environ.get("PROMPTCASE_PACKAGE_MODE", "onefile")', spec)
        self.assertIn("COLLECT(", spec)
        self.assertIn('name="PromptcaseStudio-folder"', spec)
        self.assertIn("exclude_binaries=onedir_enabled", spec)
        self.assertIn("dist\\PromptcaseStudio.exe", onefile_script)
        self.assertIn(
            "dist\\PromptcaseStudio-folder\\PromptcaseStudio.exe", onefile_script
        )
        self.assertIn('set "PROMPTCASE_PACKAGE_MODE=onedir"', folder_script)
        self.assertIn('call "%~dp0build-exe.bat" onedir', folder_script)
        self.assertIn('set "PROMPTCASE_PACKAGE_MODE=onefile"', private_onefile_script)
        self.assertIn('set "PROMPTCASE_PRIVATE_BUNDLE=1"', private_folder_script)
        self.assertIn('set "PROMPTCASE_PACKAGE_MODE=onedir"', private_folder_script)

    def test_packaging_docs_explain_the_onedir_mei_fallback(self):
        packaging = (PROJECT_ROOT / "docs" / "PACKAGING.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("build-folder.bat", packaging)
        self.assertIn("build-private-folder.bat", packaging)
        self.assertIn("PromptcaseStudio-folder", packaging)
        self.assertIn("_MEI", packaging)
        self.assertIn("폴더 전체", packaging)

    def test_private_build_uses_the_runtime_qwen_provider_selector(self):
        spec = (PROJECT_ROOT / "promptcase-studio.spec").read_text(encoding="utf-8")

        self.assertIn("select_qwen_provider_entry(", spec)
        self.assertNotIn("selected_provider = provider_entries[0]", spec)

    def test_readme_does_not_pin_a_stale_current_version(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertNotRegex(readme, r"현재 기준 버전은 `\d+\.\d+\.\d+`")


if __name__ == "__main__":
    unittest.main()
