from __future__ import annotations

import json
import re
from pathlib import Path

from promptcase_studio.config import PROJECT_ROOT
from promptcase_studio.models import ContextFile, ScanBundle
from promptcase_studio.scanner import change_manifest_markdown, redact_sensitive_text


PROMPT_MAX_CHARS = 420_000
REQUEST_MAX_CHARS = 24_000
MANIFEST_MAX_CHARS = 48_000
CHANGE_NOTES_MAX_CHARS = 16_000
REQUEST_STOP_TERMS = {
    "개발",
    "기능",
    "변경",
    "반영",
    "사항",
    "시스템",
    "요청",
    "작업",
    "적용",
    "프로그램",
}
ARCHITECTURE_SUFFIXES = re.compile(
    r"(?:serviceimpl|controller|service|usecase|mapper|repository|dao|api|endpoint|"
    r"handler|provider|store|hooks?|types?|dto|vo|model|schema|validator|assembler|"
    r"page|modal|route|router|batch|job|step|task|command|query|report|script|include)$",
    re.IGNORECASE,
)
ARTIFACT_QUALIFIERS = re.compile(
    r"\.(?:clas|prog|fugr|func|intf|incl|tabl|view|ddls|dcls|bdef|srvd)$",
    re.IGNORECASE,
)
GENERIC_CHANGE_STEMS = {
    "app",
    "application",
    "config",
    "constant",
    "constants",
    "index",
    "main",
    "readme",
    "settings",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _setting_int(
    settings: dict[str, object] | None,
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int((settings or {}).get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _truncate(text: str, maximum: int, label: str) -> str:
    value = text.strip()
    if len(value) <= maximum:
        return value
    marker = f"\n\n... {label} 일부 생략 ..."
    if maximum <= len(marker) + 20:
        return value[:maximum]
    return value[: maximum - len(marker)].rstrip() + marker


def _grant_fair(
    items: list[ContextFile],
    budgets: dict[int, int],
    total: int,
) -> int:
    remaining = max(0, total)
    active = [item for item in items if budgets.get(id(item), 0) < len(item.excerpt)]
    while remaining > 0 and active:
        share = max(1, remaining // len(active))
        next_active: list[ContextFile] = []
        progressed = 0
        for item in active:
            key = id(item)
            needed = len(item.excerpt) - budgets.get(key, 0)
            grant = min(needed, share, remaining)
            budgets[key] = budgets.get(key, 0) + grant
            remaining -= grant
            progressed += grant
            if budgets[key] < len(item.excerpt):
                next_active.append(item)
            if remaining <= 0:
                break
        if progressed == 0:
            break
        active = next_active
    return remaining


def _fair_budgets(
    items: list[ContextFile],
    total: int,
    relevance: dict[int, int] | None = None,
) -> dict[int, int]:
    budgets = {id(item): 0 for item in items}
    relevant = [item for item in items if relevance and relevance.get(id(item), 0) > 0]
    base_total = total if not relevant else int(total * 0.55)
    _grant_fair(items, budgets, base_total)
    remaining = max(0, total - sum(budgets.values()))
    if relevant and remaining:
        ordered_relevant = sorted(
            relevant,
            key=lambda item: (-relevance.get(id(item), 0), item.path.casefold()),
        )
        remaining = _grant_fair(ordered_relevant, budgets, remaining)
    if remaining:
        _grant_fair(items, budgets, remaining)
    return budgets


def _request_terms(request_text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", request_text):
        candidates = [match]
        if match.endswith("시스템") and len(match) > 5:
            candidates.append(match[: -len("시스템")])
        for value in candidates:
            key = value.casefold()
            if key not in REQUEST_STOP_TERMS and key not in seen:
                seen.add(key)
                values.append(value)
    return values[:24]


def _context_relevance(item: ContextFile, terms: list[str]) -> int:
    if not terms:
        return 0
    path = item.path.casefold()
    evidence = f"{item.reason}\n{item.excerpt}".casefold()
    score = 0
    for term in terms:
        key = term.casefold()
        if key in path:
            score += 12
        if key in evidence:
            score += 5 + min(10, evidence.count(key))
    return score


def _context_header(item: ContextFile, index: int, relevance: int = 0) -> str:
    return (
        f"## 근거 {index}: {item.path}\n\n"
        f"- 선택 방식: {item.mode}\n"
        f"- 선택 이유: {item.reason}\n"
        f"- 연관 점수: {item.score}\n"
        f"- 의뢰 연관도: {relevance}\n"
    )


def _budget_context_bundle(bundle: ScanBundle, maximum: int, request_text: str = "") -> str:
    if maximum <= 0 or not bundle.contexts:
        return "선택된 소스 본문이 없습니다."

    changed_keys = {item.key() for item in bundle.changes}
    changed: list[ContextFile] = []
    related: list[ContextFile] = []
    for item in bundle.contexts:
        key = (item.root.casefold(), item.path.replace("\\", "/").casefold())
        (changed if key in changed_keys else related).append(item)
    focus_terms = _request_terms(request_text)
    relevance = {id(item): _context_relevance(item, focus_terms) for item in bundle.contexts}
    original_order = {id(item): index for index, item in enumerate(bundle.contexts)}
    changed.sort(key=lambda item: (-relevance[id(item)], original_order[id(item)]))
    related.sort(key=lambda item: (-relevance[id(item)], -item.score, original_order[id(item)]))
    ordered = [*changed, *related]

    headers = [
        _context_header(item, index, relevance[id(item)])
        for index, item in enumerate(ordered, 1)
    ]
    header_total = sum(len(header) + 20 for header in headers)
    if header_total >= maximum:
        parts: list[str] = []
        used = 0
        for header in headers:
            compact = header + "\n본문은 프롬프트 예산으로 생략됨\n"
            if used + len(compact) > maximum:
                break
            parts.append(compact)
            used += len(compact)
        omitted = len(ordered) - len(parts)
        if omitted and used + 48 < maximum:
            parts.append(f"추가 근거 {omitted}개는 프롬프트 예산으로 생략됨")
        return "\n".join(parts)[:maximum]

    excerpt_pool = maximum - header_total
    changed_pool = min(
        sum(len(item.excerpt) for item in changed),
        int(excerpt_pool * 0.78) if related else excerpt_pool,
    )
    related_pool = min(sum(len(item.excerpt) for item in related), excerpt_pool - changed_pool)
    unused = excerpt_pool - changed_pool - related_pool
    if unused:
        changed_need = sum(len(item.excerpt) for item in changed) - changed_pool
        shift = min(unused, max(0, changed_need))
        changed_pool += shift
        unused -= shift
        related_pool += min(unused, max(0, sum(len(item.excerpt) for item in related) - related_pool))

    budgets = _fair_budgets(changed, changed_pool, relevance)
    budgets.update(_fair_budgets(related, related_pool, relevance))
    parts = []
    for index, item in enumerate(ordered, 1):
        header = _context_header(item, index, relevance[id(item)])
        budget = budgets.get(id(item), 0)
        excerpt = item.excerpt[:budget].replace("```", "` ` `").rstrip()
        if budget < len(item.excerpt):
            excerpt += "\n... 이 파일의 나머지 근거는 예산에 맞게 생략됨 ..."
        if not excerpt:
            excerpt = "본문 근거 없음"
        parts.append(f"{header}\n```text\n{excerpt}\n```")
    return _truncate("\n\n".join(parts), maximum, "컨텍스트")


def _logical_change_families(bundle: ScanBundle) -> list[str]:
    families: list[str] = []
    seen: set[str] = set()
    for change in bundle.changes:
        stem = Path(change.path).stem.casefold().lstrip(".")
        stem = ARTIFACT_QUALIFIERS.sub("", stem)
        previous = ""
        while stem and stem != previous:
            previous = stem
            stem = ARCHITECTURE_SUFFIXES.sub("", stem).rstrip("_-.")
        if not stem or stem in GENERIC_CHANGE_STEMS:
            continue
        if stem not in seen:
            seen.add(stem)
            families.append(stem)
    return families


def _test_scope_guidance(bundle: ScanBundle) -> tuple[int, str]:
    note_count = len(bundle.change_notes)
    if note_count:
        recommended = min(5, max(1, note_count))
        reason = f"사용자가 구분한 변경 주제 {note_count}개를 우선 기준으로 산정"
        return recommended, reason

    family_count = len(_logical_change_families(bundle))
    if family_count <= 1:
        recommended = 1
    elif family_count <= 3:
        recommended = 2
    elif family_count <= 7:
        recommended = 3
    elif family_count <= 15:
        recommended = 4
    else:
        recommended = 5
    reason = f"계층별 중복을 합친 논리 변경군 {max(1, family_count)}개를 기준으로 산정"
    return recommended, reason


def _scan_summary(bundle: ScanBundle) -> str:
    warning_text = "; ".join(bundle.warnings) if bundle.warnings else "없음"
    recommended_tests, scope_reason = _test_scope_guidance(bundle)
    return "\n".join(
        (
            f"- 변경 항목: {len(bundle.changes)}개",
            f"- 사용자 변경 요약: {len(bundle.change_notes)}개",
            f"- 선택된 변경 및 연관 근거: {len(bundle.contexts)}개",
            f"- 인덱싱한 후보 파일: {bundle.scanned_files}개",
            f"- 제외한 파일: {bundle.excluded_files}개",
            f"- 후보 인덱스 잘림: {'예' if bundle.truncated else '아니오'}",
            f"- 권장 테스트 흐름: {recommended_tests}개",
            f"- 테스트 흐름 산정: {scope_reason}",
            "- 테스트 흐름 상한: 5개이며 같은 동작의 계층별 파일 수는 하나의 흐름으로 통합",
            f"- 주의사항: {warning_text}",
        )
    )


def _prompt_metadata() -> str:
    path = PROJECT_ROOT / "prompts" / "manifest.json"
    default = {
        "bundleVersion": "unknown",
        "contextPolicyVersion": "unknown",
        "responseSchemaVersion": "unknown",
        "qualityPolicyVersion": "unknown",
    }
    try:
        loaded = json.loads(_read(path))
        if isinstance(loaded, dict):
            default.update({key: str(value) for key, value in loaded.items()})
    except (OSError, json.JSONDecodeError):
        pass
    return "\n".join(
        (
            f"- 프롬프트 버전: {default['bundleVersion']}",
            f"- 컨텍스트 정책 버전: {default['contextPolicyVersion']}",
            f"- 응답 스키마 버전: {default['responseSchemaVersion']}",
            f"- 품질 정책 버전: {default['qualityPolicyVersion']}",
        )
    )


def build_prompt_package(
    bundle: ScanBundle,
    request_text: str,
    prompt_settings: dict[str, object] | None = None,
    *,
    reserve_chars: int = 0,
) -> tuple[str, str]:
    configured_maximum = _setting_int(
        prompt_settings,
        "maxPromptChars",
        PROMPT_MAX_CHARS,
        50_000,
        1_200_000,
    )
    maximum = max(50_000, configured_maximum - max(0, int(reserve_chars)))
    request_maximum = _setting_int(
        prompt_settings,
        "maxRequestChars",
        REQUEST_MAX_CHARS,
        2_000,
        120_000,
    )
    manifest_maximum = _setting_int(
        prompt_settings,
        "maxManifestChars",
        MANIFEST_MAX_CHARS,
        4_000,
        240_000,
    )
    notes_maximum = _setting_int(
        prompt_settings,
        "maxChangeNotesChars",
        CHANGE_NOTES_MAX_CHARS,
        2_000,
        80_000,
    )
    system_prompt = _read(PROJECT_ROOT / "prompts" / "system.md").strip()
    task_template = _read(PROJECT_ROOT / "prompts" / "unit_test_generation.md")
    schema = json.loads(_read(PROJECT_ROOT / "schemas" / "test_case_response.schema.json"))
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
    request = _truncate(
        redact_sensitive_text(request_text),
        request_maximum,
        "개발 의뢰",
    ) or "별도 개발 의뢰가 입력되지 않음"
    manifest = _truncate(change_manifest_markdown(bundle.changes), manifest_maximum, "변경 목록")
    change_notes = _truncate(
        "\n".join(
            f"{index}. {redact_sensitive_text(note)}"
            for index, note in enumerate(bundle.change_notes, 1)
        ),
        notes_maximum,
        "사용자 변경 요약",
    ) or "별도 사용자 변경 요약 없음"

    replacements = {
        "{{PROMPT_METADATA}}": _prompt_metadata(),
        "{{SCAN_SUMMARY}}": _scan_summary(bundle),
        "{{REQUEST_TEXT}}": request,
        "{{CHANGE_NOTES}}": change_notes,
        "{{CHANGE_MANIFEST}}": manifest,
        "{{OUTPUT_SCHEMA}}": schema_text,
    }
    fixed_task = task_template
    for placeholder, value in replacements.items():
        fixed_task = fixed_task.replace(placeholder, value)
    fixed_task = fixed_task.replace("{{CONTEXT_BUNDLE}}", "")
    fixed_length = len(system_prompt) + len(fixed_task) + 16
    if fixed_length >= maximum:
        raise ValueError(
            "프롬프트의 고정 지시와 변경 목록이 전체 예산을 초과했습니다. "
            "prompt.maxPromptChars 또는 세부 입력 한도를 늘려 주세요."
        )
    context_budget = max(1000, maximum - fixed_length)
    context = _budget_context_bundle(bundle, context_budget, request)

    task_prompt = task_template
    for placeholder, value in replacements.items():
        task_prompt = task_prompt.replace(placeholder, value)
    task_prompt = task_prompt.replace("{{CONTEXT_BUNDLE}}", context)
    prompt = f"{system_prompt}\n\n---\n\n{task_prompt.strip()}\n"

    if len(prompt) > maximum:
        overflow = len(prompt) - maximum
        context = _budget_context_bundle(
            bundle,
            max(500, context_budget - overflow - 100),
            request,
        )
        task_prompt = task_template
        for placeholder, value in replacements.items():
            task_prompt = task_prompt.replace(placeholder, value)
        task_prompt = task_prompt.replace("{{CONTEXT_BUNDLE}}", context)
        prompt = f"{system_prompt}\n\n---\n\n{task_prompt.strip()}\n"
    if len(prompt) > maximum:
        raise ValueError(
            f"프롬프트 예산을 적용한 뒤에도 {len(prompt):,}자가 남아 "
            f"설정 한도 {maximum:,}자를 초과했습니다."
        )
    evidence = "\n\n".join(
        (
            "[개발 의뢰]\n" + request,
            "[사용자 변경 요약]\n" + change_notes,
            "[변경 파일 목록]\n" + manifest,
            "[선택된 소스 근거]\n" + context,
        )
    )
    return prompt, evidence


def build_prompt(
    bundle: ScanBundle,
    request_text: str,
    prompt_settings: dict[str, object] | None = None,
) -> str:
    return build_prompt_package(bundle, request_text, prompt_settings)[0]
