# 단일 EXE 패키징

Promptcase Studio는 PyInstaller의 one-file 모드로 `PromptcaseStudio.exe` 하나를 배포할 수 있습니다.
빌드 결과에는 앱 실행에 필요한 공개 리소스만 들어가며 `.env`와 로컬 설정 파일은 포함하지 않습니다.

## 빌드

Windows에서 저장소 루트의 `build-exe.bat`을 실행합니다.

```powershell
.\build-exe.bat
```

완료된 파일은 `dist\PromptcaseStudio.exe`입니다. 빌드 스크립트는
`requirements-build.txt`의 PyInstaller를 설치하고 `promptcase-studio.spec`으로 one-file 빌드를 수행합니다.

## 번들 리소스

다음 파일은 EXE 내부의 읽기 전용 기본 리소스로 포함됩니다.

- `config/app.settings.json`
- `config/qwen.settings.json`
- `prompts/`
- `schemas/`
- `templates/`
- `favicon.ico`

`.env`, `config/app.settings.local.json`, `runs/`, `outputs/`는 번들에 포함되지 않습니다.

## 최초 실행과 사용자 데이터

EXE를 처음 실행하면 다음 폴더를 자동으로 준비합니다.

```text
%LOCALAPPDATA%\Promptcase Studio\
├─ config\
├─ prompts\
├─ schemas\
├─ templates\
├─ runs\
├─ outputs\
└─ .env                 사용자가 API 키를 저장한 뒤에만 생성
```

앱 설정, 프롬프트, 스키마, 템플릿과 아이콘은 파일 해시가 기록된 관리 리소스로 복사됩니다.
사용자가 수정하지 않은 기본 파일은 새 EXE의 버전으로 자동 갱신되고, 사용자가 수정한 파일은
그대로 유지됩니다. 이전 버전처럼 해시 기록이 없는 설치는 기존 파일을 `backups/`에 보관한 뒤
새 기본 리소스로 한 번 마이그레이션합니다. Qwen 연결 설정은 최초 한 번만 복사하고 이후에는
사용자 값을 덮어쓰지 않으며, 누락된 300초 제한시간만 보완합니다.

실행 시 `config/app.settings.json`을 기본값으로 읽고 `config/app.settings.local.json`을 사용자
재정의 값으로 병합합니다. 관리 리소스 상태는 `config/.bundled-resources.json`에 저장됩니다.

개발 모드에서 `python main.py`로 실행할 때는 기존처럼 저장소 루트를 사용하며 별도 앱 데이터
복사는 수행하지 않습니다.

테스트나 포터블 배치에서 사용자 데이터 위치를 바꿔야 한다면 EXE 실행 전에
`PROMPTCASE_STUDIO_DATA_DIR` 환경변수에 절대경로를 지정할 수 있습니다.
