# Promptcase Studio 아키텍처

## 실행 흐름

```text
GUI 입력
  -> Change Collector (Git / 수정일 / 수동 목록)
  -> Deterministic Project Index
  -> Dynamic Context Builder
  -> Prompt Builder
  -> Gemini | Qwen | Mock Provider
  -> Structured Response Parser
  -> Excel Template Writer
```

## 변경 범위

- Git: working tree와 지정일 이후 commit에서 A/M/D/R 상태를 읽는다.
- 수정일: 현재 존재하는 파일 중 시작일 이후 수정된 파일을 찾는다.
- 수동 목록: 비Git 환경의 변경·삭제 설명을 보완한다.
- 같은 파일이 여러 입력에서 발견되면 Git, 수동, 수정일 순으로 신뢰도를 병합한다.

수정일 스캔만으로는 이미 삭제된 파일을 알 수 없으므로 삭제는 Git 또는 수동 입력이 필요하다.

## 컨텍스트 선택

1. 변경 파일은 크기 제한 안에서 우선 포함한다.
2. 큰 변경 파일은 focus term 주변 line window를 사용한다.
3. import, class, mapper namespace/resultType, 상대 경로를 검색어로 만든다.
4. 파일명 일치, 같은 디렉터리, content reference를 점수화한다.
5. 상위 관련 파일만 전체 컨텍스트 제한 안에서 포함한다.
6. 제외 파일과 전송 근거를 `runs/<run-id>/`에 기록한다.

## 구조화 응답

AI는 프로그램 파일 목록을 결정하지 않는다. 프로그램 정보는 change manifest에서 만들고,
AI는 테스트케이스와 테스트 결과 문안만 JSON으로 반환한다. 응답은 문서 생성 전 필수 필드와
리스트 길이를 검증한다.

## Provider 제한시간과 재시도

- Gemini와 Qwen의 기본 제한시간은 300초다.
- 한 요청은 최초 시도를 포함해 최대 3회까지만 시도한다.
- HTTP 응답 전 연결 실패와 408, 425, 429, 500, 502, 503, 504만 재시도한다.
- HTTP 응답 또는 SSE chunk 수신 후의 timeout과 parser 오류는 중복 POST 위험 때문에 재시도하지 않는다.

## Excel 생성

- 원본 템플릿을 덮어쓰지 않는다.
- 프로그램 정보의 4행을 변경 파일 수만큼 복제한다.
- 셀에 `{{placeholder}}`가 있으면 이를 우선 치환하고, 현재 빈 템플릿은 기존 좌표 규약으로 채운다.
- 고정 문구와 style index를 유지하고 동적 셀만 교체한다.
- 테스트케이스와 테스트 결과의 본문 셀에는 줄바꿈을 적용한다.
