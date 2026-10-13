"""한국 PC 중계 기록을 읽는 어댑터 (korea_only 소스용).

진주·거제·산청처럼 GitHub 러너(해외 IP)를 막는 사이트는 한국 PC 의 자체 실행기가 대신 읽어
korea-relay 브랜치에 relay.json 으로 올린다(gia/korea.py, .github/workflows/korea.yml).
GitHub 수집(collect.yml)은 그 파일을 GIA_KOREA_RELAY 경로로 받아, 사이트 대신 이 어댑터로 읽는다.
그래서 수집 기록(data/)을 고치는 쪽은 GitHub 수집 하나뿐이고, 두 실행이 같은 파일을 두고 부딪히지 않는다.

relay.json:
  {"generated_at": "2026-10-13T22:47:00+09:00",
   "sources": {"<source id>": {"status": "ok|empty|fail", "error": "", "items": [RawPosting JSON, ...]}}}
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..config import CollectorSettings, SourceConfig
from ..extract.deadline import KST
from ..models import RawListing, RawPosting
from .base import FetchError, HttpClient, SourceAdapter

RELAY_ENV = "GIA_KOREA_RELAY"
# 한국 PC 는 하루 두 번 돈다. 하루 반이 넘은 기록은 PC 가 꺼져 있었다는 뜻이라 쓰지 않는다
RELAY_MAX_AGE = timedelta(hours=36)


class KoreaRelayMissing(Exception):
    """이번 수집에 쓸 한국 PC 기록이 없다. 실패가 아니라 '건너뜀'으로 센다 (PC 가 꺼진 날 메일이 미뤄지지 않게)."""


def load_relay(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class RelayAdapter(SourceAdapter):
    type_name = "korea_relay"
    supports_backfill = False  # 본문 백필은 사이트를 다시 열어야 해서 여기서는 못 한다

    def __init__(self, cfg: SourceConfig, http: HttpClient, settings: CollectorSettings, since: date | None = None,
                 relay: dict[str, Any] | None = None, now: datetime | None = None):
        super().__init__(cfg, http, settings, since=since)
        self.relay = relay
        self.now = now or datetime.now(KST)
        self._by_url: dict[str, RawPosting] = {}

    def fetch_list(self) -> list[RawListing]:
        if not self.relay:
            raise KoreaRelayMissing("한국 PC 수집 기록 없음 (PC 가 꺼져 있었거나 아직 설치 전)")
        try:
            generated = datetime.fromisoformat(str(self.relay.get("generated_at")))
        except ValueError:
            raise KoreaRelayMissing("한국 PC 수집 기록의 시각을 읽지 못함") from None
        if self.now - generated > RELAY_MAX_AGE:
            raise KoreaRelayMissing(f"한국 PC 수집 기록이 오래됨 ({generated:%m/%d %H:%M})")
        entry = (self.relay.get("sources") or {}).get(self.cfg.id)
        if entry is None:
            raise KoreaRelayMissing("한국 PC 수집 기록에 이 소스가 없음 (설정을 바꾼 뒤 아직 한 번도 안 돎)")
        if entry.get("status") == "fail":
            raise FetchError(f"한국 PC 에서 실패: {entry.get('error', '')}"[:300])
        out: list[RawListing] = []
        for it in entry.get("items") or []:
            raw = RawPosting.model_validate(it)
            if self.since and raw.posted_at and raw.posted_at < self.since:
                continue
            self._by_url[raw.url] = raw
            out.append(RawListing(**{k: v for k, v in raw.model_dump().items() if k in RawListing.model_fields}))
        return out

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        raw = self._by_url.get(listing.url)
        if raw is None:
            raise FetchError(f"한국 PC 기록에 상세 없음: {listing.url}")
        return raw.model_copy(deep=True)
