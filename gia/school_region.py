"""공고의 시군을 채운다 ('경남' → '경남 창녕군').

강사잇다는 지역을 '경남 창원시' 꼴로 보여 준다(gangsaitda.region_label). 그런데 진행 중 공고의 대부분이 '경남'만 남아 있었다
(2026-11-01: 경남교육청 구인구직포털 57건 전부, 시군청 홈페이지 공고도 다수).
  - 시군청 홈페이지 공고: 글에 시군 이름이 '김해시'처럼 붙어 나오지 않으면 못 잡았다 → 수집처 이름(김해시)으로 채운다
  - 학교 공고: 포털 목록에는 학교 약칭('동포초')만 있다. '김해중'처럼 지명으로 시작해도 잘못 잡지 않으려고
    접미사 없는 지명은 인정하지 않는다(normalize.extract_regions) → 나이스 학교기본정보로 학교 주소를 찾는다

나이스(open.neis.go.kr) 학교기본정보는 인증키 없이 학교 이름 하나를 조회할 수 있다 (한 번에 5건까지, 2026-11-01 러너에서 확인:
동포초등학교 → 경상남도 창녕군 남지읍). 찾은 결과는 data/index/school_regions.json 에 남겨 같은 학교를 다시 묻지 않는다.
나이스가 안 되면 학교 이름이 시군 이름(옛 마산·진해 포함)으로 시작할 때만 그것으로 채운다. 그래도 모르면 '경남' 그대로 둔다.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx

from .extract.detail import expand_school_name
from .models import OrgType, Posting
from .normalize import SIGUN, extract_regions

log = logging.getLogger(__name__)

NEIS_URL = "https://open.neis.go.kr/hub/schoolInfo"
NEIS_GYEONGNAM = "S10"  # 경상남도교육청 시도교육청코드
# 한 번 실행에 나이스에 새로 물어볼 학교 수 (나머지는 다음 실행에서)
LOOKUP_MAX = 60
# 통합창원시 이전 지명. 학교 이름에 남아 있다 (마산고, 진해여고)
OLD_NAMES = {"마산": "창원", "진해": "창원"}

_ADDR_RE = re.compile(r"(?:경상남도|경남)\s*([가-힣]+?)(?:시|군)(?![가-힣])")


def has_sigun(p: Posting) -> bool:
    return any(r in SIGUN for r in p.region)


def sigun_from_address(address: str) -> str | None:
    """'경상남도 창녕군 남지읍 동포5길 17' → '창녕'. 경남 시군이 아니면 None."""
    m = _ADDR_RE.search(address or "")
    return m.group(1) if m and m.group(1) in SIGUN else None


def sigun_from_prefix(name: str) -> str | None:
    """학교 이름이 시군 이름으로 시작하면 그 시군 ('김해생명과학고' → '김해', '마산고' → '창원')."""
    for s in SIGUN:
        if name.startswith(s):
            return s
    for old, s in OLD_NAMES.items():
        if name.startswith(old):
            return s
    return None


class SchoolRegions:
    """학교 이름 → 시군. 나이스 조회 결과를 파일에 남긴다 (모르면 '' 로 남겨 다시 묻지 않음)."""

    def __init__(self, path: Path, client: httpx.Client | None = None):
        self.path = path
        self.client = client
        self.cache: dict[str, str] = {}
        self.lookups = 0
        self.failed = False  # 나이스가 안 되면 이번 실행에서는 더 묻지 않는다
        if path.exists():
            try:
                self.cache = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                self.cache = {}

    def lookup(self, school: str) -> str | None:
        if school in self.cache:
            return self.cache[school] or None
        if self.failed or self.lookups >= LOOKUP_MAX:
            return None
        self.lookups += 1
        try:
            client = self.client or httpx.Client(timeout=20)
            r = client.get(NEIS_URL, params={"Type": "json", "ATPT_OFCDC_SC_CODE": NEIS_GYEONGNAM, "SCHUL_NM": school})
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("[school_region] 나이스 조회 실패 %s: %s", school, e)
            self.failed = True
            return None
        info = data.get("schoolInfo") or []
        rows = info[1].get("row", []) if len(info) > 1 else []
        # 같은 이름이 여러 곳이면(드묾) 모두 같은 시군일 때만 쓴다
        found = {sigun_from_address(x.get("ORG_RDNMA", "")) for x in rows if x.get("SCHUL_NM") == school}
        sigun = found.pop() if len(found) == 1 else None
        self.cache[school] = sigun or ""
        return sigun

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def infer_sigun(p: Posting, source_name: str, schools: SchoolRegions) -> str | None:
    """시군을 모르는 공고의 시군. 수집처 이름 → (학교면) 나이스 → 학교 이름 앞부분 순으로 본다."""
    from_source = [r for r in extract_regions(source_name) if r in SIGUN]
    if len(from_source) == 1:
        return from_source[0]
    if p.org_type == OrgType.edu_office and p.org_name and not p.org_name.endswith(("교육청", "교육지원청")):
        school = expand_school_name(p.org_name)
        if school.endswith("학교"):
            return schools.lookup(school) or sigun_from_prefix(p.org_name)
    return None


def fill_siguns(postings, source_names: dict[str, str], schools: SchoolRegions) -> int:
    """시군이 없는 공고에 시군을 더한다 ('경남' 뒤에). 채운 공고 수."""
    filled = 0
    for p in postings:
        if has_sigun(p) or not p.sources:
            continue
        sigun = infer_sigun(p, source_names.get(p.sources[0].source_id, ""), schools)
        if sigun:
            p.region = [*p.region, sigun] if p.region else ["경남", sigun]
            filled += 1
    return filled
