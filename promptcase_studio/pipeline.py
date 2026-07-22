from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from promptcase_studio.config import resolve_project_path
from promptcase_studio.excel_writer import generate_workbook
from promptcase_studio.models import AnalysisRequest, ChangeItem, ChunkCallback, LogCallback, PipelineResult
from promptcase_studio.prompt_builder import build_prompt
from promptcase_studio.providers import create_provider
from promptcase_studio.response_parser import parse_structured_response
from promptcase_studio.scanner import build_scan_bundle, write_scan_artifacts


def _log(callback: LogCallback | None, level: str, message: str) -> None:
    if callback:
        callback(level, message)


def _project_label(change: ChangeItem) -> str:
    root_name = Path(change.root).name
    lowered = change.path.casefold()
    frontend_markers = ("frontend", "/web/", "/src/components/", "/src/pages/")
    backend_markers = ("backend", "/src/main/java/", "/mapper/", "/resources/")
    frontend_suffixes = (".tsx", ".ts", ".jsx", ".js", ".vue", ".css", ".scss")
    if any(marker in f"/{lowered}" for marker in frontend_markers) or lowered.endswith(frontend_suffixes):
        return f"{root_name} - Frontend"
    if any(marker in f"/{lowered}" for marker in backend_markers) or lowered.endswith((".java", ".kt", ".xml", ".sql")):
        return f"{root_name} - Backend"
    return root_name


def _program_info(changes: list[ChangeItem]) -> list[dict[str, str]]:
    return [
        {
            "program": Path(item.path).name,
            "project": _project_label(item),
            "workContent": "요건 변경에 따른 개발 프로그램 수정",
            "changeType": item.change_type,
        }
        for item in changes
    ]


def _safe_output_stem(name: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", name).strip("_")
    return text[:60] or "단위테스트"


def run_pipeline(
    request: AnalysisRequest,
    settings: dict[str, Any],
    log: LogCallback | None = None,
    on_chunk: ChunkCallback | None = None,
) -> PipelineResult:
    started = datetime.now()
    run_id = started.strftime("%Y%m%d-%H%M%S-%f")
    run_directory = resolve_project_path(settings.get("runDirectory", "runs")) / run_id
    run_directory.mkdir(parents=True, exist_ok=False)

    _log(log, "START", f"RUN {run_id} 시작")
    _log(log, "SCAN", f"프로젝트 루트 {len(request.project_roots)}개 스캔")
    bundle = build_scan_bundle(
        request.project_roots,
        request.manual_changes,
        request.since_date,
        request.include_git,
        settings.get("scanner", {}),
        log,
    )
    write_scan_artifacts(bundle, run_directory)
    _log(log, "ARTIFACT", "change manifest와 context bundle 저장")

    prompt = build_prompt(bundle, request.request_text)
    (run_directory / "prompt.md").write_text(prompt, encoding="utf-8")
    _log(log, "PROMPT", f"구조화 프롬프트 {len(prompt):,}자 구성")

    provider = create_provider(settings, request.environment)
    response_text = provider.generate(prompt, log=log, on_chunk=on_chunk)
    response_path = run_directory / "response.raw.txt"
    response_path.write_text(response_text, encoding="utf-8")

    _log(log, "VALIDATE", "AI JSON 계약 검증")
    structured = parse_structured_response(response_text)
    document = {"programInfo": _program_info(bundle.changes), **structured}
    (run_directory / "document.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    template_path = resolve_project_path(settings.get("templatePath", "templates/단위테스트 템플릿.xlsx"))
    output_directory = resolve_project_path(settings.get("outputDirectory", "outputs"))
    title = _safe_output_stem(structured["testCase"]["name"])
    document_path = output_directory / f"단위테스트_{title}_{started.strftime('%Y%m%d_%H%M%S')}.xlsx"
    _log(log, "EXCEL", f"템플릿 3개 시트에 문안 입력")
    generate_workbook(template_path, document_path, document)
    _log(log, "DONE", f"문서 생성 완료: {document_path.name}")
    return PipelineResult(run_id, run_directory, document_path, response_path, bundle)

