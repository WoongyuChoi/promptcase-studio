from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from promptcase_studio.config import resolve_project_path
from promptcase_studio.excel_writer import generate_workbook
from promptcase_studio.models import AnalysisRequest, ChangeItem, ChunkCallback, LogCallback, PipelineResult
from promptcase_studio.program_info import (
    DEFAULT_PROGRAM_CATEGORY,
    build_work_content,
    classify_program_detail,
    normalize_program_category,
)
from promptcase_studio.prompt_builder import build_prompt_package
from promptcase_studio.providers import create_provider
from promptcase_studio.providers.base import ProviderError, ProviderRateLimitError
from promptcase_studio.quality import build_quality_report, quality_report_markdown
from promptcase_studio.response_parser import ResponseValidationError, parse_structured_response
from promptcase_studio.scanner import build_scan_bundle, write_scan_artifacts
from promptcase_studio.template_catalog import UNIT_TEST_TEMPLATE


class PipelinePausedError(RuntimeError):
    """The current run is safely preserved and can be retried after an external limit clears."""


def _provider_interruption(exc: ProviderError) -> dict[str, Any]:
    serializer = getattr(exc, "to_dict", None)
    if callable(serializer):
        payload = serializer()
        if isinstance(payload, dict):
            return payload
    return {
        "type": "provider_error",
        "provider": exc.__class__.__name__,
        "message": str(exc),
    }


def _log(callback: LogCallback | None, level: str, message: str) -> None:
    if callback:
        callback(level, message)


def _validate_date_range(request: AnalysisRequest) -> None:
    if (request.date_from is None) != (request.date_to is None):
        raise ValueError("날짜 범위는 시작일과 종료일을 모두 선택해 주세요.")
    if request.date_from and request.date_to and request.date_from > request.date_to:
        raise ValueError("종료일은 시작일보다 빠를 수 없습니다.")


PROJECT_MARKERS = (
    ".git",
    "package.json",
    "pyproject.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
)
GENERIC_SOURCE_ROOTS = {
    "app",
    "api",
    "backend",
    "client",
    "common",
    "component",
    "components",
    "controller",
    "controllers",
    "core",
    "data",
    "domain",
    "frontend",
    "hooks",
    "infrastructure",
    "java",
    "kotlin",
    "main",
    "mock",
    "module",
    "modules",
    "pages",
    "python",
    "resources",
    "scripts",
    "server",
    "service",
    "services",
    "source",
    "src",
    "test",
    "tests",
}


def _project_label(change: ChangeItem) -> str:
    """Return the nearest project root even when a source subfolder was selected."""
    root_path = Path(change.root)
    candidates = (root_path, *root_path.parents)
    for candidate in candidates:
        name = candidate.name.strip()
        if not name:
            continue
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return name
        # A deliberately selected non-generic folder is itself a valid project
        # boundary. This prevents a nested standalone source bundle from being
        # mislabeled with an unrelated outer Git repository name.
        if name.casefold() not in GENERIC_SOURCE_ROOTS:
            return name
    return "프로젝트"


def _program_info(
    changes: list[ChangeItem],
    category: str = DEFAULT_PROGRAM_CATEGORY,
) -> list[dict[str, str]]:
    normalized_category = normalize_program_category(category)
    rows: list[dict[str, str]] = []
    for item in changes:
        detail_category = classify_program_detail(item.path)
        rows.append(
            {
                "category": normalized_category,
                "detailCategory": detail_category,
                "program": Path(item.path).name,
                "project": _project_label(item),
                "workContent": build_work_content(
                    item.change_type,
                    detail_category,
                ),
                "changeType": item.change_type,
            }
        )
    return rows


def _program_category(
    structured: dict[str, Any],
    request: AnalysisRequest,
) -> str:
    supplied = str(structured.get("documentTitle", "")).strip()
    if supplied:
        return normalize_program_category(supplied)
    inferred_title = _document_title(structured, request).replace("_", " ")
    if "시스템" in inferred_title:
        return normalize_program_category(inferred_title)
    return DEFAULT_PROGRAM_CATEGORY


def _safe_output_stem(name: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", name)
    text = re.sub(r"_+", "_", text).strip("_-")
    return text[:40].rstrip("_-") or "프로젝트"


def _document_title(structured: dict[str, Any], request: AnalysisRequest) -> str:
    title = str(structured.get("documentTitle", "")).strip()
    if not title:
        lines = [line.strip() for line in request.request_text.splitlines()]
        for index, line in enumerate(lines):
            if line.replace(" ", "") in {"요청제목", "제목"}:
                title = next((item for item in lines[index + 1 :] if item), "")
                break
        search_text = title or request.request_text
        system_match = re.search(r"[0-9A-Za-z가-힣_-]{2,40}시스템", search_text)
        if system_match:
            title = system_match.group(0)

    if not title:
        generic_roots = {"src", "source", "app", "frontend", "backend", "api"}
        for root in request.project_roots:
            candidate = root.name
            if candidate.casefold() in generic_roots:
                candidate = root.parent.name
            if candidate and candidate.casefold() not in generic_roots:
                title = re.sub(r"(?i)(?:[-_](?:backend|frontend|api))+$", "", candidate)
                break

    if not title:
        title = str(structured.get("testCase", {}).get("name", "프로젝트"))
    title = re.sub(r"\s*단위\s*테스트.*$", "", title).strip()
    title = re.sub(r"(?:19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}", "", title)
    title = re.sub(r"(?<!\d)\d{6}(?!\d)", "", title).strip(" _-")
    return _safe_output_stem(title)


def _preview(value: str, limit: int = 1_000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    head = max(1, limit - 120)
    return f"{text[:head]}\n표시 한도를 넘어 {len(text) - head:,}자를 생략했습니다"


def _correction_prompt(original_prompt: str, previous_response: str, error: Exception) -> str:
    return (
        f"{original_prompt}\n\n"
        "[응답 형식 교정 요청]\n"
        "이전 응답이 아래 계약 검증을 통과하지 못했습니다. 소스 근거와 원래 지시를 유지하면서 "
        "오류만 바로잡은 JSON 객체 하나를 다시 작성하세요. 설명이나 코드 블록은 출력하지 마세요.\n\n"
        f"검증 오류\n{error}\n\n"
        f"이전 응답\n{previous_response}"
    )


def _provider_diagnostics(provider: Any) -> dict[str, Any]:
    value = getattr(provider, "last_diagnostics", None)
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        return result if isinstance(result, dict) else {}
    return {
        key: getattr(value, key)
        for key in ("finish_reason", "prompt_tokens", "completion_tokens", "total_tokens")
        if getattr(value, key, None) is not None
    }


def _log_provider_diagnostics(provider: Any, callback: LogCallback | None) -> None:
    diagnostics = _provider_diagnostics(provider)
    if not diagnostics:
        return
    finish_reason = diagnostics.get("finish_reason") or diagnostics.get("finishReason") or "확인 불가"
    prompt_tokens = diagnostics.get("prompt_tokens") or diagnostics.get("promptTokenCount")
    completion_tokens = diagnostics.get("completion_tokens") or diagnostics.get("candidatesTokenCount")
    total_tokens = diagnostics.get("total_tokens") or diagnostics.get("totalTokenCount")
    token_rows = []
    if prompt_tokens is not None:
        token_rows.append(f"입력 {int(prompt_tokens):,}")
    if completion_tokens is not None:
        token_rows.append(f"출력 {int(completion_tokens):,}")
    if total_tokens is not None:
        token_rows.append(f"합계 {int(total_tokens):,}")
    token_text = ", ".join(token_rows) if token_rows else "토큰 정보 없음"
    _log(callback, "USAGE", f"종료 사유 {finish_reason}, {token_text}")


def _generate_validated_response(
    provider: Any,
    base_prompt: str,
    evidence: str,
    validation_attempts: int,
    run_directory: Path,
    artifact_prefix: str,
    phase_label: str,
    log: LogCallback | None,
    on_chunk: ChunkCallback | None,
) -> tuple[str, dict[str, Any]]:
    attempt_prompt = base_prompt
    for attempt in range(1, validation_attempts + 1):
        _log(log, "ATTEMPT", f"{phase_label} AI 응답 생성 {attempt}/{validation_attempts}")
        response_text = provider.generate(attempt_prompt, log=log, on_chunk=on_chunk)
        (run_directory / f"{artifact_prefix}.raw.txt").write_text(
            response_text,
            encoding="utf-8",
        )
        _log_provider_diagnostics(provider, log)
        _log(log, "RESPONSE", f"{phase_label} AI 응답 {len(response_text):,}자 수신")
        _log(log, "TRACE", f"{phase_label} 응답 미리보기\n{_preview(response_text)}")
        _log(log, "VALIDATE", f"{phase_label} JSON 계약 검증 {attempt}/{validation_attempts}")
        try:
            return response_text, parse_structured_response(response_text, evidence_text=evidence)
        except ResponseValidationError as exc:
            (run_directory / f"{artifact_prefix}.attempt-{attempt}.invalid.txt").write_text(
                response_text,
                encoding="utf-8",
            )
            if attempt >= validation_attempts:
                raise
            _log(log, "RETRY", f"{phase_label} 응답 계약 오류를 교정해 다시 요청: {exc}")
            attempt_prompt = _correction_prompt(base_prompt, response_text, exc)
    raise ResponseValidationError(f"{phase_label} AI 응답 계약 검증을 완료하지 못했습니다.")


def _quality_review_prompt(
    original_prompt: str,
    draft_response: str,
    quality_report: dict[str, Any],
) -> str:
    template = (
        resolve_project_path("prompts/quality_review.md")
        .read_text(encoding="utf-8-sig")
        .strip()
    )
    review_task = template.replace(
        "{{QUALITY_REPORT}}",
        quality_report_markdown(quality_report),
    ).replace("{{DRAFT_RESPONSE}}", draft_response.strip())
    return f"{original_prompt.rstrip()}\n\n---\n\n{review_task}\n"


def _critical_quality_issue_count(report: dict[str, Any]) -> int:
    critical_codes = {
        "semantic_duplicate",
        "implementation_as_precondition",
        "non_actionable_test_step",
        "keyword_like_test_data",
        "overloaded_expected_result",
        "overexpanded_simple_change",
    }
    return sum(
        1
        for issue in report.get("issues", [])
        if isinstance(issue, dict)
        and (
            issue.get("code") in critical_codes
            or issue.get("severity") == "required"
        )
    )


def _quality_rank(report: dict[str, Any]) -> tuple[int, int, int, int, int]:
    critical = _critical_quality_issue_count(report)
    metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
    explicit_uncovered = int(metrics.get("uncovered_explicit_scenario_count", 0))
    required_uncovered = int(metrics.get("required_uncovered_scenario_category_count", 0))
    uncovered = int(metrics.get("uncovered_scenario_category_count", 0))
    return (
        -critical,
        int(report.get("score", 0)),
        -explicit_uncovered,
        -required_uncovered,
        -uncovered,
    )


def _log_scan_details(bundle: Any, callback: LogCallback | None) -> None:
    counts = Counter(item.change_type for item in bundle.changes)
    breakdown = ", ".join(f"{key} {value}개" for key, value in sorted(counts.items())) or "변경 없음"
    _log(
        callback,
        "SCAN",
        f"파일 {bundle.scanned_files:,}개 확인, 제외 {bundle.excluded_files:,}개, 변경 후보 {len(bundle.changes):,}개: {breakdown}",
    )
    for item in bundle.changes[:12]:
        _log(callback, "TRACE", f"[{item.change_type}] {Path(item.root).name}/{item.path}")
    if len(bundle.changes) > 12:
        _log(callback, "TRACE", f"변경 후보 {len(bundle.changes) - 12:,}개는 콘솔 표시에서 생략")
    for note in bundle.change_notes[:8]:
        _log(callback, "SCAN", f"사용자 변경 요약: {note}")
    if len(bundle.change_notes) > 8:
        _log(callback, "SCAN", f"사용자 변경 요약 {len(bundle.change_notes) - 8:,}개는 콘솔 표시에서 생략")

    context_chars = sum(len(item.excerpt) for item in bundle.contexts)
    _log(
        callback,
        "CONTEXT",
        f"AI 전달 문맥 {len(bundle.contexts):,}개, 발췌문 {context_chars:,}자, 전체 한도 적용 {bundle.truncated}",
    )
    for item in bundle.contexts[:12]:
        _log(
            callback,
            "CONTEXT",
            f"{item.path} | 방식 {item.mode} | 점수 {item.score} | {len(item.excerpt):,}자 | {item.reason}",
        )
    if len(bundle.contexts) > 12:
        _log(callback, "CONTEXT", f"선택 문맥 {len(bundle.contexts) - 12:,}개는 콘솔 표시에서 생략")
    for warning in bundle.warnings[:8]:
        _log(callback, "WARN", warning)


def run_pipeline(
    request: AnalysisRequest,
    settings: dict[str, Any],
    log: LogCallback | None = None,
    on_chunk: ChunkCallback | None = None,
) -> PipelineResult:
    _validate_date_range(request)
    started = datetime.now()
    run_id = started.strftime("%Y%m%d-%H%M%S-%f")
    run_directory = resolve_project_path(settings.get("runDirectory", "runs")) / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    external_log = log
    log_path = run_directory / "pipeline.log"

    def run_log(level: str, message: str) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as handle:
            for line in str(message).splitlines() or [""]:
                handle.write(f"{timestamp} [{level}] {line}\n")
        _log(external_log, level, message)

    log = run_log

    _log(log, "START", f"RUN {run_id} 시작")
    _log(log, "SCAN", f"프로젝트 루트 {len(request.project_roots)}개 스캔")
    if request.date_from and request.date_to:
        _log(
            log,
            "DATE",
            f"변경 범위 {request.date_from.isoformat()}부터 {request.date_to.isoformat()}까지 양 끝 날짜 포함",
        )
    else:
        _log(log, "DATE", "날짜 범위 필터 사용 안 함")
    try:
        bundle = build_scan_bundle(
            request.project_roots,
            request.manual_changes,
            request.date_from,
            request.date_to,
            request.include_git,
            settings.get("scanner", {}),
            log,
            request_text=request.request_text,
        )
    except Exception as exc:
        _log(log, "ERROR", f"프로젝트 스캔 실패: {exc}")
        raise
    _log_scan_details(bundle, log)
    write_scan_artifacts(bundle, run_directory)
    _log(log, "ARTIFACT", "change manifest와 context bundle 저장")

    quality_review_enabled = bool(settings.get("qualityReviewEnabled", True))
    prompt_settings = settings.get("prompt", {})
    if not isinstance(prompt_settings, dict):
        prompt_settings = {}
    review_reserve = (
        max(0, int(prompt_settings.get("reviewReserveChars", 24000)))
        if quality_review_enabled
        else 0
    )
    prompt, evidence = build_prompt_package(
        bundle,
        request.request_text,
        prompt_settings,
        reserve_chars=review_reserve,
    )
    (run_directory / "prompt.md").write_text(prompt, encoding="utf-8")
    (run_directory / "evidence.txt").write_text(evidence, encoding="utf-8")
    _log(
        log,
        "PROMPT",
        f"구조화 프롬프트 {len(prompt):,}자 구성, 품질 검토 여유 {review_reserve:,}자",
    )
    _log(log, "TRACE", f"프롬프트 미리보기\n{_preview(prompt)}")

    response_path = run_directory / "response.raw.txt"
    validation_attempts = max(1, min(int(settings.get("responseValidationAttempts", 3)), 5))
    try:
        provider = create_provider(settings, request.environment)
        _log(
            log,
            "API",
            f"응답 대기 {getattr(provider, 'timeout', '설정값')}초, 전송 재시도 최대 "
            f"{getattr(provider, 'max_attempts', '설정값')}회, 계약 검증 최대 {validation_attempts}회",
        )
        response_text, structured = _generate_validated_response(
            provider,
            prompt,
            evidence,
            validation_attempts,
            run_directory,
            "response",
            "초안",
            log,
            on_chunk,
        )
        (run_directory / "response.draft.txt").write_text(response_text, encoding="utf-8")
        response_path.write_text(response_text, encoding="utf-8")

        quality_sources = [request.request_text, *bundle.change_notes]
        draft_report = build_quality_report(structured, bundle.changes, quality_sources)
        selected_report = draft_report
        selected_phase = "draft"
        review_report: dict[str, Any] | None = None
        review_reports: list[dict[str, Any]] = []
        review_interruption: dict[str, Any] | None = None
        (run_directory / "quality.draft.json").write_text(
            json.dumps(draft_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _log(
            log,
            "QUALITY",
            f"초안 품질 점수 {draft_report['score']}점, 검토 항목 {len(draft_report['issues'])}건, "
            f"핵심 문장 문제 {_critical_quality_issue_count(draft_report)}건",
        )

        if quality_review_enabled:
            configured_prompt_max = max(
                50_000,
                int(prompt_settings.get("maxPromptChars", 420000)),
            )
            review_attempts = max(
                1,
                min(int(settings.get("qualityReviewValidationAttempts", 2)), 3),
            )
            review_passes = max(1, min(int(settings.get("qualityReviewPasses", 2)), 3))
            _log(
                log,
                "REVIEW",
                f"품질 검토 최대 {review_passes}회, 검토별 응답 시도 최대 {review_attempts}회, "
                f"품질 단계 AI 요청 최대 {review_passes * review_attempts}회",
            )
            for pass_index in range(1, review_passes + 1):
                review_prompt = _quality_review_prompt(prompt, response_text, selected_report)
                if pass_index > 1:
                    review_prompt += (
                        "\n[필수 재교정]\n"
                        "직전 품질 검토에서도 필수 문제가 남았습니다. 사용자 의뢰 기반의 검토 필요 "
                        "시나리오와 문장 문제를 실제 절차와 판정 기준에 반영하고, 같은 응답을 반복하지 마세요.\n"
                    )
                if len(review_prompt) > configured_prompt_max:
                    raise ValueError(
                        f"품질 검토 프롬프트 {len(review_prompt):,}자가 설정 한도 "
                        f"{configured_prompt_max:,}자를 초과했습니다. prompt.reviewReserveChars를 늘려 주세요."
                    )
                suffix = "" if pass_index == 1 else f"-{pass_index}"
                (run_directory / f"prompt.quality-review{suffix}.md").write_text(
                    review_prompt,
                    encoding="utf-8",
                )
                _log(
                    log,
                    "REVIEW",
                    f"별도 AI 품질 검토 {pass_index}/{review_passes} 시작, "
                    f"프롬프트 {len(review_prompt):,}자",
                )
                try:
                    reviewed_response, reviewed_structured = _generate_validated_response(
                        provider,
                        review_prompt,
                        evidence,
                        review_attempts,
                        run_directory,
                        f"response.review{suffix}",
                        f"품질 검토 {pass_index}",
                        log,
                        on_chunk,
                    )
                except ProviderError as exc:
                    review_interruption = _provider_interruption(exc)
                    if not isinstance(exc, ProviderRateLimitError):
                        _log(
                            log,
                            "WARN",
                            "AI 품질 검토 중 공급자 오류가 발생했습니다. "
                            "이미 계약 검증을 통과한 현재 최선의 초안으로 "
                            f"문서 생성을 계속합니다: {exc}",
                        )
                        break
                    _log(
                        log,
                        "QUOTA",
                        "AI 품질 검토를 중단했습니다. 초안 응답과 품질 진단은 현재 실행 폴더에 "
                        f"보존했습니다. {exc}",
                    )
                    break
                except ResponseValidationError as exc:
                    _log(
                        log,
                        "WARN",
                        f"품질 검토 응답이 {review_attempts}회의 생성 시도 후에도 계약을 통과하지 "
                        f"못해 현재 최선의 문안을 유지하고 후속 검토를 종료합니다: {exc}",
                    )
                    break

                review_report = build_quality_report(
                    reviewed_structured,
                    bundle.changes,
                    quality_sources,
                )
                review_reports.append(review_report)
                (run_directory / f"quality.review{suffix}.json").write_text(
                    json.dumps(review_report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                _log(
                    log,
                    "QUALITY",
                    f"검토본 {pass_index} 품질 점수 {review_report['score']}점, 검토 항목 "
                    f"{len(review_report['issues'])}건, 필수 문제 "
                    f"{_critical_quality_issue_count(review_report)}건",
                )
                if _quality_rank(review_report) >= _quality_rank(selected_report):
                    response_text = reviewed_response
                    structured = reviewed_structured
                    selected_report = review_report
                    selected_phase = "review" if pass_index == 1 else f"review-{pass_index}"
                    response_path.write_text(response_text, encoding="utf-8")
                    _log(log, "REVIEW", "품질 지표가 같거나 개선된 검토본을 현재 최선의 문안으로 선택")
                else:
                    _log(log, "REVIEW", "검토본의 품질 지표가 낮아 현재 최선의 문안을 유지")

                if _critical_quality_issue_count(selected_report) == 0:
                    break
                if pass_index < review_passes:
                    _log(log, "RETRY", "필수 품질 문제가 남아 한 차례 더 교정 요청")

        quality_summary = {
            "selected": selected_phase,
            "draft": draft_report,
            "review": review_report,
            "reviews": review_reports,
            "selectedReport": selected_report,
            "interruption": review_interruption,
            "gateMode": str(settings.get("qualityGateMode", "best_effort")),
        }
        (run_directory / "quality-review.json").write_text(
            json.dumps(quality_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        critical_issues = _critical_quality_issue_count(selected_report)
        quality_gate_mode = str(settings.get("qualityGateMode", "best_effort")).strip()
        strict_quality_gate = quality_gate_mode == "strict"
        quality_status = "review_required" if critical_issues else "pass"
        if critical_issues:
            if (
                review_interruption
                and strict_quality_gate
                and review_interruption.get("type") != "rate_limit"
            ):
                raise PipelinePausedError(
                    f"초안 생성은 완료되었지만 필수 품질 문제 {critical_issues}건을 "
                    "교정하는 중 AI 공급자 오류로 품질 검토가 중단되었습니다. "
                    f"{review_interruption['message']} 초안과 품질 진단은 "
                    f"{run_directory}에 보존했습니다."
                )
            if review_interruption and strict_quality_gate:
                raise PipelinePausedError(
                    f"초안 생성은 완료되었지만 필수 품질 문제 {critical_issues}건을 교정하기 전 "
                    f"AI 사용량 한도에 도달했습니다. {review_interruption['message']} "
                    f"초안과 품질 진단은 {run_directory}에 보존했습니다."
                )
            if strict_quality_gate:
                raise ResponseValidationError(
                    f"최종 문안에 사용자 의뢰 누락 또는 실행 품질 문제가 {critical_issues}건 남아 "
                    "엄격한 품질 정책에 따라 Excel 다운로드를 활성화하지 않습니다."
                )
            _log(
                log,
                "WARN",
                f"필수 품질 검토 항목 {critical_issues}건이 남았지만 현재 최선의 계약 검증본으로 "
                "Excel 초안을 생성합니다. 다운로드 후 품질 진단을 참고해 검토해 주세요.",
            )
    except PipelinePausedError as exc:
        _log(log, "PAUSED", str(exc))
        raise
    except Exception as exc:
        _log(log, "ERROR", f"AI 응답 생성 또는 검증 실패: {exc}")
        raise
    title = _document_title(structured, request)
    document = {
        "programInfo": _program_info(
            bundle.changes,
            _program_category(structured, request),
        ),
        **structured,
    }
    (run_directory / "document.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    procedure_count = len(structured["testCase"]["procedure"])
    result_count = len(structured["testResult"]["resultChecks"])
    _log(log, "VALIDATE", f"계약 검증 완료, 테스트 절차 {procedure_count}건, 결과 확인 {result_count}건")

    template_path = resolve_project_path(
        settings.get("templatePath", UNIT_TEST_TEMPLATE.relative_path)
    )
    suggested_filename = f"{title}_단위테스트_{started.strftime('%Y%m%d_%H%M%S')}.xlsx"
    document_path = run_directory / "unit-test-preview.xlsx"
    _log(log, "EXCEL", "원본 템플릿의 서식과 3개 시트를 유지해 다운로드용 초안 생성")
    try:
        generate_workbook(template_path, document_path, document)
    except Exception as exc:
        _log(log, "ERROR", f"Excel 초안 생성 실패: {exc}")
        raise
    _log(log, "EXCEL", "Excel ZIP, worksheet, namespace 무결성 검증 완료")
    _log(log, "ARTIFACT", f"실행 근거 저장 위치: {run_directory}")
    completion = "검토 필요 초안" if quality_status == "review_required" else "검증 완료 초안"
    _log(log, "DONE", f"분석 완료, {completion} 다운로드 가능: {suggested_filename}")
    return PipelineResult(
        run_id=run_id,
        run_directory=run_directory,
        document_path=document_path,
        suggested_filename=suggested_filename,
        response_path=response_path,
        scan_bundle=bundle,
        quality_status=quality_status,
        quality_score=int(selected_report.get("score", 0)),
        quality_issue_count=len(selected_report.get("issues", [])),
        quality_critical_count=critical_issues,
    )
