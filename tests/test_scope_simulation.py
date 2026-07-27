import shutil
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from scripts.simulate_scope_recall import (
    REPOSITORY_PROFILES,
    SERVICE_PATH,
    TARGET_PATHS,
    create_repository,
    date_profiles,
    evaluate_scenario,
    input_profiles,
    scanner_settings,
)


TEMP_ROOT = Path(__file__).resolve().parent.parent / "tmp" / "tests" / "scope-simulation"


class ScopeSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.today = date(2026, 7, 27)
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.workspace = TEMP_ROOT / f"case-{uuid4().hex}"
        cls.workspace.mkdir()
        cls.profile = REPOSITORY_PROFILES[1]
        cls.repository = create_repository(cls.workspace, cls.profile, cls.today)
        cls.settings = scanner_settings()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def test_exact_range_and_complete_input_recovers_every_changed_target(self):
        result = evaluate_scenario(
            self.repository,
            self.profile,
            next(profile for profile in input_profiles() if profile.name == "complete"),
            next(profile for profile in date_profiles(self.today) if profile.name == "exact-target"),
            self.settings,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.changed_target_count, len(TARGET_PATHS))
        self.assertEqual(result.evidence_target_count, len(TARGET_PATHS))
        self.assertTrue(result.service_as_change)
        self.assertEqual(result.relation_gated_recall, 1.0)

    def test_vo_only_input_recovers_directly_referencing_changed_service(self):
        result = evaluate_scenario(
            self.repository,
            self.profile,
            next(profile for profile in input_profiles() if profile.name == "vo-paths-only"),
            next(
                profile
                for profile in date_profiles(self.today)
                if profile.name == "vo-commit-day-only"
            ),
            self.settings,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.changed_target_count, len(TARGET_PATHS))
        self.assertTrue(result.service_as_change)
        self.assertTrue(result.service_as_evidence)
        self.assertTrue(result.relation_gated_service_as_change)
        self.assertEqual(result.relation_gated_recall, result.changed_recall)
        self.assertIn(SERVICE_PATH, TARGET_PATHS)


if __name__ == "__main__":
    unittest.main()
