"""범용 HTML 게시판 어댑터 (docs/DESIGN.md 5.2 html_list)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import quote, urljoin

import httpx
# lexbor 백엔드. selectolax 1.0 이 옛 Modest 백엔드를 지웠고(2026-10-04 수집·보고가
# 멈췄다), lexbor 가 HTML5 표준을 따르는 후속이다. 쓰는 API(css·css_first·text·
# attributes·decompose·body)가 같아 이름만 바꿔 받는다.
from selectolax.lexbor import LexborHTMLParser as HTMLParser

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
    return extract_body_html(decode_html(r, encoding), selector)


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


def parse_list_html(html: str, page_url: str, a: dict, cfg, since: date) -> tuple[list[RawListing], date | None]:
    """목록 HTML에서 공고 후보를 뽑는다. 반환: (목록, 페이지 내 가장 오래된 게시일)."""
    tree = HTMLParser(html)
    rows = tree.css(a["row_selector"])
    out: list[RawListing] = []
    oldest_on_page: date | None = None
    for row in rows:
        t = row.css_first(a.get("title_selector") or "a")
        if t is None:
            continue
        title = (t.attributes.get(a["title_attr"]) if a.get("title_attr") else None) or t.text(strip=True)
        link = row.css_first(a.get("link_selector") or a.get("title_selector") or "a")
        target = resolve_link(link, page_url, a)
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
        if org is None and cfg.org_type.value != "portal":
            org = a.get("org_name") or cfg.name  # adapter.org_name: 게시판 이름 대신 쓸 기관명
        if not matches_keywords(title, a.get("keywords")):
            continue
        if posted and posted < since:
            continue
        out.append(RawListing(source_id=cfg.id, title=title, url=target, org_name=org, posted_at=posted))
    return out, oldest_on_page


def extract_body_html(html: str, selector: str, fallback_to_body: bool = True) -> str:
    tree = HTMLParser(html)
    for tag in ("script", "style", "noscript"):
        for n in tree.css(tag):
            n.decompose()
    # 본문을 편집기용 <textarea> 에 HTML 째로 넣어 두는 게시판이 있다(양산시시설관리공단).
    # textarea 안은 태그가 아니라 글자로 읽혀 '<p>' 가 그대로 남으므로 한 번 더 풀어 글만 남긴다
    for n in tree.css("textarea"):
        inner = HTMLParser(n.text(deep=True) or "")
        plain = inner.body.text(separator="\n", strip=True) if inner.body else ""
        n.replace_with(plain)
    node = tree.css_first(selector) or (tree.body if fallback_to_body else None)
    if node is None:
        return ""
    text = node.text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)[:20000]


def extract_attachments_html(html: str, page_url: str, selector: str | None,
                             regex: str | None = None, template: str | None = None) -> list[str]:
    """첨부 링크 주소들.

    href 가 javascript 함수 호출이면 regex 로 인자를 뽑아 template 의 {1}, {2} … 에 채운다
    (새올: javascript:goDownLoad('공고.hwpx','저장명','/경로') → FileDown.jsp?user_file_nm=…).
    인자는 주소에 넣을 수 있게 퍼센트 인코딩한다.
    """
    if not selector:
        return []
    tree = HTMLParser(html)
    out: list[str] = []
    for n in tree.css(selector):
        href = n.attributes.get("href")
        if not href:
            continue
        if regex:
            m = re.search(regex, href)
            if not m:
                continue
            href = (template or "{1}").format(m.group(0), *(quote(g or "", safe="/") for g in m.groups()))
        out.append(urljoin(page_url, href))
    return out


def labeled_cell_text(html: str, label: str) -> str:
    """'제목' 같은 머리 칸 바로 다음 칸의 글. 표 형식 상세 페이지에서 목록에 잘려 나온 제목을 되찾는다."""
    tree = HTMLParser(html)
    for cell in tree.css("td, th"):
        if cell.text(strip=True).replace(" ", "") != label:
            continue
        nxt = cell.next
        while nxt is not None and nxt.tag not in ("td", "th"):
            nxt = nxt.next
        if nxt is not None:
            text = " ".join(nxt.text(strip=True).split())
            if text:
                return text
    return ''


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
            listings, oldest = parse_list_html(decode_html(r, a.get("encoding")), url, a, self.cfg, since)
            if not listings and oldest is None:
                break
            out.extend(listings)
            if "{page}" not in list_url or (oldest and oldest < since):
                break
        return out

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        d = self.a.get("detail") or {}
        if d.get("fetch") is False:
            return super().fetch_detail(listing)
        r = self.http.get(listing.url)
        html = decode_html(r, d.get("encoding") or self.a.get("encoding"))
        body = extract_body_html(html, d.get("body_selector") or "body")
        attachments = extract_attachments_html(html, listing.url, d.get("attachment_selector"),
                                               d.get("attachment_regex"), d.get("attachment_url_template"))
        raw = RawPosting(**listing.model_dump(), body_text=body, attachments=attachments, fetched_at=datetime.now(KST))
        if d.get("title_label"):
            # 목록이 긴 제목을 '...' 로 자르는 곳(새올 의령·함안 등): 상세의 전체 제목으로 바꾼다
            full = labeled_cell_text(html, d["title_label"])
            if full:
                raw.title = full
        if d.get("content_selector"):
            # 판별에는 머리 정보(지역·직종)까지 담긴 body 를 쓰고, 저장할 발췌는 본문 글만 담는다
            # 셀렉터가 안 맞으면 페이지 전체로 물러나지 않고 비워 둔다 — 그러면 body 발췌를 쓴다
            raw.extra["content_text"] = extract_body_html(html, d["content_selector"], fallback_to_body=False)
        return raw
