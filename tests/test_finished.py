"""같은 게시판에 합격자·전형 결과 공고가 올라오면 앞의 모집 공고를 닫는다 (pipeline.close_finished)."""
from datetime import date, timedelta

from gia.models import SourceRef, Status
from gia.pipeline import SourceOutcome, close_finished
from gia.models import SourceRunResult
from gia.report.gangsaitda import removed_entries
from gia.store import Store
from tests.conftest import NOW, make_posting

URL = "https://www.gimhae.go.kr/view?no="


def _put(store: Store, no: int, title: str, posted: date, source: str = "gimhae", days_left: int = 50):
    p = make_posting(title, org="김해시", deadline=NOW + timedelta(days=days_left), now=NOW - timedelta(days=30),
                     sources=[SourceRef(source_id=source, url=f"{URL}{no}", fetched_at=NOW - timedelta(days=30))])
    p.posted_at = posted
    store.upsert(p)
    return p


def test_stored_result_notice_closes_recruitment(tmp_path):
    store = Store(tmp_path / "data")
    rec = _put(store, 110069, "진영한빛도서관 평생학습강좌 강사 채용 공고", date(2026, 9, 18))
    other = _put(store, 1, "장유도서관 평생학습강좌 강사 채용 공고", date(2026, 9, 18))
    _put(store, 110848, "진영한빛도서관 2027년도 평생학습강좌 강사 채용 최종합격자 공고", date(2026, 10, 30))
    assert close_finished(store, [], NOW) == 1
    assert rec.removed_at == NOW and other.removed_at is None
    assert [e["url"] for e in removed_entries(store, NOW)] == [f"{URL}110069"]


def test_result_seen_this_run_closes_recruitment(tmp_path):
    store = Store(tmp_path / "data")
    rec = _put(store, 5, "장유도서관 2027년 평생학습강좌 교육강사 채용 공고", date(2026, 9, 20))
    oc = SourceOutcome(result=SourceRunResult(source_id="gimhae"))
    oc.result_titles.append("장유도서관 2027년 평생학습강좌 교육강사 채용 서류전형 결과 및 면접시험 계획 공고")
    assert close_finished(store, [oc], NOW) == 1
    assert rec.removed_at == NOW


def test_does_not_close_wrong_ones(tmp_path):
    store = Store(tmp_path / "data")
    other_board = _put(store, 1, "진영한빛도서관 평생학습강좌 강사 채용 공고", date(2026, 9, 18), source="gne")
    short = _put(store, 2, "강사 채용 공고", date(2026, 9, 18))                       # 너무 짧아 비교 안 함
    later = _put(store, 3, "진영한빛도서관 평생학습강좌 강사 채용", date(2026, 11, 5))  # 결과 뒤에 다시 모집
    second = _put(store, 4, "진영한빛도서관 평생학습강좌 강사 2차 채용 공고", date(2026, 9, 18))
    expired = _put(store, 6, "진영한빛도서관 평생학습강좌 강사 모집 공고", date(2026, 9, 1))
    expired.status = Status.expired
    _put(store, 110848, "진영한빛도서관 2027년도 평생학습강좌 강사 채용 최종합격자 공고", date(2026, 10, 30))
    _put(store, 110849, "강사 채용 합격자 발표", date(2026, 10, 30))
    assert close_finished(store, [], NOW) == 0
    assert all(p.removed_at is None for p in (other_board, short, later, second, expired))
