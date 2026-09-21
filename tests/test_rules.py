import pytest

from gia.classify.rules import guess_employment, guess_field, score_posting

INCLUDE = [
    ("2026년 하반기 평생학습관 시민강좌 강사 모집", "근무지: 창원시 평생학습관. 강의 가능한 분", None),
    ("한국폴리텍VII대학 진주캠퍼스 2학기 시간강사 채용 공고", "", "경남"),
    ("늘봄학교 프로그램 강사 인력풀 모집", "경남교육청 관내 초등학교 방과후 수업", None),
    ("생활체육지도자 채용 공고", "김해시 체육센터", None),
]
EXCLUDE = [
    ("2026 시민강좌 수강생 모집 안내", "강사: 홍길동", "경남"),
    ("강사 합격자 발표", "", "경남"),
    ("체육시설 물품 구매 입찰 공고", "강사 휴게실 비품", "경남"),
    ("2026년 하반기 시간강사 모집", "근무지: 부산광역시 해운대구", "부산"),
]


@pytest.mark.parametrize("title,body,region", INCLUDE)
def test_include(title, body, region):
    assert score_posting(title, body, region).score >= 70


@pytest.mark.parametrize("title,body,region", EXCLUDE)
def test_exclude(title, body, region):
    assert score_posting(title, body, region).score < 30


def test_service_contract_not_penalized():
    r = score_posting("2026 직원 교육 운영 용역 입찰 공고 (강사 운영 포함)", "강의 운영 업체 모집", "경남")
    assert not any("조달어" in x for x in r.reasons)


def test_field_and_employment():
    assert guess_field("디지털배움터 스마트폰 교육 강사", "") == "it_digital"
    assert guess_field("수영 강사 모집", "체육센터") == "sports"
    assert guess_employment("시간강사 모집", "") == "시간강사"
    assert guess_employment("외부강사 위촉 공고", "") == "프리랜서"
