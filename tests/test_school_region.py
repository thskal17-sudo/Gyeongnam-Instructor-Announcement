"""시군 채우기 (gia/school_region.py): 수집처 이름, 나이스 학교 주소, 학교 이름 앞부분."""
import json

import httpx

from gia.models import OrgType, SourceRef
from gia.report.gangsaitda import region_label
from gia.school_region import SchoolRegions, fill_siguns, sigun_from_address, sigun_from_prefix
from tests.conftest import NOW, make_posting

NEIS = {
    "동포초등학교": ["경상남도 창녕군 남지읍 동포5길 17"],
    "칠원고등학교": ["경상남도 함안군 칠서면 삼칠로 281"],
    "중앙초등학교": ["경상남도 거제시 a", "경상남도 사천시 b"],  # 같은 이름이 두 시군에 → 쓰지 않는다
}


def _neis(calls: list[str], status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("SCHUL_NM")
        calls.append(name)
        assert request.url.params.get("ATPT_OFCDC_SC_CODE") == "S10"
        if status != 200:
            return httpx.Response(status)
        rows = [{"SCHUL_NM": name, "ORG_RDNMA": a} for a in NEIS.get(name, [])]
        body = {"schoolInfo": [{"head": [{"list_total_count": len(rows)}]}, {"row": rows}]} if rows else {"RESULT": {"CODE": "INFO-200"}}
        return httpx.Response(200, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def _school(org: str, source: str = "gne"):
    return make_posting(f"{org} 시간강사 모집", org=org, org_type=OrgType.edu_office, region=["경남"],
                        sources=[SourceRef(source_id=source, url=f"https://x.org/{org}", fetched_at=NOW)])


def test_address_and_prefix():
    assert sigun_from_address("경상남도 창녕군 남지읍 동포5길 17") == "창녕"
    assert sigun_from_address("경상남도 창원시 마산합포구 x") == "창원"
    assert sigun_from_address("부산광역시 해운대구") is None
    assert sigun_from_prefix("김해생명과학고") == "김해" and sigun_from_prefix("마산고") == "창원"
    assert sigun_from_prefix("진해여고") == "창원" and sigun_from_prefix("동포초") is None


def test_fills_schools_from_neis_and_caches(tmp_path):
    calls: list[str] = []
    schools = SchoolRegions(tmp_path / "school_regions.json", _neis(calls))
    dongpo, chilwon, masan, twin, unknown = (_school(o) for o in ("동포초", "칠원고", "마산고", "중앙초", "모르는초"))
    office = _school("창녕교육지원청")  # 학교가 아니면 묻지 않는다
    n = fill_siguns([dongpo, chilwon, masan, twin, unknown, office], {"gne": "경남교육청 구인구직포털"}, schools)
    assert n == 3
    assert dongpo.region == ["경남", "창녕"] and region_label(dongpo.region) == "경남 창녕군"
    assert chilwon.region == ["경남", "함안"]
    assert masan.region == ["경남", "창원"]  # 나이스에 없으면 이름 앞부분
    assert twin.region == ["경남"] and unknown.region == ["경남"] and office.region == ["경남"]
    assert "창녕교육지원청" not in " ".join(calls)

    schools.save()
    saved = json.loads((tmp_path / "school_regions.json").read_text(encoding="utf-8"))
    assert saved["동포초등학교"] == "창녕" and saved["모르는초등학교"] == ""

    # 다음 실행: 이미 물어본 학교는 다시 묻지 않는다
    calls.clear()
    again = SchoolRegions(tmp_path / "school_regions.json", _neis(calls))
    p = _school("동포초")
    fill_siguns([p], {"gne": "경남교육청 구인구직포털"}, again)
    assert p.region == ["경남", "창녕"] and calls == []


def test_neis_down_falls_back_to_prefix_and_stops_asking(tmp_path):
    calls: list[str] = []
    schools = SchoolRegions(tmp_path / "s.json", _neis(calls, status=503))
    kimhae, dongpo, chilwon = _school("김해중"), _school("동포초"), _school("칠원고")
    fill_siguns([kimhae, dongpo, chilwon], {}, schools)
    assert kimhae.region == ["경남", "김해"] and dongpo.region == ["경남"]
    assert len(calls) == 1  # 한 번 실패하면 이번 실행에서는 더 묻지 않는다
    schools.save()
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8")) == {}  # 실패는 남기지 않는다 (다음에 다시)


def test_city_office_source_name_and_existing_sigun(tmp_path):
    schools = SchoolRegions(tmp_path / "s.json", _neis([]))
    city = make_posting("평생학습 강사 모집", org="김해시", region=["경남"],
                        sources=[SourceRef(source_id="gimhae", url="https://x.org/g", fetched_at=NOW)])
    known = make_posting("강사 모집", org="진주시", region=["경남", "진주"],
                         sources=[SourceRef(source_id="gimhae", url="https://x.org/k", fetched_at=NOW)])
    portal = make_posting("강사 모집", org="어딘가", region=["경남"],
                          sources=[SourceRef(source_id="work24", url="https://x.org/w", fetched_at=NOW)])
    fill_siguns([city, known, portal], {"gimhae": "김해시", "work24": "고용24"}, schools)
    assert city.region == ["경남", "김해"] and region_label(city.region) == "경남 김해시"
    assert known.region == ["경남", "진주"]  # 이미 있으면 그대로
    assert portal.region == ["경남"]
