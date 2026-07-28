from __future__ import annotations

from typing import Any, Mapping


SCENARIO_KIND_LABELS: dict[str, str] = {
    "success": "정상 케이스",
    "validation": "입력 검증",
    "boundary": "경계 조건",
    "permission": "권한 거부",
    "error": "오류 처리",
    "regression": "회귀 확인",
}
SCENARIO_KINDS = frozenset(SCENARIO_KIND_LABELS)


def scenario_label(value: Mapping[str, Any]) -> str:
    return SCENARIO_KIND_LABELS.get(str(value.get("kind", "")), "테스트 케이스")


__all__ = [
    "SCENARIO_KIND_LABELS",
    "SCENARIO_KINDS",
    "scenario_label",
]
