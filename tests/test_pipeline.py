from datetime import timedelta

import httpx

from gia.collectors.base import HttpClient
from gia.config import ConfigBundle
from gia.models import Status
from gia.pipeline import collect
from gia.report.build import select_postings
from gia.store import Store
from tests.conftest import FIXTURES, NOW, make_source


def _bundle(settings, sources):
    return ConfigBundle(settings=settings, sources=sources, aliases={})


def _http(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/list":
            return httpx.Response(200, content=(FIXTURES / "api_list.json").read_bytes(), headers={"content-type": "application/json"})
        if path == "/board/list":
            return httpx.Response(200, content=(FIXTURES / "board_list.html").read_bytes(), headers={"content-type": "text/html"})
        if path == "/board/view":
            return httpx.Response(200, content=(FIXTURES / "board_view_3.html").read_bytes(), headers={"content-type": "text/html"})
        if path == "/down":
            return httpx.Response(503)
        return httpx.Response(404)
    return HttpClient(settings.collector, transport=httpx.MockTransport(handler))


def _sources(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    api = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list", items_path="result",
                      params={"serviceKey": "${DATA_GO_KR_KEY}"},
                      field_map={"title": "recrutPbancTtl", "org_name": "instNm", "posted_at": "pbancBgngYmd", "deadline": "pbancEndYmd", "region": "workRgnNmLst", "url": "srcUrl"},
                      region_filter="@gyeongnam", keywords=["강사"], detail={"fetch": False})
    board = make_source("board", "local_public", type="html_list", list_url="https://site.example.org/board/list",
                        row_selector="table.board tbody tr", title_selector="td.title a", date_selector="td.date", detail={"body_selector": "div.content"})
    board.name = "경남인재평생교육진흥원"
    down = make_source("down", "local_gov", type="html_list", list_url="https://site.example.org/down", row_selector="tr")
    todo = make_source("todo", "local_gov", type="html_list", list_url="TODO", row_selector="tr")
    return [api, board, down, todo]


def test_collect_end_to_end(settings, tmp_path, monkeypatch):
    bundle = _bundle(settings, _sources(monkeypatch))
    store = Store(tmp_path / "data")
    run = collect(bundle, store, _http(settings), now=NOW)

    by_id = {s.source_id: s for s in run.sources}
    assert by_id["gojobs"].status == "ok" and by_id["gojobs"].new == 1
    assert by_id["board"].status == "ok" and by_id["board"].new == 1
    assert by_id["down"].status == "fail"
    assert by_id["todo"].status == "unconfigured"

    titles = sorted(p.title for p in store.values())
    assert titles == ["2026 하반기 시민강좌 강사 모집", "2026-2학기 시간강사(전기) 모집"]
    board_post = next(p for p in store.values() if "시민강좌" in p.title)
    assert board_post.flags == ["재공고"]
    assert board_post.deadline.isoformat() == "2026-09-30T18:00:00+09:00"
    assert board_post.region == ["경남", "창원"]
    assert "[전화번호]" not in board_post.title
    assert (tmp_path / "data" / "postings" / "2026-09.jsonl").exists()
    assert (tmp_path / "data" / "runs").exists()

    # 두 번째 실행: 이미 본 URL은 상세를 다시 가져오지 않고 신규도 없다
    run2 = collect(bundle, store, _http(settings), now=NOW + timedelta(hours=6))
    assert run2.totals["new"] == 0
    assert {s.source_id: s.detail_fetched for s in run2.sources}["board"] == 0

    # 리포트 선별: 둘 다 신규, 마감 임박 없음 (9/30 마감, 현재 9/21)
    data = select_postings(bundle, store, NOW)
    assert len(data.new) == 2 and data.closing == []
    store.mark_reported(data.keys(), NOW, 3)
    assert all(p.status == Status.active for p in store.values())


def test_collect_dry_run_does_not_write(settings, tmp_path, monkeypatch):
    bundle = _bundle(settings, _sources(monkeypatch)[:1])
    store = Store(tmp_path / "data")
    collect(bundle, store, _http(settings), now=NOW, dry_run=True)
    assert not (tmp_path / "data").exists()
