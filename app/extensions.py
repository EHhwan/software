"""여러 파일에서 함께 쓰는 확장 객체. create_app() 에서 앱에 연결한다."""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
