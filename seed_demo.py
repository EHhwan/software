"""시연용 예시 데이터 넣기: python seed_demo.py

예시 사용자 3명(비밀번호는 모두 demo1234)과 레시피 6개를 넣는다. 이미 있으면 건너뛴다.
배포 서버의 DB는 재시작하면 비워질 수 있으니 데모데이 전에 한 번 실행해 둔다.
"""
from app import create_app
from app.extensions import db
from app.models import Like, Recipe, User
from app.services import apply_recipe_data

USERS = [("jieun", "지은"), ("minsu", "민수"), ("soyeon", "소연")]

RECIPES = [
    ("jieun", "김치볶음밥", "밥·덮밥·볶음밥", "잘 익은 김치와 대파로 만드는 간단한 한 끼.", 2, 20,
     [("밥", 2, "공기"), ("김치", 200, "g"), ("대파", 0.5, "대"), ("식용유", 1, "큰술"), ("간장", 1, "작은술")],
     ["김치와 대파를 먹기 좋은 크기로 썹니다.", "팬에 식용유를 두르고 대파를 볶아 향을 냅니다.",
      "김치를 넣고 볶은 뒤 밥을 넣어 고루 섞습니다.", "간장을 넣고 볶아 마무리합니다."]),
    ("minsu", "버섯 크림 리소토", "밥·덮밥·볶음밥", "버섯의 풍미를 우유와 치즈로 부드럽게.", 2, 25,
     [("밥", 2, "공기"), ("버섯", 100, "g"), ("우유", 200, "ml"), ("치즈", 30, "g"), ("소금", 0.5, "작은술")],
     ["버섯을 썰어 준비합니다.", "버섯을 먼저 볶아 수분을 날립니다.", "밥과 우유를 넣고 약불에서 부드럽게 익힙니다.",
      "치즈와 소금으로 간을 맞춰 마무리합니다."]),
    ("soyeon", "토마토 달걀볶음", "반찬", "달걀과 토마토로 가볍게 완성하는 반찬.", 2, 15,
     [("토마토", 2, "개"), ("달걀", 3, "개"), ("식용유", 1, "큰술"), ("소금", None, "약간")],
     ["토마토를 썰고 달걀을 풀어 둡니다.", "달걀을 먼저 볶아 따로 덜어 둡니다.", "토마토를 볶은 뒤 달걀을 넣고 섞습니다.",
      "소금으로 간을 맞춰 마무리합니다."]),
    ("minsu", "대파 달걀 덮밥", "밥·덮밥·볶음밥", "대파의 향을 살린 따뜻한 한 그릇.", 2, 15,
     [("밥", 2, "공기"), ("달걀", 3, "개"), ("대파", 1, "대"), ("간장", 1, "큰술"), ("식용유", 1, "큰술")],
     ["대파를 썰고 달걀을 풀어 둡니다.", "팬에 대파를 볶아 향을 냅니다.", "달걀을 넣고 익힌 뒤 간장을 더합니다.",
      "밥 위에 올려 마무리합니다."]),
    ("jieun", "들기름 비빔국수", "면", "간단한 양념으로 고소하게 비벼 먹는 국수.", 2, 10,
     [("국수", 200, "g"), ("들기름", 2, "큰술"), ("간장", 1, "큰술"), ("김", 1, "장")],
     ["물을 끓여 국수를 삶습니다.", "국수를 찬물에 헹궈 물기를 뺍니다.", "들기름과 간장을 넣고 고루 비빕니다.",
      "김을 잘라 올려 마무리합니다."]),
    ("soyeon", "감자 양파 수프", "국·탕·찌개", "감자와 양파를 우유로 부드럽게 끓인 수프.", 2, 30,
     [("감자", 2, "개"), ("양파", 1, "개"), ("우유", 300, "ml"), ("버터", 10, "g"), ("소금", None, "약간")],
     ["감자와 양파를 얇게 썹니다.", "버터에 양파를 볶다가 감자를 넣습니다.", "우유를 붓고 감자가 익을 때까지 끓입니다.",
      "곱게 갈아 소금으로 간을 맞춥니다."]),
]

LIKES = {"김치볶음밥": ["minsu", "soyeon"], "버섯 크림 리소토": ["jieun", "soyeon"], "들기름 비빔국수": ["minsu"]}


def main():
    app = create_app()
    with app.app_context():
        users = {}
        for username, nickname in USERS:
            u = db.session.scalar(db.select(User).filter_by(username=username))
            if not u:
                u = User(username=username, nickname=nickname)
                u.set_password("demo1234")
                db.session.add(u)
            users[username] = u
        db.session.flush()
        added = 0
        for username, title, category, desc, servings, minutes, items, steps in RECIPES:
            if db.session.scalar(db.select(Recipe.id).filter_by(title=title, author_id=users[username].id)):
                continue
            recipe = Recipe(author=users[username], origin="user")
            apply_recipe_data(recipe, {
                "title": title, "description": desc, "category": category, "servings": servings, "cook_time_min": minutes,
                "is_public": True, "steps": steps,
                "ingredients": [{"name": n, "quantity": q, "unit": unit} for n, q, unit in items],
            })
            db.session.add(recipe)
            added += 1
        db.session.flush()
        for title, likers in LIKES.items():
            r = db.session.scalar(db.select(Recipe).filter_by(title=title))
            for name in likers:
                if r and not db.session.get(Like, (users[name].id, r.id)):
                    db.session.add(Like(user_id=users[name].id, recipe_id=r.id))
        db.session.commit()
        print(f"예시 레시피 {added}개를 넣었어요. 로그인: jieun / minsu / soyeon (비밀번호 demo1234)")


if __name__ == "__main__":
    main()
