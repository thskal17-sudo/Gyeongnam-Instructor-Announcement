"""국내 프록시로 나갈 때의 동작 (docs/SOURCE_VERIFICATION.md '국내 IP 로 수집하기').

지자체·대학 상당수가 GitHub 러너 IP 대역을 막는다. 프록시를 환경변수로 걸면 httpx 는
trust_env 로 알아서 쓰지만, 브라우저(playwright)는 안 본다. 그 두 길이 어긋나지 않는지와,
프록시 주소에 비밀번호가 들어와도 로그에 안 남는지를 잠근다.
"""
from __future__ import annotations

import pytest

from gia.collectors.base import HttpClient
from gia.collectors.playwright_list import proxy_config
from gia.logsafe import redact

PROXY_ENVS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch):
    for name in (*PROXY_ENVS, "NO_PROXY", "no_proxy", "KR_PROXY_URL"):
        monkeypatch.delenv(name, raising=False)


def test_egress_note_without_proxy():
    assert HttpClient.egress_note() == "러너 IP 직접"


def test_proxy_config_without_proxy():
    assert proxy_config() is None


@pytest.mark.parametrize("name", PROXY_ENVS)
def test_egress_note_names_proxy_host(monkeypatch, name):
    monkeypatch.setenv(name, "http://proxy.example.kr:3128")
    note = HttpClient.egress_note()
    assert "proxy.example.kr" in note and "3128" in note


def test_proxy_config_adds_scheme_when_missing(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "proxy.example.kr:3128")
    assert proxy_config()["server"] == "http://proxy.example.kr:3128"


def test_proxy_config_carries_no_proxy_as_bypass(monkeypatch):
    """브라우저는 NO_PROXY 를 안 지킨다. 넘겨 주지 않으면 127.0.0.1 까지 프록시를 탄다."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.kr:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,github.com")
    assert proxy_config()["bypass"] == "localhost,127.0.0.1,github.com"


def test_proxy_config_omits_bypass_when_unset(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.kr:3128")
    assert "bypass" not in proxy_config()


def test_egress_note_hides_password(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://me:s3cret@proxy.example.kr:3128")
    note = HttpClient.egress_note()
    assert "s3cret" not in note and "me" not in note.split("://")[1].split(":")[0]
    assert "proxy.example.kr" in note


def test_redact_hides_proxy_credentials():
    line = "요청 실패: http://me:s3cret@proxy.example.kr:3128 로 보냈다"
    out = redact(line)
    assert "s3cret" not in out
    assert "proxy.example.kr" in out  # 호스트는 남아야 원인을 본다


def test_httpx_client_trusts_env_proxy(monkeypatch):
    """프록시 지원은 httpx 의 trust_env 에 기대고 있다. 기본값이 바뀌면 조용히 안 타게 된다."""
    import httpx

    assert httpx.Client().trust_env is True
