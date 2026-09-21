from datetime import date, timedelta

from gia.dedupe import canonical_key, find_duplicate, merge
from gia.models import SourceRef, Status
from tests.conftest import NOW, make_posting


def test_canonical_key_ignores_flags():
    assert canonical_key("경남TP", "[재공고] 강사 모집") == canonical_key("경남 TP", "강사 모집")


def test_fuzzy_duplicate_same_org():
    a = make_posting("2026년 하반기 시민강좌 강사 모집 공고", posted_at=date(2026, 9, 20))
    b = make_posting("2026년 하반기 시민강좌 강사 모집", posted_at=date(2026, 9, 21))
    assert find_duplicate(b, [a]) is a


def test_not_duplicate_different_org_or_far_date():
    a = make_posting("시민강좌 강사 모집", org="창원시", posted_at=date(2026, 9, 1))
    b = make_posting("시민강좌 강사 모집", org="김해시", posted_at=date(2026, 9, 1))
    c = make_posting("시민강좌 강사 모집 공고", org="창원시", posted_at=date(2026, 9, 20))  # 유사 일치 경로, 날짜 창 초과
    assert find_duplicate(b, [a]) is None
    assert find_duplicate(c, [a]) is None


def test_merge_extends_deadline_and_adds_source():
    a = make_posting("강사 모집", deadline=NOW + timedelta(days=5))
    b = make_posting("강사 모집", deadline=NOW + timedelta(days=12), sources=[SourceRef(source_id="other", url="https://x.org/1", fetched_at=NOW)], flags=["연장"])
    merged, changed = merge(a, b, NOW + timedelta(days=1))
    assert changed
    assert merged.deadline == b.deadline
    assert {s.source_id for s in merged.sources} == {"src", "other"}
    assert "연장" in merged.flags


def test_merge_without_change():
    a = make_posting("강사 모집", deadline=NOW + timedelta(days=5))
    b = make_posting("강사 모집", deadline=NOW + timedelta(days=5))
    merged, changed = merge(a, b, NOW)
    assert not changed and merged.status == Status.new
