from datetime import date
from pathlib import Path

import httpx

from gia.collectors.api_json import ApiJsonAdapter, xml_to_obj
from gia.collectors.base import HttpClient
from gia.collectors.html_list import HtmlListAdapter
from tests.conftest import FIXTURES, make_source


def _client(settings, routes: dict[str, tuple[str, str]]) -> HttpClient:
    """routes: path → (content-type, fixture 파일명)"""
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path
        if key in routes:
            ctype, name = routes[key]
            return httpx.Response(200, content=(FIXTURES / name).read_bytes(), headers={"content-type": ctype})
        return httpx.Response(404)
    return HttpClient(settings.collector, transport=httpx.MockTransport(handler))


def test_api_json_filters_keywords_and_region(settings, monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    cfg = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list", format="json",
                      params={"serviceKey": "${DATA_GO_KR_KEY}"}, paging={"page_param": "pageNo", "size_param": "numOfRows", "size": 100, "max_pages": 2},
                      items_path="result", field_map={"title": "recrutPbancTtl", "org_name": "instNm", "posted_at": "pbancBgngYmd", "deadline": "pbancEndYmd", "region": "workRgnNmLst", "url": "srcUrl"},
                      keywords=["강사"], region_filter="@gyeongnam")
    http = _client(settings, {"/list": ("application/json", "api_list.json")})
    ad = ApiJsonAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    listings = ad.fetch_list()
    assert [l.title for l in listings] == ["2026-2학기 시간강사(전기) 모집"]
    l = listings[0]
    assert l.org_name == "한국폴리텍VII대학 창원캠퍼스" and l.posted_at == date(2026, 9, 18) and l.deadline_text == "20260930"


def test_api_json_missing_secret(settings, monkeypatch):
    from gia.config import MissingSecret
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    cfg = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list", params={"serviceKey": "${DATA_GO_KR_KEY}"}, items_path="result", field_map={"title": "t"})
    http = _client(settings, {})
    try:
        ApiJsonAdapter(cfg, http, settings.collector).fetch_list()
        assert False, "MissingSecret expected"
    except MissingSecret:
        pass


def test_api_xml(settings, monkeypatch):
    monkeypatch.setenv("WORKNET_API_KEY", "k")
    cfg = make_source("work24", "portal", type="api_json", endpoint="https://api.example.org/wanted", format="xml",
                      params={"authKey": "${WORKNET_API_KEY}"}, items_path="wantedRoot.wanted",
                      field_map={"title": "title", "org_name": "company", "posted_at": "regDt", "deadline": "closeDate", "region": "region", "url": "wantedInfoUrl"},
                      date_formats=["%y-%m-%d"])
    http = _client(settings, {"/wanted": ("application/xml", "worknet.xml")})
    listings = ApiJsonAdapter(cfg, http, settings.collector, since=date(2026, 9, 1)).fetch_list()
    assert len(listings) == 2
    assert listings[0].posted_at == date(2026, 9, 19) and listings[0].region_text == "경남 창원시"
    assert listings[1].deadline_text == "상시"


def test_xml_to_obj_single_item_becomes_list_via_adapter():
    import xml.etree.ElementTree as ET
    root = ET.fromstring("<r><item><a>1</a></item></r>")
    assert xml_to_obj(root) == {"item": {"a": "1"}}


def test_html_list_and_detail(settings):
    cfg = make_source("board", "local_public", type="html_list", list_url="https://site.example.org/board/list?page={page}",
                      row_selector="table.board tbody tr", title_selector="td.title a", date_selector="td.date",
                      paging={"max_pages": 3}, detail={"body_selector": "div.content", "attachment_selector": "a.file"})
    http = _client(settings, {"/board/list": ("text/html", "board_list.html"), "/board/view": ("text/html", "board_view_3.html")})
    ad = HtmlListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    listings = ad.fetch_list()
    # 6월 게시글은 since 이전이라 제외, 페이지 2는 가장 오래된 글이 since 이전이라 요청하지 않음
    assert [l.title for l in listings] == ["[재공고] 2026 하반기 시민강좌 강사 모집", "2026 시민강좌 수강생 모집 안내"]
    assert listings[0].url == "https://site.example.org/board/view?id=3"
    assert listings[0].org_name == "board 기관"
    raw = ad.fetch_detail(listings[0])
    assert "접수기간" in raw.body_text and "alert" not in raw.body_text
    assert raw.attachments == ["https://site.example.org/files/공고문.hwp"]
