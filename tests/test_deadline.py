from datetime import date, datetime

import pytest

from gia.extract.deadline import KST, DeadlineType, parse_deadline, parse_known_format

REF = date(2026, 9, 15)

CASES = [
    ("접수기간: 2026. 9. 22.(월) ~ 2026. 9. 30.(수) 18:00까지", datetime(2026, 9, 30, 18, 0, tzinfo=KST)),
    ("제출기한 2026.09.30.(수)", datetime(2026, 9, 30, 23, 59, tzinfo=KST)),
    ("2026년 9월 30일 18시까지 접수", datetime(2026, 9, 30, 18, 0, tzinfo=KST)),
    ("접수: 9. 22.(월) ~ 9. 30.(수)", datetime(2026, 9, 30, 23, 59, tzinfo=KST)),
    ("공고기간 2026-09-16 ~ 2026-09-25", datetime(2026, 9, 25, 23, 59, tzinfo=KST)),
    ("면접일: 2026. 10. 5.(월) / 서류 제출 마감: 2026. 9. 28.(월) 오후 6시", datetime(2026, 9, 28, 18, 0, tzinfo=KST)),
    ("접수마감 12. 3.(목) 17:00까지", datetime(2026, 12, 3, 17, 0, tzinfo=KST)),
    ("접수기간 2026.12.20 ~ 1.10 까지", datetime(2027, 1, 10, 23, 59, tzinfo=KST)),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_fixed_deadlines(text, expected):
    res = parse_deadline(text, REF)
    assert res.deadline_type == DeadlineType.fixed
    assert res.deadline == expected


def test_until_filled():
    res = parse_deadline("모집인원 충원 시까지 상시 접수", REF)
    assert res.deadline_type == DeadlineType.until_filled
    assert res.deadline is None


def test_unknown_when_only_dates_are_negative_context():
    res = parse_deadline("면접일 2026. 10. 5.(월), 합격자 발표 2026. 10. 7.(수)", REF)
    assert res.deadline is None
    assert res.deadline_type == DeadlineType.unknown


def test_partial_without_context_is_ignored():
    res = parse_deadline("강의시간은 주 1.5시간이며 3.5명 규모입니다", REF)
    assert res.deadline is None


def test_known_formats():
    assert parse_known_format("20260930") == datetime(2026, 9, 30, 23, 59, tzinfo=KST)
    assert parse_known_format("2026-09-30 18:00:00") == datetime(2026, 9, 30, 18, 0, tzinfo=KST)
    assert parse_known_format("상시") is None
