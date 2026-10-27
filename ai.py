"""Gemini API 연결 모듈. 서비스의 AI 기능은 모두 이 파일의 ask() 를 거쳐 호출한다.

AI 기능 자체(프롬프트 설계, 응답 검증)는 12주차에 이 파일에 추가한다.
"""
import os

DEFAULT_MODEL = "gemini-2.0-flash"  # 안내문 예제 기준. AI Studio 에서 지금 쓸 수 있는 모델명을 확인해 .env 의 GEMINI_MODEL 로 바꾼다
TIMEOUT_SEC = 10

_model = None


class AIUnavailable(Exception):
    """API 키가 없거나, 응답이 없거나, 오류가 났을 때. 화면에서는 이 예외를 잡아 안내 문구를 보여 준다."""


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
    except Exception as e:  # 네트워크 오류, 시간 초과, 할당량 초과, 안전 차단 등
        raise AIUnavailable(str(e)) from e
