"""국내 중계(KR_PROXY_URL): 한국 사이트만 중계로 보내고, 중계로 안 되면 바로 접속한다 (울산판과 같은 방식)."""
from __future__ import annotations

import httpx
import pytest

from gia.collectors.base import HttpClient
from gia.logsafe import redact

PROXY = "http://myid:verylongpassword123@1.2.3.4:8888"


class _FakeClient:
    def __init__(self, name: str, calls: list, fail: dict | None = None):
        self.name, self.calls, self.fail = name, calls, fail or {}

    def get(self, url, **kw):
        self.calls.append((self.name, url))
        for key, exc in self.fail.items():
            if key in url:
                raise exc
        return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

    def close(self):
        pass


def _client(settings, calls, proxy_fail=None) -> HttpClient:
    settings.collector.respect_robots = False
    settings.collector.per_domain_delay_sec = 0
    c = HttpClient(settings.collector, kr_proxy=PROXY)
    c._client = _FakeClient("direct", calls)
    c._proxy_clients["verify"] = _FakeClient("proxy", calls, proxy_fail)
    return c


def test_korean_sites_go_through_proxy(settings):
    calls: list = []
    c = _client(settings, calls)
    c.get("https://www.jinju.go.kr/a")
    c.get("https://apis.data.go.kr/b")
    c.get("https://www.work24.go.kr/c")
    c.get("https://example.com/d")
    assert [n for n, _ in calls] == ["proxy", "proxy", "proxy", "direct"]  # .kr 이 아니면 중계하지 않는다


def test_site_refused_by_proxy_falls_back_to_direct(settings):
    calls: list = []
    c = _client(settings, calls, {"blocked.go.kr": httpx.ProxyError("403 Forbidden")})
    c.get("https://blocked.go.kr/1")
    c.get("https://blocked.go.kr/2")
    c.get("https://ok.go.kr/3")
    assert calls == [("proxy", "https://blocked.go.kr/1"), ("direct", "https://blocked.go.kr/1"),
                     ("direct", "https://blocked.go.kr/2"),  # 같은 실행에서는 그 사이트만 바로 접속
                     ("proxy", "https://ok.go.kr/3")]
    assert c.kr_proxy == PROXY


def test_proxy_auth_failure_disables_proxy(settings):
    calls: list = []
    c = _client(settings, calls, {"go.kr": httpx.ProxyError("407 Proxy Authentication Required")})
    c.get("https://a.go.kr/1")
    c.get("https://b.go.kr/2")
    assert [n for n, _ in calls] == ["proxy", "direct", "direct"] and c.kr_proxy is None


def test_proxy_down_disables_after_three_sites(settings):
    calls: list = []
    c = _client(settings, calls, {"go.kr": httpx.ConnectError("connection refused")})
    for h in ("a", "b", "c", "d"):
        c.get(f"https://{h}.go.kr/")
    assert [n for n, _ in calls] == ["proxy", "direct"] * 3 + ["direct"]
    assert c.kr_proxy is None


def test_no_proxy_without_env(settings, monkeypatch):
    monkeypatch.delenv("KR_PROXY_URL", raising=False)
    assert HttpClient(settings.collector).kr_proxy is None


def test_egress_note_hides_proxy_address(monkeypatch):
    monkeypatch.setenv("KR_PROXY_URL", PROXY)
    note = HttpClient.egress_note()
    assert "1.2.3.4" not in note and "myid" not in note and "KR_PROXY_URL" in note


def test_proxy_url_redacted_in_logs(monkeypatch):
    monkeypatch.setenv("KR_PROXY_URL", PROXY)
    out = redact(f"오류: {PROXY} 연결 실패")
    assert "verylongpassword123" not in out and "myid" not in out
