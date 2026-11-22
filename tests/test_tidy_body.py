"""본문 다듬기: HWP 에서 붙여넣은 공고문의 어긋난 공백을 되돌리고 항목 기호 앞에서 줄을 바꾼다."""
from __future__ import annotations

from gia.normalize import tidy_body

공고 = (
    "경상남도교육청 2026 년 11 월 6 일 제 2 차 공고 1. 모집분야 ○ 전일제강사 ( 체육 ) "
    "2. 응모자격 ○ 교원자격증 소지자로서 교육 · 연구경력 2 년 이상인 자 "
    "3. 접수 가 . 기간 : 2026. 11. 6.( 금 ) ~ 11. 13.( 금 ) 나 . 방법 : 방문 접수 "
    "① 이력서 1 부 ② 자기소개서 1 부"
)


def test_숫자와_단위_사이_공백을_붙인다():
    out = tidy_body(공고)
    assert "2026년 11월 6일" in out and "제2차" in out and "2년 이상인 자" in out and "이력서 1부" in out


def test_괄호와_문장부호_앞뒤_공백을_없앤다():
    out = tidy_body(공고)
    assert "(체육)" in out and "기간:" in out


def test_항목_기호_앞에서_줄을_바꾼다():
    lines = tidy_body(공고).split("\n")
    assert "1. 모집분야" in lines and "2. 응모자격" in lines and "나. 방법: 방문 접수" in lines
    assert any(ln.startswith("○ 전일제강사") for ln in lines)
    assert any(ln.startswith("① 이력서") for ln in lines)


def test_날짜_가운데에서는_줄을_바꾸지_않는다():
    assert "2026. 11. 6.(금) ~ 11. 13.(금)" in tidy_body(공고)


def test_가운뎃점은_끊지_않는다():
    assert "교육 · 연구경력" in tidy_body(공고)


def test_원래_있던_줄바꿈을_지킨다():
    """본문 셀렉터가 문단을 살려 주는 게시판이 있다 — 그 줄바꿈까지 뭉개지 않는다."""
    out = tidy_body("첫 문단입니다.\n\n둘째 문단입니다.")
    assert out.split("\n") == ["첫 문단입니다.", "둘째 문단입니다."]


def test_빈_값():
    assert tidy_body("") == "" and tidy_body(None) == ""
