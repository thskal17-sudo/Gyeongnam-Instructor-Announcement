"""원문에서 내려간 공고 찾기 (pipeline.check_removed) 와 강사잇다용 removed.json (gangsaitda.removed_entries)."""
from datetime import timedelta

import httpx

from gia.collectors.base import HttpClient
from gia.config import ConfigBundle
from gia.models import SourceRef, Status
from gia.pipeline import collect
from gia.report.build import select_postings
from gia.report.gangsaitda import removed_entries, select_postings as gangsaitda_postings
from gia.store import Store
from tests.conftest import NOW, make_posting, make_source

BASE = "https://gne.example.org"
LIST = f"""<table class="list"><tbody>
<tr><td class="tl"><a href="{BASE}/view?id=1">초등 방과후 코딩 강사 모집</a></td><td class="date">2026.09.20</td></tr>
</tbody></table>"""
VIEW_OK = '<html><body><div class="prgr-bd-view">본문: 강사를 모집합니다.</div></body></html>'
VIEW_ERROR = "<html><body><h1>사이트 오류</h1><p>요청하신 페이지를 찾을 수 없습니다.</p></body></html>"


def _source(removed_check: bool = True, gone_status: list[int] | None = None):
    detail = {"body_selector": "div.prgr-bd-view", "removed_check": removed_check}
    if gone_status:
        detail["gone_status"] = gone_status
    return make_source("gne", "edu_office", type="html_list", list_url=f"{BASE}/list",
                       row_selector="table.list tbody tr", title_selector="td.tl a", date_selector="td.date",
                       keywords=["강사"], detail=detail)


def _http(settings, pages: dict[str, httpx.Response]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list":
            return httpx.Response(200, text=LIST, headers={"content-type": "text/html; charset=utf-8"})
        key = request.url.params.get("id")
        if key in pages:
            return pages[key]
        return httpx.Response(200, text=VIEW_OK, headers={"content-type": "text/html; charset=utf-8"})
    return HttpClient(settings.collector, transport=httpx.MockTransport(handler))


def _old(store: Store, key: str, title: str, days_left: int = 3, **kw):
    """지난 수집에서 저장된 gne 공고 (이번 목록에는 없음)."""
    p = make_posting(title, org=f"{title[:4]}초", deadline=NOW + timedelta(days=days_left),
                     now=NOW - timedelta(days=2),
                     sources=[SourceRef(source_id="gne", url=f"{BASE}/view?id={key}", fetched_at=NOW - timedelta(days=2))],
                     body_excerpt="본문", **kw)
    store.upsert(p)
    return p


def _html(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "text/html; charset=utf-8"})


def test_marks_deleted_posting_and_keeps_others(settings, tmp_path):
    store = Store(tmp_path / "data")
    gone = _old(store, "9", "11월 전일제 강사 모집 공고")            # 학교가 지움 → 오류 화면
    alive = _old(store, "8", "늘봄 프로그램 강사 모집")                # 목록 밖으로 밀렸지만 상세는 그대로
    flaky = _old(store, "7", "돌봄교실 강사 채용")                     # 서버 오류 → 알 수 없음
    missing = _old(store, "6", "방과후 영어 강사 모집")                # 없는 글(404)
    pages = {"9": _html(VIEW_ERROR), "7": httpx.Response(503), "6": httpx.Response(404)}
    bundle = ConfigBundle(settings=settings, sources=[_source()], aliases={})

    run = collect(bundle, store, _http(settings, pages), now=NOW)

    result = next(s for s in run.sources if s.source_id == "gne")
    assert result.status == "ok" and result.removed == 2
    assert run.totals["removed"] == 2
    assert store.get(gone.canonical_key).removed_at == NOW
    assert store.get(missing.canonical_key).removed_at == NOW
    assert store.get(alive.canonical_key).removed_at is None
    assert store.get(flaky.canonical_key).removed_at is None

    # 저장했다 다시 읽어도 남는다
    store.save()
    again = Store(tmp_path / "data").load()
    assert again.get(gone.canonical_key).removed_at == NOW

    # 리포트·강사잇다 양식에서 빠지고, removed.json 에 원문 주소가 실린다
    keys = select_postings(bundle, again, NOW).keys()
    assert gone.canonical_key not in keys and alive.canonical_key in keys
    assert gone.canonical_key not in {p.canonical_key for p in gangsaitda_postings(again, NOW)}
    entries = removed_entries(again, NOW)
    assert {e["url"] for e in entries} == {f"{BASE}/view?id=9", f"{BASE}/view?id=6"}
    assert entries[0]["title"] and entries[0]["org"]


def test_reappearing_posting_is_unmarked(settings, tmp_path):
    store = Store(tmp_path / "data")
    p = _old(store, "1", "초등 방과후 코딩 강사 모집", removed_at=NOW - timedelta(hours=6))
    bundle = ConfigBundle(settings=settings, sources=[_source()], aliases={})
    collect(bundle, store, _http(settings, {}), now=NOW)  # id=1 이 목록에 다시 있다
    assert store.get(p.canonical_key).removed_at is None


def test_skips_when_control_detail_is_not_readable(settings, tmp_path):
    """지금 목록에 있는 공고의 상세도 본문 칸이 없으면(사이트 구조 변경) 아무것도 표시하지 않는다."""
    store = Store(tmp_path / "data")
    p = _old(store, "9", "11월 전일제 강사 모집 공고")
    pages = {"1": _html(VIEW_ERROR), "9": _html(VIEW_ERROR)}
    bundle = ConfigBundle(settings=settings, sources=[_source()], aliases={})
    run = collect(bundle, store, _http(settings, pages), now=NOW)
    result = next(s for s in run.sources if s.source_id == "gne")
    assert result.removed == 0 and store.get(p.canonical_key).removed_at is None
    assert any("건너뜀" in e for e in result.errors)


def test_refuses_mass_removal(settings, tmp_path):
    store = Store(tmp_path / "data")
    olds = [_old(store, str(10 + i), f"학교{i} 시간강사 모집 공고") for i in range(6)]
    pages = {str(10 + i): _html(VIEW_ERROR) for i in range(6)}
    bundle = ConfigBundle(settings=settings, sources=[_source()], aliases={})
    run = collect(bundle, store, _http(settings, pages), now=NOW)
    result = next(s for s in run.sources if s.source_id == "gne")
    assert result.removed == 0 and all(store.get(p.canonical_key).removed_at is None for p in olds)
    assert any("너무 많아" in e for e in result.errors)


def test_off_unless_configured_and_ignores_closed(settings, tmp_path):
    store = Store(tmp_path / "data")
    p = _old(store, "9", "11월 전일제 강사 모집 공고")
    closed = _old(store, "5", "지난 강사 모집", days_left=-1, status=Status.expired)
    bundle = ConfigBundle(settings=settings, sources=[_source(removed_check=False)], aliases={})
    collect(bundle, store, _http(settings, {"9": _html(VIEW_ERROR), "5": _html(VIEW_ERROR)}), now=NOW)
    assert store.get(p.canonical_key).removed_at is None

    bundle = ConfigBundle(settings=settings, sources=[_source()], aliases={})
    collect(bundle, store, _http(settings, {"9": _html(VIEW_ERROR), "5": _html(VIEW_ERROR)}), now=NOW)
    assert store.get(p.canonical_key).removed_at == NOW
    assert store.get(closed.canonical_key).removed_at is None  # 마감 지난 공고는 확인하지 않는다


def test_removed_entries_drop_old_and_closed(tmp_path):
    store = Store(tmp_path / "data")
    recent = _old(store, "1", "최근 내려간 강사 공고", removed_at=NOW - timedelta(days=1))
    _old(store, "2", "오래전에 내려간 강사 공고", days_left=30, removed_at=NOW - timedelta(days=20))
    _old(store, "3", "마감 지난 강사 공고", days_left=-1, removed_at=NOW - timedelta(days=1))
    assert [e["url"] for e in removed_entries(store, NOW)] == [recent.primary_url]


def test_server_error_counts_as_gone_only_when_configured(settings, tmp_path):
    """경남교육청 포털은 지워진 공고를 HTTP 500 으로 돌려준다 (2026-11-02). gone_status: [500] 인 소스만 사라짐으로 본다."""
    error_page = httpx.Response(500, text="<html><title>SERVER ERROR</title><body>서버 오류가 발생했습니다!</body></html>")

    store = Store(tmp_path / "a")
    p = _old(store, "9", "11월 전일제 강사 모집 공고")
    bundle = ConfigBundle(settings=settings, sources=[_source()], aliases={})
    collect(bundle, store, _http(settings, {"9": error_page}), now=NOW)
    assert store.get(p.canonical_key).removed_at is None  # 설정이 없으면 서버 오류는 '알 수 없음'

    store = Store(tmp_path / "b")
    p = _old(store, "9", "11월 전일제 강사 모집 공고")
    bundle = ConfigBundle(settings=settings, sources=[_source(gone_status=[500])], aliases={})
    run = collect(bundle, store, _http(settings, {"9": error_page}), now=NOW)
    assert store.get(p.canonical_key).removed_at == NOW
    assert next(s for s in run.sources if s.source_id == "gne").removed == 1
