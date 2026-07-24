# 버전 관리

Promptcase Studio는 `MAJOR.MINOR.PATCH` 형식의 Semantic Versioning을 사용한다.
현재 제품 버전의 기준 파일은 `promptcase_studio/__init__.py`이며 CLI 시작 화면과
Windows EXE 파일 속성이 이 값을 사용한다. `prompts/manifest.json`의 `bundleVersion`도
배포 버전과 동일하게 유지한다.

## 버전 증가 기준

- `MAJOR`: 기존 설정, 입력, 출력 문서 또는 사용 흐름과 호환되지 않는 변경
- `MINOR`: 새 화면, provider, 분석 단계, 문서 유형, 지원 언어처럼 사용자가 인지하는 기능 추가
- `PATCH`: 버그 수정, UI 보정, 프롬프트·검증·스캔 정확도 개선, 패키징 안정화

문서나 테스트만 바뀌고 배포 동작이 달라지지 않으면 버전을 올리지 않는다. 하나의 작업에
여러 변경이 있으면 가장 높은 수준을 적용한다.

## 버전 변경

```powershell
python scripts/bump_version.py --check
python scripts/bump_version.py patch
python scripts/bump_version.py minor
python scripts/bump_version.py major
python scripts/bump_version.py 4.0.0
```

스크립트는 제품 버전과 프롬프트 번들 버전을 함께 갱신한다. 버전 변경 후에는 CHANGELOG를
작성하고 전체 테스트와 배포 빌드를 완료한 다음 동일한 버전으로 Git 태그를 생성한다.

```powershell
$version = python -c "from promptcase_studio import __version__; print(__version__)"
git tag -a "v$version" -m "Promptcase Studio $version"
```

## 릴리즈 체크리스트

1. 변경 수준에 맞춰 `bump_version.py`로 버전을 올린다.
2. `CHANGELOG.md`에 사용자 관점 변경 사항을 기록한다.
3. 전체 오프라인 테스트와 버전 일치 검사를 통과한다.
4. 사내용 기본 릴리즈는 `build-private-folder.bat`으로 빌드한다.
5. `dist\PromptcaseStudio-{버전}-windows-x64.zip`을 깨끗한 폴더에 모두 압축 해제한다.
6. 압축 해제한 `PromptcaseStudio.exe`로 시작·종료 smoke test를 수행한다.
7. ZIP의 SHA-256을 확인하고 동일한 버전의 Git 태그를 만든다.

사용자에게는 버전형 ZIP만 공유한다. 폴더형 `PromptcaseStudio.exe`는 `_internal`에 의존하므로
실행 파일만 따로 전달하지 않는다. 단일 EXE 빌드는 폴더형 ZIP을 사용할 수 없는 특별한 경우에만
대체 산출물로 제공한다.
