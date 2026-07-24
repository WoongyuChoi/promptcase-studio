import json
import re
import unittest

from promptcase_studio import __version__
from promptcase_studio.config import PROJECT_ROOT


class VersioningTests(unittest.TestCase):
    def test_product_version_is_semver(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_product_prompt_bundle_and_readme_versions_match(self):
        manifest = json.loads(
            (PROJECT_ROOT / "prompts" / "manifest.json").read_text(
                encoding="utf-8-sig"
            )
        )
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        readme_version = re.search(
            r"img\.shields\.io/badge/Version-(\d+\.\d+\.\d+)-", readme
        )

        self.assertEqual(manifest["bundleVersion"], __version__)
        self.assertIsNotNone(readme_version)
        self.assertEqual(readme_version.group(1), __version__)

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
        self.assertIn('name=f"PromptcaseStudio-{app_version}"', spec)
        self.assertIn("exclude_binaries=onedir_enabled", spec)
        self.assertIn("dist\\PromptcaseStudio.exe", onefile_script)
        self.assertIn(
            "dist\\PromptcaseStudio-%APP_VERSION%\\PromptcaseStudio.exe",
            onefile_script,
        )
        self.assertIn("Compress-Archive", onefile_script)
        self.assertIn(
            "PromptcaseStudio-%APP_VERSION%-windows-x64.zip", onefile_script
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
        self.assertIn("PromptcaseStudio-{버전}", packaging)
        self.assertIn("-windows-x64.zip", packaging)
        self.assertIn("_MEI", packaging)
        self.assertIn("폴더 전체", packaging)

    def test_release_docs_make_the_versioned_zip_the_primary_artifact(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        versioning = (PROJECT_ROOT / "docs" / "VERSIONING.md").read_text(
            encoding="utf-8"
        )
        agent_rules = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        artifact = "PromptcaseStudio-{버전}-windows-x64.zip"
        self.assertIn(artifact, readme)
        self.assertIn(artifact, versioning)
        self.assertIn(artifact, agent_rules)
        self.assertIn("ZIP만 공유", readme)
        self.assertIn("실행 파일만 따로 전달하지 않는다", versioning)
        self.assertIn("build-private-folder.bat", agent_rules)

    def test_private_build_uses_the_runtime_qwen_provider_selector(self):
        spec = (PROJECT_ROOT / "promptcase-studio.spec").read_text(encoding="utf-8")

        self.assertIn("select_qwen_provider_entry(", spec)
        self.assertNotIn("selected_provider = provider_entries[0]", spec)

    def test_bump_script_keeps_the_readme_badge_in_sync(self):
        script = (PROJECT_ROOT / "scripts" / "bump_version.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("README_FILE", script)
        self.assertIn("README_VERSION_BADGE", script)
        self.assertIn("read_readme_version()", script)


if __name__ == "__main__":
    unittest.main()
