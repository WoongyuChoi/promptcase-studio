from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentTemplate:
    template_id: str
    relative_path: str
    download_name: str
    button_label: str
    legacy_paths: tuple[str, ...] = ()


UNIT_TEST_TEMPLATE = DocumentTemplate(
    template_id="unit_test",
    relative_path="templates/unittest_template.xlsx",
    download_name="단위테스트 템플릿.xlsx",
    button_label="템플릿 내려받기",
    legacy_paths=("templates/단위테스트 템플릿.xlsx",),
)
