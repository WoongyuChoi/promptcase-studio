# Promptcase Studio 개발 기준

## 제품 목적

- 프로젝트 변경 범위와 사용자 의뢰 내용을 근거로 단위테스트 문안을 생성한다.
- AI 입력은 프로젝트 전체를 무조건 보내지 않고 변경 파일, diff, import/참조 관계, focused excerpt를 조합한다.
- AI 응답은 JSON 계약으로 검증한 뒤 원본 Excel 템플릿의 고정 문구와 서식을 보존해 출력한다.

## 아키텍처 원칙

- GUI는 입력과 진행 상태만 관리하고 스캔/API/문서 생성 로직을 직접 소유하지 않는다.
- 프로그램 정보의 파일명과 신규/변경/삭제 판정은 가능한 한 로컬 분석 결과를 source of truth로 삼는다.
- Git이 없으면 수정일과 수동 입력을 사용하며 삭제 파일은 반드시 사용자가 명시해야 한다.
- 스캐너는 정렬된 결정적 인덱스를 사용하고 secret-like 파일과 생성 디렉터리를 제외한다.
- 전체 파일, focused excerpt, Git diff를 목적에 맞게 구분하고 전송 근거를 run artifact에 남긴다.
- 온라인 provider는 Gemini, 중요단말망 provider는 Qwen 설정을 사용한다.
- API 키와 실제 단말망 설정은 Git에 커밋하지 않는다.

## UI 원칙

- 왼쪽은 밝은 카드형 제어 패널, 오른쪽은 다크 터미널 패널로 구성한다.
- 긴 작업은 QThread에서 실행하고 단계 로그와 가능한 경우 응답 chunk를 UI에 전달한다.
- 기본 환경은 설정 파일의 `defaultEnvironment`에서 결정하며 초기값은 `online`이다.

## 배포 원칙

- 사용자용 기본 릴리즈는 `PromptcaseStudio-{버전}-windows-x64.zip` 형식의 폴더형 패키지다.
- 사내 릴리즈는 `build-private-folder.bat`으로 만들고, ZIP을 깨끗한 위치에 풀어 시작과 종료를 검증한다.
- 폴더형 `PromptcaseStudio.exe`만 따로 배포하지 않으며 `_internal`을 포함한 ZIP 전체를 전달한다.
- 단일 EXE는 백신·EDR의 `_MEI` 임시 폴더 잠금 가능성이 있으므로 특별한 경우에만 대체 산출물로 제공한다.

## 프롬프트와 문서

- 프롬프트는 `prompts/`, 구조화 응답 계약은 `schemas/`에서 버전 관리한다.
- 템플릿 제목, 헤더와 `단위테스트` 문구는 변경하지 않는다. 프로그램 정보의 구분, 상세구분과 작업 내용은 시스템명, 파일 종류와 변경구분을 근거로 동적으로 생성한다.
- `Frism 반영여부` 열은 만들지 않고 프로그램 정보의 열 이름은 `프로젝트`를 유지한다.
- 원본 템플릿을 덮어쓰지 않고 항상 `outputs/`에 새 파일을 생성한다.

## 테스트 원칙

- 기본 테스트는 외부 네트워크를 사용하지 않는다.
- provider는 mock으로 교체 가능해야 하며 Gemini/Qwen 응답 fixture를 별도로 검증한다.
- 스캐너, 응답 parser, Excel 셀 매핑과 서식 보존을 회귀 테스트한다.
- 실제 API 통합 테스트는 사용자가 명시적으로 실행할 때만 허용한다.

## 버전 관리

- 제품 버전은 `promptcase_studio/__init__.py`의 `__version__`을 source of truth로 사용한다.
- `prompts/manifest.json`의 `bundleVersion`은 제품 버전과 항상 같아야 하며 `scripts/bump_version.py`로 함께 변경한다.
- 호환성 파괴는 MAJOR, 사용자 기능 추가는 MINOR, 버그·UI·프롬프트·검증·패키징 개선은 PATCH를 올린다.
- 문서와 테스트만 변경되고 배포 동작이 같으면 버전을 올리지 않는다.
- 배포 가능한 변경을 마칠 때 변경 범위에 맞는 버전 증가 여부를 판단하고, 버전이 바뀌면 CLI, EXE 파일 속성, CHANGELOG에 반영한다.
- Git 태그는 `vMAJOR.MINOR.PATCH` 형식을 사용하되 실제 태그 생성과 원격 반영은 사용자가 수행한다.
