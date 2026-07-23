import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from promptcase_studio.excel_writer import (
    MAIN_NS,
    REL_NS,
    _parse_xml_preserving_namespaces,
    _serialize_xml_preserving_namespaces,
    _set_inline_text,
    generate_workbook,
    validate_workbook,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "templates" / "unittest_template.xlsx"
TEMP_ROOT = PROJECT_ROOT / "tmp" / "tests"


def document_fixture():
    return {
        "programInfo": [
            {
                "category": "사업계획관리시스템",
                "detailCategory": "Program",
                "program": "UserService.java",
                "project": "sample",
                "changeType": "변경",
            },
            {
                "category": "정산시스템",
                "detailCategory": "SQL",
                "program": "delete_legacy_api.sql",
                "project": "sample",
                "workContent": "요건 변경에 따른 불필요 SQL 삭제",
                "changeType": "삭제",
            },
        ],
        "testCase": {
            "name": "사용자 조회 단위테스트",
            "procedure": ["화면에 진입한다", "사용자를 조회한다", "결과를 확인한다"],
            "targetIds": ["USR1000"],
            "targetNames": ["사용자 조회"],
            "preconditions": ["로그인 상태다", "사용자가 존재한다", "조회 권한이 있다"],
            "testData": "활성 사용자 데이터를 사용한다",
            "expectedResult": "활성 사용자만 정상 조회된다",
            "notes": "",
        },
        "testResult": {
            "processingDetails": [{"title": "조회 조건 변경", "detail": "활성 상태 조건 반영"}],
            "testDetails": ["진입 확인", "조회 확인", "결과 확인"],
            "resultChecks": ["활성 사용자 조회 결과 확인"],
        },
    }


def sheet_paths(archive):
    main = f"{{{MAIN_NS}}}"
    wb = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relmap = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
    result = {}
    for sheet in wb.find(f"{main}sheets"):
        target = relmap[sheet.attrib[f"{{{REL_NS}}}id"]]
        if target.startswith("/xl/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        result[sheet.attrib["name"]] = target
    return result


def shared_string_values(archive):
    main = f"{{{MAIN_NS}}}"
    shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(f"{main}t")) for item in shared]


def cell_value(sheet, reference, shared_values=None):
    main = f"{{{MAIN_NS}}}"
    for cell in sheet.iter(f"{main}c"):
        if cell.attrib.get("r") == reference:
            if cell.attrib.get("t") == "s" and shared_values is not None:
                raw_value = cell.find(f"{main}v")
                return shared_values[int(raw_value.text)] if raw_value is not None else ""
            return "".join(node.text or "" for node in cell.iter(f"{main}t"))
    return None


def row_height(sheet, row_number):
    main = f"{{{MAIN_NS}}}"
    for row in sheet.iter(f"{main}row"):
        if int(row.attrib.get("r", "0")) == row_number:
            return float(row.attrib.get("ht", "0"))
    return 0.0


def cell_style_id(sheet, reference):
    main = f"{{{MAIN_NS}}}"
    for cell in sheet.iter(f"{main}c"):
        if cell.attrib.get("r") == reference:
            return int(cell.attrib.get("s", "0"))
    return 0


def style_alignment(archive, style_id):
    main = f"{{{MAIN_NS}}}"
    styles = ET.fromstring(archive.read("xl/styles.xml"))
    style = list(styles.find(f"{main}cellXfs"))[style_id]
    return style.find(f"{main}alignment")


def style_fill_color(archive, style_id):
    main = f"{{{MAIN_NS}}}"
    styles = ET.fromstring(archive.read("xl/styles.xml"))
    style = list(styles.find(f"{main}cellXfs"))[style_id]
    fill = list(styles.find(f"{main}fills"))[int(style.attrib["fillId"])]
    color = fill.find(f"{main}patternFill/{main}fgColor")
    return color.attrib.get("rgb", "") if color is not None else ""


def merged_ranges(sheet):
    main = f"{{{MAIN_NS}}}"
    merge_cells = sheet.find(f"{main}mergeCells")
    if merge_cells is None:
        return []
    return [merge.attrib["ref"] for merge in merge_cells]


def workbook_text_values(archive):
    main = f"{{{MAIN_NS}}}"
    shared_values = shared_string_values(archive)
    values = list(shared_values)
    for path in sheet_paths(archive).values():
        sheet = ET.fromstring(archive.read(path))
        values.extend(
            "".join(node.text or "" for node in cell.iter(f"{main}t"))
            for cell in sheet.iter(f"{main}c")
            if cell.attrib.get("t") == "inlineStr"
        )
    return values


def make_placeholder_template(destination):
    placements = {
        "프로그램 정보": {
            "B4": "{{category}}",
            "C4": "{{detail_category}}",
            "D4": "{{program}}",
            "E4": "{{project}}",
            "F4": "{{work_content}}",
            "G4": "{{change_type}}",
        },
        "테스트케이스": {
            "C3": "테스트케이스 {{name}}",
            "C4": "{{type}}",
            "C5": "{{procedure}}",
            "C6": "{{target_ids}}",
            "C7": "{{target_names}}",
            "C8": "{{preconditions}}",
            "C9": "{{test_data}}",
            "C10": "{{expected_result}}",
            "C11": "{{notes}}",
        },
        "테스트 결과": {
            "C3": "{{processing_details}}",
            "C4": "{{test_details}}",
            "C5": "{{result_checks}}",
        },
    }
    with zipfile.ZipFile(TEMPLATE, "r") as source:
        paths = sheet_paths(source)
        replacements = {}
        main = f"{{{MAIN_NS}}}"
        for sheet_name, cells in placements.items():
            source_xml = source.read(paths[sheet_name])
            sheet, namespaces = _parse_xml_preserving_namespaces(source_xml)
            by_reference = {cell.attrib.get("r"): cell for cell in sheet.iter(f"{main}c")}
            for reference, value in cells.items():
                _set_inline_text(by_reference[reference], value)
            replacements[paths[sheet_name]] = _serialize_xml_preserving_namespaces(
                sheet,
                source_xml,
                namespaces,
            )
        with zipfile.ZipFile(destination, "w") as target:
            for info in source.infolist():
                target.writestr(info, replacements.get(info.filename, source.read(info.filename)))


class ExcelWriterTests(unittest.TestCase):
    def test_validation_failure_preserves_existing_destination(self):
        case_directory = TEMP_ROOT / "excel-atomic-validation"
        case_directory.mkdir(parents=True, exist_ok=True)
        output = case_directory / "existing.xlsx"
        original = b"existing user workbook"
        output.write_bytes(original)

        with (
            patch(
                "promptcase_studio.excel_writer.validate_workbook",
                side_effect=ValueError("synthetic validation failure"),
            ),
            self.assertRaisesRegex(ValueError, "synthetic validation failure"),
        ):
            generate_workbook(TEMPLATE, output, document_fixture())

        self.assertEqual(output.read_bytes(), original)
        self.assertFalse(output.with_suffix(".tmp.xlsx").exists())

    def test_preserves_template_and_fills_three_sheets(self):
        case_directory = TEMP_ROOT / "excel-writer"
        case_directory.mkdir(parents=True, exist_ok=True)
        output = case_directory / "result.xlsx"
        generate_workbook(TEMPLATE, output, document_fixture())
        with zipfile.ZipFile(output) as archive:
            paths = sheet_paths(archive)
            shared_values = shared_string_values(archive)
            program = ET.fromstring(archive.read(paths["프로그램 정보"]))
            test_case = ET.fromstring(archive.read(paths["테스트케이스"]))
            result = ET.fromstring(archive.read(paths["테스트 결과"]))
            self.assertEqual(
                cell_value(program, "B4", shared_values),
                "사업계획관리시스템",
            )
            self.assertEqual(cell_value(program, "C4", shared_values), "Program")
            self.assertEqual(cell_value(program, "D4", shared_values), "UserService.java")
            self.assertEqual(
                cell_value(program, "F4", shared_values),
                "요건 변경에 따른 개발 프로그램 수정",
            )
            self.assertEqual(
                cell_value(program, "D5", shared_values),
                "delete_legacy_api.sql",
            )
            self.assertEqual(cell_value(program, "G5", shared_values), "삭제")
            self.assertEqual(cell_value(program, "B5", shared_values), "정산시스템")
            self.assertEqual(cell_value(program, "C5", shared_values), "SQL")
            self.assertEqual(
                cell_value(program, "F5", shared_values),
                "요건 변경에 따른 불필요 SQL 삭제",
            )
            self.assertEqual(row_height(program, 4), 15.0)
            self.assertEqual(row_height(program, 5), 15.0)
            work_alignment = style_alignment(archive, cell_style_id(program, "F5"))
            self.assertEqual(work_alignment.attrib.get("horizontal"), "center")
            self.assertEqual(cell_value(test_case, "C4", shared_values), "단위테스트")
            self.assertIn("1. 화면에 진입한다", cell_value(test_case, "C5", shared_values))
            self.assertIn("조회 조건 변경", cell_value(result, "C3", shared_values))
            self.assertEqual(cell_value(result, "C5", shared_values), "1. 활성 사용자 조회 결과 확인")
            self.assertEqual(cell_value(result, "C6", shared_values), "캡처 이미지를 여기에 붙여 넣으세요")
            all_values = workbook_text_values(archive)
            self.assertIn("프로젝트", all_values)
            self.assertFalse(any("Frism" in value for value in all_values))
            with zipfile.ZipFile(TEMPLATE) as template_archive:
                self.assertEqual(set(archive.namelist()), set(template_archive.namelist()))
                changed_members = {"xl/styles.xml", *paths.values()}
                for member in archive.namelist():
                    if member not in changed_members:
                        self.assertEqual(archive.read(member), template_archive.read(member))
        validate_workbook(output)

    def test_replaces_placeholders_without_rebuilding_template(self):
        case_directory = TEMP_ROOT / "excel-placeholder"
        case_directory.mkdir(parents=True, exist_ok=True)
        placeholder_template = case_directory / "placeholder-template.xlsx"
        output = case_directory / "result.xlsx"
        make_placeholder_template(placeholder_template)
        generate_workbook(placeholder_template, output, document_fixture())

        with zipfile.ZipFile(output) as archive:
            paths = sheet_paths(archive)
            shared_values = shared_string_values(archive)
            program = ET.fromstring(archive.read(paths["프로그램 정보"]))
            test_case = ET.fromstring(archive.read(paths["테스트케이스"]))
            self.assertEqual(cell_value(program, "B5", shared_values), "정산시스템")
            self.assertEqual(cell_value(program, "C5", shared_values), "SQL")
            self.assertEqual(
                cell_value(program, "D5", shared_values),
                "delete_legacy_api.sql",
            )
            self.assertEqual(cell_value(program, "E5", shared_values), "sample")
            self.assertEqual(
                cell_value(program, "F5", shared_values),
                "요건 변경에 따른 불필요 SQL 삭제",
            )
            self.assertEqual(cell_value(program, "G5", shared_values), "삭제")
            self.assertEqual(
                cell_value(test_case, "C3", shared_values),
                "테스트케이스 사용자 조회 단위테스트",
            )
            self.assertFalse(any("{{" in value for value in workbook_text_values(archive)))

    def test_program_rows_are_compact_while_descriptive_cells_expand(self):
        case_directory = TEMP_ROOT / "excel-long-values"
        case_directory.mkdir(parents=True, exist_ok=True)
        output = case_directory / "result.xlsx"
        document = document_fixture()
        document["programInfo"][0]["program"] = "VeryLongProgramName" * 5 + ".java"
        document["testCase"]["name"] = "사업계획 기준정보와 사용자 권한 및 메뉴 구성을 함께 검증하는 " * 2 + "단위테스트"
        document["testCase"]["targetIds"] = ["SCREEN_IDENTIFIER_" + "A" * 55] * 3
        document["testCase"]["targetNames"] = ["사업계획 기준정보 사용자 권한 메뉴 구성 화면"] * 4
        document["testCase"]["testData"] = "사업계획 기준정보와 사용자 권한 및 메뉴 구성을 구분할 수 있는 데이터 " * 3
        generate_workbook(TEMPLATE, output, document)

        with zipfile.ZipFile(output) as archive:
            paths = sheet_paths(archive)
            program = ET.fromstring(archive.read(paths["프로그램 정보"]))
            test_case = ET.fromstring(archive.read(paths["테스트케이스"]))
            self.assertEqual(row_height(program, 4), 15.0)
            for row_number in (3, 6, 7, 9):
                with self.subTest(row=row_number):
                    self.assertGreater(row_height(test_case, row_number), 19.95)

    def test_limits_test_items_and_builds_repeated_capture_areas(self):
        case_directory = TEMP_ROOT / "excel-capture-layout"
        case_directory.mkdir(parents=True, exist_ok=True)
        output = case_directory / "result.xlsx"
        document = document_fixture()
        document["testCase"]["procedure"] = [f"테스트 절차 {index}" for index in range(1, 8)]
        document["testCase"]["preconditions"] = [f"테스트 사전조건 {index}" for index in range(1, 8)]
        document["testCase"]["expectedResult"] = "첫 번째 예상결과\n두 번째 예상결과\n세 번째 예상결과"
        document["testResult"]["processingDetails"] = [
            {"title": f"처리내역 {index}", "detail": f"처리내용 {index}"}
            for index in range(1, 8)
        ]
        document["testResult"]["testDetails"] = [f"테스트내역 {index}" for index in range(1, 8)]
        document["testResult"]["resultChecks"] = [f"결과화면 {index}" for index in range(1, 8)]

        generate_workbook(TEMPLATE, output, document)
        validate_workbook(output)

        with zipfile.ZipFile(output) as archive:
            paths = sheet_paths(archive)
            shared_values = shared_string_values(archive)
            test_case = ET.fromstring(archive.read(paths["테스트케이스"]))
            result = ET.fromstring(archive.read(paths["테스트 결과"]))

            procedure = cell_value(test_case, "C5", shared_values)
            preconditions = cell_value(test_case, "C8", shared_values)
            expected_result = cell_value(test_case, "C10", shared_values)
            self.assertEqual(len(procedure.splitlines()), 5)
            self.assertNotIn("테스트 절차 6", procedure)
            self.assertEqual(len(preconditions.splitlines()), 5)
            self.assertNotIn("테스트 사전조건 6", preconditions)
            self.assertEqual(len(expected_result.splitlines()), 2)
            self.assertIn("세 번째 예상결과", expected_result.splitlines()[1])
            self.assertLessEqual(row_height(test_case, 5), 96.5)
            self.assertLessEqual(row_height(test_case, 8), 96.5)
            self.assertLessEqual(row_height(test_case, 10), 47.0)

            processing = cell_value(result, "C3", shared_values)
            test_details = cell_value(result, "C4", shared_values)
            self.assertIn("처리내역 5", processing)
            self.assertNotIn("처리내역 6", processing)
            self.assertIn("5. 테스트내역 5", test_details)
            self.assertNotIn("테스트내역 6", test_details)
            self.assertEqual(merged_ranges(result), ["B5:B14"])
            self.assertEqual(result.find(f"{{{MAIN_NS}}}dimension").attrib["ref"], "B1:C14")

            for index, (description_row, capture_row) in enumerate(
                zip(range(5, 14, 2), range(6, 15, 2)),
                1,
            ):
                with self.subTest(result=index):
                    self.assertEqual(
                        cell_value(result, f"C{description_row}", shared_values),
                        f"{index}. 결과화면 {index}",
                    )
                    self.assertEqual(
                        cell_value(result, f"C{capture_row}", shared_values),
                        "캡처 이미지를 여기에 붙여 넣으세요",
                    )
                    self.assertEqual(row_height(result, capture_row), 150.0)
                    capture_style = cell_style_id(result, f"C{capture_row}")
                    self.assertEqual(style_fill_color(archive, capture_style), "FFFCE8EF")
                    alignment = style_alignment(archive, capture_style)
                    self.assertEqual(alignment.attrib.get("horizontal"), "center")

            self.assertNotIn("결과화면 6", workbook_text_values(archive))


if __name__ == "__main__":
    unittest.main()
