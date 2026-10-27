"""입력 폼과 검증 규칙. 화면(HTML)의 제한은 쉽게 우회되므로 서버에서 다시 검사한다."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length, Regexp, ValidationError

from .extensions import db
from .models import User


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _strip_lower(value):
    return value.strip().lower() if isinstance(value, str) else value


class RegisterForm(FlaskForm):
    username = StringField("아이디", filters=[_strip_lower], validators=[
        DataRequired("아이디를 입력해 주세요."),
        Regexp(r"^[a-z0-9_]{4,20}$", message="아이디는 영어 소문자·숫자·_(밑줄)로 4~20자예요."),
    ])
    nickname = StringField("닉네임", filters=[_strip], validators=[
        DataRequired("닉네임을 입력해 주세요."),
        Length(2, 12, message="닉네임은 2~12자예요."),
    ])
    password = PasswordField("비밀번호", validators=[
        DataRequired("비밀번호를 입력해 주세요."),
        Length(8, 64, message="비밀번호는 8~64자예요."),
    ])
    password2 = PasswordField("비밀번호 확인", validators=[
        DataRequired("비밀번호를 한 번 더 입력해 주세요."),
        EqualTo("password", message="비밀번호가 서로 달라요."),
    ])
    submit = SubmitField("가입하기")

    def validate_username(self, field):
        if db.session.scalar(db.select(User.id).filter_by(username=field.data)):
            raise ValidationError("이미 사용 중인 아이디예요.")

    def validate_nickname(self, field):
        if db.session.scalar(db.select(User.id).filter_by(nickname=field.data)):
            raise ValidationError("이미 사용 중인 닉네임이에요.")


class LoginForm(FlaskForm):
    username = StringField("아이디", filters=[_strip_lower], validators=[DataRequired("아이디를 입력해 주세요.")])
    password = PasswordField("비밀번호", validators=[DataRequired("비밀번호를 입력해 주세요.")])
    remember = BooleanField("로그인 유지")
    submit = SubmitField("로그인")
