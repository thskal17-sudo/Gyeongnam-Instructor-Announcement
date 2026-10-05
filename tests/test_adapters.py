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
    assert [l.title for l in listings] == ["디지털 문해교육 강사 인력풀 모집", "[재공고] 2026 하반기 시민강좌 강사 모집", "2026 시민강좌 수강생 모집 안내"]
    listings = listings[1:]
    assert listings[0].url == "https://site.example.org/board/view?id=3"
    assert listings[0].org_name == "board 기관"
    raw = ad.fetch_detail(listings[0])
    assert "접수기간" in raw.body_text and "alert" not in raw.body_text
    assert raw.attachments == ["https://site.example.org/files/공고문.hwp"]


def test_html_list_onclick_links(settings):
    cfg = make_source("onclick", "local_gov", type="html_list", list_url="https://site.example.org/bbs/list",
                      row_selector="table.bbs_list tbody tr", title_selector="td.subject a", date_selector="td.date",
                      link_attr="onclick", link_regex=r"fn_view\('(\d+)'\)", link_url_template="https://site.example.org/bbs/view?seq={1}")
    http = _client(settings, {"/bbs/list": ("text/html", "board_onclick.html")})
    listings = HtmlListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1)).fetch_list()
    assert [(l.title, l.url) for l in listings] == [("체육센터 수영강사 모집", "https://site.example.org/bbs/view?seq=1001")]
    assert listings[0].posted_at == date(2026, 9, 19)


def test_tls_verify_false_routes_host_to_insecure_client(settings):
    """adapter.tls_verify: false 인 소스의 호스트만 검증 없는 클라이언트로 보내고, 다른 호스트는 그대로 둔다 (#13)."""
    import httpx
    from gia.collectors.base import HttpClient
    from gia.collectors.registry import build_adapter, insecure_hosts
    from tests.conftest import make_source

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, text="<html><body><table><tbody></tbody></table></body></html>", headers={"content-type": "text/html"})

    http = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    cfg = make_source("insecure", type="html_list", list_url="https://Insecure.example.org/board?page={page}", row_selector="tr",
                      link_url_template="https://files.example.org/view/{1}", tls_verify=False)
    assert insecure_hosts(cfg) == ["insecure.example.org", "files.example.org"]
    build_adapter(cfg, http, settings.collector)
    assert http._client_for("https://insecure.example.org/board") is http._mode_clients["insecure"]
    assert http._client_for("https://files.example.org/view/1") is http._mode_clients["insecure"]
    assert http._client_for("https://other.example.org/") is http._client
    assert http._mode_clients["insecure"] is not http._client
    assert http.get("https://insecure.example.org/board").status_code == 200
    assert http.get("https://other.example.org/").status_code == 200
    assert seen == ["insecure.example.org", "other.example.org"]
    http.close()

    plain = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    build_adapter(make_source("secure", type="html_list", list_url="https://secure.example.org/board", row_selector="tr"), plain, settings.collector)
    assert plain._mode_clients == {}
    plain.close()

    legacy = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    build_adapter(make_source("old", type="html_list", list_url="https://old.example.org/board", row_selector="tr", tls_legacy=True), legacy, settings.collector)
    assert legacy._host_mode == {"old.example.org": "legacy"}
    assert legacy._client_for("https://old.example.org/x") is legacy._mode_clients["legacy"]
    assert legacy.get("https://old.example.org/board").status_code == 200
    import ssl
    ctx = HttpClient.legacy_tls_context()
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1 and ctx.verify_mode == ssl.CERT_NONE
    legacy.close()


def test_4xx_error_carries_server_reason(settings):
    """4xx 는 상태 코드만 남기지 말고 서버가 알려준 거부 사유까지 실어야 한다 (공공데이터포털 403 진단)."""
    import pytest

    from gia.collectors.base import FetchError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"returnAuthMsg": "SERVICE_ACCESS_DENIED_ERROR", "returnReasonCode": "20"},
            text="<OpenAPI_ServiceResponse>\n  <cmmMsgHeader>\n    <errMsg>SERVICE ERROR</errMsg>\n  </cmmMsgHeader>\n</OpenAPI_ServiceResponse>",
        )

    http = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError) as e:
        http.get("https://apis.data.go.kr/1051000/recruitment/list")
    msg = str(e.value)
    assert "HTTP 403" in msg
    assert "returnAuthMsg=SERVICE_ACCESS_DENIED_ERROR" in msg
    assert "returnReasonCode=20" in msg
    assert "SERVICE ERROR" in msg
    http.close()


def test_4xx_without_reason_stays_short(settings):
    """본문·헤더가 비면 기존처럼 짧은 메시지 그대로."""
    import pytest

    from gia.collectors.base import FetchError

    http = HttpClient(settings.collector, transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(FetchError) as e:
        http.get("https://example.org/gone")
    assert str(e.value) == "HTTP 404 https://example.org/gone"
    http.close()


def test_encoding_form_api_key_is_decoded_once(settings, monkeypatch):
    """공공데이터포털 Encoding 키(%2B…)를 넣어도 이중 인코딩되지 않고 원래 키로 전달된다."""
    from gia.collectors.api_json import normalize_api_key

    raw = "abc+def/ghi=="
    encoded = "abc%2Bdef%2Fghi%3D%3D"
    assert normalize_api_key("serviceKey", encoded) == raw
    assert normalize_api_key("authKey", encoded) == raw
    # Decoding 키(이미 원본)는 그대로 둔다 — 퍼센트 이스케이프가 없다.
    assert normalize_api_key("serviceKey", raw) == raw
    # 붙여넣을 때 딸려온 앞뒤 공백·줄바꿈은 떼어낸다.
    assert normalize_api_key("serviceKey", f"  {raw}\n") == raw
    assert normalize_api_key("serviceKey", f"{encoded}\n") == raw
    # 키가 아닌 파라미터는 건드리지 않는다.
    assert normalize_api_key("keyword", "%EA%B0%95%EC%82%AC") == "%EA%B0%95%EC%82%AC"
    assert normalize_api_key("keyword", " 강사 ") == " 강사 "

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["serviceKey"])
        return httpx.Response(200, json={"result": []}, headers={"content-type": "application/json"})

    monkeypatch.setenv("DATA_GO_KR_KEY", encoded)
    cfg = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list", format="json",
                      params={"serviceKey": "${DATA_GO_KR_KEY}"}, items_path="result",
                      field_map={"title": "t", "url": "u"})
    http = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    ApiJsonAdapter(cfg, http, settings.collector).fetch_list()
    assert seen == [raw]
    http.close()



def test_api_json_logs_filter_counts_and_empty_shape(settings, monkeypatch, caplog):
    """0건일 때 원인이 필터인지 빈 응답인지 로그로 구별된다 (나라일터 403 → 0건, 2026-09-30)."""
    import json
    import logging

    monkeypatch.setenv("DATA_GO_KR_KEY", "SECRETKEY123")
    cfg = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list",
                      params={"serviceKey": "${DATA_GO_KR_KEY}"}, items_path="result", keywords=["강사"],
                      field_map={"title": "t"})

    def serve(body: dict) -> HttpClient:
        return HttpClient(settings.collector, transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=json.dumps(body, ensure_ascii=False).encode(),
                                       headers={"content-type": "application/json"})))

    with caplog.at_level(logging.INFO, logger="gia.collectors.api_json"):
        assert ApiJsonAdapter(cfg, serve({"result": [{"t": "사무원 채용"}, {"t": "행정 보조"}]}), settings.collector).fetch_list() == []
    assert "응답 2건 → 통과 0건 (걸러짐: 키워드 2)" in caplog.text
    assert "첫 항목 필드 ['t']" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="gia.collectors.api_json"):
        empty = {"resultCode": 30, "resultMsg": "key SECRETKEY123 not registered", "result": []}
        assert ApiJsonAdapter(cfg, serve(empty), settings.collector).fetch_list() == []
    assert "첫 페이지에 'result' 항목 없음" in caplog.text
    assert "resultCode" in caplog.text and "not registered" in caplog.text
    assert "SECRETKEY123" not in caplog.text, "인증키는 로그에 남기지 않는다"


def test_eminwon_saeol_list(settings):
    """새올 고시공고: onclick=searchDetail('id') 행을 읽고 제목 키워드로 채용·모집만 남긴다 (2026-10-03)."""
    import yaml
    anchor = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))["x-eminwon"]
    anchor = {**anchor, "paging": {"max_pages": 1}}  # 고정 응답이라 쪽 넘김은 보지 않는다
    cfg = make_source("hadong", "local_gov", type="html_list", **anchor,
                      list_url="http://eminwon.example.go.kr/emwp/list?pageIndex={page}",
                      link_url_template="http://eminwon.example.go.kr/emwp/view?not_ancmt_mgt_no={1}")
    http = _client(settings, {"/emwp/list": ("text/html", "eminwon_list.html")})
    listings = HtmlListAdapter(cfg, http, settings.collector, since=date(2026, 9, 25)).fetch_list()
    # 셀렉터 묶음(A, B)은 묶음 순서대로 돌려주므로 순서는 보지 않는다
    assert sorted((l.title, l.url, l.posted_at) for l in listings) == sorted([
        ("2026년 하동군 평생학습센터 프로그램 강사 모집 공고",
         "http://eminwon.example.go.kr/emwp/view?not_ancmt_mgt_no=45253", date(2026, 10, 2)),
        # 의령형: onclick 이 <a> 가 아니라 <td> 에 붙어 있다
        ("2026년 의령군 체육회 생활체육지도자 채용 공고",
         "http://eminwon.example.go.kr/emwp/view?not_ancmt_mgt_no=36475", date(2026, 10, 1))])


def test_eminwon_detail_full_title_and_js_attachment(settings):
    """새올 상세: 목록에서 '...' 로 잘린 제목을 '제목' 칸으로 되찾고, goDownLoad 첨부를 FileDown.jsp 주소로 만든다."""
    import yaml

    from gia.extract.attachments import file_extension, filename_from_url
    from gia.models import RawListing
    anchor = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))["x-eminwon"]
    cfg = make_source("uiryeong", "local_gov", type="html_list", **anchor,
                      list_url="http://eminwon.example.go.kr/emwp/list?pageIndex={page}",
                      link_url_template="http://eminwon.example.go.kr/emwp/view?not_ancmt_mgt_no={1}")
    http = _client(settings, {"/emwp/view": ("text/html", "eminwon_detail.html")})
    listing = RawListing(source_id="uiryeong", title="2026년 의령군 평생학습센터 하반기 프로그램 강사(요가·서예...",
                         url="http://eminwon.example.go.kr/emwp/view?not_ancmt_mgt_no=36475")
    raw = HtmlListAdapter(cfg, http, settings.collector).fetch_detail(listing)
    assert raw.title == "2026년 의령군 평생학습센터 하반기 프로그램 강사(요가·서예·스마트폰 활용) 모집 공고"
    assert raw.extra["content_text"].startswith("의령군 평생학습센터")
    assert len(raw.attachments) == 1
    url = raw.attachments[0]
    assert url.startswith("http://eminwon.example.go.kr/emwp/jsp/ofr/FileDown.jsp?user_file_nm=")
    assert "file_path=/ntishome/file/upload/ofr/ofr/20261002" in url
    # 첨부 받기 단계가 확장자로 거르므로, 주소에서 원래 파일 이름을 읽을 수 있어야 한다
    assert filename_from_url(url) == "강사 모집 공고문.hwpx" and file_extension(filename_from_url(url)) == ".hwpx"


def test_host_policy_waits_longer_and_retries_only_that_host():
    """adapter.timeout_sec·retries 는 그 소스의 호스트에만 걸린다 (새올 고성 시간초과, 2026-10-05)."""
    from gia.collectors.registry import build_adapter
    from gia.config import CollectorSettings

    calls: list[tuple[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.host, request.extensions["timeout"]["read"]))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "slow.example.go.kr" and len([c for c in calls if c[0] == "slow.example.go.kr"]) < 4:
            raise httpx.ReadTimeout("멈춤", request=request)
        return httpx.Response(200, text="<html></html>")

    cs = CollectorSettings(per_domain_delay_sec=0)
    http = HttpClient(cs, transport=httpx.MockTransport(handler))
    cfg = make_source("goseong", type="html_list", list_url="http://slow.example.go.kr/list?p={page}",
                      row_selector="tr", timeout_sec=40, retries=3)
    build_adapter(cfg, http, cs)
    assert http.get("http://slow.example.go.kr/list").status_code == 200   # 2번 멈춘 뒤 3번째에 받음
    slow = [t for h, t in calls if h == "slow.example.go.kr"]
    assert slow[1:] == [40.0, 40.0, 40.0]           # robots.txt 다음 목록 요청 세 번, 모두 40초
    calls.clear()
    http.get("http://fast.example.org/x")
    assert [t for h, t in calls if h == "fast.example.org"][-1] == cs.request_timeout_sec  # 다른 호스트는 그대로
