import json
import unittest

from promptcase_studio.models import ChangeItem, ScanBundle
from promptcase_studio.release_note import (
    RELEASE_NOTE_MARKER,
    ReleaseNoteValidationError,
    build_release_note_prompt,
    fallback_release_note,
    parse_release_note_response,
    render_release_note,
)


class ReleaseNoteTests(unittest.TestCase):
    def setUp(self):
        self.structured = {
            "testCase": {
                "name": "저장 변경사항 확인",
                "procedure": [
                    "변경 사항이 없는 상태에서 저장을 실행한다",
                    "값을 수정한 뒤 저장을 실행한다",
                ],
                "targetNames": ["사용자 정보 저장"],
            },
            "testResult": {
                "processingDetails": [
                    {
                        "title": "저장 전 변경 확인",
                        "detail": "변경된 항목이 없으면 안내 메시지를 표시하도록 변경",
                    }
                ],
                "testDetails": [
                    "변경 사항이 없을 때 안내 메시지가 표시되는지 확인한다",
                    "변경 사항이 있으면 기존 저장 흐름이 정상 동작하는지 확인한다",
                ],
            },
        }

    def test_prompt_contains_grounded_release_note_contract(self):
        bundle = ScanBundle(
            changes=[
                ChangeItem(
                    "C:/Project/sample",
                    "src/SavePage.tsx",
                    "변경",
                    "manual",
                    True,
                )
            ],
            change_notes=["feat: 변경된 내용이 없으면 Alert 처리"],
        )

        prompt = build_release_note_prompt(
            bundle,
            "저장 시 변경된 내용이 없으면 안내해 주세요.",
            self.structured,
        )

        self.assertIn(RELEASE_NOTE_MARKER, prompt)
        self.assertIn("SavePage.tsx", prompt)
        self.assertIn("변경된 내용이 없으면 Alert 처리", prompt)
        self.assertIn('"subject"', prompt)
        self.assertIn("최종 단위테스트 문안", prompt)

    def test_response_parser_accepts_complete_human_mail(self):
        raw = """{
          "subject": "[공유] 사용자 저장 조건 변경",
          "body": "안녕하세요.\\n\\n사용자 저장 조건 변경 사항을 공유드립니다.\\n\\n[변경 사항]\\n- 변경된 값이 없을 때 안내 메시지 표시\\n- 변경된 값이 있을 때 기존 저장 흐름 유지\\n\\n[적용 범위]\\n- 사용자 정보 저장 기능\\n\\n[확인 요청 사항]\\n- 값을 바꾸지 않은 상태에서 저장해 주세요.\\n- 안내 메시지가 표시되는지 확인해 주세요.\\n- 값을 수정하고 다시 저장해 주세요.\\n- 수정한 값이 반영되는지 확인해 주세요.\\n\\n확인 중 문제나 예상과 다른 결과가 있으면 메일 또는 메신저로 알려주세요.\\n\\n감사합니다."
        }"""

        release_note = parse_release_note_response(raw)

        self.assertTrue(release_note["body"].startswith("안녕하세요"))
        self.assertTrue(release_note["body"].endswith("감사합니다."))
        self.assertIn("제목:", render_release_note(release_note))

    def test_response_parser_rejects_ai_written_trace(self):
        raw = """{
          "subject": "[공유] 사용자 저장 조건 변경",
          "body": "안녕하세요.\\n\\nAI가 분석한 저장 조건 변경 사항을 공유드립니다.\\n\\n[변경 사항]\\n- 변경된 값이 없을 때 안내 메시지 표시\\n\\n[적용 범위]\\n- 사용자 정보 저장 기능\\n\\n[확인 요청 사항]\\n- 값을 바꾸지 않은 상태에서 저장해 주세요.\\n- 안내 메시지가 표시되는지 확인해 주세요.\\n\\n확인 중 문제나 예상과 다른 결과가 있으면 메일 또는 메신저로 알려주세요.\\n\\n감사합니다."
        }"""

        with self.assertRaises(ReleaseNoteValidationError):
            parse_release_note_response(raw)

    def test_response_parser_rejects_verbose_request_suffix(self):
        raw = """{
          "subject": "[공유] 사용자 저장 조건 변경 반영 및 확인 요청",
          "body": "안녕하세요.\\n\\n사용자 저장 조건 변경 사항을 공유드립니다.\\n\\n[변경 사항]\\n- 변경된 값이 없을 때 안내 메시지 표시\\n\\n[적용 범위]\\n- 사용자 정보 저장 기능\\n\\n[확인 요청 사항]\\n- 값을 바꾸지 않은 상태에서 저장해 주세요.\\n- 안내 메시지가 표시되는지 확인해 주세요.\\n\\n확인 중 문제나 예상과 다른 결과가 있으면 메일 또는 메신저로 알려주세요.\\n\\n감사합니다."
        }"""

        with self.assertRaisesRegex(ReleaseNoteValidationError, "관용 표현"):
            parse_release_note_response(raw)

    def test_fallback_builds_complete_mail_from_final_test_document(self):
        release_note = fallback_release_note(self.structured, "채산관리시스템")
        parsed = parse_release_note_response(
            json.dumps(release_note, ensure_ascii=False)
        )

        self.assertTrue(release_note["subject"].startswith("[공유] "))
        self.assertIn("채산관리시스템", release_note["subject"])
        self.assertTrue(parsed["body"].startswith("안녕하세요"))
        self.assertTrue(parsed["body"].endswith("감사합니다."))
        self.assertIn("[변경 사항]", parsed["body"])
        self.assertIn("[적용 범위]", parsed["body"])
        self.assertIn("[확인 요청 사항]", parsed["body"])
        self.assertIn("저장 전 변경 확인", parsed["body"])
        self.assertIn("확인해 주세요", parsed["body"])


if __name__ == "__main__":
    unittest.main()
