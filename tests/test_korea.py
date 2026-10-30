"""한국 PC 중계(korea_only): 한국 PC 가 읽은 기록을 GitHub 수집이 사이트 대신 쓴다."""
import json
from datetime import timedelta

import httpx

from gia.collectors.base import HttpClient
from gia.collectors.relay import RELAY_ENV
from gia.korea import export_relay
from gia.pipeline import collect
from gia.store import Store
from tests.conftest import NOW, make_source
from tests.test_pipeline import _bundle, _http


def _korea_board():
    src = make_source("jinju_board", "local_gov", type="html_list", list_url="https://site.example.org/board/list",
                      row_selector="table.board tbody tr", title_selector="td.title a", date_selector="td.date",
                      detail={"body_selector": "div.content", "attachment_selector": "a.file"})
    src.name = "경남인재평생교육진흥원"
    src.korea_only = True
    return src


def _blocked(settings, seen: list[str]):
    """GitHub 러너: 해외 IP 라 사이트가 모두 막힌다."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(403)
    return HttpClient(settings.collector, transport=httpx.MockTransport(handler))


def _export(settings, bundle, prev=None):
    http = _http(settings)
    try:
        return export_relay(bundle, http, NOW, NOW.date() - timedelta(days=14), prev=prev)
    finally:
        http.close()


def test_relay_round_trip(settings, tmp_path, monkeypatch):
    bundle = _bundle(settings, [_korea_board()])
    relay = _export(settings, bundle)
    entry = relay["sources"]["jinju_board"]
    assert entry["status"] == "ok" and len(entry["items"]) == 3  # 판별은 GitHub 수집이 한다
    attach = next(it for it in entry["items"] if "디지털 문해" in it["title"])
    assert "2026. 10. 15." in attach["body_text"]  # 첨부(HWPX) 글을 한국 PC 에서 붙여 둔다
    blob = json.dumps(relay, ensure_ascii=False)
    assert "055-" not in blob  # 공개 브랜치에 올라가므로 전화번호는 가린다

    path = tmp_path / "relay.json"
    path.write_text(json.dumps(relay, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv(RELAY_ENV, str(path))
    seen: list[str] = []
    store = Store(tmp_path / "data")
    run = collect(bundle, store, _blocked(settings, seen), now=NOW + timedelta(hours=1))

    assert seen == []  # 사이트도 첨부도 다시 열지 않는다
    res = run.sources[0]
    assert res.status == "ok" and res.new == 2
    post = next(p for p in store.values() if "디지털 문해" in p.title)
    assert post.deadline.isoformat() == "2026-10-15T17:00:00+09:00"
    assert post.sources[0].source_id == "jinju_board"


def test_missing_or_stale_relay_is_skipped_not_failed(settings, tmp_path, monkeypatch):
    """PC 가 꺼진 날은 '건너뜀'이다. 실패로 세면 --hold-if-degraded 가 그날 메일을 미룬다."""
    bundle = _bundle(settings, [_korea_board()])
    monkeypatch.setenv(RELAY_ENV, str(tmp_path / "none.json"))
    run = collect(bundle, Store(tmp_path / "a"), _blocked(settings, []), now=NOW)
    assert run.sources[0].status == "skipped" and "한국 PC" in run.sources[0].errors[0]

    old = {"generated_at": (NOW - timedelta(days=2)).isoformat(), "sources": {"jinju_board": {"status": "ok", "items": []}}}
    (tmp_path / "old.json").write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setenv(RELAY_ENV, str(tmp_path / "old.json"))
    run = collect(bundle, Store(tmp_path / "b"), _blocked(settings, []), now=NOW)
    assert run.sources[0].status == "skipped" and "오래됨" in run.sources[0].errors[0]


def test_failure_on_korea_pc_is_reported_as_fail(settings, tmp_path, monkeypatch):
    bundle = _bundle(settings, [_korea_board()])
    relay = {"generated_at": NOW.isoformat(),
             "sources": {"jinju_board": {"status": "fail", "error": "ConnectTimeout: 시간 초과", "items": []}}}
    (tmp_path / "r.json").write_text(json.dumps(relay), encoding="utf-8")
    monkeypatch.setenv(RELAY_ENV, str(tmp_path / "r.json"))
    run = collect(bundle, Store(tmp_path / "data"), _blocked(settings, []), now=NOW)
    assert run.sources[0].status == "fail" and "한국 PC 에서 실패" in run.sources[0].errors[0]


def test_without_relay_env_reads_site_directly(settings, tmp_path, monkeypatch):
    """국내 PC 에서 손으로 돌릴 때(GIA_KOREA_RELAY 없음)는 korea_only 소스도 사이트를 바로 읽는다."""
    monkeypatch.delenv(RELAY_ENV, raising=False)
    bundle = _bundle(settings, [_korea_board()])
    run = collect(bundle, Store(tmp_path / "data"), _http(settings), now=NOW)
    assert run.sources[0].status == "ok" and run.sources[0].new == 2


def test_export_reuses_previous_details(settings):
    bundle = _bundle(settings, [_korea_board()])
    first = _export(settings, bundle)
    calls: list[str] = []
    inner = _http(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return inner._client._transport.handle_request(request)

    http = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    try:
        second = export_relay(bundle, http, NOW, NOW.date() - timedelta(days=14), prev=first)
    finally:
        http.close()
        inner.close()
    assert "/board/view" not in calls  # 목록만 다시 읽고, 이미 읽은 글의 상세는 다시 열지 않는다
    assert len(second["sources"]["jinju_board"]["items"]) == 3


def test_kr_proxy_reads_korea_only_site_when_no_relay(settings, tmp_path, monkeypatch):
    """국내 중계(KR_PROXY_URL)가 있고 한국 PC 기록이 없으면 건너뛰지 말고 사이트를 읽는다."""
    monkeypatch.setenv(RELAY_ENV, str(tmp_path / "none.json"))
    monkeypatch.setenv("KR_PROXY_URL", "http://u:p@1.2.3.4:8888")
    bundle = _bundle(settings, [_korea_board()])
    run = collect(bundle, Store(tmp_path / "data"), _http(settings), now=NOW)
    assert run.sources[0].status == "ok" and run.sources[0].new == 2
