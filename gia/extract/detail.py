"""상세 본문에서 강사잇다 양식 칸을 뽑는다 (규칙 기반).

학교 공고는 '나. 채용인원 : 1명', '2.계약기간: 2026년 10월 16일 ~ …' 처럼 항목 이름
뒤에 값을 적는 형식이 대부분이다. 항목 이름으로 시작하는 줄을 찾아 같은 줄의 값을
쓰고, 값이 비었으면 이어지는 글머리 줄(◦ ○ - ·)을 모은다.

못 찾으면 빈 값을 돌려준다. 지어내지 않는다 — 빈 필수 칸은 양식의 '처리=보류'로
넘겨 사람이 원문을 보고 채우게 한다.
"""
from __future__ import annotations

import re
from datetime import date

# 줄 머리의 번호·글머리: '2.', '나.', '1)', '(1)', '①', '◦', '○', '-', '※' …
_PREFIX = r"^\s*(?:\(?\d{1,2}[.)]|[가-하][.)]|[①-⑳]|[○◦•·∙\-\*※□■▶►▪])?\s*"
_SEP = r"\s*[:：]\s*"
# 다음 항목의 시작으로 보는 줄: 번호·가나다 머리
_NEXT_ITEM = re.compile(r"^\s*(?:\d{1,2}[.)]|[가-하][.)]|\(\d{1,2}\)|[①-⑳])\s*\S")
_BULLET = re.compile(r"^\s*[○◦•·∙\-\*▪]\s*")

_SCHEDULE_PERIOD = [
    r"계약\s*기간", r"임용\s*기간", r"근무\s*기간", r"운영\s*기간", r"수업\s*기간", r"강의\s*기간",
    r"교육\s*기간", r"위촉\s*기간", r"활동\s*기간", r"강좌\s*기간", r"(?:수업|강의|교육|운영|근무)\s*일시",
    # 학교 공고는 '채용기간'이 근무 기간이다(접수는 '접수기간'). 맨 끝의 '기간'은 '3. 기간: …' 꼴 —
    # 줄 머리에서만 맞추므로 '접수기간'·'공고 기간'·'기간제' 에는 걸리지 않는다
    r"채용\s*기간", r"기\s*간",
]
# 표로 된 공고는 칸 이름과 값이 따로 떨어져 '2026.10. 1. ~ 2026.12.31.' 만 한 줄로 남는다
_RANGE_LINE = re.compile(
    r"^\D{0,4}(?P<y>20\d{2})\s*[.년/-]\s*(?P<m>\d{1,2})\s*[.월/-]\s*(?P<d>\d{1,2})[^~∼～]{0,12}[~∼～]\s*\S"
)
_DATEISH = re.compile(r"\d{1,2}\s*[.월/]\s*\d{1,2}")
_NOT_SCHEDULE = re.compile(r"접수|공고|서류|면접|발표|전형|제출|게시|등록|결과")
_SCHEDULE_TIME = [r"(?:수업|강의|근무|운영|교육)\s*(?:시간|요일)", r"근무\s*형태"]
_TARGET = [r"(?:수업|교육|운영|수강|참여|프로그램)\s*대상", r"대상\s*(?:학생|학년)", r"대상"]
_HEADCOUNT = [r"(?:채용|모집|선발|위촉)\s*(?:예정\s*)?인원", r"인\s*원"]
_OFFER_LINE = re.compile(r"(?:모집|채용|선발)\s*(?:강좌|분야|과목|종목|프로그램)")
_QUALIFY = [r"(?:응모|지원|응시|채용)\s*자격", r"자격\s*(?:요건|기준|조건)", r"자\s*격"]
_DOCS = [r"제출\s*서류", r"구비\s*서류", r"제출\s*서식", r"제출물"]

# 상세 내용에서 뺄 줄: 게시판 틀(목록·미리보기)과 가려진 연락처만 남은 줄
_NOISE_LINE = re.compile(r"^(?:목록|미리보기|이전글|다음글|첨부파일|\[전화번호\]|\[이메일\]|.{0,12}문의처\s*:?)$")
_DETAIL_MAX = 1500


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines()]


def _label_re(labels: list[str]) -> re.Pattern[str]:
    # 항목 이름 뒤에는 구분자(:)가 오거나 줄이 끝나야 한다. '대상자 선정' 같은 문장 속 낱말은 거른다
    return re.compile(_PREFIX + r"(?:" + "|".join(labels) + r")(?:" + _SEP + r"(?P<val>.*)|\s*)$")


def _labeled(text: str, labels: list[str], follow: int = 6, want: re.Pattern[str] | None = None) -> list[str]:
    """항목 값을 줄 목록으로. 같은 줄 값이 있으면 그것 하나, 없으면 이어지는 글머리 줄들.

    want 를 주면 이어지는 줄 가운데 그 꼴인 것만 받는다 — 표 머리 '기간' 아래 줄이
    다른 칸 값('물리(과학), 1명')일 수 있어서다.
    """
    lines = _lines(text)
    pat = _label_re(labels)
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if not m:
            continue
        val = (m.group("val") or "").strip()
        if val:
            return [val]
        out: list[str] = []
        for nxt in lines[i + 1:i + 1 + follow]:
            if not nxt:
                if out:
                    break
                continue
            if _NEXT_ITEM.match(nxt) and not _BULLET.match(nxt):
                break
            if want is not None and not want.search(nxt):
                continue
            out.append(_BULLET.sub("", nxt).strip())
        if out:
            return out
    return []


def _unlabeled_ranges(text: str, not_before: date) -> list[str]:
    """이름표 없는 날짜 범위 줄. 접수 마감(not_before) 이후에 시작하는 것만 — 접수·전형 기간을 거른다."""
    out: list[str] = []
    for ln in _lines(text):
        if out and not _RANGE_LINE.match(ln):
            break  # 붙어 있는 범위 줄만 모은다('11.23.~12.4.', '12.28.~12.31.')
        m = _RANGE_LINE.match(ln)
        if not m or _NOT_SCHEDULE.search(ln):
            continue
        try:
            start = date(int(m["y"]), int(m["m"]), int(m["d"]))
        except ValueError:
            continue
        if start >= not_before:
            out.append(ln)
            if len(out) == 3:
                break
    return out


def extract_schedule(text: str, not_before: date | None = None) -> str:
    """수업 일정: 기간 줄 + (있으면) 시간·요일 줄.

    not_before(보통 접수 마감일)를 주면, 이름표가 없는 표 형식 공고에서 그 뒤에 시작하는
    날짜 범위 줄을 일정으로 본다. 마감일을 모르면 이 추정은 하지 않는다.
    """
    period = _labeled(text, _SCHEDULE_PERIOD, follow=2, want=_DATEISH)[:1]
    if not period and not_before is not None:
        period = [", ".join(_unlabeled_ranges(text, not_before))]
    when = _labeled(text, _SCHEDULE_TIME, follow=1)
    parts = [p for p in (period + when[:1]) if p]
    return " / ".join(parts)[:160]


def extract_target(text: str) -> str:
    v = _labeled(text, _TARGET, follow=2)
    return " ".join(v)[:80] if v else ""


def extract_headcount(text: str) -> int | None:
    """모집 인원(숫자). '채용인원 : 1명' 이 없으면 '모집강좌: 클레이(1명),영어(1명)' 의 합."""
    for v in _labeled(text, _HEADCOUNT, follow=1):
        m = re.search(r"(\d{1,3})\s*(?:명|인)", v) or re.fullmatch(r"\s*(\d{1,3})\s*", v)
        if m:
            return int(m.group(1))
    for ln in _lines(text):
        if _OFFER_LINE.search(ln):
            nums = [int(n) for n in re.findall(r"(\d{1,3})\s*명", ln)]
            if nums:
                return sum(nums)
    return None


def extract_qualifications(text: str) -> list[str]:
    return [q for q in _labeled(text, _QUALIFY, follow=6) if q][:6]


def extract_documents(text: str) -> str:
    docs = [d for d in _labeled(text, _DOCS, follow=8) if d]
    return ", ".join(docs)[:300]


def _glue_fragments(lines: list[str]) -> list[str]:
    """글자 단위로 끊긴 줄('2026','년','9','월')을 앞 줄에 붙인다.

    본문을 span 마다 줄로 떼는 사이트가 있다(통영국제음악재단). 세 글자 이하이고 번호·글머리로
    시작하지 않는 줄만 붙인다.
    """
    out: list[str] = []
    for ln in lines:
        if out and ln and len(ln) <= 3 and not _NEXT_ITEM.match(ln) and not _BULLET.match(ln):
            out[-1] = out[-1] + ln
        else:
            out.append(ln)
    return out


def clean_detail(text: str, title: str = "") -> str:
    """상세 내용: 게시판 틀 줄을 빼고 1,500자 안쪽에서 줄 단위로 자른다."""
    out: list[str] = []
    size = 0
    for ln in _glue_fragments([ln for ln in _lines(text) if ln and not _NOISE_LINE.match(ln)]):
        if not out and title and ln.replace(" ", "") == title.replace(" ", ""):
            continue  # 본문 첫 줄이 제목을 되풀이하면 뺀다
        if size + len(ln) + 1 > _DETAIL_MAX:
            break
        out.append(ln)
        size += len(ln) + 1
    return "\n".join(out)


# ---- 제목·기관명 ------------------------------------------------------

# 제목 머리의 연도·학기: '2026. ', '2026년 ', '2026학년도 ', '[2026] ', '2026. 2학기 '
_TITLE_YEAR = re.compile(r"^\s*\[?\s*20\d{2}\s*(?:학년도|년도|년|\.)?\s*\]?\s*(?:[12]\s*학기\s*)?")
# 제목 속 날짜 괄호: '(~10.2.)', '(9.28.~10.2.)', '(10/2까지)'
_TITLE_DATE_PAREN = re.compile(
    r"\(\s*~?\s*\d{1,2}\s*[./]\s*\d{1,2}\.?\s*(?:~\s*\d{1,2}\s*[./]\s*\d{1,2}\.?)?\s*(?:까지)?\s*\)"
)


def clean_title(title: str) -> str:
    """강사잇다 양식은 제목에 날짜·기간을 넣지 말라고 한다(수업 일정 칸에 따로 적는다)."""
    t = _TITLE_YEAR.sub("", title or "")
    t = _TITLE_DATE_PAREN.sub("", t)
    return re.sub(r"\s{2,}", " ", t).strip(" -·") or (title or "").strip()


_SCHOOL_SUFFIX = [("여고", "여자고등학교"), ("여중", "여자중학교"), ("초", "초등학교"), ("중", "중학교"), ("고", "고등학교")]


def expand_school_name(org: str) -> str:
    """교육청 포털의 약칭 작성자('경해여자고', '한일여고', '대진초')를 학교 이름으로 편다."""
    if not org or org.endswith("학교") or org.endswith("교육지원청") or org.endswith("교육청"):
        return org
    for short, full in _SCHOOL_SUFFIX:
        if org.endswith(short) and len(org) > len(short):
            return org[: -len(short)] + full
    return org
