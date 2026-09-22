from gia.normalize import clean_url, extract_regions, mask_pii, norm_key, normalize_title, standardize_org


def test_title_flags():
    t, flags = normalize_title("[재공고] 2026년  하반기 시민강좌 강사 모집 (긴급)")
    assert t == "2026년 하반기 시민강좌 강사 모집"
    assert flags == ["긴급", "재공고"]


def test_title_keeps_meaningful_brackets():
    t, flags = normalize_title("(창원캠퍼스) 시간강사 모집")
    assert t == "(창원캠퍼스) 시간강사 모집"
    assert flags == []


def test_norm_key_ignores_flags_and_symbols():
    assert norm_key("[재공고] 강사 모집!") == norm_key("강사  모집")


def test_org_alias():
    aliases = {"경남테크노파크": ["경남TP", "(재)경남테크노파크"]}
    assert standardize_org("경남TP", aliases) == "경남테크노파크"
    assert standardize_org("(재)경남테크노파크", aliases) == "경남테크노파크"
    assert standardize_org("재단법인 김해문화재단", aliases) == "김해문화재단"


def test_regions():
    assert extract_regions("경상남도 창원시 및 김해시 근무") == ["경남", "창원", "김해"]
    assert extract_regions("서울시 강남구") == []


def test_regions_need_suffix_or_gyeongnam_context():
    """시군 이름이 다른 단어에 섞여 있을 때 지역으로 잡지 않는다 (2026-09-22 실수집 오탐)."""
    assert extract_regions("고성능 빔프로젝터를 쓰는 김해시 도서관 강좌") == ["김해"]
    assert extract_regions("제품 대량 양산 라인") == []
    assert extract_regions("거창한 규모의 남해안 축제") == []
    assert extract_regions("최고성적 우수자 / 사천원 지급") == []
    assert extract_regions("근무지: 경남 고성") == ["경남", "고성"]
    assert extract_regions("고성군청 평생학습관") == ["고성"]


def test_mentions_gyeongnam():
    from gia.normalize import mentions_gyeongnam
    assert mentions_gyeongnam("양산시 소재")
    assert not mentions_gyeongnam("대량 양산 공정")


def test_mask_pii():
    out = mask_pii("문의 055-123-4567 / hong@example.com")
    assert "055" not in out and "@" not in out


def test_clean_url():
    assert clean_url("HTTPS://Example.org/a?b=1&utm_source=x#frag") == "https://example.org/a?b=1"
