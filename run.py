"""실행 파일.
- 내 노트북: python run.py → http://127.0.0.1:5000
- 배포(Render): gunicorn run:app (render.yaml 참고)
"""
import os

from app import create_app

app = create_app()

# 배포 서버(Render 무료)는 명령을 직접 실행할 수 없으므로, SEED_DEMO=1 이면 시작할 때 예시 데이터를 넣는다.
# 이미 있으면 건너뛰므로 재시작할 때마다 실행돼도 괜찮다.
if os.environ.get("SEED_DEMO") == "1":
    import seed_demo
    seed_demo.seed(app)

if __name__ == "__main__":
    app.run(debug=True)
