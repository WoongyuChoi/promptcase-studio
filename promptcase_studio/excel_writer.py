from __future__ import annotations

import copy
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)

PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def _q(tag: str) -> str:
    return f"{{{MAIN_NS}}}{tag}"


def _sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relation_map = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
    result: dict[str, str] = {}
    sheets = workbook.find(_q("sheets"))
    if sheets is None:
        raise ValueError("템플릿 workbook.xml에 sheets 요소가 없습니다.")
    for sheet in sheets:
        relation_id = sheet.attrib[f"{{{REL_NS}}}id"]
        target = relation_map[relation_id].replace("\\", "/")
        if target.startswith("/xl/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = f"xl/{target.lstrip('/')}"
        result[sheet.attrib["name"]] = target
    return result


def _cell_reference(cell: ET.Element) -> str:
    return cell.attrib.get("r", "")


def _find_cell(sheet: ET.Element, reference: str) -> ET.Element:
    for cell in sheet.iter(_q("c")):
        if _cell_reference(cell) == reference:
            return cell
    raise ValueError(f"템플릿 셀을 찾지 못했습니다: {reference}")


def _set_inline_text(cell: ET.Element, value: str) -> None:
    for child in list(cell):
        cell.remove(child)
    cell.attrib["t"] = "inlineStr"
    inline = ET.SubElement(cell, _q("is"))
    text = ET.SubElement(inline, _q("t"))
    text.attrib[f"{{{XML_NS}}}space"] = "preserve"
    text.text = value


def _shared_string_values(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(_q("t")))
        for item in root
    ]


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    if cell.attrib.get("t") == "s":
        value = cell.find(_q("v"))
        if value is None or value.text is None:
            return ""
        index = int(value.text)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(_q("t")))
    value = cell.find(_q("v"))
    return value.text if value is not None and value.text is not None else ""


def _replace_placeholders(
    element: ET.Element,
    shared_strings: list[str],
    values: dict[str, str],
    style_map: dict[int, int],
) -> set[str]:
    used: set[str] = set()
    for cell in element.iter(_q("c")):
        original = _cell_text(cell, shared_strings)
        if "{{" not in original:
            continue

        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip().casefold()
            if key not in values:
                return match.group(0)
            used.add(key)
            return values[key]

        replaced = PLACEHOLDER_PATTERN.sub(replace, original)
        if replaced != original:
            _set_inline_text(cell, replaced)
            if "\n" in replaced or len(replaced) > 42:
                _use_wrapped_style(cell, style_map)
    return used


def _aliases_used(used: set[str], aliases: tuple[str, ...]) -> bool:
    return bool(used.intersection(aliases))


def _add_wrapped_styles(styles: ET.Element, source_ids: set[int]) -> dict[int, int]:
    cell_xfs = styles.find(_q("cellXfs"))
    if cell_xfs is None:
        raise ValueError("템플릿 styles.xml에 cellXfs가 없습니다.")
    mapping: dict[int, int] = {}
    original = list(cell_xfs)
    for source_id in sorted(source_ids):
        if source_id < 0 or source_id >= len(original):
            continue
        cloned = copy.deepcopy(original[source_id])
        cloned.attrib["applyAlignment"] = "1"
        alignment = cloned.find(_q("alignment"))
        if alignment is None:
            alignment = ET.SubElement(cloned, _q("alignment"))
        alignment.attrib["wrapText"] = "1"
        alignment.attrib.setdefault("vertical", "center")
        cell_xfs.append(cloned)
        mapping[source_id] = len(cell_xfs) - 1
    cell_xfs.attrib["count"] = str(len(cell_xfs))
    return mapping


def _use_wrapped_style(cell: ET.Element, style_map: dict[int, int]) -> None:
    current = int(cell.attrib.get("s", "0"))
    if current in style_map:
        cell.attrib["s"] = str(style_map[current])


def _set_text(sheet: ET.Element, reference: str, value: str, style_map: dict[int, int]) -> None:
    cell = _find_cell(sheet, reference)
    _set_inline_text(cell, value)
    if "\n" in value or len(value) > 42:
        _use_wrapped_style(cell, style_map)


def _set_row_height(sheet: ET.Element, row_number: int, value: str, minimum: float, maximum: float) -> None:
    lines = max(1, value.count("\n") + 1)
    estimated = max(minimum, min(maximum, 16.5 * lines + 14))
    for row in sheet.iter(_q("row")):
        if int(row.attrib.get("r", "0")) == row_number:
            row.attrib["ht"] = f"{estimated:.2f}"
            row.attrib["customHeight"] = "1"
            return


def _clone_program_rows(
    sheet: ET.Element,
    program_rows: list[dict[str, str]],
    shared_strings: list[str],
    style_map: dict[int, int],
) -> None:
    sheet_data = sheet.find(_q("sheetData"))
    if sheet_data is None:
        raise ValueError("프로그램 정보 시트에 sheetData가 없습니다.")
    rows = list(sheet_data.findall(_q("row")))
    template = next((row for row in rows if row.attrib.get("r") == "4"), None)
    if template is None:
        raise ValueError("프로그램 정보의 템플릿 행 4를 찾지 못했습니다.")
    for row in rows:
        if int(row.attrib.get("r", "0")) >= 4:
            sheet_data.remove(row)

    for offset, item in enumerate(program_rows):
        row_number = 4 + offset
        row = copy.deepcopy(template)
        row.attrib["r"] = str(row_number)
        row.attrib["ht"] = "30"
        row.attrib["customHeight"] = "1"
        for cell in row.findall(_q("c")):
            column = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
            if column:
                cell.attrib["r"] = f"{column.group(0)}{row_number}"
        field_values = {
            "program": item.get("program", ""),
            "project": item.get("project", ""),
            "work_content": item.get("workContent", "요건 변경에 따른 개발 프로그램 수정"),
            "change_type": item.get("changeType", "변경"),
        }
        aliases = {
            "program": ("program", "program_name", "file_name", "filename"),
            "project": ("project", "project_name"),
            "work_content": ("work_content", "workcontent"),
            "change_type": ("change_type", "changetype"),
        }
        placeholder_values = {
            alias: field_values[field]
            for field, names in aliases.items()
            for alias in names
        }
        used = _replace_placeholders(row, shared_strings, placeholder_values, style_map)
        fallback_columns = {
            "program": "D",
            "project": "E",
            "change_type": "G",
        }
        for cell in row.findall(_q("c")):
            column = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
            if not column:
                continue
            for field, fallback_column in fallback_columns.items():
                if column.group(0) == fallback_column and not _aliases_used(used, aliases[field]):
                    _set_inline_text(cell, field_values[field])
                    if field in {"program", "project"}:
                        _use_wrapped_style(cell, style_map)
                    break
            else:
                if "\n" in _cell_text(cell, shared_strings):
                    _use_wrapped_style(cell, style_map)
        sheet_data.append(row)

    dimension = sheet.find(_q("dimension"))
    if dimension is not None:
        dimension.attrib["ref"] = f"B1:G{3 + len(program_rows)}"


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))


def _write_test_case(
    sheet: ET.Element,
    data: dict[str, Any],
    shared_strings: list[str],
    style_map: dict[int, int],
) -> None:
    field_values = {
        "name": data["name"],
        "type": "단위테스트",
        "procedure": _numbered(data["procedure"]),
        "target_ids": ", ".join(data["targetIds"]),
        "target_names": ", ".join(data["targetNames"]),
        "preconditions": _numbered(data["preconditions"]),
        "test_data": data["testData"],
        "expected_result": data["expectedResult"],
        "notes": data.get("notes", ""),
    }
    aliases = {
        "name": ("name", "testcase_name", "test_case_name"),
        "type": ("type", "testcase_type", "test_case_type"),
        "procedure": ("procedure", "test_procedure"),
        "target_ids": ("target_ids", "target_id"),
        "target_names": ("target_names", "target_name"),
        "preconditions": ("preconditions", "test_preconditions"),
        "test_data": ("test_data", "testdata"),
        "expected_result": ("expected_result", "expectedresult"),
        "notes": ("notes", "note"),
    }
    placeholder_values = {
        alias: field_values[field]
        for field, names in aliases.items()
        for alias in names
    }
    used = _replace_placeholders(sheet, shared_strings, placeholder_values, style_map)
    fallback_cells = {
        "name": "C3",
        "type": "C4",
        "procedure": "C5",
        "target_ids": "C6",
        "target_names": "C7",
        "preconditions": "C8",
        "test_data": "C9",
        "expected_result": "C10",
        "notes": "C11",
    }
    for field, reference in fallback_cells.items():
        if not _aliases_used(used, aliases[field]):
            _set_text(sheet, reference, field_values[field], style_map)
    _set_row_height(sheet, 5, field_values["procedure"], 79.95, 130)
    _set_row_height(sheet, 8, field_values["preconditions"], 79.95, 130)
    _set_row_height(sheet, 10, field_values["expected_result"], 30, 90)
    _set_row_height(sheet, 11, field_values["notes"], 19.95, 75)


def _write_test_result(
    sheet: ET.Element,
    data: dict[str, Any],
    shared_strings: list[str],
    style_map: dict[int, int],
) -> None:
    processing = "\n\n".join(
        f"○ {item['title']}\n{item['detail']}" for item in data["processingDetails"]
    )
    test_details = _numbered(data["testDetails"])
    result_checks = "\n".join(f"- {item}" for item in data["resultChecks"])
    field_values = {
        "processing_details": processing,
        "test_details": test_details,
        "result_checks": result_checks,
    }
    aliases = {
        "processing_details": ("processing_details", "processing"),
        "test_details": ("test_details", "test_detail"),
        "result_checks": ("result_checks", "result_check"),
    }
    placeholder_values = {
        alias: field_values[field]
        for field, names in aliases.items()
        for alias in names
    }
    used = _replace_placeholders(sheet, shared_strings, placeholder_values, style_map)
    fallback_cells = {
        "processing_details": "C3",
        "test_details": "C4",
        "result_checks": "C5",
    }
    for field, reference in fallback_cells.items():
        if not _aliases_used(used, aliases[field]):
            _set_text(sheet, reference, field_values[field], style_map)
    _set_row_height(sheet, 3, processing, 100.05, 240)
    _set_row_height(sheet, 4, test_details, 100.05, 180)
    _set_row_height(sheet, 5, result_checks, 120, 300)


def generate_workbook(template_path: Path, output_path: Path, document: dict[str, Any]) -> Path:
    if not template_path.exists():
        raise FileNotFoundError(f"Excel 템플릿을 찾을 수 없습니다: {template_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(template_path, "r") as source:
        sheet_paths = _sheet_paths(source)
        required = {"프로그램 정보", "테스트케이스", "테스트 결과"}
        if not required.issubset(sheet_paths):
            raise ValueError(f"필수 시트가 없습니다: {sorted(required - set(sheet_paths))}")

        styles = ET.fromstring(source.read("xl/styles.xml"))
        shared_strings = _shared_string_values(source)
        sheets = {
            name: ET.fromstring(source.read(sheet_paths[name]))
            for name in required
        }
        source_style_ids = {
            int(cell.attrib.get("s", "0"))
            for sheet in sheets.values()
            for cell in sheet.iter(_q("c"))
        }
        style_map = _add_wrapped_styles(styles, source_style_ids)

        program_rows = document.get("programInfo") or [
            {"program": "", "project": "", "changeType": "변경"}
        ]
        _clone_program_rows(sheets["프로그램 정보"], program_rows, shared_strings, style_map)
        _write_test_case(sheets["테스트케이스"], document["testCase"], shared_strings, style_map)
        _write_test_result(sheets["테스트 결과"], document["testResult"], shared_strings, style_map)

        unresolved = {
            match.group(0)
            for sheet in sheets.values()
            for cell in sheet.iter(_q("c"))
            for match in PLACEHOLDER_PATTERN.finditer(_cell_text(cell, shared_strings))
        }
        if unresolved:
            raise ValueError(f"지원하지 않거나 치환되지 않은 Excel placeholder: {sorted(unresolved)}")

        replacements = {
            "xl/styles.xml": ET.tostring(styles, encoding="utf-8", xml_declaration=True),
            **{
                sheet_paths[name]: ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
                for name, sheet in sheets.items()
            },
        }
        temp_path = output_path.with_suffix(".tmp.xlsx")
        with zipfile.ZipFile(temp_path, "w") as target:
            for info in source.infolist():
                target.writestr(info, replacements.get(info.filename, source.read(info.filename)))
        temp_path.replace(output_path)

    validate_workbook(output_path)
    return output_path


def validate_workbook(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"생성된 Excel ZIP 손상: {bad_member}")
        sheet_paths = _sheet_paths(archive)
        for name in ("프로그램 정보", "테스트케이스", "테스트 결과"):
            sheet = ET.fromstring(archive.read(sheet_paths[name]))
            if sheet.find(_q("sheetData")) is None:
                raise ValueError(f"생성된 Excel 시트가 올바르지 않습니다: {name}")
