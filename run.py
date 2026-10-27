"""실행 파일.
- 내 노트북: python run.py → http://127.0.0.1:5000
- 배포(Render): gunicorn run:app
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
