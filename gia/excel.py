"""엑셀 산출물 (공고목록·요약·수집원 현황). docs/DESIGN.md 1.3 산출물."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .config import SourceConfig
from .extract.deadline import KST
from .models import FIELD_NAMES, Posting, Status
from .stats import ORG_TYPE_NAMES

FONT = "맑은 고딕"  # 한글 업무 문서 표준 글꼴
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(name=FONT, size=10, bold=True, color="FFFFFF")
BASE_FONT = Font(name=FONT, size=10)
BOLD_FONT = Font(name=FONT, size=10, bold=True)
SECTION_FONT = Font(name=FONT, size=11, bold=True)
TITLE_FONT = Font(name=FONT, size=14, bold=True)
NOTE_FONT = Font(name=FONT, size=9, italic=True, color="666666")
LINK_FONT = Font(name=FONT, size=10, color="0563C1", underline="single")
_THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

STATUS_LABELS = {
    Status.new.value: "신규",
    Status.updated.value: "변경",
    Status.closing_soon.value: "마감임박",
    Status.active.value: "진행중",
    Status.expired.value: "마감",
}
STATUS_ORDER = ("신규", "변경", "마감임박", "진행중", "마감")
STATUS_FILLS = {
    "마감임박": PatternFill("solid", fgColor="FCE4D6"),
    "신규": PatternFill("solid", fgColor="E2EFDA"),
    "변경": PatternFill("solid", fgColor="FFF2CC"),
    "마감": PatternFill("solid", fgColor="F2F2F2"),
}


@dataclass(frozen=True)
class Column:
    header: str
    width: int
    wrap: bool = False


# 공고목록 시트의 열 정의 (순서가 곧 열 순서)
COLUMNS: Sequence[Column] = (
    Column("상태", 9),
    Column("D-day", 8),
    Column("마감일", 13),
    Column("분야", 12),
    Column("기관", 22),
    Column("공고 제목", 48, wrap=True),
    Column("지역", 12),
    Column("고용형태", 10),
    Column("강사료", 16),
    Column("한 줄 요약", 34, wrap=True),
    Column("자격요건", 30, wrap=True),
    Column("접수방법", 10),
    Column("게시일", 12),
    Column("원문 링크", 14),
    Column("출처", 20),
    Column("점수", 7),
    Column("비고", 16),
)
COL = {c.header: get_column_letter(i) for i, c in enumerate(COLUMNS, 1)}
WRAP = {c.header: c.wrap for c in COLUMNS}
HEADER_ROW = 3  # 1행 제목, 2행 기준시각, 3행 머리글
FIRST_DATA_ROW = HEADER_ROW + 1


def _naive(dt: datetime | None) -> datetime | None:
    """엑셀은 시간대 정보를 다루지 못하므로 KST 로 바꾼 뒤 시간대를 떼어 낸다."""
    return dt.astimezone(KST).replace(tzinfo=None) if dt else None


def _titles(ws: Worksheet, title: str, subtitle: str) -> None:
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws["A2"] = subtitle
    ws["A2"].font = NOTE_FONT


def build_postings_sheet(ws: Worksheet, postings: Sequence[Posting], now: datetime, source_names: dict[str, str]) -> None:
    _titles(
        ws,
        "경남 강사 구인공고",
        f"기준 {now.astimezone(KST):%Y-%m-%d %H:%M} KST · 총 {len(postings)}건 · "
        "D-day 와 요약 시트 수치는 파일을 열 때 자동으로 다시 계산됩니다",
    )
    for i, c in enumerate(COLUMNS, 1):
        cell = ws.cell(row=HEADER_ROW, column=i, value=c.header)
        cell.font, cell.fill, cell.border = HEADER_FONT, HEADER_FILL, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = c.width

    for r, p in enumerate(postings, FIRST_DATA_ROW):
        status = STATUS_LABELS.get(p.status.value, p.status.value)
        dl = COL["마감일"]
        # D-day 는 수식이라 파일을 여는 날짜 기준으로 갱신된다
        dday = f'=IF({dl}{r}="","",IF({dl}{r}<TODAY(),"마감",{dl}{r}-TODAY()))'
        posted = (
            datetime(p.posted_at.year, p.posted_at.month, p.posted_at.day) if p.posted_at else None
        )
        values = {
            "상태": status,
            "D-day": dday,
            "마감일": _naive(p.deadline),
            "분야": FIELD_NAMES.get(p.field, p.field),
            "기관": p.org_name,
            "공고 제목": p.title,
            "지역": ", ".join(p.region) or "미상",
            "고용형태": p.employment_type,
            "강사료": p.pay or "",
            "한 줄 요약": p.one_line_summary,
            "자격요건": " / ".join(p.qualifications),
            "접수방법": p.apply_method or "",
            "게시일": posted,
            "원문 링크": "원문 보기" if p.primary_url else "",
            "출처": ", ".join(dict.fromkeys(source_names.get(s.source_id, s.source_id) for s in p.sources)),
            "점수": p.relevance_score,
            "비고": ", ".join(p.flags),
        }
        for header, value in values.items():
            cell = ws[f"{COL[header]}{r}"]
            cell.value = value
            cell.font = BASE_FONT
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=WRAP[header])
        ws[f'{COL["마감일"]}{r}'].number_format = "yyyy-mm-dd"
        ws[f'{COL["게시일"]}{r}'].number_format = "yyyy-mm-dd"
        ws[f'{COL["D-day"]}{r}'].alignment = Alignment(horizontal="center", vertical="top")
        if p.primary_url:
            link = ws[f'{COL["원문 링크"]}{r}']
            link.hyperlink = p.primary_url
            link.font = LINK_FONT
        if status in STATUS_FILLS:
            ws[f'{COL["상태"]}{r}'].fill = STATUS_FILLS[status]

    last = max(FIRST_DATA_ROW, FIRST_DATA_ROW + len(postings) - 1)
    ws.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(len(COLUMNS))}{last}"
    ws.freeze_panes = f"A{FIRST_DATA_ROW}"


def _count_block(ws: Worksheet, row: int, heading: str, value_col: str, labels: Iterable[str], n: int) -> int:
    """요약 시트에 집계 표 하나를 쓰고 다음 빈 행을 돌려준다. 수치는 모두 COUNTIF 수식."""
    ws[f"A{row}"] = heading
    ws[f"A{row}"].font = SECTION_FONT
    row += 1
    for i, head in enumerate(("구분", "전체", "진행중"), 1):
        cell = ws.cell(row=row, column=i, value=head)
        cell.font, cell.fill, cell.border = HEADER_FONT, HEADER_FILL, BORDER
        cell.alignment = Alignment(horizontal="center")
    row += 1

    last = FIRST_DATA_ROW + n - 1
    target = f"'공고목록'!${value_col}${FIRST_DATA_ROW}:${value_col}${last}"
    status = f"'공고목록'!${COL['상태']}${FIRST_DATA_ROW}:${COL['상태']}${last}"
    start = row
    for label in labels:
        ws[f"A{row}"] = label
        # 부분 일치(지역은 "창원, 김해"처럼 여러 값이 한 칸에 들어간다)
        ws[f"B{row}"] = f'=COUNTIF({target},"*"&A{row}&"*")'
        ws[f"C{row}"] = f'=COUNTIFS({target},"*"&A{row}&"*",{status},"<>마감")'
        for c in "ABC":
            ws[f"{c}{row}"].font = BASE_FONT
            ws[f"{c}{row}"].border = BORDER
        row += 1
    ws[f"A{row}"] = "합계"
    ws[f"B{row}"] = f"=SUM(B{start}:B{row - 1})"
    ws[f"C{row}"] = f"=SUM(C{start}:C{row - 1})"
    for c in "ABC":
        ws[f"{c}{row}"].font = BOLD_FONT
        ws[f"{c}{row}"].border = BORDER
    return row + 2


def build_summary_sheet(ws: Worksheet, postings: Sequence[Posting], now: datetime) -> None:
    n = max(1, len(postings))
    _titles(
        ws,
        "요약",
        f"기준 {now.astimezone(KST):%Y-%m-%d %H:%M} KST · "
        "모든 수치는 공고목록 시트를 COUNTIF 로 집계합니다 (값을 직접 적어 넣지 않음)",
    )
    for col, width in (("A", 20), ("B", 10), ("C", 10)):
        ws.column_dimensions[col].width = width

    fields = [FIELD_NAMES[k] for k in FIELD_NAMES if any(p.field == k for p in postings)]
    regions = sorted({r for p in postings for r in (p.region or ["미상"])})
    org_types = [ORG_TYPE_NAMES[k] for k in ORG_TYPE_NAMES if any(p.org_type.value == k for p in postings)]

    row = _count_block(ws, 4, "상태별", COL["상태"], STATUS_ORDER, n)
    row = _count_block(ws, row, "분야별", COL["분야"], fields, n)
    row = _count_block(ws, row, "지역별", COL["지역"], regions, n)
    row = _count_block(ws, row, "고용형태별", COL["고용형태"], sorted({p.employment_type for p in postings}), n)

    notes = [
        "지역은 한 공고에 여러 곳이 들어갈 수 있어 합계가 공고 수보다 클 수 있습니다.",
        f"기관 유형 구성: {', '.join(org_types) or '없음'} (정확한 분류는 수집원 현황 시트 참조)",
        "'진행중' 열은 마감된 공고를 뺀 수입니다.",
    ]
    for i, note in enumerate(notes):
        ws[f"A{row + i}"] = note
        ws[f"A{row + i}"].font = NOTE_FONT


def build_sources_sheet(ws: Worksheet, sources: Sequence[SourceConfig], now: datetime) -> None:
    enabled = sum(1 for s in sources if s.enabled)
    _titles(ws, "수집원 현황", f"기준 {now.astimezone(KST):%Y-%m-%d %H:%M} KST · 전체 {len(sources)}곳 · 활성 {enabled}곳")
    headers = ("Tier", "id", "기관", "유형", "활성", "검증", "어댑터", "홈페이지", "메모 / 미설정 사유")
    widths = (6, 24, 30, 14, 7, 7, 13, 38, 46)
    for i, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=HEADER_ROW, column=i, value=h)
        cell.font, cell.fill, cell.border = HEADER_FONT, HEADER_FILL, BORDER
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = w

    for r, s in enumerate(sorted(sources, key=lambda x: (x.tier, x.id)), FIRST_DATA_ROW):
        reason = s.unconfigured_reason()
        values = (
            s.tier, s.id, s.name, ORG_TYPE_NAMES.get(s.org_type.value, s.org_type.value),
            "O" if s.enabled else "-", "O" if s.verified else "-", s.adapter.get("type", "-"),
            s.homepage or "", reason or (s.notes or "").strip().replace("\n", " ")[:120],
        )
        for i, v in enumerate(values, 1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.font = BASE_FONT
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=i == 9, horizontal="center" if i in (1, 5, 6) else "left")
    last = max(FIRST_DATA_ROW, FIRST_DATA_ROW + len(sources) - 1)
    ws.auto_filter.ref = f"A{HEADER_ROW}:I{last}"
    ws.freeze_panes = f"A{FIRST_DATA_ROW}"


def build_workbook(
    postings: Sequence[Posting],
    sources: Sequence[SourceConfig],
    out_path: Path,
    now: datetime,
    source_names: dict[str, str] | None = None,
) -> Path:
    """공고목록·요약·수집원 현황 3개 시트로 엑셀 파일을 만든다. 마감 가까운 순, 마감된 공고는 뒤로."""
    ordered = sorted(
        postings,
        key=lambda p: (p.status == Status.expired, p.deadline is None, p.deadline or now),
    )
    wb = Workbook()
    build_postings_sheet(wb.active, ordered, now, source_names or {})
    wb.active.title = "공고목록"
    build_summary_sheet(wb.create_sheet("요약"), ordered, now)
    build_sources_sheet(wb.create_sheet("수집원 현황"), sources, now)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
