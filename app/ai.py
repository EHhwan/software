"""Gemini API 연결. 서비스의 AI 호출은 모두 이 파일을 거치고, 반드시 Flask 서버에서만 실행된다.
(API 키가 브라우저로 내려가지 않도록 화면의 JavaScript 에서는 Gemini 를 직접 부르지 않는다)

레시피 믹스(4차)와 보유 재료 추천(5차)의 프롬프트·응답 검증은 이후 단계에서 이 파일에 추가한다.
"""
import os

DEFAULT_MODEL = "gemini-3.6-flash"  # gemini-2.0-flash 는 서비스 종료됨. 모델명이 바뀌면 .env 의 GEMINI_MODEL 로 바꾼다
TIMEOUT_SEC = 30                    # 레시피 생성은 답이 길어 시간이 걸린다

_model = None


class AIUnavailable(Exception):
    """API 키가 없거나, 응답이 없거나, 사용량 제한에 걸렸을 때. 화면에서는 이 예외를 잡아 안내 문구를 보여 준다."""


def _get_model():
    global _model
    if _model is None:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise AIUnavailable("GEMINI_API_KEY 가 설정되지 않았어요. .env 파일을 확인해 주세요.")
        import google.generativeai as genai
        genai.configure(api_key=key)
        _model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
    return _model


def ask(prompt, **generation_config):
    """프롬프트 하나를 보내고 응답 텍스트를 돌려준다. 실패하면 AIUnavailable."""
    try:
        res = _get_model().generate_content(
            prompt,
            generation_config=generation_config or None,
            request_options={"timeout": TIMEOUT_SEC},
        )
        return res.text
    except AIUnavailable:
        raise
    except Exception as e:  # 네트워크 오류, 시간 초과, 사용량 제한(429), 안전 차단 등
        raise AIUnavailable(str(e)) from e
