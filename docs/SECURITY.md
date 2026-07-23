# 보안 원칙

- Gemini/Qwen API 키를 소스, 프롬프트, run artifact, 콘솔 로그에 기록하지 않는다.
- 실제 키는 OS 환경변수 또는 Git에서 제외된 `.env`에 둔다.
- Qwen 기본 `config/qwen.settings.json`은 공개 가능한 연결 설정으로 관리하고 실제 인증값이 필요할 때만 환경변수 또는 `.env`에 둔다.
- `.env*`, key/pem, credential/secret 이름의 파일과 reparse point는 스캔 컨텍스트에서 제외한다.
- 포함 가능한 소스뿐 아니라 개발 의뢰와 사용자 변경 요약의 API 키, access token, password, Bearer 값은 전송 전 `[REDACTED]`로 치환한다.
- 생성 전송 목록은 확인할 수 있지만 secret 파일 내용은 표시하거나 전송하지 않는다.
- `runs/`에는 소스 excerpt와 AI 응답이 포함될 수 있으므로 Git에서 제외하고 공유 전 검토한다.
- GUI의 API 키는 사용자가 값을 확인하고 편집할 수 있도록 평문으로 표시하되 저장 위치는 Git에서 제외된 `.env`로만 제한한다.
- `.env`는 개발 PC에 존재할 수 있지만 Git index에는 추가하지 않는다. 공유할 때는 값이 빈 `.env.example`만 사용한다.
