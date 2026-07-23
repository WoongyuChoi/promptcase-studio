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


FORBIDDEN_DECORATION = re.compile(r"[\\:;：；·ㆍ‧∙⋅○●•◦▪▫◆◇▶▷■□※★☆♥♡♠♣\"'“”‘’「」『』＂＇`*#><\[\]{}|~]")
ENDING_PUNCTUATION = (".", ",", "!", "?", ";", ":")
LEADING_LIST_MARK = re.compile(r"^\s*(?:[-*#>]|\d+[.)])\s*")
TECHNICAL_ID = re.compile(r"^[A-Za-z0-9가-힣_./-]+$")
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
GROUNDABLE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Z][A-Z0-9_./-]{3,}|"
    r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9_]*)+|"
    r"[a-z][a-z0-9]+(?:[A-Z][A-Za-z0-9_]*)+|"
    r"[a-z][A-Za-z_]*\d+[A-Za-z0-9_]*|"
    r"(?:test|sample|dummy|mock|demo)[a-z0-9_-]{2,}|"
    r"Spring(?:Boot)?|React|Oracle|Kafka|Redis|MySQL|PostgreSQL|MSSQL|H2|\d{4,})"
    r"(?![A-Za-z0-9_])|"
    r"(?:최고|슈퍼|시스템|운영|마스터|총괄)[가-힣]{0,8}(?:관리자|권한|계정)|"
    r"스프링(?:부트)?|리액트|오라클|카프카|레디스"
)


def _extract_json_text(raw: str) -> str:
    text = raw.lstrip("\ufeff").strip()
    if not text.startswith("{") or not text.endswith("}"):
        if "```" in text:
            raise ResponseValidationError(
                "AI 응답에 Markdown 코드 펜스가 있습니다. JSON 객체 하나만 출력해야 합니다."
            )
        if "{" in text and "}" in text:
            raise ResponseValidationError(
                "AI 응답의 JSON 앞뒤에 설명이 있습니다. JSON 객체 하나만 출력해야 합니다."
            )
        raise ResponseValidationError("AI 응답에서 JSON 객체를 찾지 못했습니다.")
    return text


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
    if not minimum <= len(text) <= maximum:
        raise ResponseValidationError(f"{field} 길이는 {minimum}~{maximum}자여야 합니다.")
    if any(character in text for character in "\r\n\t"):
        raise ResponseValidationError(f"{field}는 줄바꿈 없이 한 줄로 작성해야 합니다.")
    if FORBIDDEN_DECORATION.search(text):
        raise ResponseValidationError(
            f"{field}에 콜론, 세미콜론, 가운데점, 장식 기호, Markdown 기호 또는 따옴표를 사용할 수 없습니다."
        )
    if text.endswith(ENDING_PUNCTUATION):
        raise ResponseValidationError(f"{field} 끝에 문장 부호를 붙이지 마세요.")
    if LEADING_LIST_MARK.match(text):
        raise ResponseValidationError(f"{field} 앞에 번호나 글머리 기호를 붙이지 마세요.")
    if text.endswith((".", ",", "!", "?", ";", "。", "，", "！", "？")):
        raise ResponseValidationError(f"{field} 끝에 불필요한 문장 부호를 붙이지 마세요.")
    if endings and not text.endswith(endings):
        ending_text = " 또는 ".join(endings)
        raise ResponseValidationError(f"{field}는 {ending_text}로 끝나는 완결된 문장이어야 합니다.")
    if text in GENERIC_ONLY:
        raise ResponseValidationError(f"{field}가 너무 일반적입니다. 확인 대상과 조건을 포함해 주세요.")
    if re.search(r"\s{2,}", text):
        raise ResponseValidationError(f"{field}에 불필요한 연속 공백이 있습니다.")
    return text


def _unique(items: list[str], field: str) -> list[str]:
    keys = [re.sub(r"\s+", " ", item).casefold() for item in items]
    if len(keys) != len(set(keys)):
        raise ResponseValidationError(f"{field}에 중복된 항목이 있습니다.")
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
    if not minimum_items <= len(value) <= maximum_items:
        errors.append(f"{field} 항목 수는 {minimum_items}~{maximum_items}개여야 합니다.")
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
    if errors:
        raise ResponseValidationError(errors)
    return items


def _identifier_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 12:
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
    if errors:
        raise ResponseValidationError(errors)
    return items


def _target_name_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 12:
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
    if errors:
        raise ResponseValidationError(errors)
    return items


def _validate_grounded_targets(
    target_ids: list[str],
    target_names: list[str],
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
    for value in target_names:
        if value.casefold() not in evidence:
            errors.append(f"testCase.targetNames 값이 입력 근거에서 확인되지 않습니다: {value}")
    if errors:
        raise ResponseValidationError(errors)


def _validate_grounded_content(values: Iterable[str], evidence_text: str | None) -> None:
    if evidence_text is None:
        return
    evidence = evidence_text.casefold()
    errors: list[str] = []
    for value in values:
        for match in GROUNDABLE_TOKEN.finditer(value):
            token = match.group(0)
            if token.casefold() not in evidence:
                errors.append(f"문안의 기술 식별자 또는 코드값이 입력 근거에서 확인되지 않습니다: {token}")
    if errors:
        raise ResponseValidationError(errors)


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
    if not 1 <= len(value) <= 5:
        errors.append("testResult.processingDetails 항목 수는 1~5개여야 합니다.")
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
    document_title = collector.capture(
        lambda: _human_text(
            data.get("documentTitle", ""),
            "documentTitle",
            minimum=2,
            maximum=40,
            allow_empty=True,
        ),
        raw_document_title,
    )
    if raw_document_title and (
        re.search(r"단위\s*테스트", raw_document_title)
        or raw_document_title.casefold().endswith(".xlsx")
    ):
        collector.add("documentTitle에는 단위테스트 문구나 파일 확장자를 넣지 마세요.")
    if raw_document_title and re.search(r"[()（）]", raw_document_title):
        collector.add("documentTitle에는 괄호를 넣지 마세요.")
    if raw_document_title and re.search(
        r"(?:19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}|(?<!\d)\d{6}(?!\d)",
        raw_document_title,
    ):
        collector.add("documentTitle에는 날짜나 시간을 넣지 마세요.")
    if raw_document_title and evidence_text is not None:
        normalized_title = re.sub(r"\s+", "", raw_document_title).casefold()
        normalized_evidence = re.sub(r"\s+", "", evidence_text).casefold()
        if normalized_title not in normalized_evidence:
            collector.add(
                f"documentTitle 값이 입력 근거에서 확인되지 않습니다: {raw_document_title}"
            )

    name = ""
    if "name" in test_case:
        name = collector.capture(
            lambda: _human_text(test_case.get("name"), "testCase.name", minimum=6, maximum=100),
            _raw_string(test_case.get("name")),
        )
    if test_case_is_object and not name.endswith("단위테스트"):
        collector.add("testCase.name은 단위테스트로 끝나야 합니다.")

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
                endings=("한다",),
            ),
            _raw_string_list(test_case.get("procedure")),
        )
    preconditions: list[str] = []
    if "preconditions" in test_case:
        preconditions = collector.capture(
            lambda: _human_list(
                test_case.get("preconditions"),
                "testCase.preconditions",
                1,
                5,
                minimum_chars=8,
                maximum_chars=160,
                endings=("한다",),
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
        lambda: _validate_grounded_targets(target_ids, target_names, evidence_text),
        None,
    )

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
                endings=("확인한다",),
            ),
            _raw_string_list(test_result.get("testDetails")),
        )
    if {item.casefold() for item in procedure} & {item.casefold() for item in test_details}:
        collector.add("procedure와 testDetails는 절차와 확인 결과를 구분해 작성해야 합니다.")
    if procedure and test_details and len(procedure) != len(test_details):
        collector.add(
            "testResult.testDetails는 testCase.procedure와 같은 항목 수로 대응해 작성해야 합니다."
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
                endings=("한다",),
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
                endings=("한다", "된다"),
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
    collector.capture(
        lambda: _validate_grounded_content(
            [
                name,
                *procedure,
                *preconditions,
                test_data,
                expected_result,
                notes,
                *(item["title"] for item in normalized_processing),
                *(item["detail"] for item in normalized_processing),
                *test_details,
                *result_checks,
            ],
            evidence_text,
        ),
        None,
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
