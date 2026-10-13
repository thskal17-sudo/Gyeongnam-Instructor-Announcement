"""한국 PC 에서 해외 차단 사이트(korea_only)를 읽어 중계 기록(relay.json)을 만든다.

한국 PC 의 GitHub 자체 실행기(라벨 korea, .github/workflows/korea.yml)가 `gia korea-export` 로 돌린다.
목록과 상세, 첨부 글까지 여기서 읽어 둔다 — GitHub 수집은 그 사이트에 닿지 못하기 때문이다.
판별·중복 정리·저장은 하지 않는다. 그 일은 GitHub 수집이 이 기록을 받아서 한다(collectors/relay.py).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from .collectors.base import HttpClient
from .collectors.registry import build_adapter
from .config import ConfigBundle
from .normalize import mask_pii
from .pipeline import enrich_attachments

log = logging.getLogger("gia.korea")


def korea_sources(bundle: ConfigBundle, only: list[str] | None = None):
    if only is not None:
        return [s for s in bundle.sources if s.id in only]
    return [s for s in bundle.sources if s.korea_only and s.enabled]


def export_relay(bundle: ConfigBundle, http: HttpClient, now: datetime, since: date,
                 prev: dict[str, Any] | None = None, only: list[str] | None = None) -> dict[str, Any]:
    """korea_only 소스를 읽어 relay 사전을 만든다.

    prev(지난번 기록)에 있던 글은 상세를 다시 열지 않고 그대로 옮긴다. 하루 두 번 도는데
    게시판마다 같은 글 상세를 매번 여는 것은 상대 서버에 부담이다.
    """
    cs = bundle.settings.collector
    prev_items: dict[str, dict] = {}
    for sid, entry in ((prev or {}).get("sources") or {}).items():
        for it in entry.get("items") or []:
            if it.get("url"):
                prev_items[it["url"]] = it
    out: dict[str, Any] = {"generated_at": now.isoformat(), "sources": {}}
    for cfg in korea_sources(bundle, only):
        entry: dict[str, Any] = {"status": "ok", "error": "", "items": [], "errors": []}
        out["sources"][cfg.id] = entry
        try:
            adapter = build_adapter(cfg, http, cs, since=since)
            listings = adapter.fetch_list()
        except Exception as e:  # noqa: BLE001 - 소스 격리
            entry["status"], entry["error"] = "fail", f"{type(e).__name__}: {e}"[:300]
            log.warning("[korea] %s 목록 실패: %s", cfg.id, entry["error"])
            continue
        reused = 0
        for l in listings:
            old = prev_items.get(l.url)
            if old and old.get("source_id") == cfg.id:
                entry["items"].append(old)
                reused += 1
                continue
            try:
                raw = adapter.fetch_detail(l)
                enrich_attachments(raw, http, cs)
            except Exception as e:  # noqa: BLE001
                entry["errors"].append(f"상세 실패 {l.url}: {e}"[:300])
                continue
            raw.extra["relay_enriched"] = True
            # 이 기록은 공개 저장소의 브랜치에 올라간다. data/ 에 남기는 발췌와 같이 전화·메일을 가린다
            # (GitHub 수집도 판별 전에 같은 방식으로 가리므로 결과는 달라지지 않는다)
            raw.body_text = mask_pii(raw.body_text)
            for k in ("content_text", "attachment_text"):
                if isinstance(raw.extra.get(k), str):
                    raw.extra[k] = mask_pii(raw.extra[k])
            entry["items"].append(json.loads(raw.model_dump_json()))
        adapter.close()
        if not entry["items"]:
            entry["status"] = "empty"
        log.info("[korea] %s: 목록 %d건 (지난 기록 재사용 %d)", cfg.id, len(listings), reused)
    return out
