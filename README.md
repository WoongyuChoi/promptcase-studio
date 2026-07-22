# Promptcase Studio

Promptcase Studio는 소스 변경 범위와 개발 의뢰 내용을 분석해 AI로 단위테스트 문안을 만들고,
기존 Excel 템플릿을 보존한 결과 문서를 생성하는 Windows용 Python GUI 도구입니다.

## 핵심 흐름

1. 분석할 프로젝트 폴더를 하나 이상 선택합니다.
2. Git Diff, 수정 시작일, 수동 변경 파일 목록을 조합해 변경 범위를 만듭니다.
3. 의뢰서 또는 변경 로직 설명을 입력합니다.
4. 변경 파일과 import/참조 관계를 따라 관련 소스를 선별합니다.
5. 온라인 환경은 Gemini, 중요단말망은 Qwen으로 구조화된 단위테스트 문안을 생성합니다.
6. `templates/단위테스트 템플릿.xlsx`를 그대로 복사한 뒤 빈 셀 또는 `{{placeholder}}`만 치환해 결과를 만듭니다.

오른쪽 터미널 패널에는 스캔, 컨텍스트 선정, 프롬프트 전송, 응답 검증,
문서 생성 단계가 순서대로 표시됩니다.

## 실행

Python 3.11 이상과 PyQt5가 필요합니다.

```powershell
python -m pip install -r requirements.txt
python main.py
```

Windows에서는 `run-promptcase-studio.bat`을 더블클릭해도 됩니다.

## API 설정

- 기본 환경은 `온라인`이며 Gemini를 사용합니다.
- `중요단말망`은 저장소의 `config/qwen.settings.json`을 기본으로 사용하며 환경설정에서 다른 파일을 선택할 수 있습니다.
- 실제 API 키는 `.env`의 `GEMINI_API_KEY` 또는 같은 이름의 OS 환경변수에 둡니다.
- `.env`, 로컬 설정, 실행 로그와 생성 문서는 Git에 포함되지 않습니다.
- Gemini와 Qwen의 기본 응답 제한시간은 300초이며 최대 3회까지 시도합니다.
- 재시도는 응답 시작 전 연결 실패와 HTTP 408, 425, 429, 5xx에만 적용됩니다.

```powershell
Copy-Item .env.example .env
```

노출된 키는 재사용하지 말고 새 키를 발급해 입력하세요.

## 오프라인 테스트

기본 자동 테스트는 외부 API를 호출하지 않습니다.

```powershell
python -m unittest discover -s tests -v
```

개발 중 GUI에서 전체 흐름을 확인하려면 환경설정의 `오프라인 Mock 사용`을 켭니다.

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
outputs/                생성 문서, Git 제외
runs/                   스캔·프롬프트·응답 진단 산출물, Git 제외
```

자세한 흐름은 [아키텍처 문서](docs/ARCHITECTURE.md)와 [Excel 템플릿 규약](docs/EXCEL_TEMPLATE.md)을 참고하세요.
