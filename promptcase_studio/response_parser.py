from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Iterable, TypeVar


T = TypeVar("T")


class ResponseValidationError(ValueError):
    """One or more independently correctable response-contract failures."""

    def __init__(self, errors: str | Iterable[str]) -> None:
        values = [errors] if isinstance(errors, str) else list(errors)
        unique_errors = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if not unique_errors:
            unique_errors = ("알 수 없는 응답 계약 오류입니다.",)
        self.errors = unique_errors
        if len(unique_errors) == 1:
            message = unique_errors[0]
        else:
            details = "\n".join(f"{index}. {value}" for index, value in enumerate(unique_errors, 1))
            message = f"응답 계약 오류 {len(unique_errors)}건\n{details}"
        super().__init__(message)


class _ValidationCollector:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, error: str | ResponseValidationError) -> None:
        values = error.errors if isinstance(error, ResponseValidationError) else (str(error),)
        for value in values:
            if value and value not in self.errors:
                self.errors.append(value)

    def capture(self, validator: Callable[[], T], fallback: T) -> T:
        try:
            return validator()
        except ResponseValidationError as exc:
            self.add(exc)
            return fallback

    def raise_if_any(self) -> None:
        if self.errors:
            raise ResponseValidationError(self.errors)


LEADING_LIST_MARK = re.compile(
    r"^\s*(?:(?:[-*#>○●•◦▪▫◆◇▶▷■□※]+)|\d+[.)])\s*"
)
TRAILING_PUNCTUATION = ".。,，!！?？;；:："
TECHNICAL_ID = re.compile(r"^[A-Za-z0-9가-힣_./\\:#=~\[\]<>@$-]+$")
GENERIC_ONLY = {
    "결과를 확인한다",
    "기능을 확인한다",
    "기능이 정상 동작한다",
    "변경 사항을 확인한다",
    "변경사항을 확인한다",
    "정상 동작 여부를 확인한다",
    "정상 동작한다",
    "정상 처리된다",
}
def _top_level_json_objects(text: str) -> list[str]:
    """Return independently parseable top-level JSON objects embedded in text."""

    candidates: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : index + 1]
                try:
                    value = json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(value, dict):
                        candidates.append(candidate)
                start = -1
    return candidates


def _json_object_brace_balance(text: str) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                return None
    return None if in_string or escaped else depth


def _extract_json_text(raw: str) -> str:
    text = raw.lstrip("\ufeff").strip()
    candidates = _top_level_json_objects(text)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ResponseValidationError(
            "AI 응답에 JSON 객체가 여러 개 있습니다. JSON 객체 하나만 출력해야 합니다."
        )
    # Preserve a malformed object-shaped response so json.loads can report the
    # precise syntax error in the correction request.
    if text.startswith("{"):
        if _json_object_brace_balance(text) == 1:
            repaired = f"{text}}}"
            try:
                value = json.loads(repaired)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(value, dict):
                    return repaired
        return text
    raise ResponseValidationError("AI 응답에서 JSON 객체를 찾지 못했습니다.")


def _ensure_keys(
    value: dict[str, Any],
    field: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    unexpected = sorted(set(value) - allowed)
    errors: list[str] = []
    if missing:
        errors.append(f"{field} 필수 필드가 없습니다: {', '.join(missing)}")
    if unexpected:
        errors.append(f"{field}에 허용되지 않은 필드가 있습니다: {', '.join(unexpected)}")
    if errors:
        raise ResponseValidationError(errors)


def _string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ResponseValidationError(f"{field}는 문자열이어야 합니다.")
    text = value.strip()
    if not text and not allow_empty:
        raise ResponseValidationError(f"{field}는 비어 있지 않은 문자열이어야 합니다.")
    return text


def _human_text(
    value: Any,
    field: str,
    *,
    minimum: int,
    maximum: int,
    endings: tuple[str, ...] = (),
    allow_empty: bool = False,
) -> str:
    text = _string(value, field, allow_empty=allow_empty)
    if not text and allow_empty:
        return ""
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = LEADING_LIST_MARK.sub("", text, count=1).strip()
    text = text.rstrip(TRAILING_PUNCTUATION).rstrip()
    if not minimum <= len(text) <= maximum:
        raise ResponseValidationError(f"{field} 길이는 {minimum}~{maximum}자여야 합니다.")
    if endings and not text.endswith(endings):
        ending_text = " 또는 ".join(endings)
        raise ResponseValidationError(f"{field}는 {ending_text}로 끝나는 완결된 문장이어야 합니다.")
    if text in GENERIC_ONLY:
        raise ResponseValidationError(f"{field}가 너무 일반적입니다. 확인 대상과 조건을 포함해 주세요.")
    return text


def _unique(items: list[str], field: str) -> list[str]:
    del field  # Kept for caller compatibility and future normalization diagnostics.
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = re.sub(r"\s+", " ", item).casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    items[:] = normalized
    return items


def _human_list(
    value: Any,
    field: str,
    minimum_items: int,
    maximum_items: int,
    *,
    minimum_chars: int,
    maximum_chars: int,
    endings: tuple[str, ...] = (),
) -> list[str]:
    if not isinstance(value, list):
        raise ResponseValidationError(f"{field}는 문자열 배열이어야 합니다.")
    errors: list[str] = []
    items: list[str] = []
    for index, item in enumerate(value):
        try:
            items.append(
                _human_text(
                    item,
                    f"{field}[{index}]",
                    minimum=minimum_chars,
                    maximum=maximum_chars,
                    endings=endings,
                )
            )
        except ResponseValidationError as exc:
            errors.extend(exc.errors)
    try:
        _unique(items, field)
    except ResponseValidationError as exc:
        errors.extend(exc.errors)
    if not minimum_items <= len(items) <= maximum_items:
        errors.append(f"{field} 항목 수는 {minimum_items}~{maximum_items}개여야 합니다.")
    if errors:
        raise ResponseValidationError(errors)
    return items


def _identifier_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ResponseValidationError(f"{field}는 최대 12개의 문자열 배열이어야 합니다.")
    items: list[str] = []
    errors: list[str] = []
    for index, item in enumerate(value):
        try:
            text = _string(item, f"{field}[{index}]")
        except ResponseValidationError as exc:
            errors.extend(exc.errors)
            continue
        if not 2 <= len(text) <= 80 or not TECHNICAL_ID.fullmatch(text):
            errors.append(f"{field}[{index}]는 근거에서 확인된 식별자 형식이어야 합니다.")
            continue
        items.append(text)
    try:
        _unique(items, field)
    except ResponseValidationError as exc:
        errors.extend(exc.errors)
    if len(items) > 12:
        errors.append(f"{field}는 최대 12개의 문자열 배열이어야 합니다.")
    if errors:
        raise ResponseValidationError(errors)
    return items


def _target_name_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ResponseValidationError(f"{field}는 최대 12개의 문자열 배열이어야 합니다.")
    items: list[str] = []
    errors: list[str] = []
    for index, item in enumerate(value):
        try:
            items.append(_human_text(item, f"{field}[{index}]", minimum=2, maximum=100))
        except ResponseValidationError as exc:
            errors.extend(exc.errors)
    try:
        _unique(items, field)
    except ResponseValidationError as exc:
        errors.extend(exc.errors)
    if len(items) > 12:
        errors.append(f"{field}는 최대 12개의 문자열 배열이어야 합니다.")
    if errors:
        raise ResponseValidationError(errors)
    return items


def _validate_grounded_targets(
    target_ids: list[str],
    evidence_text: str | None,
) -> None:
    if evidence_text is None:
        return
    evidence = evidence_text.casefold()
    errors: list[str] = []
    for value in target_ids:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(value.casefold())}(?![A-Za-z0-9_])"
        )
        if not pattern.search(evidence):
            errors.append(f"testCase.targetIds 값이 입력 근거에서 확인되지 않습니다: {value}")
    if errors:
        raise ResponseValidationError(errors)


def _grounded_target_names(
    target_names: list[str],
    evidence_text: str | None,
) -> list[str]:
    if evidence_text is None:
        return target_names
    normalized_evidence = re.sub(r"\s+", " ", evidence_text).casefold()
    return [
        value
        for value in target_names
        if re.sub(r"\s+", " ", value).casefold() in normalized_evidence
    ]


def _raw_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _raw_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _processing_details(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ResponseValidationError("testResult.processingDetails는 객체 배열이어야 합니다.")
    errors: list[str] = []
    normalized: list[dict[str, str]] = []
    titles: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"processingDetails[{index}]는 객체여야 합니다.")
            continue
        try:
            _ensure_keys(item, f"processingDetails[{index}]", {"title", "detail"})
        except ResponseValidationError as exc:
            errors.extend(exc.errors)
        title = ""
        detail = ""
        if "title" in item:
            try:
                title = _human_text(
                    item.get("title"),
                    f"processingDetails[{index}].title",
                    minimum=3,
                    maximum=80,
                )
            except ResponseValidationError as exc:
                errors.extend(exc.errors)
        if "detail" in item:
            try:
                detail = _human_text(
                    item.get("detail"),
                    f"processingDetails[{index}].detail",
                    minimum=6,
                    maximum=160,
                )
            except ResponseValidationError as exc:
                errors.extend(exc.errors)
        if title:
            titles.append(title)
        if title and detail:
            normalized.append({"title": title, "detail": detail})
    try:
        _unique(titles, "testResult.processingDetails 제목")
    except ResponseValidationError as exc:
        errors.extend(exc.errors)
    deduplicated: list[dict[str, str]] = []
    seen_rows: set[tuple[str, str]] = set()
    for item in normalized:
        key = (
            re.sub(r"\s+", " ", item["title"]).casefold(),
            re.sub(r"\s+", " ", item["detail"]).casefold(),
        )
        if key in seen_rows:
            continue
        seen_rows.add(key)
        deduplicated.append(item)
    normalized = deduplicated
    if not 1 <= len(normalized) <= 5:
        errors.append("testResult.processingDetails 항목 수는 1~5개여야 합니다.")
    if errors:
        raise ResponseValidationError(errors)
    return normalized


def _raw_processing_details(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(
                {
                    "title": _raw_string(item.get("title")),
                    "detail": _raw_string(item.get("detail")),
                }
            )
    return normalized


def parse_structured_response(raw: str, evidence_text: str | None = None) -> dict[str, Any]:
    try:
        data = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError as exc:
        raise ResponseValidationError(f"AI JSON 파싱 실패: {exc}") from exc
    if not isinstance(data, dict):
        raise ResponseValidationError("AI 응답 최상위 값은 JSON 객체여야 합니다.")
    collector = _ValidationCollector()
    collector.capture(
        lambda: _ensure_keys(data, "응답", {"testCase", "testResult"}, {"documentTitle"}),
        None,
    )

    raw_test_case = data.get("testCase")
    raw_test_result = data.get("testResult")
    test_case_is_object = isinstance(raw_test_case, dict)
    test_result_is_object = isinstance(raw_test_result, dict)
    if not test_case_is_object:
        collector.add("testCase는 JSON 객체여야 합니다.")
    if not test_result_is_object:
        collector.add("testResult는 JSON 객체여야 합니다.")
    # Keep traversing a well-formed sibling object so one correction request
    # can report its independent failures too. Invalid objects become empty
    # sentinels and are never inspected internally.
    test_case: dict[str, Any] = raw_test_case if test_case_is_object else {}
    test_result: dict[str, Any] = raw_test_result if test_result_is_object else {}

    if test_case_is_object:
        collector.capture(
            lambda: _ensure_keys(
                test_case,
                "testCase",
                {
                    "name",
                    "procedure",
                    "targetIds",
                    "targetNames",
                    "preconditions",
                    "testData",
                    "expectedResult",
                    "notes",
                },
            ),
            None,
        )
    if test_result_is_object:
        collector.capture(
            lambda: _ensure_keys(
                test_result,
                "testResult",
                {"processingDetails", "testDetails", "resultChecks"},
            ),
            None,
        )

    raw_document_title = _raw_string(data.get("documentTitle", ""))
    invalid_document_title = bool(
        raw_document_title
        and (
            not 2 <= len(raw_document_title) <= 40
            or re.search(r"단위\s*테스트", raw_document_title)
            or raw_document_title.casefold().endswith(".xlsx")
            or re.search(r"[()（）]", raw_document_title)
            or re.search(
                r"(?:19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}|(?<!\d)\d{6}(?!\d)",
                raw_document_title,
            )
        )
    )
    document_title = "" if invalid_document_title else raw_document_title
    if document_title and evidence_text is not None:
        normalized_title = re.sub(r"\s+", "", document_title).casefold()
        normalized_evidence = re.sub(r"\s+", "", evidence_text).casefold()
        if normalized_title not in normalized_evidence:
            document_title = ""

    name = ""
    if "name" in test_case:
        name_candidate = _raw_string(test_case.get("name"))
        suffix_match = re.search(r"\s*단위\s*테스트\s*$", name_candidate)
        if suffix_match:
            name_candidate = (
                f"{name_candidate[:suffix_match.start()].rstrip()} 단위테스트".strip()
            )
        elif name_candidate:
            name_candidate = f"{name_candidate} 단위테스트"
        name = collector.capture(
            lambda: _human_text(name_candidate, "testCase.name", minimum=6, maximum=100),
            _raw_string(test_case.get("name")),
        )

    procedure: list[str] = []
    if "procedure" in test_case:
        procedure = collector.capture(
            lambda: _human_list(
                test_case.get("procedure"),
                "testCase.procedure",
                1,
                5,
                minimum_chars=8,
                maximum_chars=160,
                endings=("다",),
            ),
            _raw_string_list(test_case.get("procedure")),
        )
    preconditions: list[str] = []
    if "preconditions" in test_case:
        preconditions = collector.capture(
            lambda: _human_list(
                test_case.get("preconditions"),
                "testCase.preconditions",
                0,
                5,
                minimum_chars=8,
                maximum_chars=160,
                endings=("다",),
            ),
            _raw_string_list(test_case.get("preconditions")),
        )
    target_ids: list[str] = []
    if "targetIds" in test_case:
        target_ids = collector.capture(
            lambda: _identifier_list(test_case.get("targetIds"), "testCase.targetIds"),
            _raw_string_list(test_case.get("targetIds")),
        )
    target_names: list[str] = []
    if "targetNames" in test_case:
        target_names = collector.capture(
            lambda: _target_name_list(test_case.get("targetNames"), "testCase.targetNames"),
            _raw_string_list(test_case.get("targetNames")),
        )
    collector.capture(
        lambda: _validate_grounded_targets(target_ids, evidence_text),
        None,
    )
    target_names = _grounded_target_names(target_names, evidence_text)

    normalized_processing: list[dict[str, str]] = []
    if "processingDetails" in test_result:
        normalized_processing = collector.capture(
            lambda: _processing_details(test_result.get("processingDetails")),
            _raw_processing_details(test_result.get("processingDetails")),
        )

    test_details: list[str] = []
    if "testDetails" in test_result:
        test_details = collector.capture(
            lambda: _human_list(
                test_result.get("testDetails"),
                "testResult.testDetails",
                1,
                5,
                minimum_chars=8,
                maximum_chars=160,
                endings=("다",),
            ),
            _raw_string_list(test_result.get("testDetails")),
        )
    notes = ""
    if "notes" in test_case:
        notes = collector.capture(
            lambda: _human_text(
                test_case.get("notes"),
                "testCase.notes",
                minimum=2,
                maximum=300,
                allow_empty=True,
            ),
            _raw_string(test_case.get("notes")),
        )
    test_data = ""
    if "testData" in test_case:
        test_data = collector.capture(
            lambda: _human_text(
                test_case.get("testData"),
                "testCase.testData",
                minimum=10,
                maximum=180,
                endings=("다",),
                allow_empty=True,
            ),
            _raw_string(test_case.get("testData")),
        )
    expected_result = ""
    if "expectedResult" in test_case:
        expected_result = collector.capture(
            lambda: _human_text(
                test_case.get("expectedResult"),
                "testCase.expectedResult",
                minimum=10,
                maximum=180,
                endings=("다",),
            ),
            _raw_string(test_case.get("expectedResult")),
        )
    result_checks: list[str] = []
    if "resultChecks" in test_result:
        result_checks = collector.capture(
            lambda: _human_list(
                test_result.get("resultChecks"),
                "testResult.resultChecks",
                1,
                5,
                minimum_chars=5,
                maximum_chars=120,
            ),
            _raw_string_list(test_result.get("resultChecks")),
        )
    collector.raise_if_any()

    return {
        "documentTitle": document_title,
        "testCase": {
            "name": name,
            "procedure": procedure,
            "targetIds": target_ids,
            "targetNames": target_names,
            "preconditions": preconditions,
            "testData": test_data,
            "expectedResult": expected_result,
            "notes": notes,
        },
        "testResult": {
            "processingDetails": normalized_processing,
            "testDetails": test_details,
            "resultChecks": result_checks,
        },
    }
