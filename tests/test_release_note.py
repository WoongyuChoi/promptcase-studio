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
          "subject": "[릴리즈 안내] 저장 조건 변경 및 확인 요청",
          "body": "안녕하세요.\\n\\n이번 릴리즈에서는 저장할 변경 사항이 없는 경우 안내 메시지를 표시하도록 수정했습니다.\\n\\n주요 변경 사항\\n- 변경된 값이 없으면 저장 요청 대신 안내 메시지를 표시합니다.\\n- 변경된 값이 있으면 기존 저장 흐름을 그대로 진행합니다.\\n\\n확인 부탁드리는 내용\\n- 변경 사항 유무에 따라 안내와 저장이 각각 정상 동작하는지 테스트해 주세요.\\n\\n확인 후 특이 사항이 있으면 편하게 말씀해 주세요.\\n\\n감사합니다."
        }"""

        release_note = parse_release_note_response(raw)

        self.assertTrue(release_note["body"].startswith("안녕하세요"))
        self.assertTrue(release_note["body"].endswith("감사합니다."))
        self.assertIn("제목:", render_release_note(release_note))

    def test_response_parser_rejects_ai_written_trace(self):
        raw = """{
          "subject": "[릴리즈 안내] 저장 조건 변경 및 확인 요청",
          "body": "안녕하세요.\\n\\nAI가 제공된 정보를 바탕으로 저장 조건 변경 내용을 정리했습니다. 변경 사항이 없을 때 안내 메시지가 표시되며 기존 저장 기능도 함께 테스트해 주세요. 관련된 기능을 충분히 확인하고 검증해 주시기 바랍니다. 추가 확인 사항이 있으면 말씀해 주세요.\\n\\n감사합니다."
        }"""

        with self.assertRaises(ReleaseNoteValidationError):
            parse_release_note_response(raw)

    def test_fallback_builds_complete_mail_from_final_test_document(self):
        release_note = fallback_release_note(self.structured, "채산관리시스템")

        self.assertIn("채산관리시스템", release_note["subject"])
        self.assertTrue(release_note["body"].startswith("안녕하세요"))
        self.assertTrue(release_note["body"].endswith("감사합니다."))
        self.assertIn("저장 전 변경 확인", release_note["body"])
        self.assertIn("확인해 주세요", release_note["body"])


if __name__ == "__main__":
    unittest.main()
