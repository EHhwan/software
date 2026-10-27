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

## 배포 (Render 무료 플랜)
1. render.com 에 GitHub 계정으로 로그인 → **New → Web Service** → 이 저장소 선택
2. 설정
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
3. **Environment** 에 환경변수 등록
   - `GEMINI_API_KEY`: AI Studio 에서 발급받은 키
   - `SECRET_KEY`: 아무 긴 임의 문자열 (세션·CSRF 보호용, 코드의 기본값을 쓰지 않기)
   - `KAKAO_JS_KEY`: 카카오 JavaScript 키 (카카오 콘솔에서 배포 주소 `https://xxx.onrender.com` 을 도메인에 추가)
4. 시간대는 `app.py` 가 한국 시간(Asia/Seoul)으로 고정하므로 따로 설정하지 않아도 된다.

주의: 무료 플랜은 디스크가 유지되지 않아 재배포·재시작 때 SQLite(`campus_fit.db`)의 글이 사라진다. 데모데이 직전에 시연용 글을 다시 만들어 둘 것.
