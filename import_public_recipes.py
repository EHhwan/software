"""공공 레시피 가져오기: python import_public_recipes.py

식품의약품안전처 '조리식품의 레시피 DB'(식품안전나라 OpenAPI)에서 레시피를 받아 DB 에 저장한다.
- .env 의 FOODSAFETY_API_KEY 를 쓴다.
- DB 는 run.py 와 같다: DATABASE_URL 이 없으면 내 PC 의 SQLite, 있으면 그 PostgreSQL(예: Neon).
- 이미 저장한 레시피는 건너뛰므로 여러 번 실행해도 된다.

옵션
  --limit 20          처음 20개만 (시험용)
  --save rows.json    받은 원본을 파일로 저장 (검증 기록·테스트용)
  --from-file rows.json  API 대신 저장해 둔 파일에서 가져오기
"""
import argparse
import json
import os
import sys

from app import create_app
from app.public_recipes import PublicAPIError, fetch_rows, import_rows, public_count


def main():
    parser = argparse.ArgumentParser(description="공공 레시피 가져오기")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--save")
    parser.add_argument("--from-file")
    args = parser.parse_args()

    if args.from_file:
        with open(args.from_file, encoding="utf-8") as f:
            rows = json.load(f)
    else:
        key = os.environ.get("FOODSAFETY_API_KEY", "").strip()
        if not key:
            sys.exit("FOODSAFETY_API_KEY 가 없어요. .env 파일에 FOODSAFETY_API_KEY=발급받은키 를 넣어 주세요.")
        print("식품안전나라에서 레시피를 받는 중…")
        try:
            rows = fetch_rows(key, args.limit)
        except PublicAPIError as e:
            sys.exit(str(e))
    print(f"받은 레시피 {len(rows)}개")
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"원본을 {args.save} 에 저장했어요.")

    app = create_app()  # create_app 이 .env 를 읽는다
    with app.app_context():
        added, skipped, bad = import_rows(rows[: args.limit] if args.limit else rows)
        print(f"저장 {added}개 · 이미 있어서 건너뜀 {skipped}개 · 재료나 조리 순서가 없어 뺌 {bad}개")
        print(f"지금 DB 의 공공 레시피: {public_count()}개")


if __name__ == "__main__":
    main()
