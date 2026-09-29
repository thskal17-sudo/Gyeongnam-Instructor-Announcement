from datetime import timedelta

from gia.models import Status
from gia.store import Store
from tests.conftest import NOW, make_posting


def test_roundtrip(tmp_path):
    s = Store(tmp_path)
    p = make_posting("강사 모집", deadline=NOW + timedelta(days=10))
    s.upsert(p)
    s.state["last_run_at"] = NOW.isoformat()
    s.save()
    s2 = Store(tmp_path).load()
    assert s2.get(p.canonical_key).title == "강사 모집"
    assert s2.by_url(p.sources[0].url) is not None
    assert (tmp_path / "postings" / "2026-09.jsonl").exists()


def test_status_transitions(tmp_path):
    s = Store(tmp_path)
    soon = make_posting("A 강사", deadline=NOW + timedelta(days=2))
    later = make_posting("B 강사", deadline=NOW + timedelta(days=20))
    past = make_posting("C 강사", deadline=NOW - timedelta(days=1))
    for p in (soon, later, past):
        s.upsert(p)
    s.refresh_statuses(NOW, 3)
    assert s.get(past.canonical_key).status == Status.expired
    assert s.get(soon.canonical_key).status == Status.new  # 아직 보고 전
    s.mark_reported([soon.canonical_key, later.canonical_key], NOW, 3)
    assert s.get(soon.canonical_key).status == Status.closing_soon
    assert s.get(later.canonical_key).status == Status.active
    assert s.state["last_report_at"] == NOW.isoformat()


def _posting(**kw):
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from gia.models import OrgType, Posting, SourceRef, Status
    KST = ZoneInfo("Asia/Seoul")
    base = dict(
        id="x1", canonical_key="x1", title="강사 모집",
        org_name="하동군", org_type=OrgType.local_gov,
        posted_at=date(2026, 9, 11),
        first_seen_at=datetime(2026, 9, 21, tzinfo=KST), last_seen_at=datetime(2026, 9, 21, tzinfo=KST),
        status=Status.active, relevance_score=80,
        sources=[SourceRef(source_id="hadong", url="https://example.org/1",
                           fetched_at=datetime(2026, 9, 21, tzinfo=KST))],
    )
    base.update(kw)
    return Posting(**base)


def test_sanitize_deadline_clears_contract_end_date():
    """계약기간 종료일이 마감일로 남은 옛 기록은 미상으로 되돌린다."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from gia.models import DeadlineType
    from gia.store import sanitize_deadline
    KST = ZoneInfo("Asia/Seoul")

    # 게시 2026-09-11 기준 +384일 — 유효 구간(+365일) 밖
    p = _posting(deadline=datetime(2027, 9, 30, 23, 59, tzinfo=KST),
                 deadline_type=DeadlineType.fixed, deadline_text="2027. 9. 30.")
    assert sanitize_deadline(p) is True
    assert p.deadline is None
    assert p.deadline_type == DeadlineType.unknown
    assert p.deadline_text is None
    assert "마감일무효" in p.flags
    # 두 번 돌려도 플래그가 늘지 않는다
    assert sanitize_deadline(p) is False
    assert p.flags.count("마감일무효") == 1


def test_sanitize_deadline_clears_far_past_regulation_year():
    """근거 규정 연도가 마감일로 잡힌 기록도 마찬가지."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from gia.models import DeadlineType
    from gia.store import sanitize_deadline
    KST = ZoneInfo("Asia/Seoul")

    p = _posting(posted_at=date(2026, 9, 21),
                 deadline=datetime(2017, 12, 31, 23, 59, tzinfo=KST),
                 deadline_type=DeadlineType.fixed, deadline_text="2017.12.31.")
    assert sanitize_deadline(p) is True
    assert p.deadline is None


def test_sanitize_deadline_keeps_valid_ones():
    """유효 구간 안의 마감일과 마감일 없는 기록은 건드리지 않는다."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from gia.models import DeadlineType
    from gia.store import sanitize_deadline
    KST = ZoneInfo("Asia/Seoul")

    ok = _posting(deadline=datetime(2026, 10, 2, 12, 0, tzinfo=KST),
                  deadline_type=DeadlineType.fixed, deadline_text="2026. 10. 2. 12:00")
    assert sanitize_deadline(ok) is False
    assert ok.deadline is not None
    assert ok.flags == []

    none = _posting(deadline=None)
    assert sanitize_deadline(none) is False
    assert none.flags == []


def test_drop_moves_url_to_excluded(tmp_path):
    """지운 공고의 주소는 제외 목록으로 가야 한다. 안 그러면 다음 수집이 다시 주워 온다."""
    s = Store(tmp_path)
    p = make_posting("창원시 청원경찰 채용시험 계획 공고", deadline=NOW + timedelta(days=10))
    s.upsert(p)
    s.save()

    url = p.sources[0].url
    assert s.drop(p.canonical_key) is not None
    assert s.get(p.canonical_key) is None
    assert url not in s.seen_urls
    assert url in s.excluded_urls
    s.save()

    s2 = Store(tmp_path).load()
    assert s2.get(p.canonical_key) is None
    assert url in s2.excluded_urls
    assert s2.drop(p.canonical_key) is None, "없는 공고를 지워도 터지지 않는다"
