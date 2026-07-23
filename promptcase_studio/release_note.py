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
RELEASE_NOTE_HEADERS = ("[변경 사항]", "[적용 범위]", "[확인 요청 사항]")


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
    if not 8 <= len(subject) <= 60 or "\n" in subject:
        raise ReleaseNoteValidationError("릴리즈 노트 메일 제목은 8~60자의 한 줄이어야 합니다.")
    if not subject.startswith("[공유] "):
        raise ReleaseNoteValidationError("릴리즈 노트 메일 제목은 [공유]로 시작해야 합니다.")
    if "릴리즈" in subject:
        raise ReleaseNoteValidationError(
            "메일 제목에는 릴리즈라는 표현을 반복하지 말고 핵심 변경 주제만 쓰세요."
        )
    if re.search(r"(?:반영\s*)?(?:및\s*)?확인\s*요청$", subject):
        raise ReleaseNoteValidationError(
            "메일 제목 끝의 반영 및 확인 요청 같은 관용 표현을 빼고 핵심 변경 주제만 쓰세요."
        )
    if not 120 <= len(body) <= 5_000:
        raise ReleaseNoteValidationError("릴리즈 노트 메일 본문은 120~5,000자여야 합니다.")
    if "```" in body:
        raise ReleaseNoteValidationError("릴리즈 노트 본문에 Markdown 코드 펜스를 넣지 마세요.")
    if not body.startswith("안녕하세요"):
        raise ReleaseNoteValidationError("릴리즈 노트 본문은 안녕하세요로 시작해야 합니다.")
    if not re.search(r"감사합니다[.!]?$", body):
        raise ReleaseNoteValidationError("릴리즈 노트 본문은 감사합니다로 끝나야 합니다.")
    if "[주요 변경 사항]" in body:
        raise ReleaseNoteValidationError("[주요 변경 사항] 대신 [변경 사항]을 사용하세요.")
    header_positions = []
    for header in RELEASE_NOTE_HEADERS:
        if body.count(header) != 1:
            raise ReleaseNoteValidationError(f"릴리즈 노트 본문에 {header}을 한 번 포함해야 합니다.")
        header_positions.append(body.index(header))
    if header_positions != sorted(header_positions):
        raise ReleaseNoteValidationError(
            "본문은 변경 사항, 적용 범위, 확인 요청 사항 순서로 작성해야 합니다."
        )

    lines = [line.strip() for line in body.splitlines()]
    nonempty_lines = [line for line in lines if line]
    if any(header not in lines for header in RELEASE_NOTE_HEADERS):
        raise ReleaseNoteValidationError("각 본문 구분 제목은 다른 내용 없이 한 줄로 작성하세요.")
    if any(len(line) > 100 for line in nonempty_lines):
        raise ReleaseNoteValidationError(
            "본문의 한 줄이 100자를 넘습니다. 행동이나 확인 결과별로 줄을 나누세요."
        )
    header_line_indexes = [lines.index(header) for header in RELEASE_NOTE_HEADERS]
    greeting_index = next(
        (index for index, line in enumerate(lines) if line.startswith("안녕하세요")),
        -1,
    )
    intro_lines = [
        line
        for line in lines[greeting_index + 1 : header_line_indexes[0]]
        if line
    ]
    if len(intro_lines) != 1 or len(intro_lines[0]) > 70:
        raise ReleaseNoteValidationError(
            "첫 안내 문단은 70자 이내의 간단한 한 문장으로 작성하세요."
        )
    if "릴리즈했습니다" in intro_lines[0]:
        raise ReleaseNoteValidationError(
            "첫 안내 문단은 릴리즈했습니다 대신 변경 사항을 공유드립니다처럼 간결하게 쓰세요."
        )

    change_lines = [
        line
        for line in lines[header_line_indexes[0] + 1 : header_line_indexes[1]]
        if line
    ]
    scope_lines = [
        line
        for line in lines[header_line_indexes[1] + 1 : header_line_indexes[2]]
        if line
    ]
    closing_indexes = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(r"감사합니다[.!]?", line)
    ]
    if not closing_indexes:
        raise ReleaseNoteValidationError("감사합니다 인사는 별도 줄에 작성하세요.")
    closing_index = max(closing_indexes)
    request_and_contact = [
        line
        for line in lines[header_line_indexes[2] + 1 : closing_index]
        if line
    ]
    if not 1 <= len(change_lines) <= 5 or not all(
        line.startswith("- ") for line in change_lines
    ):
        raise ReleaseNoteValidationError("[변경 사항]은 1~5개의 짧은 목록으로 작성하세요.")
    if not 1 <= len(scope_lines) <= 3 or not all(
        line.startswith("- ") for line in scope_lines
    ):
        raise ReleaseNoteValidationError("[적용 범위]는 1~3개의 짧은 목록으로 작성하세요.")
    if len(request_and_contact) < 3:
        raise ReleaseNoteValidationError(
            "[확인 요청 사항]에는 두 개 이상의 확인 단계와 연락 안내를 포함해야 합니다."
        )
    request_lines = request_and_contact[:-1]
    contact_line = request_and_contact[-1]
    if not 2 <= len(request_lines) <= 8 or not all(
        line.startswith("- ") for line in request_lines
    ):
        raise ReleaseNoteValidationError(
            "[확인 요청 사항]은 한 줄에 한 행동 또는 한 결과를 담아 2~8개로 작성하세요."
        )
    if not re.search(r"메일|메신저", contact_line) or not re.search(
        r"문제|이상|예상", contact_line
    ):
        raise ReleaseNoteValidationError(
            "감사 인사 앞에 문제 발생 시 메일 또는 메신저로 알려 달라는 안내를 넣으세요."
        )
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
    test_case = structured.get("testCase", {})
    procedure = list(test_case.get("procedure", []))[:4]
    test_details = list(structured.get("testResult", {}).get("testDetails", []))[:4]

    def compact(value: Any, maximum: int = 88) -> str:
        text = re.sub(r"\s+", " ", str(value)).strip(" .")
        if len(text) <= maximum:
            return text
        return text[: maximum - 1].rstrip() + "…"

    def request_sentence(value: Any) -> str:
        text = compact(value, 86)
        text = re.sub(r"확인한다$", "확인해 주세요", text)
        text = re.sub(r"한다$", "해 주세요", text)
        if not text.endswith((".", "!", "?")):
            text += "."
        return text

    change_rows = [
        f"- {compact(item.get('title', ''), 30)}: {compact(item.get('detail', ''), 54)}"
        for item in processing
        if isinstance(item, dict)
        and str(item.get("title", "")).strip()
        and str(item.get("detail", "")).strip()
    ]
    if not change_rows:
        change_rows = ["- 요청된 기능의 변경 사항을 반영했습니다."]
    check_rows: list[str] = []
    for action, outcome in zip(procedure, test_details):
        if str(action).strip():
            check_rows.append(f"- {request_sentence(action)}")
        if str(outcome).strip() and len(check_rows) < 8:
            check_rows.append(f"- {request_sentence(outcome)}")
    if not check_rows:
        check_rows = [
            "- 변경된 기능을 실행해 주세요.",
            "- 실행 결과가 예상대로 표시되는지 확인해 주세요.",
        ]
    safe_title = title.strip() or "프로젝트"
    target_names = [
        compact(item, 60)
        for item in test_case.get("targetNames", [])
        if str(item).strip()
    ][:3]
    if not target_names:
        scope = re.sub(r"\s*단위테스트$", "", str(test_case.get("name", "")).strip())
        target_names = [compact(scope or f"{safe_title} 변경 기능", 70)]
    scope_rows = [f"- {item}" for item in target_names]
    topic = ""
    if processing and isinstance(processing[0], dict):
        topic = compact(processing[0].get("title", ""), 30)
    subject_detail = compact(f"{safe_title} {topic or '변경 사항'}", 53)
    body = "\n".join(
        (
            "안녕하세요.",
            "",
            f"{compact(safe_title, 40)} 변경 사항을 공유드립니다.",
            "",
            "[변경 사항]",
            *change_rows,
            "",
            "[적용 범위]",
            *scope_rows,
            "",
            "[확인 요청 사항]",
            *check_rows,
            "",
            "확인 중 문제나 예상과 다른 결과가 있으면 메일 또는 메신저로 알려주세요.",
            "",
            "감사합니다.",
        )
    )
    return {
        "subject": f"[공유] {subject_detail}",
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
