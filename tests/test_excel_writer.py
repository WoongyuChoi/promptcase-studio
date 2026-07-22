import json
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from promptcase_studio.excel_writer import MAIN_NS, REL_NS, _set_inline_text, generate_workbook


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "templates" / "단위테스트 템플릿.xlsx"
TEMP_ROOT = PROJECT_ROOT / "tmp" / "tests"


def document_fixture():
    return {
        "programInfo": [
            {"program": "UserService.java", "project": "sample - Backend", "changeType": "변경"},
            {"program": "LegacyApi.java", "project": "sample - Backend", "changeType": "삭제"},
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
            sheet = ET.fromstring(source.read(paths[sheet_name]))
            by_reference = {cell.attrib.get("r"): cell for cell in sheet.iter(f"{main}c")}
            for reference, value in cells.items():
                _set_inline_text(by_reference[reference], value)
            replacements[paths[sheet_name]] = ET.tostring(
                sheet,
                encoding="utf-8",
                xml_declaration=True,
            )
        with zipfile.ZipFile(destination, "w") as target:
            for info in source.infolist():
                target.writestr(info, replacements.get(info.filename, source.read(info.filename)))


class ExcelWriterTests(unittest.TestCase):
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
            self.assertEqual(cell_value(program, "D4", shared_values), "UserService.java")
            self.assertEqual(cell_value(program, "D5", shared_values), "LegacyApi.java")
            self.assertEqual(cell_value(program, "G5", shared_values), "삭제")
            self.assertEqual(cell_value(program, "B5", shared_values), "채산관리시스템")
            self.assertEqual(cell_value(program, "C5", shared_values), "Program")
            self.assertEqual(cell_value(program, "F5", shared_values), "요건 변경에 따른 개발 프로그램 수정")
            self.assertEqual(cell_value(test_case, "C4", shared_values), "단위테스트")
            self.assertIn("1. 화면에 진입한다", cell_value(test_case, "C5", shared_values))
            self.assertIn("조회 조건 변경", cell_value(result, "C3", shared_values))
            all_values = workbook_text_values(archive)
            self.assertIn("프로젝트", all_values)
            self.assertFalse(any("Frism" in value for value in all_values))
            with zipfile.ZipFile(TEMPLATE) as template_archive:
                self.assertEqual(set(archive.namelist()), set(template_archive.namelist()))
                changed_members = {"xl/styles.xml", *paths.values()}
                for member in archive.namelist():
                    if member not in changed_members:
                        self.assertEqual(archive.read(member), template_archive.read(member))

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
            self.assertEqual(cell_value(program, "D5", shared_values), "LegacyApi.java")
            self.assertEqual(cell_value(program, "E5", shared_values), "sample - Backend")
            self.assertEqual(cell_value(program, "F5", shared_values), "요건 변경에 따른 개발 프로그램 수정")
            self.assertEqual(cell_value(program, "G5", shared_values), "삭제")
            self.assertEqual(
                cell_value(test_case, "C3", shared_values),
                "테스트케이스 사용자 조회 단위테스트",
            )
            self.assertFalse(any("{{" in value for value in workbook_text_values(archive)))


if __name__ == "__main__":
    unittest.main()
