# 🍳 레시피 믹스

내 레시피와 다른 사람의 레시피를 Gemini로 조합하고, 보유 재료에 맞게 레시피를 재구성하는 레시피 커뮤니티 (소프트웨어개발 3회차)

- 문서: [보고서](docs/보고서.md) ([docx](docs/보고서.docx)) · [AI 기능 설명](docs/AI기능설명.md) ([docx](docs/AI기능설명.docx)) · [검증 기록](docs/검증기록.md) · [요구사항](docs/요구사항.md)
- 배포 URL: https://recipe-mix-65dy.onrender.com/
- 기술 스택: Flask, Flask-Login, Flask-SQLAlchemy, Flask-WTF, Bootstrap 5, SQLite / PostgreSQL, Google Gemini API

## UI 시안

[화면 시안·이미지·실행 안내](docs/ui-proposal/README.md) · [시안 ZIP 다운로드](docs/ui-proposal/recipe-mix-preview.zip?raw=true)

변경 부분 형광펜 비교, 재료 자동완성, 카테고리·검색 필터 등을 확인할 수 있는 독립 시안입니다. 실제 Flask 앱에 적용하기 전 디자인 검토용입니다.

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
  main.py            레시피 둘러보기(검색·카테고리·필터·정렬), 마이페이지
  recipes.py         레시피 등록·수정·삭제·상세, 좋아요, 즐겨찾기, 공개 전환
  mix.py             AI 레시피 믹스, AI 결과 미리보기·비교·저장
  pantry.py          보유 재료 추천 (후보는 일반 코드, 대체·조정은 AI), 재료 자동완성
  public_recipes.py  공공 레시피 가져오기 (식품의약품안전처 조리식품의 레시피 DB → 우리 레시피 형식)
  ai.py              Gemini 프롬프트·호출·응답 검증 (서버에서만)
  services.py        권한 확인, 좋아요 집계, 레시피 저장, AI 호출 제한
  recipe_util.py     재료량 표시(4~5개, 1/2대), 폼 검증, 재료 이름 정리
  templates/         화면 (Bootstrap + docs/ui-proposal 시안 디자인)
  static/            style.css, app.js
seed_demo.py         시연용 예시 사용자·레시피 넣기
import_public_recipes.py  공공 레시피 직접 가져오기
tests/               테스트
docs/                요구사항, 검증 기록
instance/            SQLite DB 파일 (자동 생성, GitHub에 올라가지 않음)
```

## 간단 실행 (Windows)
프로젝트 폴더의 **`start.cmd` 를 더블클릭**하면 가상환경 확인 → 패키지 설치 → `.env` 확인 → 서버 실행 → 브라우저 열기까지 한 번에 된다. 끄려면 검은 창에서 `Ctrl + C`.

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

**시연용 예시 데이터:** `python seed_demo.py` → 예시 레시피 6개와 사용자 `jieun`, `minsu`, `soyeon`(비밀번호 `demo1234`)이 생긴다.
AI 믹스는 '내 레시피'와 '다른 사람의 공개 레시피'가 하나씩 있어야 하니, 예시 사용자로 로그인하거나 직접 레시피를 등록한 뒤 써 본다.

DB를 처음부터 다시 만들고 싶으면 서버를 끄고 `instance/recipe_mix.db` 를 지운 뒤 다시 실행한다.

## 공공 레시피 (식품안전나라 OpenAPI)
식품의약품안전처 **조리식품의 레시피 DB**(서비스 `COOKRCP01`, 약 1,100개)를 가져와 '공공 레시피'로 보여 준다.

- 인증키: 식품안전나라 → 공공데이터 → '조리식품의 레시피 DB' → 인증키 신청. `.env` 에 `FOODSAFETY_API_KEY=키` (GitHub 에 올리지 않음)
- 키가 있으면 서버를 켤 때 **공공 레시피가 하나도 없을 때만** 뒤에서 가져온다 (사이트는 그동안에도 사용 가능)
- 직접 가져오기: `python import_public_recipes.py` (시험: `--limit 20`, 원본 저장: `--save rows.json`). 이미 있는 레시피는 건너뛴다
- 재료 글('연두부 75g(3/4모), 소금 약간')을 이름·양·단위로 나누고, 괄호 안이 개·큰술 같은 단위면 그쪽을 쓴다
- 원본에 조리 시간이 없어 '시간 정보 없음'으로 표시하고, 대신 1회 제공량 영양 정보(열량·나트륨 등)를 보여 준다
- 최신순·인기순에서 같은 조건이면 커뮤니티 레시피를 먼저, 작성 방식 필터에서 '공공 레시피'만 볼 수 있다
- 보유 재료 추천의 후보, AI 레시피 믹스의 '다른 사람의 레시피'로 쓸 수 있다

## 배포 (Render)
`render.yaml` 에 웹 서비스·환경변수 설정이 들어 있어 Blueprint 로 만든다. DB는 만료 기간이 없는 **Neon(무료 PostgreSQL)** 을 쓴다.

1. render.com 에 **GitHub 계정으로 로그인**
2. 오른쪽 위 **New → Blueprint** → 이 저장소(`software`) 연결 → 브랜치 `ccr-51585c03-aolzd2` 선택
3. 화면에 나오는 `GEMINI_API_KEY` 칸에 AI Studio 키 입력 → **Apply** (나머지 SECRET_KEY·DB 주소는 자동)
4. 몇 분 뒤 `https://recipe-mix-xxxx.onrender.com` 주소로 접속

- 시작할 때 예시 레시피가 자동으로 들어간다(`SEED_DEMO=1`). 로그인: jieun / minsu / soyeon, 비밀번호 demo1234
- 코드를 `git push` 하면 Render 가 자동으로 다시 배포한다.
- 무료 플랜은 15분 동안 접속이 없으면 잠들어, 다음 첫 접속이 30~60초 걸린다. **데모데이에는 발표 전에 미리 한 번 열어 둔다.**
- 무료 PostgreSQL 은 일정 기간이 지나면 만료될 수 있다. Render 대시보드에서 만료일을 확인하고 데모데이와 겹치지 않게 한다.
- 로컬에서 PostgreSQL 로 테스트: `TEST_DATABASE_URL=postgresql://... python -m pytest tests -q`
