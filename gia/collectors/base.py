"""어댑터 인터페이스와 HTTP 클라이언트 (docs/DESIGN.md 5절)."""
from __future__ import annotations

import random
import re
import threading
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ..config import CollectorSettings, SourceConfig
from ..extract.deadline import KST
from ..models import RawListing, RawPosting


class FetchError(Exception):
    pass


class UnconfiguredSource(Exception):
    pass


class HttpClient:
    """도메인별 요청 간격, 재시도, robots.txt 확인을 담당한다."""

    def __init__(self, settings: CollectorSettings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._client = httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept-Language": "ko,en;q=0.8"},
            timeout=settings.request_timeout_sec,
            follow_redirects=True,
            transport=transport,
        )
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._robots: dict[str, RobotFileParser | None] = {}

    def close(self) -> None:
        self._client.close()

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        host = urlsplit(url).netloc
        if self.settings.respect_robots and not self._allowed(url):
            raise FetchError(f"robots.txt 차단: {url}")
        with self._lock_for(host):
            self._wait(host)
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    r = self._client.get(url, params=params, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_err = e
                    time.sleep(2 ** attempt * 0.5 if self.settings.per_domain_delay_sec else 0)
                    continue
                if r.status_code >= 500:
                    last_err = FetchError(f"HTTP {r.status_code} {url}")
                    time.sleep(2 ** attempt * 0.5 if self.settings.per_domain_delay_sec else 0)
                    continue
                if r.status_code >= 400:
                    raise FetchError(f"HTTP {r.status_code} {url}")
                return r
            raise FetchError(f"재시도 실패: {last_err}")

    def download(self, url: str, max_bytes: int) -> tuple[bytes, str | None]:
        """첨부파일을 크기 상한까지 내려받는다. 반환: (bytes, Content-Disposition 파일명)."""
        host = urlsplit(url).netloc
        if self.settings.respect_robots and not self._allowed(url):
            raise FetchError(f"robots.txt 차단: {url}")
        with self._lock_for(host):
            self._wait(host)
            try:
                with self._client.stream("GET", url) as r:
                    if r.status_code >= 400:
                        raise FetchError(f"HTTP {r.status_code} {url}")
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > max_bytes:
                            raise FetchError(f"첨부 크기 초과(>{max_bytes // 1024 // 1024}MB): {url}")
                    return bytes(buf), filename_from_headers(r.headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                raise FetchError(f"첨부 다운로드 실패: {e}") from e

    def post_json(self, url: str, payload: dict) -> httpx.Response:
        r = self._client.post(url, json=payload)
        if r.status_code >= 400:
            raise FetchError(f"HTTP {r.status_code} {url}: {r.text[:200]}")
        return r

    def check_allowed(self, url: str) -> None:
        """robots.txt 정책상 허용되지 않으면 FetchError."""
        if self.settings.respect_robots and not self._allowed(url):
            raise FetchError(f"robots.txt 차단: {url}")

    def throttle(self, url: str) -> None:
        """HTTP 클라이언트를 거치지 않는 요청(브라우저 렌더링)도 도메인별 간격을 지키게 한다."""
        host = urlsplit(url).netloc
        with self._lock_for(host):
            self._wait(host)

    def _lock_for(self, host: str) -> threading.Lock:
        with self._guard:
            if host not in self._locks:
                self._locks[host] = threading.Lock()
            return self._locks[host]

    def _wait(self, host: str) -> None:
        delay = self.settings.per_domain_delay_sec
        if delay <= 0:
            return
        last = self._last.get(host)
        if last is not None:
            gap = delay + random.uniform(-0.5, 0.5)
            remaining = max(0.0, gap) - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)
        self._last[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._guard:
            cached = self._robots.get(base, "miss")
        if cached == "miss":
            rp: RobotFileParser | None = RobotFileParser()
            try:
                r = self._client.get(base + "/robots.txt")
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None
            except httpx.HTTPError:
                rp = None
            with self._guard:
                self._robots[base] = rp
            cached = rp
        if cached is None:
            return True
        return cached.can_fetch(self.settings.user_agent, url)


class SourceAdapter:
    type_name = "base"

    def __init__(self, cfg: SourceConfig, http: HttpClient, settings: CollectorSettings, since: date | None = None):
        self.cfg = cfg
        self.http = http
        self.settings = settings
        self.a: dict[str, Any] = cfg.adapter
        self.since = since

    def fetch_list(self) -> list[RawListing]:
        raise NotImplementedError

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        return RawPosting(**listing.model_dump(), body_text=str(listing.extra.get("body_text", "")), fetched_at=datetime.now(KST))

    def close(self) -> None:
        """브라우저 등 자원을 정리한다."""


# ---- helpers ---------------------------------------------------------
_CD_EXT = re.compile(r"filename\*=(?:[\w-]+)''([^;]+)", re.I)
_CD_PLAIN = re.compile(r'filename="?([^";]+)"?', re.I)


def filename_from_headers(headers) -> str | None:
    cd = headers.get("content-disposition", "") if headers else ""
    if not cd:
        return None
    from urllib.parse import unquote
    m = _CD_EXT.search(cd)
    if m:
        return unquote(m.group(1)).strip()
    m = _CD_PLAIN.search(cd)
    if m:
        name = m.group(1).strip()
        try:
            return name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return unquote(name)
    return None

def get_path(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


_DATE_FORMATS = ["%Y%m%d", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M", "%y-%m-%d", "%Y.%m.%d."]
_DATE_LOOSE = re.compile(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def parse_date_loose(value: Any, formats: list[str] | None = None) -> date | None:
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    for fmt in (formats or []) + _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    m = _DATE_LOOSE.search(v)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def matches_keywords(text: str, keywords: list[str] | None) -> bool:
    if not keywords:
        return True
    return any(k in text for k in keywords)


def substitute_placeholders(obj: Any, today: date, since: date) -> Any:
    """{today}, {since} (YYYYMMDD) 와 _dash / _dot 변형을 치환한다."""
    table = {
        "today": today.strftime("%Y%m%d"), "since": since.strftime("%Y%m%d"),
        "today_dash": today.isoformat(), "since_dash": since.isoformat(),
        "today_dot": today.strftime("%Y.%m.%d"), "since_dot": since.strftime("%Y.%m.%d"),
    }
    pat = re.compile(r"\{(today|since)(_dash|_dot)?\}")
    if isinstance(obj, str):
        return pat.sub(lambda m: table[m.group(1) + (m.group(2) or "")], obj)
    if isinstance(obj, dict):
        return {k: substitute_placeholders(v, today, since) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_placeholders(v, today, since) for v in obj]
    return obj
