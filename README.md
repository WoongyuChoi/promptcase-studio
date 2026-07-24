# Promptcase Studio

소스 변경 근거를 읽고, 검증 가능한 단위테스트 문서와 공유용 릴리즈 노트를 만드는 Windows 데스크톱 도구입니다.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white)
![PyQt5](https://img.shields.io/badge/UI-PyQt5-41CD52?logo=qt&logoColor=white)
![AI](https://img.shields.io/badge/AI-Gemini%20%7C%20Qwen-7C3AED)
![문서](https://img.shields.io/badge/Output-Excel%20%7C%20Release%20Note-217346)
![버전](https://img.shields.io/badge/Version-3.4.1-F97316)

[주요 기능](#주요-기능) · [사용자 실행](#사용자-실행) · [동작 방식](#동작-방식) ·
[개발 환경](#개발-환경-실행) · [릴리즈](#패키지-빌드와-릴리즈) · [문서](#관련-문서)

Promptcase Studio는 프로젝트 전체를 무작정 AI에 보내지 않습니다. Git 변경 이력, 현재 diff,
사용자 의뢰와 실제 소스의 참조 관계를 조합해 필요한 근거를 선별하고, AI 응답을 로컬 계약과
품질 규칙으로 검증한 뒤 기존 Excel 템플릿의 서식을 보존해 결과를 생성합니다.

## 주요 기능

| 기능 | 설명 |
| --- | --- |
| 변경 범위 분석 | Git commit·diff, 수정일, 수동 변경 파일과 사용자 변경 요약을 함께 분석합니다. |
| 범용 소스 스캔 | Java·JSP·TypeScript뿐 아니라 Python, SQL/PLSQL, SAP ABAP/CDS, .NET, Go, Rust 등 다양한 환경을 다룹니다. |
| 연관 근거 선별 | import, include, endpoint, 함수 호출과 DB 객체 관계를 따라 필요한 소스만 제한적으로 포함합니다. |
| 이중 AI 환경 | 온라인은 Gemini, 폐쇄망은 Qwen을 사용하며 동일한 구조화 응답 계약을 적용합니다. |
| 안전한 결과 검증 | JSON 구조, 근거 식별자, 테스트 절차와 기대 결과를 검증하고 표현 차이는 안전한 범위에서 자동 정리합니다. |
| 문서 자동화 | 원본 Excel 서식을 보존한 단위테스트 문서와 팀 공유용 릴리즈 노트 메일을 함께 만듭니다. |
| 실행 근거 보존 | 선택 파일, 프롬프트, 응답, 품질 보고서와 로그를 실행별 폴더에 남깁니다. |

## 지원 소스 환경

기본 스캐너는 다음 범주를 지원합니다. 목록에 없는 사내 전용 텍스트 소스는
`scanner.additionalSourceSuffixes` 설정으로 확장자를 추가할 수 있습니다.

| 범주 | 예시 |
| --- | --- |
| 웹·애플리케이션 | Java, Kotlin, JSP, JavaScript, TypeScript, TSX, Vue, Python, PHP, Ruby |
| 데이터·인터페이스 | SQL, PL/SQL, HANA SQLScript, MyBatis XML, GraphQL, Protocol Buffers |
| SAP | ABAP, CDS, BDEF, SRVD, HANA 객체 |
| 시스템·배치 | C/C++, C#, Go, Rust, Swift, Scala, Groovy, Dart, COBOL, JCL |
| 자동화·설정 | PowerShell, Shell, Batch, Terraform, YAML, JSON, TOML |

특정 언어나 프레임워크의 계층 구조를 강제하지 않으며, 인식 가능한 정확한 참조와 변경 근거를
우선합니다. 사내 전용 문법은 원문과 diff를 분석할 수 있지만 더 깊은 의미 관계가 필요하면
별도의 언어 프로파일을 추가해야 합니다.

## 동작 방식

1. 분석할 프로젝트 폴더를 하나 이상 선택합니다.
2. Git Diff, 시작일과 종료일, 수동 변경 파일 목록과 개발자 변경 요약을 조합해 변경 범위를 만듭니다.
3. 의뢰서 또는 변경 로직 설명을 입력합니다.
4. 변경 파일과 언어별 import, include, endpoint, 호출 및 데이터 객체 관계를 따라 관련 소스를 선별합니다.
5. 온라인 환경은 Gemini, 폐쇄망은 Qwen으로 구조화된 단위테스트 초안을 생성합니다.
6. 변경 앵커와 정상, 부정, 경계, 권한, 오류, 삭제, 회귀 커버리지를 검사하고 품질 기준에 미달하면 별도 AI 품질 검토에서 더 나은 문안을 선택합니다.
   사용자 의뢰에 명시된 저장, 조회조건, 다운로드, 삭제 등의 동작은 실행 절차와 판정 기준이 함께 있어야 통과합니다.
7. 같은 변경 근거와 최종 테스트 문안으로 팀 공유용 릴리즈 노트 메일을 별도 생성합니다.
8. 내부 템플릿 `templates/unittest_template.xlsx`의 빈 셀 또는 `{{placeholder}}`만 치환해 검증된 초안을 만듭니다.
9. 분석이 끝나면 `릴리즈 노트 뷰`에서 메일을 복사·임시 편집하고, `테스트케이스 다운로드`에서 저장 폴더와 파일명을 직접 선택합니다.

오른쪽 터미널 패널에는 스캔, 컨텍스트 선정, 프롬프트 전송, 응답 검증,
문서 생성 단계가 순서대로 표시됩니다.

날짜 범위의 기본값은 이번 달 1일부터 오늘까지이며 시작일과 종료일을 모두 포함합니다.

## 사용자 실행

릴리즈 파일은 `PromptcaseStudio-{버전}-windows-x64.zip` 형식으로 제공합니다.

1. 전달받은 ZIP을 쓰기 가능한 폴더에 모두 압축 해제합니다.
2. 압축 해제된 `PromptcaseStudio-{버전}` 폴더를 엽니다.
3. 폴더 안의 `PromptcaseStudio.exe`를 실행합니다.

`PromptcaseStudio.exe`만 따로 이동하거나 ZIP 내부에서 바로 실행하면 안 됩니다. `_internal`
폴더에는 Python 런타임과 실행에 필요한 파일이 들어 있으므로 EXE와 항상 함께 있어야 합니다.
Python은 사용자 PC에 별도로 설치하지 않아도 됩니다.

## 개발 환경 실행

Python 3.11 이상과 PyQt5가 필요합니다.

```powershell
python -m pip install -r requirements.txt
python main.py
```

Windows에서는 `run-promptcase-studio.bat`을 더블클릭해도 됩니다.

## 패키지 빌드와 릴리즈

사내 사용자에게 전달할 기본 릴리즈는 인증 설정을 포함한 폴더형 ZIP입니다.

```powershell
.\build-private-folder.bat
```

결과는 다음 두 위치에 생성됩니다.

```text
dist\PromptcaseStudio-{버전}\
dist\PromptcaseStudio-{버전}-windows-x64.zip
```

릴리즈할 때는 ZIP만 공유합니다. ZIP에는 `PromptcaseStudio.exe`, `_internal`, 실행 안내와
필수 리소스가 모두 들어 있습니다. 인증정보는 추출될 수 있으므로 승인된 사내 경로에서만
배포해야 합니다.

인증정보가 없는 공개 폴더형 ZIP은 다음 명령으로 만듭니다.

```powershell
.\build-folder.bat
```

단일 EXE가 꼭 필요한 경우에만 다음 빌드를 사용할 수 있습니다.

```powershell
.\build-exe.bat
.\build-private-exe.bat
```

단일 EXE는 실행할 때 `%TEMP%\_MEI...`에 파일을 풀기 때문에 일부 백신·EDR 환경에서 종료
정리 경고가 발생할 수 있습니다. 따라서 일반 사용자 릴리즈에는 폴더형 ZIP을 우선합니다.

개발 모드에서는 기존 저장소 경로를 그대로 사용합니다. 세부 내용은
[Windows 패키징 문서](docs/PACKAGING.md)를 참고하세요.

## 생성 결과

| 위치·기능 | 내용 |
| --- | --- |
| 테스트케이스 다운로드 | 원본 서식을 보존한 `.xlsx` 단위테스트 문서 |
| 릴리즈 노트 뷰 | 복사하고 임시 편집할 수 있는 공유용 메일 제목과 본문 |
| `runs/{실행 ID}/` | 변경 목록, 선택 근거, 프롬프트, AI 원문, 검증·품질 보고서와 로그 |
| `outputs/` | 저장 대화상자의 기본 출력 위치 |

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
- AI 품질 검토는 기본으로 켜져 있지만 필수 문제가 없고 기본 95점 이상인 초안은 추가 호출 없이 사용하며, 환경설정에서 검토 자체를 끌 수 있습니다.
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

## 버전 관리

제품 버전은 Semantic Versioning을 사용하며 현재 버전은 CLI 시작 화면과
Windows EXE 파일 속성에서 확인할 수 있습니다.
버전 변경 기준과 명령은 [버전 관리 문서](docs/VERSIONING.md)를 참고하세요.

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

## 관련 문서

- [아키텍처와 분석 흐름](docs/ARCHITECTURE.md)
- [Windows 패키징](docs/PACKAGING.md)
- [버전 관리와 릴리즈](docs/VERSIONING.md)
- [Excel 템플릿 규약](docs/EXCEL_TEMPLATE.md)
- [보안 원칙](docs/SECURITY.md)
- [변경 이력](CHANGELOG.md)
