"""데이터 모델: 사용자, 레시피(재료·조리 순서), 좋아요, 즐겨찾기, AI 레시피 출처, AI 결과 임시 보관."""
import json
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    """DB 에는 UTC(시간대 정보 없이)로 저장하고, 화면에서 |kst 필터로 한국 시간으로 바꿔 보여 준다."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False, index=True)  # 로그인 아이디 (소문자로 저장)
    nickname = db.Column(db.String(12), unique=True, nullable=False)             # 레시피 작성자로 표시되는 이름
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    recipes = db.relationship("Recipe", back_populates="author", cascade="all, delete-orphan",
                              order_by="Recipe.created_at.desc()")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)  # 비밀번호 원문은 저장하지 않는다

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


CATEGORIES = ["밥·덮밥·볶음밥", "면", "국·탕·찌개", "반찬", "구이·찜·볶음", "샐러드", "간식·디저트", "기타"]


class Recipe(db.Model):
    __tablename__ = "recipes"

    ORIGINS = ("user", "ai_mix", "ai_pantry")  # 직접 작성 / AI 레시피 믹스 / AI 보유 재료 추천
    ORIGIN_LABEL = {"user": "직접 작성", "ai_mix": "AI 조합", "ai_pantry": "AI 재료 맞춤"}

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(60), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    category = db.Column(db.String(20), nullable=False, default="기타", index=True)
    servings = db.Column(db.Integer, nullable=False)          # 인분
    cook_time_min = db.Column(db.Integer, nullable=False)     # 조리 시간(분)
    origin = db.Column(db.String(20), nullable=False, default="user")
    ai_note = db.Column(db.Text)                              # AI 결과의 '달라진 점·변경 이유' 등 (JSON 문자열, 4차)
    is_public = db.Column(db.Boolean, nullable=False, default=True)  # AI 결과는 비공개로 저장했다가 공개할 수 있다
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    author = db.relationship("User", back_populates="recipes")
    ingredients = db.relationship("Ingredient", back_populates="recipe", cascade="all, delete-orphan",
                                  order_by="Ingredient.position", passive_deletes=True)
    steps = db.relationship("Step", back_populates="recipe", cascade="all, delete-orphan",
                            order_by="Step.number", passive_deletes=True)
    likes = db.relationship("Like", back_populates="recipe", cascade="all, delete-orphan", passive_deletes=True)
    # 이 레시피가 AI 로 만들어졌다면, 재료가 된 원본 레시피들
    sources = db.relationship("RecipeSource", foreign_keys="RecipeSource.recipe_id", back_populates="recipe",
                              cascade="all, delete-orphan", order_by="RecipeSource.position", passive_deletes=True)

    @property
    def is_ai(self):
        return self.origin != "user"

    @property
    def origin_label(self):
        return self.ORIGIN_LABEL.get(self.origin, "직접 작성")

    @property
    def ai_info(self):
        """AI 결과의 특징·달라진 점·변경 이유 (ai_note JSON). 직접 작성한 레시피는 빈 dict."""
        try:
            return json.loads(self.ai_note) if self.ai_note else {}
        except ValueError:
            return {}


class Ingredient(db.Model):
    __tablename__ = "ingredients"

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)    # 화면에 보이는 순서
    name = db.Column(db.String(40), nullable=False)
    quantity = db.Column(db.Float)                      # '약간', '적당량' 처럼 수치가 없으면 비워 둔다
    unit = db.Column(db.String(20), nullable=False, default="")  # g, ml, 큰술, 개, 약간 ...

    recipe = db.relationship("Recipe", back_populates="ingredients")


class Step(db.Model):
    __tablename__ = "steps"
    __table_args__ = (db.UniqueConstraint("recipe_id", "number"),)

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    number = db.Column(db.Integer, nullable=False)      # 1, 2, 3 ... 조리 순서
    content = db.Column(db.Text, nullable=False)

    recipe = db.relationship("Recipe", back_populates="steps")


class Like(db.Model):
    """(사용자, 레시피) 조합이 기본키라 같은 사용자는 한 레시피에 좋아요를 한 번만 누를 수 있다."""
    __tablename__ = "likes"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    recipe = db.relationship("Recipe", back_populates="likes")


class RecipeSource(db.Model):
    """AI 로 만든 레시피 ↔ 원본 레시피 출처 관계.

    원본이 나중에 삭제돼도 '어떤 레시피에서 왔는지' 표시할 수 있도록 제목·작성자를 함께 기록해 둔다.
    """
    __tablename__ = "recipe_sources"
    __table_args__ = (db.UniqueConstraint("recipe_id", "position"),)

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    source_recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="SET NULL"), index=True)
    position = db.Column(db.Integer, nullable=False)    # 1 = 내 레시피, 2 = 다른 사용자의 레시피
    source_title = db.Column(db.String(60), nullable=False)
    source_author = db.Column(db.String(12), nullable=False)

    recipe = db.relationship("Recipe", foreign_keys=[recipe_id], back_populates="sources")
    source_recipe = db.relationship("Recipe", foreign_keys=[source_recipe_id])


class Bookmark(db.Model):
    """즐겨찾기. 좋아요(공개 인기 지표)와 달리 나만 보는 '다시 만들고 싶은 레시피' 목록."""
    __tablename__ = "bookmarks"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class AIDraft(db.Model):
    """저장 전 AI 결과. 사용자가 확인·수정한 뒤 레시피로 저장하면 Recipe 가 만들어진다."""
    __tablename__ = "ai_drafts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)          # "ai_mix" / "ai_pantry" (= 저장될 레시피의 origin)
    payload = db.Column(db.Text, nullable=False)              # 검증을 통과한 AI 결과 (JSON)
    sources = db.Column(db.Text, nullable=False, default="[]")  # [{id, title, author}, ...] 원본 레시피
    goal = db.Column(db.Text, nullable=False, default="")    # 조합 목표 · 보유 재료 등 요청 내용
    saved_recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @property
    def data(self):
        return json.loads(self.payload)

    @property
    def source_list(self):
        return json.loads(self.sources or "[]")


class AICall(db.Model):
    """AI 호출 기록 (사용자별 분당 횟수 제한용). 무료 사용량을 한 사람이 다 쓰지 않게 한다."""
    __tablename__ = "ai_calls"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
