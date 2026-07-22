from __future__ import annotations

import json
import re
from typing import Any


class ResponseValidationError(ValueError):
    pass


def _extract_json_text(raw: str) -> str:
    text = raw.strip().lstrip("\ufeff")
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ResponseValidationError("AI 응답에서 JSON 객체를 찾지 못했습니다.")
    return text[start : end + 1]


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResponseValidationError(f"{field}는 비어 있지 않은 문자열이어야 합니다.")
    return value.strip()


def _string_list(
    value: Any,
    field: str,
    minimum: int,
    maximum: int,
) -> list[str]:
    if not isinstance(value, list):
        raise ResponseValidationError(f"{field}는 문자열 배열이어야 합니다.")
    items = [_string(item, field) for item in value if isinstance(item, str) and item.strip()]
    if not minimum <= len(items) <= maximum:
        raise ResponseValidationError(f"{field} 항목 수는 {minimum}~{maximum}개여야 합니다.")
    return items


def parse_structured_response(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError as exc:
        raise ResponseValidationError(f"AI JSON 파싱 실패: {exc}") from exc
    if not isinstance(data, dict):
        raise ResponseValidationError("AI 응답 최상위 값은 JSON 객체여야 합니다.")

    test_case = data.get("testCase")
    test_result = data.get("testResult")
    if not isinstance(test_case, dict) or not isinstance(test_result, dict):
        raise ResponseValidationError("testCase와 testResult 객체가 필요합니다.")

    target_ids = test_case.get("targetIds", [])
    target_names = test_case.get("targetNames", [])
    if not isinstance(target_ids, list) or not all(isinstance(item, str) for item in target_ids):
        raise ResponseValidationError("testCase.targetIds는 문자열 배열이어야 합니다.")
    if not isinstance(target_names, list) or not all(isinstance(item, str) for item in target_names):
        raise ResponseValidationError("testCase.targetNames는 문자열 배열이어야 합니다.")

    processing = test_result.get("processingDetails")
    if not isinstance(processing, list) or not processing:
        raise ResponseValidationError("testResult.processingDetails가 한 개 이상 필요합니다.")
    normalized_processing: list[dict[str, str]] = []
    for index, item in enumerate(processing):
        if not isinstance(item, dict):
            raise ResponseValidationError(f"processingDetails[{index}]는 객체여야 합니다.")
        normalized_processing.append(
            {
                "title": _string(item.get("title"), f"processingDetails[{index}].title"),
                "detail": _string(item.get("detail"), f"processingDetails[{index}].detail"),
            }
        )

    notes = test_case.get("notes", "")
    if not isinstance(notes, str):
        raise ResponseValidationError("testCase.notes는 문자열이어야 합니다.")

    return {
        "testCase": {
            "name": _string(test_case.get("name"), "testCase.name"),
            "procedure": _string_list(test_case.get("procedure"), "testCase.procedure", 3, 3),
            "targetIds": [item.strip() for item in target_ids if item.strip()],
            "targetNames": [item.strip() for item in target_names if item.strip()],
            "preconditions": _string_list(test_case.get("preconditions"), "testCase.preconditions", 3, 3),
            "testData": _string(test_case.get("testData"), "testCase.testData"),
            "expectedResult": _string(test_case.get("expectedResult"), "testCase.expectedResult"),
            "notes": notes.strip(),
        },
        "testResult": {
            "processingDetails": normalized_processing,
            "testDetails": _string_list(test_result.get("testDetails"), "testResult.testDetails", 3, 3),
            "resultChecks": _string_list(test_result.get("resultChecks"), "testResult.resultChecks", 1, 5),
        },
    }

