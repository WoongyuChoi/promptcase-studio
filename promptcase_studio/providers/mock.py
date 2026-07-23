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
                "subject": "[릴리즈 안내] 사용자 조회 조건 변경 및 확인 요청",
                "body": (
                    "안녕하세요.\n\n"
                    "이번 릴리즈에서는 사용자 조회 조건을 정리하고 활성 상태와 비활성 상태의 "
                    "처리 기준을 반영했습니다.\n\n"
                    "주요 변경 사항\n"
                    "- 활성 사용자 조회 흐름을 반영했습니다.\n"
                    "- 비활성 사용자가 조회 결과에서 제외되도록 변경했습니다.\n\n"
                    "확인 부탁드리는 내용\n"
                    "- 활성 사용자가 조회 결과에 정상적으로 표시되는지 확인해 주세요.\n"
                    "- 비활성 사용자가 조회 결과에서 제외되는지 확인해 주세요.\n\n"
                    "변경된 조회 조건과 기존 기능을 함께 테스트해 주시면 감사하겠습니다.\n"
                    "추가로 확인이 필요한 내용이 있으면 편하게 말씀해 주세요.\n\n"
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
