"""로그에 인증키가 남지 않는다 (probe 출력에 serviceKey 가 실렸다, 2026-09-30)."""
import logging

from gia import logsafe


def test_redacts_key_query_in_any_encoding(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_KEY", "ab+cd/ef==XYZ")
    line = ('GET https://apis.data.go.kr/x/list?serviceKey=ab%2Bcd%2Fef%3D%3DXYZ&resultType=json&pageNo=1 '
            '"HTTP/1.1 200 OK"')
    out = logsafe.redact(line)
    assert "ab%2Bcd" not in out and "serviceKey=***&resultType=json" in out
    assert logsafe.redact("authKey=RAWKEY123&x=1") == "authKey=***&x=1"
    assert "ab+cd/ef==XYZ" not in logsafe.redact("echo ab+cd/ef==XYZ")


def test_filter_applies_to_other_libraries_loggers(monkeypatch, capsys):
    """httpx 처럼 %s 인자로 URL 을 넘기는 로거도 가려진다."""
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    try:
        logsafe.install()
        logging.getLogger("httpx").warning("HTTP Request: %s %s", "GET", "https://a.kr/l?serviceKey=SECRET99&p=1")
    finally:
        root.removeHandler(handler)
    err = capsys.readouterr().err
    assert "SECRET99" not in err and "serviceKey=***" in err
