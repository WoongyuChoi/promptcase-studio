import unittest
from copy import deepcopy
from pathlib import Path

from promptcase_studio.config import load_settings
from promptcase_studio.models import AnalysisRequest
from promptcase_studio.pipeline import run_pipeline


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_project"
TEMP_ROOT = PROJECT_ROOT / "tmp" / "tests"


class PipelineTests(unittest.TestCase):
    def test_mock_pipeline_runs_without_network_and_generates_xlsx(self):
        case_directory = TEMP_ROOT / "pipeline"
        case_directory.mkdir(parents=True, exist_ok=True)
        settings = deepcopy(load_settings())
        settings["mockMode"] = True
        settings["templatePath"] = str(PROJECT_ROOT / "templates" / "단위테스트 템플릿.xlsx")
        settings["runDirectory"] = str(case_directory / "runs")
        settings["outputDirectory"] = str(case_directory / "outputs")
        request = AnalysisRequest(
            project_roots=[FIXTURE_ROOT.resolve()],
            manual_changes="변경: src/service/UserService.java",
            request_text="활성 사용자 조회 조건을 변경함",
            environment="online",
            since_date=None,
            include_git=False,
        )
        logs = []
        result = run_pipeline(request, settings, log=lambda level, message: logs.append((level, message)))
        self.assertTrue(result.document_path.exists())
        self.assertTrue((result.run_directory / "change_manifest.json").exists())
        self.assertTrue((result.run_directory / "context_bundle.md").exists())
        self.assertTrue(any(level == "MOCK" for level, _ in logs))


if __name__ == "__main__":
    unittest.main()
