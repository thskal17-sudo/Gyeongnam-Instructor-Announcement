"""로그에서 API 인증키를 가린다.

httpx 는 요청마다 URL 전체를 INFO 로 남기는데, 공공데이터포털·워크넷은 인증키를 쿼리
(serviceKey=, authKey=)로 받는다. 공개 저장소의 Actions 로그와 probe-results 브랜치에
URL 인코딩된 키가 그대로 실렸다(2026-09-30). GitHub 의 비밀값 가리기는 등록한 문자열과
똑같을 때만 가리므로, %2B 로 바뀐 키는 걸러지지 않는다.
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import quote

_KEY_QUERY = re.compile(r"(?i)\b((?:service|auth)key=)[^&\s\"'<>]+")
SECRET_ENVS = ("DATA_GO_KR_KEY", "WORKNET_API_KEY")


def redact(text: str) -> str:
    text = _KEY_QUERY.sub(r"\1***", text)
    for name in SECRET_ENVS:
        v = (os.environ.get(name) or "").strip()
        if len(v) >= 8:
            for form in {v, quote(v, safe=""), quote(v)}:
                text = text.replace(form, "***")
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def install() -> None:
    """루트 핸들러 전부에 건다. 다른 모듈의 로거(httpx 등)도 루트 핸들러를 거친다."""
    for h in logging.getLogger().handlers:
        if not any(isinstance(f, RedactFilter) for f in h.filters):
            h.addFilter(RedactFilter())
