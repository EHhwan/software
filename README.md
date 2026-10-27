# 🍳 레시피 믹스

내 레시피와 다른 사람의 레시피를 Gemini로 조합하고, 보유 재료에 맞게 레시피를 재구성하는 레시피 커뮤니티 (소프트웨어개발 3회차)

- 요구사항: [docs/요구사항.md](docs/요구사항.md) · 검증 기록: [docs/검증기록.md](docs/검증기록.md)
- 기술 스택: Flask, Flask-Login, Flask-SQLAlchemy, Flask-WTF, Bootstrap 5, SQLite / PostgreSQL, Google Gemini API

## 폴더 구조
```
run.py               실행 파일 (python run.py / gunicorn run:app)
check_gemini.py      Gemini API 키 연결 확인
app/
  __init__.py        앱 만들기 (설정, DB, 로그인, 오류 페이지)
  config.py          환경변수 설정, DB 주소 (SQLite ↔ PostgreSQL)
  models.py          테이블: 사용자, 레시피, 재료, 조리 순서, 좋아요, 출처
  forms.py           회원가입·로그인 입력 검증
  auth.py            회원가입, 로그인, 로그아웃
  main.py            메인, 마이페이지
  ai.py              Gemini 호출 (서버에서만)
  templates/         화면 (Bootstrap)
  static/            CSS, JS
tests/               테스트
docs/                요구사항, 검증 기록
instance/            SQLite DB 파일 (자동 생성, GitHub에 올라가지 않음)
```

## 내 노트북에서 처음 설정하기 (Windows)
1. 설치: Python 3.12 이상(설치할 때 "Add python.exe to PATH" 체크), Git, VS Code(+ Python 확장)
2. 코드 받기
   ```
   git clone -b ccr-51585c03-aolzd2 https://github.com/EHhwan/software.git recipe-mix
   cd recipe-mix
   ```
3. 가상환경 만들고 패키지 설치
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
   "스크립트를 실행할 수 없습니다" 오류가 나면 한 번만 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
4. `.env.example` 을 복사해 이름을 `.env` 로 바꾸고 `GEMINI_API_KEY`, `SECRET_KEY` 입력
5. 연결 확인: `python check_gemini.py` → "✅ Gemini 연결 성공"
6. 실행: `python run.py` → http://127.0.0.1:5000
7. 테스트: `python -m pytest tests -q`

DB를 처음부터 다시 만들고 싶으면 서버를 끄고 `instance/recipe_mix.db` 를 지운 뒤 다시 실행한다.

## 배포 (6차, Render)
1. Render 에서 **PostgreSQL** 을 만들고 Internal Database URL 을 복사
2. **Web Service** 생성 → 이 저장소 선택
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn run:app`
3. Environment: `GEMINI_API_KEY`, `SECRET_KEY`(긴 임의 문자열), `DATABASE_URL`(1번에서 복사한 주소)

- `postgres://` 형식 주소도 `app/config.py` 가 알아서 바꿔 준다.
- gunicorn 은 Windows 에서 실행되지 않는다. 내 노트북에서는 `python run.py` 를 쓴다.
- Render 무료 PostgreSQL 은 일정 기간 뒤 만료될 수 있으니 데모데이 날짜에 맞춰 확인한다.
