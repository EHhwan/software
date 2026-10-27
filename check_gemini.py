"""Gemini API 키가 제대로 설정됐는지 확인하는 스크립트.
실행: python check_gemini.py
"""
import os

from dotenv import load_dotenv

import ai

load_dotenv()

key = os.environ.get("GEMINI_API_KEY", "")
print("API 키:", f"{key[:6]}… (설정됨)" if key else "없음 - .env 파일을 확인하세요")
print("모델  :", os.environ.get("GEMINI_MODEL", ai.DEFAULT_MODEL))

try:
    print("응답  :", ai.ask("'연결 성공'이라고만 답해 줘.").strip())
    print("✅ Gemini 연결 성공")
except ai.AIUnavailable as e:
    print("❌ 연결 실패:", str(e)[:300])
    print("   - 키를 다시 복사해 .env 에 붙여 넣었는지")
    print("   - 모델명이 맞는지 (AI Studio 에서 확인 후 .env 에 GEMINI_MODEL=모델명)")
    print("   - 인터넷 연결")
