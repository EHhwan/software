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
    with app.app_context():
        from app.extensions import db
        db.session.remove()
        db.engine.dispose()  # 예시 데이터를 넣느라 연 DB 연결도 닫고 요청은 새 연결로 시작

# 공공 레시피(식품의약품안전처 API): 인증키가 있고 아직 한 번도 가져오지 않았으면, 서버를 켤 때 뒤에서(별도 스레드) 가져온다.
# 1,000개가 넘어 몇십 초 걸리므로 그동안에도 사이트는 바로 쓸 수 있게 한다. 직접 가져오려면 python import_public_recipes.py
# (python run.py 는 코드가 바뀌면 다시 켜지는 감시 프로세스가 하나 더 있어서, 실제 서버 프로세스에서만 실행한다)
if os.environ.get("FOODSAFETY_API_KEY") and (__name__ != "__main__" or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
    import threading

    from app.public_recipes import import_public_in_background
    threading.Thread(target=import_public_in_background, args=(app, os.environ["FOODSAFETY_API_KEY"]), daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)
