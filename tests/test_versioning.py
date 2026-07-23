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


if __name__ == "__main__":
    unittest.main()
