from __future__ import annotations

import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from promptcase_studio.config import (
    _migrate_legacy_template_path,
    _replace_from_bundle,
    build_runtime_paths,
    initialize_runtime_environment,
    resolve_project_path,
    resource_path,
)
from promptcase_studio.template_catalog import UNIT_TEST_TEMPLATE


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMP_ROOT = PROJECT_ROOT / "tmp" / "tests"


@contextmanager
def writable_test_directory():
    directory = TEMP_ROOT / "runtime-paths" / uuid4().hex
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class RuntimePathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def test_source_mode_keeps_repository_layout(self) -> None:
        with writable_test_directory() as directory:
            repository = directory / "repository"
            ignored_data_root = directory / "app-data"
            paths = build_runtime_paths(
                frozen=False,
                resource_root=repository,
                data_root=ignored_data_root,
            )

            self.assertEqual(paths.resource_root, repository.resolve())
            self.assertEqual(paths.data_root, repository.resolve())
            self.assertFalse(paths.frozen)

    def test_legacy_unit_test_template_path_is_migrated(self) -> None:
        settings = {"templatePath": "templates\\단위테스트 템플릿.xlsx"}

        migrated = _migrate_legacy_template_path(settings)

        self.assertEqual(migrated["templatePath"], UNIT_TEST_TEMPLATE.relative_path)
        self.assertEqual(UNIT_TEST_TEMPLATE.download_name, "단위테스트 템플릿.xlsx")

    def test_bundled_resource_replace_retries_transient_windows_lock(self) -> None:
        with writable_test_directory() as directory:
            source = directory / "source.md"
            destination = directory / "destination.md"
            source.write_text("new", encoding="utf-8")
            destination.write_text("old", encoding="utf-8")
            original_replace = Path.replace
            attempts = 0

            def flaky_replace(path: Path, target: Path):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("synthetic antivirus lock")
                return original_replace(path, target)

            with (
                patch.object(Path, "replace", new=flaky_replace),
                patch("promptcase_studio.config.time.sleep") as sleep,
            ):
                _replace_from_bundle(source, destination)

            self.assertEqual(destination.read_text(encoding="utf-8"), "new")
            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_frozen_mode_separates_resources_and_user_data(self) -> None:
        with writable_test_directory() as base:
            resources = base / "bundle"
            app_data = base / "app-data"
            paths = build_runtime_paths(
                frozen=True,
                resource_root=resources,
                data_root=app_data,
            )

            self.assertEqual(paths.resource_root, resources.resolve())
            self.assertEqual(paths.data_root, app_data.resolve())
            self.assertEqual(paths.default_settings, app_data / "config" / "app.settings.json")
            self.assertEqual(resource_path("favicon.ico", paths), resources / "favicon.ico")
            self.assertEqual(resolve_project_path("outputs", paths), app_data / "outputs")

    def test_first_run_copies_public_resources_without_secrets(self) -> None:
        with writable_test_directory() as base:
            resources = base / "bundle"
            app_data = base / "app-data"
            source_files = {
                "config/app.settings.json": "{\"schemaVersion\": 1}",
                "config/qwen.settings.json": "{\"model\": {}}",
                "prompts/system.md": "system prompt",
                "schemas/test_case_response.schema.json": "{}",
                "templates/unittest_template.xlsx": "template",
                "favicon.ico": "icon",
                ".env": "GEMINI_API_KEY=must-not-be-copied",
            }
            for relative, content in source_files.items():
                path = resources / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            paths = build_runtime_paths(
                frozen=True,
                resource_root=resources,
                data_root=app_data,
            )
            initialize_runtime_environment(paths)

            for directory_name in (
                "config",
                "prompts",
                "schemas",
                "templates",
                "runs",
                "outputs",
            ):
                self.assertTrue((app_data / directory_name).is_dir())
            for relative in source_files:
                if relative == ".env":
                    self.assertFalse((app_data / relative).exists())
                else:
                    self.assertTrue((app_data / relative).is_file(), relative)
            self.assertTrue((app_data / "config" / ".bundled-resources.json").is_file())

    def test_reinitialization_preserves_user_customizations(self) -> None:
        with writable_test_directory() as base:
            resources = base / "bundle"
            app_data = base / "app-data"
            bundled_prompt = resources / "prompts" / "system.md"
            bundled_prompt.parent.mkdir(parents=True)
            bundled_prompt.write_text("bundled", encoding="utf-8")
            paths = build_runtime_paths(
                frozen=True,
                resource_root=resources,
                data_root=app_data,
            )

            initialize_runtime_environment(paths)
            user_prompt = app_data / "prompts" / "system.md"
            user_prompt.write_text("customized", encoding="utf-8")
            bundled_prompt.write_text("updated bundle", encoding="utf-8")
            initialize_runtime_environment(paths)

            self.assertEqual(user_prompt.read_text(encoding="utf-8"), "customized")

    def test_unchanged_managed_resource_is_upgraded(self) -> None:
        with writable_test_directory() as base:
            resources = base / "bundle"
            app_data = base / "app-data"
            bundled_prompt = resources / "prompts" / "system.md"
            bundled_prompt.parent.mkdir(parents=True)
            bundled_prompt.write_text("version one", encoding="utf-8")
            paths = build_runtime_paths(
                frozen=True,
                resource_root=resources,
                data_root=app_data,
            )

            initialize_runtime_environment(paths)
            bundled_prompt.write_text("version two", encoding="utf-8")
            initialize_runtime_environment(paths)

            self.assertEqual(
                (app_data / "prompts" / "system.md").read_text(encoding="utf-8"),
                "version two",
            )

    def test_legacy_defaults_are_backed_up_before_upgrade(self) -> None:
        with writable_test_directory() as base:
            resources = base / "bundle"
            app_data = base / "app-data"
            bundled_prompt = resources / "prompts" / "system.md"
            bundled_prompt.parent.mkdir(parents=True)
            bundled_prompt.write_text("new bundled prompt", encoding="utf-8")
            old_prompt = app_data / "prompts" / "system.md"
            old_prompt.parent.mkdir(parents=True)
            old_prompt.write_text("old local prompt", encoding="utf-8")
            paths = build_runtime_paths(
                frozen=True,
                resource_root=resources,
                data_root=app_data,
            )

            initialize_runtime_environment(paths)

            self.assertEqual(old_prompt.read_text(encoding="utf-8"), "new bundled prompt")
            backups = list((app_data / "backups").rglob("system.md"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "old local prompt")


if __name__ == "__main__":
    unittest.main()
