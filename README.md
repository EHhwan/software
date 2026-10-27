# 📢 공지핏

나에게 해당되는 학교 공지만 골라 3줄 요약과 마감일로 알려 주는 AI 비서 (소프트웨어개발 3회차)

- 기술 스택: Flask, SQLite, Jinja2, Tailwind CSS, Google Gemini API
- 기획: [docs/기획서.md](docs/기획서.md) · 검증 기록: [docs/검증기록.md](docs/검증기록.md)

## 폴더 구조
```
app.py            Flask 앱 (라우트, DB)
ai.py             Gemini 연결 (모든 AI 호출은 ai.ask() 를 거친다)
check_gemini.py   API 키 연결 확인용
templates/        화면 (base.html 공통 틀)
static/           이미지, CSS, JS
tests/            테스트
docs/             기획서, 검증 기록
```

## 내 PC에서 처음 설정하기 (Windows)
1. 코드 받기
   ```
   git clone -b ccr-51585c03-aolzd2 https://github.com/EHhwan/software.git notice-fit
   cd notice-fit
   ```
2. 가상환경 만들고 켜기 (프로젝트마다 패키지를 따로 관리)
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
   PowerShell 에서 "스크립트를 실행할 수 없습니다" 오류가 나면 한 번만:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 입력 후 다시 실행
3. 패키지 설치: `pip install -r requirements.txt`
4. `.env.example` 을 복사해 이름을 `.env` 로 바꾸고 AI Studio 에서 받은 키를 넣는다.
5. 연결 확인: `python check_gemini.py` → "✅ Gemini 연결 성공"
6. 실행: `python app.py` → 브라우저에서 http://127.0.0.1:5000
7. 테스트: `python -m pytest tests -q`

`venv/` 와 `.env` 는 `.gitignore` 에 있어서 GitHub 에 올라가지 않는다.

## 배포 (13주차, Render 무료 플랜)
1. render.com 에 GitHub 계정으로 로그인 → **New → Web Service** → 이 저장소 선택
2. Build Command: `pip install -r requirements.txt` / Start Command: `gunicorn app:app`
3. Environment 에 `GEMINI_API_KEY`, `SECRET_KEY`(아무 긴 문자열), 필요하면 `GEMINI_MODEL` 등록
4. 시간대는 `app.py` 가 한국 시간으로 고정한다.

주의: 무료 플랜은 재시작·재배포 때 SQLite 파일이 초기화된다.
