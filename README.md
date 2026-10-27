# 캠퍼스 핏 (Campus Fit)

대학생 실시간 캠퍼스 번개 매칭 서비스 · Flask + Jinja2 + SQLite

## 3회차: ✨ 한 줄로 번개 만들기 (Gemini)
말하듯 한 줄 적으면 Gemini가 작성 폼을 채워 준다. 자세한 설명: [docs/AI_기능_설명.md](docs/AI_기능_설명.md)

### 실행 방법
1. `templates/new.html`의 작성 폼 위에 `{% include "_ai_draft.html" %}`가 이미 들어가 있다.
2. 패키지를 설치한다: `pip install -r requirements.txt`
3. `.env.example`을 복사해 `.env`로 이름을 바꾸고 Gemini API 키를 넣는다. (`.env`는 `.gitignore`에 있어서 GitHub에 올라가지 않는다)
4. 실행: `python app.py`, 테스트: `python -m pytest tests -q`

배포 서버에서는 `.env` 대신 환경변수 `GEMINI_API_KEY`를 직접 등록해야 한다.
