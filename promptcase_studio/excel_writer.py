from __future__ import annotations

import copy
import io
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"

ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)

PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")

PROGRAM_ROW_HEIGHT_POINTS = 15.0  # Excel row height equivalent to about 20 pixels.
MAX_TEST_CASE_STEPS = 5
MAX_EXPECTED_RESULT_LINES = 2
MAX_TEST_RESULT_ITEMS = 5
CAPTURE_ROW_HEIGHT_POINTS = 120.0
CAPTURE_GUIDANCE = "캡처 이미지를 여기에 붙여 넣으세요"


def _q(tag: str) -> str:
    return f"{{{MAIN_NS}}}{tag}"


def _parse_xml_preserving_namespaces(data: bytes) -> tuple[ET.Element, list[tuple[str, str]]]:
    namespaces: list[tuple[str, str]] = []
    for _event, item in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        prefix, uri = item
        normalized = (prefix or "", uri)
        if normalized not in namespaces:
            namespaces.append(normalized)
    for prefix, uri in namespaces:
        ET.register_namespace(prefix, uri)
    return ET.fromstring(data), namespaces


def _serialize_xml_preserving_namespaces(
    element: ET.Element,
    original: bytes,
    namespaces: list[tuple[str, str]],
) -> bytes:
    payload = ET.tostring(element, encoding="utf-8", xml_declaration=False)
    root_end = payload.find(b">")
    if root_end < 0:
        raise ValueError("Excel XML 루트 요소를 직렬화하지 못했습니다.")
    root_start = payload[:root_end]
    for prefix, uri in namespaces:
        marker = b"xmlns=" if not prefix else f"xmlns:{prefix}=".encode("utf-8")
        if marker in root_start:
            continue
        attribute = (
            f' xmlns{":" + prefix if prefix else ""}="{uri.replace("&", "&amp;").replace(chr(34), "&quot;")}"'
        ).encode("utf-8")
        root_start += attribute
    payload = root_start + payload[root_end:]
    declaration = re.match(br"\s*(<\?xml[^?]*\?>)", original)
    header = declaration.group(1) if declaration else b'<?xml version="1.0" encoding="UTF-8"?>'
    return header + b"\r\n" + payload


def _validate_ignorable_namespaces(data: bytes, part_name: str) -> None:
    root, namespaces = _parse_xml_preserving_namespaces(data)
    declared = {prefix for prefix, _uri in namespaces}
    ignored = root.attrib.get(f"{{{MC_NS}}}Ignorable", "").split()
    missing = sorted(prefix for prefix in ignored if prefix not in declared)
    if missing:
        raise ValueError(
            f"Excel XML의 mc:Ignorable namespace 선언이 누락되었습니다: {part_name} - {missing}"
        )


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


def _add_wrapped_styles(
    styles: ET.Element,
    source_ids: set[int],
    *,
    horizontal: str | None = None,
) -> dict[int, int]:
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
        if horizontal:
            alignment.attrib["horizontal"] = horizontal
        cell_xfs.append(cloned)
        mapping[source_id] = len(cell_xfs) - 1
    cell_xfs.attrib["count"] = str(len(cell_xfs))
    return mapping


def _add_capture_style(styles: ET.Element, source_id: int) -> int:
    fills = styles.find(_q("fills"))
    borders = styles.find(_q("borders"))
    cell_xfs = styles.find(_q("cellXfs"))
    if fills is None or borders is None or cell_xfs is None:
        raise ValueError("템플릿 styles.xml에 캡처 영역 서식을 추가할 수 없습니다.")

    fill = ET.Element(_q("fill"))
    pattern = ET.SubElement(fill, _q("patternFill"), {"patternType": "solid"})
    ET.SubElement(pattern, _q("fgColor"), {"rgb": "FFFCE8EF"})
    ET.SubElement(pattern, _q("bgColor"), {"indexed": "64"})
    fills.append(fill)
    fill_id = len(list(fills)) - 1
    fills.attrib["count"] = str(len(list(fills)))

    border = ET.Element(_q("border"))
    for edge_name in ("left", "right", "top", "bottom"):
        edge = ET.SubElement(border, _q(edge_name), {"style": "thin"})
        ET.SubElement(edge, _q("color"), {"rgb": "FFE6A7BA"})
    ET.SubElement(border, _q("diagonal"))
    borders.append(border)
    border_id = len(list(borders)) - 1
    borders.attrib["count"] = str(len(list(borders)))

    source_styles = list(cell_xfs)
    if source_id < 0 or source_id >= len(source_styles):
        source_id = 0
    cloned = copy.deepcopy(source_styles[source_id])
    cloned.attrib.update(
        {
            "fillId": str(fill_id),
            "borderId": str(border_id),
            "applyFill": "1",
            "applyBorder": "1",
            "applyAlignment": "1",
        }
    )
    alignment = cloned.find(_q("alignment"))
    if alignment is None:
        alignment = ET.SubElement(cloned, _q("alignment"))
    alignment.attrib.update(
        {
            "horizontal": "center",
            "vertical": "center",
            "wrapText": "1",
        }
    )
    alignment.attrib.pop("indent", None)
    cell_xfs.append(cloned)
    cell_xfs.attrib["count"] = str(len(list(cell_xfs)))
    return len(list(cell_xfs)) - 1


def _use_wrapped_style(cell: ET.Element, style_map: dict[int, int]) -> None:
    current = int(cell.attrib.get("s", "0"))
    if current in style_map:
        cell.attrib["s"] = str(style_map[current])


def _use_style(cell: ET.Element, style_id: int) -> None:
    cell.attrib["s"] = str(style_id)


def _set_text(sheet: ET.Element, reference: str, value: str, style_map: dict[int, int]) -> None:
    cell = _find_cell(sheet, reference)
    _set_inline_text(cell, value)
    if "\n" in value or len(value) > 42:
        _use_wrapped_style(cell, style_map)


def _estimated_text_lines(value: str, characters_per_line: int) -> int:
    segments = value.splitlines() or [""]
    return sum(
        max(1, (len(segment) + characters_per_line - 1) // characters_per_line)
        for segment in segments
    )


def _set_row_height(
    sheet: ET.Element,
    row_number: int,
    value: str,
    minimum: float,
    maximum: float,
    characters_per_line: int = 52,
) -> None:
    lines = _estimated_text_lines(value, characters_per_line)
    estimated = max(minimum, min(maximum, 16.5 * lines + 14))
    for row in sheet.iter(_q("row")):
        if int(row.attrib.get("r", "0")) == row_number:
            row.attrib["ht"] = f"{estimated:.2f}"
            row.attrib["customHeight"] = "1"
            return


def _limited_strings(items: list[Any], maximum: int) -> list[str]:
    return [str(item).strip() for item in items if str(item).strip()][:maximum]


def _limit_lines(value: Any, maximum: int) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if len(lines) <= maximum:
        return "\n".join(lines)
    return "\n".join([*lines[: maximum - 1], " ".join(lines[maximum - 1 :])])


def _placeholder_reference(
    sheet: ET.Element,
    shared_strings: list[str],
    aliases: tuple[str, ...],
) -> str | None:
    accepted = {alias.casefold() for alias in aliases}
    for cell in sheet.iter(_q("c")):
        for match in PLACEHOLDER_PATTERN.finditer(_cell_text(cell, shared_strings)):
            if match.group(1).strip().casefold() in accepted:
                return _cell_reference(cell)
    return None


def _renumber_row(row: ET.Element, row_number: int) -> None:
    row.attrib["r"] = str(row_number)
    for cell in row.findall(_q("c")):
        column = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
        if column:
            cell.attrib["r"] = f"{column.group(0)}{row_number}"


def _set_vertical_merge(sheet: ET.Element, column: str, start_row: int, end_row: int) -> None:
    merge_cells = sheet.find(_q("mergeCells"))
    if merge_cells is None:
        merge_cells = ET.Element(_q("mergeCells"))
        trailing = {
            "phoneticPr",
            "conditionalFormatting",
            "dataValidations",
            "hyperlinks",
            "printOptions",
            "pageMargins",
            "pageSetup",
            "headerFooter",
            "drawing",
            "legacyDrawing",
        }
        insert_at = next(
            (
                index
                for index, child in enumerate(list(sheet))
                if child.tag.rsplit("}", 1)[-1] in trailing
            ),
            len(list(sheet)),
        )
        sheet.insert(insert_at, merge_cells)

    anchor_prefix = f"{column}{start_row}:"
    for merge in list(merge_cells):
        reference = merge.attrib.get("ref", "")
        if reference == f"{column}{start_row}" or reference.startswith(anchor_prefix):
            merge_cells.remove(merge)
    if end_row > start_row:
        ET.SubElement(
            merge_cells,
            _q("mergeCell"),
            {"ref": f"{column}{start_row}:{column}{end_row}"},
        )
    merge_cells.attrib["count"] = str(len(list(merge_cells)))


def _write_capture_rows(
    sheet: ET.Element,
    anchor_reference: str,
    result_checks: list[str],
    shared_strings: list[str],
    style_map: dict[int, int],
    capture_style_id: int,
) -> None:
    match = re.fullmatch(r"([A-Z]+)(\d+)", anchor_reference)
    if not match:
        raise ValueError(f"결과 화면 placeholder 셀 주소가 올바르지 않습니다: {anchor_reference}")
    target_column, row_text = match.groups()
    if target_column != "C":
        raise ValueError("결과 화면 placeholder는 테스트 결과 시트 C열에 배치해야 합니다.")
    start_row = int(row_text)
    label_column = "B"
    items = _limited_strings(result_checks, MAX_TEST_RESULT_ITEMS) or ["결과 화면을 확인한다"]

    sheet_data = sheet.find(_q("sheetData"))
    if sheet_data is None:
        raise ValueError("테스트 결과 시트에 sheetData가 없습니다.")
    rows = list(sheet_data.findall(_q("row")))
    template = next((row for row in rows if int(row.attrib.get("r", "0")) == start_row), None)
    if template is None:
        raise ValueError(f"테스트 결과의 캡처 템플릿 행을 찾지 못했습니다: {start_row}")
    template_index = rows.index(template)

    generated_row_count = len(items) * 2
    shift = generated_row_count - 1
    for row in reversed(rows):
        current = int(row.attrib.get("r", "0"))
        if current > start_row:
            _renumber_row(row, current + shift)
    sheet_data.remove(template)

    generated_rows: list[ET.Element] = []
    for index, item in enumerate(items, 1):
        description_row_number = start_row + (index - 1) * 2
        capture_row_number = description_row_number + 1
        description_row = copy.deepcopy(template)
        capture_row = copy.deepcopy(template)
        _renumber_row(description_row, description_row_number)
        _renumber_row(capture_row, capture_row_number)

        description_row.attrib["ht"] = f"{max(30.0, min(63.0, 16.5 * _estimated_text_lines(item, 88) + 14)):.2f}"
        description_row.attrib["customHeight"] = "1"
        capture_row.attrib["ht"] = f"{CAPTURE_ROW_HEIGHT_POINTS:.2f}"
        capture_row.attrib["customHeight"] = "1"

        for row, value, is_capture in (
            (description_row, f"{index}. {item}", False),
            (capture_row, CAPTURE_GUIDANCE, True),
        ):
            for cell in row.findall(_q("c")):
                column_match = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
                if not column_match:
                    continue
                column = column_match.group(0)
                if column == target_column:
                    _set_inline_text(cell, value)
                    if is_capture:
                        _use_style(cell, capture_style_id)
                    else:
                        _use_wrapped_style(cell, style_map)
                elif column == label_column:
                    if description_row_number == start_row and not is_capture:
                        continue
                    _set_inline_text(cell, "")
                else:
                    _set_inline_text(cell, "")
        generated_rows.extend((description_row, capture_row))

    for offset, row in enumerate(generated_rows):
        sheet_data.insert(template_index + offset, row)

    end_row = start_row + generated_row_count - 1
    _set_vertical_merge(sheet, label_column, start_row, end_row)
    dimension = sheet.find(_q("dimension"))
    if dimension is not None:
        maximum_row = max(int(row.attrib.get("r", "0")) for row in sheet_data.findall(_q("row")))
        dimension.attrib["ref"] = f"B1:C{maximum_row}"


def _clone_program_rows(
    sheet: ET.Element,
    program_rows: list[dict[str, str]],
    shared_strings: list[str],
    style_map: dict[int, int],
    centered_style_map: dict[int, int],
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
        _renumber_row(row, row_number)
        row.attrib["ht"] = f"{PROGRAM_ROW_HEIGHT_POINTS:.2f}"
        row.attrib["customHeight"] = "1"
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
        for cell in row.findall(_q("c")):
            if cell.attrib.get("r", "").startswith("F"):
                _use_wrapped_style(cell, centered_style_map)
        used = _replace_placeholders(row, shared_strings, placeholder_values, style_map)
        fallback_columns = {
            "program": "D",
            "project": "E",
            "work_content": "F",
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
                    elif field == "work_content":
                        _use_wrapped_style(cell, centered_style_map)
                    break
            else:
                if "\n" in _cell_text(cell, shared_strings):
                    _use_wrapped_style(cell, style_map)
            if column.group(0) == "F":
                _use_wrapped_style(cell, centered_style_map)
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
    procedure = _limited_strings(data["procedure"], MAX_TEST_CASE_STEPS)
    preconditions = _limited_strings(data["preconditions"], MAX_TEST_CASE_STEPS)
    field_values = {
        "name": data["name"],
        "type": "단위테스트",
        "procedure": _numbered(procedure),
        "target_ids": ", ".join(data["targetIds"]),
        "target_names": ", ".join(data["targetNames"]),
        "preconditions": _numbered(preconditions),
        "test_data": data["testData"],
        "expected_result": _limit_lines(data["expectedResult"], MAX_EXPECTED_RESULT_LINES),
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
    _set_row_height(sheet, 3, field_values["name"], 19.95, 75, 48)
    _set_row_height(sheet, 5, field_values["procedure"], 79.95, 96.5, 52)
    _set_row_height(sheet, 6, field_values["target_ids"], 19.95, 150, 52)
    _set_row_height(sheet, 7, field_values["target_names"], 19.95, 150, 48)
    _set_row_height(sheet, 8, field_values["preconditions"], 79.95, 96.5, 52)
    _set_row_height(sheet, 9, field_values["test_data"], 19.95, 105, 48)
    _set_row_height(sheet, 10, field_values["expected_result"], 30, 47, 52)
    _set_row_height(sheet, 11, field_values["notes"], 19.95, 90, 52)


def _write_test_result(
    sheet: ET.Element,
    data: dict[str, Any],
    shared_strings: list[str],
    style_map: dict[int, int],
    capture_style_id: int,
) -> None:
    processing_items = list(data["processingDetails"])[:MAX_TEST_RESULT_ITEMS]
    detail_items = _limited_strings(data["testDetails"], MAX_TEST_RESULT_ITEMS)
    result_items = _limited_strings(data["resultChecks"], MAX_TEST_RESULT_ITEMS)
    processing = "\n\n".join(
        f"○ {item['title']}\n{item['detail']}" for item in processing_items
    )
    test_details = _numbered(detail_items)
    result_checks = "\n".join(f"{index}. {item}" for index, item in enumerate(result_items, 1))
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
    result_anchor = _placeholder_reference(
        sheet,
        shared_strings,
        aliases["result_checks"],
    ) or "C5"
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
    _write_capture_rows(
        sheet,
        result_anchor,
        result_items,
        shared_strings,
        style_map,
        capture_style_id,
    )


def generate_workbook(template_path: Path, output_path: Path, document: dict[str, Any]) -> Path:
    if not template_path.exists():
        raise FileNotFoundError(f"Excel 템플릿을 찾을 수 없습니다: {template_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(template_path, "r") as source:
        sheet_paths = _sheet_paths(source)
        required = {"프로그램 정보", "테스트케이스", "테스트 결과"}
        if not required.issubset(sheet_paths):
            raise ValueError(f"필수 시트가 없습니다: {sorted(required - set(sheet_paths))}")

        styles_source = source.read("xl/styles.xml")
        styles, styles_namespaces = _parse_xml_preserving_namespaces(styles_source)
        shared_strings = _shared_string_values(source)
        sheet_sources = {name: source.read(sheet_paths[name]) for name in required}
        parsed_sheets = {
            name: _parse_xml_preserving_namespaces(sheet_sources[name])
            for name in required
        }
        sheets = {name: parsed_sheets[name][0] for name in required}
        sheet_namespaces = {name: parsed_sheets[name][1] for name in required}
        source_style_ids = {
            int(cell.attrib.get("s", "0"))
            for sheet in sheets.values()
            for cell in sheet.iter(_q("c"))
        }
        style_map = _add_wrapped_styles(styles, source_style_ids)
        centered_style_map = _add_wrapped_styles(
            styles,
            source_style_ids,
            horizontal="center",
        )
        result_capture_source = int(_find_cell(sheets["테스트 결과"], "C5").attrib.get("s", "0"))
        capture_style_id = _add_capture_style(styles, result_capture_source)

        program_rows = document.get("programInfo") or [
            {"program": "", "project": "", "changeType": "변경"}
        ]
        _clone_program_rows(
            sheets["프로그램 정보"],
            program_rows,
            shared_strings,
            style_map,
            centered_style_map,
        )
        _write_test_case(sheets["테스트케이스"], document["testCase"], shared_strings, style_map)
        _write_test_result(
            sheets["테스트 결과"],
            document["testResult"],
            shared_strings,
            style_map,
            capture_style_id,
        )

        unresolved = {
            match.group(0)
            for sheet in sheets.values()
            for cell in sheet.iter(_q("c"))
            for match in PLACEHOLDER_PATTERN.finditer(_cell_text(cell, shared_strings))
        }
        if unresolved:
            raise ValueError(f"지원하지 않거나 치환되지 않은 Excel placeholder: {sorted(unresolved)}")

        replacements = {
            "xl/styles.xml": _serialize_xml_preserving_namespaces(
                styles,
                styles_source,
                styles_namespaces,
            ),
            **{
                sheet_paths[name]: _serialize_xml_preserving_namespaces(
                    sheet,
                    sheet_sources[name],
                    sheet_namespaces[name],
                )
                for name, sheet in sheets.items()
            },
        }
        temp_path = output_path.with_suffix(".tmp.xlsx")
        try:
            with zipfile.ZipFile(temp_path, "w") as target:
                for info in source.infolist():
                    target.writestr(info, replacements.get(info.filename, source.read(info.filename)))
            # Never expose a partially valid workbook at the requested path.
            # This also preserves a user's existing file when validation fails.
            validate_workbook(temp_path)
            temp_path.replace(output_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    return output_path


def validate_workbook(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"생성된 Excel ZIP 손상: {bad_member}")
        sheet_paths = _sheet_paths(archive)
        _validate_ignorable_namespaces(archive.read("xl/styles.xml"), "xl/styles.xml")
        for name in ("프로그램 정보", "테스트케이스", "테스트 결과"):
            sheet_data = archive.read(sheet_paths[name])
            _validate_ignorable_namespaces(sheet_data, sheet_paths[name])
            sheet = ET.fromstring(sheet_data)
            if sheet.find(_q("sheetData")) is None:
                raise ValueError(f"생성된 Excel 시트가 올바르지 않습니다: {name}")
