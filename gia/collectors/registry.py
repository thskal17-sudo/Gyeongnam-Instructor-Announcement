from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from ..config import CollectorSettings, SourceConfig
from .api_json import ApiJsonAdapter
from .base import HttpClient, SourceAdapter, UnconfiguredSource
from .html_list import HtmlListAdapter
from .playwright_list import PlaywrightListAdapter
from .relay import RelayAdapter
from .search_portal import SearchPortalAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    "api_json": ApiJsonAdapter,
    "html_list": HtmlListAdapter,
    "playwright": PlaywrightListAdapter,
    "search_portal": SearchPortalAdapter,
}


def build_adapter(cfg: SourceConfig, http: HttpClient, settings: CollectorSettings, since: date | None = None,
                  relay: dict[str, Any] | None = None, use_relay: bool = False,
                  now: datetime | None = None) -> SourceAdapter:
    """use_relay=True 면 korea_only 소스는 사이트 대신 한국 PC 기록(relay)을 읽는다 (GitHub 수집)."""
    reason = cfg.unconfigured_reason()
    if reason:
        raise UnconfiguredSource(reason)
    if cfg.korea_only and use_relay:
        return RelayAdapter(cfg, http, settings, since=since, relay=relay, now=now)
    kind = cfg.adapter.get("type")
    cls = ADAPTERS.get(kind)
    if cls is None:
        raise UnconfiguredSource(f"지원하지 않는 adapter.type: {kind} (지원: api_json, html_list, playwright, search_portal)")
    if cfg.adapter.get("tls_legacy") is True:
        for host in insecure_hosts(cfg):
            http.set_tls_mode(host, "legacy")
    elif cfg.adapter.get("tls_verify") is False:
        for host in insecure_hosts(cfg):
            http.set_tls_mode(host, "insecure")
    if cfg.adapter.get("timeout_sec") or cfg.adapter.get("retries"):
        for host in insecure_hosts(cfg):  # 이름과 달리 소스의 URL 호스트 전부를 모은다
            http.set_host_policy(host, cfg.adapter.get("timeout_sec"), cfg.adapter.get("retries"))
    return cls(cfg, http, settings, since=since)


def insecure_hosts(cfg: SourceConfig) -> list[str]:
    """adapter.tls_verify: false / tls_legacy: true 인 소스의 URL 값(list_url, endpoint, link_url_template 등)에서 호스트를 모은다."""
    hosts: list[str] = []
    for v in cfg.adapter.values():
        if isinstance(v, str) and v.startswith("http"):
            host = urlsplit(v).netloc.lower()
            if host and host not in hosts:
                hosts.append(host)
    return hosts
