from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from promptcase_studio.config import PROJECT_ROOT
from promptcase_studio.models import ScanBundle
from promptcase_studio.scanner import change_manifest_markdown, redact_sensitive_text


RELEASE_NOTE_MARKER = "[릴리즈 노트 메일 작성]"
RELEASE_NOTE_MAX_PROMPT_CHARS = 100_000


class ReleaseNoteValidationError(ValueError):
    pass


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig")


def _truncate(value: str, maximum: int, label: str) -> str:
    text = value.strip()
    if len(text) <= maximum:
        return text
    marker = f"\n\n... {label} 일부 생략 ..."
    return text[: maximum - len(marker)].rstrip() + marker


def build_release_note_prompt(
    bundle: ScanBundle,
    request_text: str,
    structured: dict[str, Any],
    *,
    maximum: int = RELEASE_NOTE_MAX_PROMPT_CHARS,
) -> str:
    system_prompt = _read("prompts/release_note_system.md").strip()
    task = _read("prompts/release_note.md")
    schema = json.loads(_read("schemas/release_note_response.schema.json"))
    replacements = {
        "{{REQUEST_TEXT}}": _truncate(
            redact_sensitive_text(request_text),
            18_000,
            "개발 의뢰",
        ),
        "{{CHANGE_NOTES}}": _truncate(
            "\n".join(
                f"{index}. {redact_sensitive_text(note)}"
                for index, note in enumerate(bundle.change_notes, 1)
            )
            or "별도 사용자 변경 요약 없음",
            12_000,
            "사용자 변경 요약",
        ),
        "{{CHANGE_MANIFEST}}": _truncate(
            change_manifest_markdown(bundle.changes),
            24_000,
            "변경 목록",
        ),
        "{{FINAL_DOCUMENT}}": _truncate(
            json.dumps(structured, ensure_ascii=False, indent=2),
            24_000,
            "최종 단위테스트 문안",
        ),
        "{{OUTPUT_SCHEMA}}": json.dumps(schema, ensure_ascii=False, indent=2),
    }
    for placeholder, value in replacements.items():
        task = task.replace(placeholder, value)
    prompt = f"{system_prompt}\n\n---\n\n{task.strip()}\n"
    if len(prompt) > maximum:
        raise ValueError(
            f"릴리즈 노트 프롬프트 {len(prompt):,}자가 한도 {maximum:,}자를 초과했습니다."
        )
    return prompt


def parse_release_note_response(raw: str) -> dict[str, str]:
    text = raw.lstrip("\ufeff").strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise ReleaseNoteValidationError("릴리즈 노트 응답은 JSON 객체 하나여야 합니다.")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReleaseNoteValidationError(f"릴리즈 노트 JSON 파싱 실패: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseNoteValidationError("릴리즈 노트 응답 최상위 값은 객체여야 합니다.")
    if set(value) != {"subject", "body"}:
        raise ReleaseNoteValidationError(
            "릴리즈 노트 응답에는 subject와 body 필드만 있어야 합니다."
        )
    subject = value.get("subject")
    body = value.get("body")
    if not isinstance(subject, str) or not isinstance(body, str):
        raise ReleaseNoteValidationError("릴리즈 노트 subject와 body는 문자열이어야 합니다.")
    subject = re.sub(r"\s+", " ", subject).strip()
    body = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not 8 <= len(subject) <= 120 or "\n" in subject:
        raise ReleaseNoteValidationError("릴리즈 노트 메일 제목은 8~120자의 한 줄이어야 합니다.")
    if not 120 <= len(body) <= 5_000:
        raise ReleaseNoteValidationError("릴리즈 노트 메일 본문은 120~5,000자여야 합니다.")
    if "```" in body:
        raise ReleaseNoteValidationError("릴리즈 노트 본문에 Markdown 코드 펜스를 넣지 마세요.")
    if not body.startswith("안녕하세요"):
        raise ReleaseNoteValidationError("릴리즈 노트 본문은 안녕하세요로 시작해야 합니다.")
    if not re.search(r"감사합니다[.!]?$", body):
        raise ReleaseNoteValidationError("릴리즈 노트 본문은 감사합니다로 끝나야 합니다.")
    if not re.search(r"변경|추가|개선|수정|삭제", body):
        raise ReleaseNoteValidationError("릴리즈 노트 본문에 실제 변경 내용을 포함해야 합니다.")
    if not re.search(r"확인|테스트|검증", body):
        raise ReleaseNoteValidationError("릴리즈 노트 본문에 확인 또는 테스트 안내를 포함해야 합니다.")
    if re.search(r"AI가|인공지능|제공된 (?:소스|정보)|분석 결과를 바탕", body):
        raise ReleaseNoteValidationError("릴리즈 노트 본문에서 AI 작성 흔적을 제거해 주세요.")
    return {"subject": subject, "body": body}


def render_release_note(release_note: dict[str, str]) -> str:
    return f"제목: {release_note['subject'].strip()}\n\n{release_note['body'].strip()}"


def fallback_release_note(
    structured: dict[str, Any],
    title: str,
) -> dict[str, str]:
    processing = list(structured.get("testResult", {}).get("processingDetails", []))[:5]
    test_details = list(structured.get("testResult", {}).get("testDetails", []))[:5]
    change_rows = [
        f"- {str(item.get('title', '')).strip()}: {str(item.get('detail', '')).strip()}"
        for item in processing
        if isinstance(item, dict)
        and str(item.get("title", "")).strip()
        and str(item.get("detail", "")).strip()
    ]
    if not change_rows:
        change_rows = ["- 요청된 기능의 변경 사항을 반영했습니다."]
    check_rows = [
        f"- {re.sub(r'확인한다$', '확인해 주세요.', str(item).strip())}"
        for item in test_details
        if str(item).strip()
    ]
    if not check_rows:
        check_rows = ["- 변경된 기능과 기존 기능이 함께 정상적으로 동작하는지 확인해 주세요."]
    safe_title = title.strip() or "프로젝트"
    body = "\n".join(
        (
            "안녕하세요.",
            "",
            f"{safe_title} 관련 변경 사항을 공유드립니다.",
            "",
            "주요 변경 사항",
            *change_rows,
            "",
            "확인 부탁드리는 내용",
            *check_rows,
            "",
            "업무 적용 전후로 위 항목을 확인해 주시면 감사하겠습니다.",
            "추가로 확인이 필요한 내용이 있으면 편하게 말씀해 주세요.",
            "",
            "감사합니다.",
        )
    )
    return {
        "subject": f"[릴리즈 안내] {safe_title} 변경 사항 및 확인 요청",
        "body": body,
    }


__all__ = [
    "RELEASE_NOTE_MARKER",
    "ReleaseNoteValidationError",
    "build_release_note_prompt",
    "fallback_release_note",
    "parse_release_note_response",
    "render_release_note",
]
