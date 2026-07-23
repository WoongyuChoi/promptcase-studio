# Promptcase Studio

Promptcase Studio는 소스 변경 범위와 개발 의뢰 내용을 분석해 AI로 단위테스트 문안을 만들고,
기존 Excel 템플릿을 보존한 결과 문서를 생성하는 Windows용 Python GUI 도구입니다.

## 핵심 흐름

1. 분석할 프로젝트 폴더를 하나 이상 선택합니다.
2. Git Diff, 시작일과 종료일, 수동 변경 파일 목록과 개발자 변경 요약을 조합해 변경 범위를 만듭니다.
3. 의뢰서 또는 변경 로직 설명을 입력합니다.
4. 변경 파일과 import/참조 관계를 따라 관련 소스를 선별합니다.
5. 온라인 환경은 Gemini, 폐쇄망은 Qwen으로 구조화된 단위테스트 초안을 생성합니다.
6. 변경 앵커와 정상, 부정, 경계, 권한, 오류, 삭제, 회귀 커버리지를 검사한 뒤 별도 AI 품질 검토에서 더 나은 문안을 선택합니다.
   사용자 의뢰에 명시된 저장, 조회조건, 다운로드, 삭제 등의 동작은 실행 절차와 판정 기준이 함께 있어야 통과합니다.
7. 내부 템플릿 `templates/unittest_template.xlsx`의 빈 셀 또는 `{{placeholder}}`만 치환해 검증된 초안을 만듭니다.
8. 분석이 끝나면 `테스트케이스 다운로드`에서 저장 폴더와 파일명을 직접 선택합니다.

오른쪽 터미널 패널에는 스캔, 컨텍스트 선정, 프롬프트 전송, 응답 검증,
문서 생성 단계가 순서대로 표시됩니다.

날짜 범위의 기본값은 이번 달 1일부터 오늘까지이며 시작일과 종료일을 모두 포함합니다.

## 실행

Python 3.11 이상과 PyQt5가 필요합니다.

```powershell
python -m pip install -r requirements.txt
python main.py
```

Windows에서는 `run-promptcase-studio.bat`을 더블클릭해도 됩니다.

## 단일 EXE 배포

Windows 사용자에게는 PyInstaller one-file 결과물 하나만 배포할 수 있습니다.

```powershell
.\build-exe.bat
```

결과는 `dist\PromptcaseStudio.exe`에 생성됩니다. EXE 최초 실행 시 공개 기본 리소스를
`%LOCALAPPDATA%\Promptcase Studio` 아래로 복사하고 `config`, `prompts`, `schemas`,
`templates`, `runs`, `outputs` 폴더를 자동으로 준비합니다. API 키용 `.env`는 번들에
포함하지 않으며, 사용자가 환경설정에서 키를 저장한 경우에만 사용자 데이터 폴더에 생성됩니다.
미수정 기본 프롬프트, 스키마와 템플릿은 새 EXE에서 자동 갱신되며 사용자 수정본은 보존됩니다.

개발 모드에서는 기존 저장소 경로를 그대로 사용합니다. 세부 내용은
[단일 EXE 패키징 문서](docs/PACKAGING.md)를 참고하세요.

## API 설정

- 기본 환경은 `폐쇄망`이며 Qwen을 사용합니다.
- Gemini 모델은 기본값 `Auto`에서 `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` 순서로 사용합니다. 일일 한도는 즉시, RPM과 TPM 제한은 서버 대기 및 재시도 후 다음 모델로 전환합니다.
- 환경설정에서 특정 모델을 선택하면 해당 모델만 고정 사용합니다. 자동 목록은 텍스트 출력, 구조화 JSON, 1M 입력 컨텍스트를 지원하는 안정 모델만 사용합니다.
- AI 품질 검토 횟수와 검토별 응답 시도 횟수를 각각 1회에서 3회까지 정할 수 있습니다. 기본 완료 정책은 계약을 통과한 최선본을 다운로드하게 하고 남은 품질 항목을 경고하며, 필요하면 엄격한 차단 정책을 선택할 수 있습니다.
- `폐쇄망`은 저장소의 `config/qwen.settings.json`을 기본으로 사용하며 환경설정에서 다른 파일을 선택할 수 있습니다.
- 실제 API 키는 `.env`의 `GEMINI_API_KEY` 또는 같은 이름의 OS 환경변수에 둡니다.
- `.env`, 로컬 설정, 실행 로그와 생성 문서는 Git에 포함되지 않습니다.
- Gemini와 Qwen의 기본 응답 제한시간은 300초, 출력 한도는 32768토큰이며 최대 3회까지 시도합니다.
- 재시도는 응답 시작 전 연결 실패와 HTTP 408, 425, 429, 5xx에만 적용됩니다.
- 응답이 JSON 문서 계약을 벗어나면 검증 오류를 반영해 기본 3회까지 교정 요청합니다.
- 정상 종료가 아닌 출력 잘림과 안전 차단은 성공으로 처리하지 않으며 종료 사유와 토큰 사용량을 실행 로그에 남깁니다.
- 2차 품질 검토는 기본으로 켜져 있고 환경설정에서 끌 수 있습니다.
- 필수 의뢰 조건이 첫 검토에도 남으면 최대 2차례 교정하며, 결정적 누락은 검토 설정을 꺼도 Excel 생성을 차단합니다.

```powershell
Copy-Item .env.example .env
```

노출된 키는 재사용하지 말고 새 키를 발급해 입력하세요.

## 오프라인 테스트

기본 자동 테스트는 외부 API를 호출하지 않습니다.

```powershell
python -m unittest discover -s tests -v
```

개발 중 GUI에서 전체 흐름을 확인하려면 환경설정의 `오프라인 Mock 모드`를 켭니다.

`tests/`는 스캐너, provider 재시도, Excel 템플릿 보존과 GUI 생성의 회귀를 막는 소스이므로
저장소와 최초 커밋에 포함합니다. 테스트가 만드는 임시 결과만 `tmp/`로 제외됩니다.

## 프로젝트 구조

```text
config/                 Git에 포함되는 기본 앱 설정과 실제 Qwen 연결 설정
docs/                   아키텍처와 보안 원칙
prompts/                버전 관리되는 시스템/문서 생성 프롬프트
schemas/                AI 구조화 응답 계약
promptcase_studio/      GUI, 스캐너, provider, 파이프라인, Excel 생성기
templates/              원본 Excel 템플릿
tests/                  네트워크 없는 회귀 테스트와 프로젝트 fixture
outputs/                저장 대화상자의 기본 위치, Git 제외
runs/                   스캔, 프롬프트, 초안, 품질 보고서, 최종 응답과 로그, Git 제외
```

자세한 흐름은 [아키텍처 문서](docs/ARCHITECTURE.md)와 [Excel 템플릿 규약](docs/EXCEL_TEMPLATE.md)을 참고하세요.
