from __future__ import annotations

import json

from promptcase_studio.models import ChunkCallback, LogCallback
from promptcase_studio.providers.base import TextGenerationProvider


class MockProvider(TextGenerationProvider):
    def generate(
        self,
        prompt: str,
        log: LogCallback | None = None,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        if log:
            log("MOCK", f"외부 네트워크 없이 {len(prompt):,}자 프롬프트 처리")
        payload = {
            "testCase": {
                "name": "소스 변경사항 단위테스트",
                "procedure": [
                    "변경 대상 기능에 접근해 기본 조회 결과를 확인한다",
                    "변경 조건에 해당하는 입력 또는 데이터를 적용한다",
                    "처리 결과와 연관 화면 또는 저장 데이터를 확인한다",
                ],
                "targetIds": [],
                "targetNames": ["변경 대상 기능"],
                "preconditions": [
                    "대상 기능을 사용할 수 있는 계정으로 로그인되어 있어야 한다",
                    "변경 조건을 확인할 수 있는 기준 데이터가 준비되어 있어야 한다",
                    "연관 기능의 정상 결과와 비교할 수 있어야 한다",
                ],
                "testData": "변경 조건과 정상 조건을 각각 확인할 수 있는 테스트 데이터를 사용한다",
                "expectedResult": "변경 요구사항이 반영되고 기존 연관 기능이 정상 동작한다",
                "notes": "Mock 응답으로 생성한 문서이며 실제 AI 분석 결과가 아닙니다",
            },
            "testResult": {
                "processingDetails": [
                    {"title": "변경 로직 반영", "detail": "의뢰 내용과 변경 소스의 주요 처리 흐름을 반영"}
                ],
                "testDetails": [
                    "변경 대상 기능의 기본 진입과 조회가 정상인지 확인한다",
                    "변경 조건 적용 시 기대한 처리 결과가 표시되는지 확인한다",
                    "연관 기능과 기존 정상 흐름에 영향이 없는지 확인한다",
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

