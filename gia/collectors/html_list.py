"""범용 HTML 게시판 어댑터 (docs/DESIGN.md 5.2 html_list)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from ..extract.deadline import KST
from ..models import RawListing, RawPosting
from .base import SourceAdapter, matches_keywords, parse_date_loose

_META_CHARSET = re.compile(rb"charset=[\"']?([\w\-]+)", re.I)


def decode_html(r: httpx.Response, encoding: str | None = None) -> str:
    enc = encoding
    if not enc:
        m = _META_CHARSET.search(r.content[:4096])
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    if not enc:
        enc = r.encoding or "utf-8"
    try:
        return r.content.decode(enc, errors="replace")
    except LookupError:
        return r.content.decode("utf-8", errors="replace")


def extract_body(r: httpx.Response, selector: str, encoding: str | None = None) -> str:
    tree = HTMLParser(decode_html(r, encoding))
    for tag in ("script", "style", "noscript"):
        for n in tree.css(tag):
            n.decompose()
    node = tree.css_first(selector) or tree.body
    if node is None:
        return ""
    text = node.text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)[:20000]


def resolve_link(node, page_url: str, a: dict) -> str | None:
    """href 또는 onclick에서 상세 URL을 만든다.

    - link_attr: 읽을 속성 (기본 href, 없으면 onclick)
    - link_regex: 속성값에서 식별자를 뽑는 정규식 (그룹 사용)
    - link_url_template: "{1}" 같은 그룹 자리표시자를 채울 URL 템플릿
    """
    if node is None:
        return None
    attrs = node.attributes
    value = attrs.get(a.get("link_attr") or "href") or attrs.get("onclick") or attrs.get("href") or ""
    regex = a.get("link_regex")
    if regex:
        m = re.search(regex, value)
        if not m:
            return None
        tpl = a.get("link_url_template")
        if tpl:
            return tpl.format(m.group(0), *m.groups())
        return urljoin(page_url, m.group(1) if m.groups() else m.group(0))
    if not value or value.startswith(("javascript:", "#")):
        return None
    return urljoin(page_url, value)


class HtmlListAdapter(SourceAdapter):
    type_name = "html_list"

    def fetch_list(self) -> list[RawListing]:
        a = self.a
        list_url: str = a["list_url"]
        max_pages = int((a.get("paging") or {}).get("max_pages") or self.settings.default_pages)
        since = self.since or (date.today() - timedelta(days=self.settings.default_days))
        out: list[RawListing] = []
        for page in range(1, max_pages + 1):
            url = list_url.replace("{page}", str(page))
            r = self.http.get(url)
            tree = HTMLParser(decode_html(r, a.get("encoding")))
            rows = tree.css(a["row_selector"])
            if not rows:
                break
            oldest_on_page: date | None = None
            for row in rows:
                t = row.css_first(a.get("title_selector") or "a")
                if t is None:
                    continue
                title = (t.attributes.get(a["title_attr"]) if a.get("title_attr") else None) or t.text(strip=True)
                link = row.css_first(a.get("link_selector") or a.get("title_selector") or "a")
                target = resolve_link(link, url, a)
                if not title or not target:
                    continue
                posted = None
                if a.get("date_selector"):
                    dn = row.css_first(a["date_selector"])
                    posted = parse_date_loose(dn.text(strip=True) if dn is not None else None, a.get("date_formats"))
                    if posted and (oldest_on_page is None or posted < oldest_on_page):
                        oldest_on_page = posted
                org = None
                if a.get("org_selector"):
                    on = row.css_first(a["org_selector"])
                    org = on.text(strip=True) if on is not None else None
                if org is None and self.cfg.org_type.value != "portal":
                    org = self.cfg.name
                if not matches_keywords(title, a.get("keywords")):
                    continue
                if posted and posted < since:
                    continue
                out.append(RawListing(source_id=self.cfg.id, title=title, url=target, org_name=org, posted_at=posted))
            if "{page}" not in list_url or (oldest_on_page and oldest_on_page < since):
                break
        return out

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        d = self.a.get("detail") or {}
        if d.get("fetch") is False:
            return super().fetch_detail(listing)
        r = self.http.get(listing.url)
        body = extract_body(r, d.get("body_selector") or "body", d.get("encoding") or self.a.get("encoding"))
        attachments: list[str] = []
        if d.get("attachment_selector"):
            tree = HTMLParser(decode_html(r, self.a.get("encoding")))
            for n in tree.css(d["attachment_selector"]):
                href = n.attributes.get("href")
                if href:
                    attachments.append(urljoin(listing.url, href))
        return RawPosting(**listing.model_dump(), body_text=body, attachments=attachments, fetched_at=datetime.now(KST))
