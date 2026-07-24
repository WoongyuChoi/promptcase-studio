# Windows 패키징

Promptcase Studio는 PyInstaller의 one-file 모드로 `PromptcaseStudio.exe` 하나를 배포할 수 있습니다.
빌드 결과에는 앱 실행에 필요한 공개 리소스만 들어가며 `.env`와 로컬 설정 파일은 포함하지 않습니다.
백신이나 EDR이 one-file의 임시 `_MEI` 폴더를 잠그는 PC에는 임시 압축 해제가 없는 폴더형
(onedir) 패키지를 같은 설정으로 빌드해 배포할 수 있습니다.

## 단일 EXE 빌드

Windows에서 저장소 루트의 `build-exe.bat`을 실행합니다.

```powershell
.\build-exe.bat
```

완료된 파일은 `dist\PromptcaseStudio.exe`입니다. 빌드 스크립트는
`requirements-build.txt`의 PyInstaller를 설치하고 `promptcase-studio.spec`으로 one-file 빌드를 수행합니다.
CLI 시작 화면과 Windows 파일 속성의 제품 버전은 `promptcase_studio/__init__.py`에서 읽습니다.
제품 버전 변경은 [버전 관리 문서](VERSIONING.md)의 스크립트를 사용합니다.

Windows one-file 종료 시 백신이나 OS가 임시 `_MEI` 폴더의 DLL을 잠그는 문제를 줄이기 위해
정리 재시도와 VC 런타임 잠금 대응이 포함된 PyInstaller 6.21.0을 고정 사용하고 UPX 압축은
사용하지 않습니다. 빌드 환경의 이전 PyInstaller가 그대로 사용되지 않도록
`requirements-build.txt`를 거치지 않은 수동 빌드는 배포하지 않습니다.

## 폴더형 대체 빌드

앱을 종료할 때 `Failed to remove temporary directory: ...\_MEI...` 경고가 반복되는 PC에는
아래 폴더형 빌드를 사용합니다.

```powershell
.\build-folder.bat
```

결과는 `dist\PromptcaseStudio-folder\`이며, 배포할 때 폴더 안의 파일을 모두 함께 전달해야
합니다. 실행 파일은 `dist\PromptcaseStudio-folder\PromptcaseStudio.exe`입니다. 이 방식은
실행 때 `_MEI` 임시 폴더에 프로그램을 풀지 않으므로 백신의 임시 DLL 잠금으로 인한 종료
경고를 피할 수 있습니다. 단일 EXE 결과물 `dist\PromptcaseStudio.exe`는 삭제하거나
덮어쓰지 않습니다.

폴더 안에서 `PromptcaseStudio.exe`만 따로 복사하면 실행되지 않습니다. 폴더 전체를 ZIP으로
묶어 전달하고, 사용자는 쓰기 가능한 위치에 압축을 푼 뒤 실행하는 방식을 권장합니다.

## 사내용 인증정보 포함 빌드

Python이나 별도 설정 파일이 없는 사내 사용자에게 하나의 EXE만 배포해야 한다면 아래 스크립트를 사용합니다.

```powershell
.\build-private-exe.bat
```

이 빌드는 Git에서 제외된 저장소 루트의 `.env`와 현재 선택된 Qwen 설정 파일을 빌드 순간에만
`_private` 리소스로 추가합니다. 최초 실행 시 EXE가 있는 폴더에 Gemini 키와 Qwen 설정을
한 번 복사하며, 사용자가 이후 수정한 값은 덮어쓰지 않습니다.

API 키를 포함한 EXE는 PyInstaller 분석 도구로 추출할 수 있으므로 공개 저장소, 외부 메신저,
공용 파일 서버에 올리지 말고 승인된 사내 경로에서만 배포해야 합니다. 키를 교체하면 EXE도
다시 빌드해야 합니다.

같은 인증정보를 포함한 폴더형 대체 패키지는 아래처럼 빌드합니다.

```powershell
.\build-private-folder.bat
```

결과는 `dist\PromptcaseStudio-folder\`입니다. 일반 폴더형 빌드와 마찬가지로 폴더 전체를
배포해야 하며, `.env`와 선택된 Qwen 설정을 `_private` 리소스로 포함하는 검증 절차는
단일 EXE 사내용 빌드와 동일합니다.

## 번들 리소스

다음 파일은 EXE 또는 폴더 패키지의 읽기 전용 기본 리소스로 포함됩니다.

- `config/app.settings.json`
- `config/qwen.settings.json`
- `prompts/`
- `schemas/`
- `templates/`
- `favicon.ico`

일반 빌드에서는 `.env`, `config/app.settings.local.json`, `runs/`, `outputs/`가 번들에 포함되지
않습니다. 사내용 인증정보 포함 빌드만 `.env`와 선택된 Qwen 설정을 추가합니다.

## 최초 실행과 사용자 데이터

앱을 처음 실행하면 실행 파일이 있는 배포 폴더에 다음 항목을 자동으로 준비합니다.

```text
배포 폴더\
├─ PromptcaseStudio.exe
├─ _internal\            폴더형 빌드에만 존재하며 함께 배포
├─ config\
├─ prompts\
├─ schemas\
├─ templates\
├─ runs\
├─ outputs\
└─ .env                 일반 빌드는 사용자가 키를 저장할 때, 사내용 빌드는 최초 실행 시 생성
```

배포 폴더에는 쓰기 권한이 있어야 합니다. 앱 설정, 프롬프트, 스키마, 템플릿과 아이콘은
파일 해시가 기록된 관리 리소스로 복사됩니다.
사용자가 수정하지 않은 기본 파일은 새 EXE의 버전으로 자동 갱신되고, 사용자가 수정한 파일은
그대로 유지됩니다. 이전 버전처럼 해시 기록이 없는 설치는 기존 파일을 `backups/`에 보관한 뒤
새 기본 리소스로 한 번 마이그레이션합니다. Qwen 연결 설정은 최초 한 번만 복사하고 이후에는
사용자 값을 덮어쓰지 않으며, 누락된 300초 제한시간만 보완합니다.

실행 시 `config/app.settings.json`을 기본값으로 읽고 `config/app.settings.local.json`을 사용자
재정의 값으로 병합합니다. 관리 리소스 상태는 `config/.bundled-resources.json`에 저장됩니다.

개발 모드에서 `python main.py`로 실행할 때는 기존처럼 저장소 루트를 사용하며 별도 앱 데이터
복사는 수행하지 않습니다.

별도의 데이터 위치를 사용해야 한다면 EXE 실행 전에
`PROMPTCASE_STUDIO_DATA_DIR` 환경변수에 절대경로를 지정할 수 있습니다.
