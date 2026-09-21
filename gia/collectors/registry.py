from __future__ import annotations

from datetime import date

from ..config import CollectorSettings, SourceConfig
from .api_json import ApiJsonAdapter
from .base import HttpClient, SourceAdapter, UnconfiguredSource
from .html_list import HtmlListAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    "api_json": ApiJsonAdapter,
    "html_list": HtmlListAdapter,
}


def build_adapter(cfg: SourceConfig, http: HttpClient, settings: CollectorSettings, since: date | None = None) -> SourceAdapter:
    reason = cfg.unconfigured_reason()
    if reason:
        raise UnconfiguredSource(reason)
    kind = cfg.adapter.get("type")
    cls = ADAPTERS.get(kind)
    if cls is None:
        raise UnconfiguredSource(f"지원하지 않는 adapter.type: {kind} (Phase 1은 api_json, html_list만 지원)")
    return cls(cfg, http, settings, since=since)
