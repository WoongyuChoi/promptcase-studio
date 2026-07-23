from __future__ import annotations

import json

from promptcase_studio.models import ChunkCallback, LogCallback
from promptcase_studio.providers.base import TextGenerationProvider
from promptcase_studio.release_note import RELEASE_NOTE_MARKER


class MockProvider(TextGenerationProvider):
    def generate(
        self,
        prompt: str,
        log: LogCallback | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        if log:
            log("MOCK", f"외부 네트워크 없이 {len(prompt):,}자 프롬프트 처리")
        if RELEASE_NOTE_MARKER in prompt:
            payload = {
                "subject": "[공유] 사용자 조회 조건 변경",
                "body": (
                    "안녕하세요.\n\n"
                    "사용자 조회 조건 변경 사항을 공유드립니다.\n\n"
                    "[변경 사항]\n"
                    "- 활성 상태 기준 사용자 조회\n"
                    "- 비활성 사용자의 조회 결과 제외\n\n"
                    "[적용 범위]\n"
                    "- 사용자 조회 기능\n\n"
                    "[확인 요청 사항]\n"
                    "- 활성 상태를 선택하고 사용자를 조회해 주세요.\n"
                    "- 활성 사용자가 조회 결과에 표시되는지 확인해 주세요.\n"
                    "- 비활성 상태를 선택하고 다시 조회해 주세요.\n"
                    "- 비활성 사용자가 결과에서 제외되는지 확인해 주세요.\n\n"
                    "확인 중 문제나 예상과 다른 결과가 있으면 메일 또는 메신저로 알려주세요.\n\n"
                    "감사합니다."
                ),
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            if log:
                log("RESPONSE", f"Mock 릴리즈 노트 응답 {len(text):,}자 생성")
            return text
        payload = {
            "testCase": {
                "name": "소스 변경사항 단위테스트",
                "procedure": [
                    "활성 상태 조건을 선택해 사용자 조회를 실행한다",
                    "비활성 상태 조건을 선택해 사용자 조회를 다시 실행한다",
                ],
                "targetIds": [],
                "targetNames": [],
                "preconditions": [
                    "대상 기능을 사용할 수 있는 계정으로 로그인되어 있어야 한다",
                    "활성 상태와 비활성 상태의 사용자 데이터가 준비되어 있어야 한다",
                ],
                "testData": "활성 상태 사용자 데이터와 비활성 상태 사용자 데이터를 각각 사용한다",
                "expectedResult": "활성 사용자는 조회되고 비활성 사용자는 조회 결과에서 제외된다",
                "notes": "Mock 응답으로 생성한 문서이며 실제 AI 분석 결과가 아닙니다",
            },
            "testResult": {
                "processingDetails": [
                    {"title": "변경 로직 반영", "detail": "의뢰 내용과 변경 소스의 주요 처리 흐름을 반영"}
                ],
                "testDetails": [
                    "활성 상태 사용자가 조회 결과에 표시되는지 확인한다",
                    "비활성 상태 사용자가 조회 결과에서 제외되는지 확인한다",
                ],
                "resultChecks": [
                    "변경 요구사항 적용 결과 확인",
                    "기존 기능 정상 동작 확인",
                ],
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if on_chunk:
            for index in range(0, len(text), 120):
                on_chunk(text[index : index + 120])
        if log:
            log("RESPONSE", f"Mock 응답 {len(text):,}자 생성")
        return text
