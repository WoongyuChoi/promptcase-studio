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
작성하고 전체 테스트와 EXE 빌드를 완료한 다음 동일한 버전으로 Git 태그를 생성한다.

```powershell
git tag -a v3.3.2 -m "Promptcase Studio 3.3.2"
```
