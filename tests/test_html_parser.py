"""HTML 파서(lexbor)가 설정의 셀렉터를 그대로 읽는지 지킨다.

2026-10-04 에 selectolax 1.0 이 옛 Modest 백엔드를 지우면서 두 저장소의 수집·보고가
한꺼번에 멈췄다. lexbor 로 옮기면서 가장 걱정한 것은 파서가 바뀌어 셀렉터가 조용히
어긋나는 일이었다 — 멈추는 것보다 나쁘다. 실제로 저장된 픽스처에 설정의 셀렉터를
모두 걸어 보고 옮겼고, 그 확인을 여기에 남긴다.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest
import yaml

from gia.collectors.html_list import HTMLParser

ROOT = Path(__file__).resolve().parents[1]


def configured_selectors() -> set[str]:
    """config/sources.yaml 이 실제로 쓰는 CSS 셀렉터 전부."""
    out: set[str] = set()
    data = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    for s in data.get("sources") or []:
        a = s.get("adapter") or {}
        for k, v in a.items():
            if k.endswith("_selector") and v and v != ":row":  # ':row' 는 '행 자체'를 뜻하는 표시다 (html_list.py)
                out.add(v)
        for k, v in (a.get("detail") or {}).items():
            if k.endswith("_selector") and v:
                out.add(v)
    return out


def test_uses_lexbor_backend():
    """옛 Modest 백엔드로 되돌아가지 않는다 — 그것은 selectolax 1.0 에서 사라졌다."""
    assert HTMLParser.__module__.startswith("selectolax.lexbor"), HTMLParser.__module__


def test_every_configured_selector_parses():
    """설정의 셀렉터가 모두 lexbor 에서 문법 오류 없이 돈다."""
    html = "<html><body><table><tr><td>x</td></tr></table></body></html>"
    tree = HTMLParser(html)
    bad = []
    for sel in sorted(configured_selectors()):
        try:
            tree.css(sel)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{sel}: {e}")
    assert not bad, "lexbor 가 못 읽는 셀렉터:\n" + "\n".join(bad)


def test_implied_tbody_still_matches():
    """설정 상당수가 'tbody tr' 을 쓴다. 게시판 HTML 에 tbody 가 없어도 맞아야 한다."""
    tree = HTMLParser("<table class='t'><tr><td>A</td></tr><tr><td>B</td></tr></table>")
    assert len(tree.css("table.t tbody tr")) == 2


@pytest.mark.parametrize("path", sorted(glob.glob(str(ROOT / "tests" / "fixtures" / "*.html"))))
def test_fixtures_still_yield_rows(path: str):
    """저장된 게시판 픽스처에서 셀렉터가 여전히 뭔가를 찾는다 (0건이면 조용한 고장)."""
    tree = HTMLParser(Path(path).read_text(encoding="utf-8", errors="replace"))
    assert any(tree.css(sel) for sel in configured_selectors()), f"{Path(path).name}: 맞는 셀렉터가 하나도 없다"


def test_body_inside_textarea_is_read_as_text():
    """양산시시설관리공단은 본문을 <textarea> 에 HTML 째로 둔다. 태그가 글자로 남으면 안 된다."""
    from gia.collectors.html_list import extract_body_html
    html = ("<div class='boardView_Wrap'><div class='boardViewTitle'>수영 위촉강사 모집 공고</div>"
            "<div class='boardViewCon'><textarea id='content'><p>□ 모집 분야: 수영</p>"
            "<p>접수: 10. 6.(화) 17:00</p></textarea></div></div>")
    body = extract_body_html(html, "div.boardViewCon")
    assert "<p>" not in body
    assert "□ 모집 분야: 수영" in body and "접수: 10. 6.(화) 17:00" in body
    assert extract_body_html(html, "div.boardView_Wrap").startswith("수영 위촉강사 모집 공고")


def test_deadline_from_list_period():
    """목록 칸의 접수기간 '시작 ~ 끝' 에서 끝을 마감일로 쓴다 (경남교육청 구인포털, 2026-10-24)."""
    from datetime import date

    from gia.collectors.html_list import parse_list_html
    from tests.conftest import make_source

    html = """<table class="frmbd-list-tbl"><tbody><tr>
      <td class="tl"><span class="cate">함안  ｜ 결원대체강사</span>
        <span class="tit"><a onclick="openDetail('1815159');">거창중앙고 시간강사 채용</a></span></td>
      <td><span class="cate">모집기관</span><span>거창중앙고</span></td>
      <td><span class="cate">접수기간</span><span>2026.10.24 ~ 2026.10.27</span></td>
    </tr></tbody></table>"""
    cfg = make_source("gne", "edu_office", type="html_list", list_url="https://www.gne.go.kr/l")
    a = {"row_selector": "table.frmbd-list-tbl tr", "title_selector": "td.tl span.tit", "link_selector": "td.tl a",
         "link_attr": "onclick", "link_regex": r"openDetail\('(\d+)'\)",
         "link_url_template": "https://www.gne.go.kr/d?regSn={1}",
         "date_selector": "td:nth-child(3) span:nth-of-type(2)",
         "deadline_selector": "td:nth-child(3) span:nth-of-type(2)", "region_selector": "td.tl span.cate"}
    rows, _ = parse_list_html(html, "https://www.gne.go.kr/l", a, cfg, date(2026, 10, 1))
    assert rows[0].posted_at == date(2026, 10, 24)
    assert rows[0].deadline_text == "2026.10.27"
    assert rows[0].region_text == "함안  ｜ 결원대체강사"  # 학교 지역 (2026-11-01)


def test_deadline_from_list_period_korean_words():
    """'2026-11-04부터 2026-11-11까지' 꼴 접수기간 (경남도청 경남채용정보, 2026-10-30)."""
    from datetime import date

    from gia.collectors.html_list import parse_list_html
    from tests.conftest import make_source

    html = """<table class="basicList"><tbody><tr><td class="title"><a href="/board/view.gyeong?dataSid=1">강사 모집</a></td>
      <td class="state">2026-11-04부터<br/>2026-11-11까지</td></tr></tbody></table>"""
    cfg = make_source("gyeongnam_go", "local_gov", type="html_list", list_url="https://www.gyeongnam.go.kr/l")
    a = {"row_selector": "table.basicList tbody tr", "title_selector": "td.title a", "link_selector": "td.title a",
         "date_selector": "td.state", "deadline_selector": "td.state"}
    rows, _ = parse_list_html(html, "https://www.gyeongnam.go.kr/l", a, cfg, date(2026, 10, 1))
    assert rows[0].posted_at == date(2026, 11, 4) and rows[0].deadline_text == "2026-11-11"


def test_link_from_row_attribute():
    """글 링크가 행 속성(data-idx)에만 있는 게시판 — link_selector ':row' (김해문화관광재단, 2026-10-31)."""
    from datetime import date

    from gia.collectors.html_list import parse_list_html
    from tests.conftest import make_source

    html = """<table class="basic_table"><tbody><tr data-idx="1737"><td class="title">
      <button class="board_title_btn">시민스포츠센터 수익배분제 강사 모집 공고</button></td>
      <td class="date">2026-10-28 13:46:21</td></tr></tbody></table>"""
    cfg = make_source("gh_ct", "local_public", type="html_list", list_url="https://www.ghct.or.kr/board/board02")
    a = {"row_selector": "table.basic_table tbody tr[data-idx]", "title_selector": "button.board_title_btn",
         "link_selector": ":row", "link_attr": "data-idx", "link_regex": r"(\d+)",
         "link_url_template": "https://www.ghct.or.kr/board/detail/board02/{1}", "date_selector": "td.date"}
    rows, _ = parse_list_html(html, "https://www.ghct.or.kr/board/board02", a, cfg, date(2026, 10, 1))
    assert rows[0].url == "https://www.ghct.or.kr/board/detail/board02/1737"
    assert rows[0].posted_at == date(2026, 10, 28)


def test_yangsan_library_config_reads_onclick_and_egov_files():
    """양산시 도서관(ys_lib): onclick 의 게시판·글 번호로 상세 주소를, fn_egov_downFile 로 첨부 주소를 만든다."""
    from datetime import date

    from gia.collectors.html_list import extract_attachments_html, parse_list_html
    from tests.conftest import make_source

    src = next(s for s in yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))["sources"]
               if s["id"] == "ys_lib")
    a = src["adapter"]
    html = """<table class="book_table1 book_table2"><tr><th>번호</th><th>제목</th></tr>
      <tr><td class="h2">219</td><td>중앙도서관</td><td class="h5 tlt"><a href="javascript:void(0);"
      onclick="fncNoticedetail('BBSMSTR_000000000004', '4970');">2026년 양산시립도서관 문화강좌 강사 모집 공고</a></td>
      <td class="h4 name">관리자</td><td class="h4 date">2026-10-20</td><td class="h4">12</td></tr></table>"""
    cfg = make_source("ys_lib", "local_gov", type="html_list", list_url=a["list_url"])
    rows, _ = parse_list_html(html, "https://lib.yangsan.go.kr/YS/madang/BBSMSTR_000000000004/hire.do", a, cfg,
                              date(2026, 10, 1))
    assert rows[0].url == "https://lib.yangsan.go.kr/YS/madang/detail.do?bbsId=BBSMSTR_000000000004&nttId=4970"
    assert rows[0].posted_at == date(2026, 10, 20)

    d = a["detail"]
    view = """<table id="egov_file_view_table"><tr><td class="view_file_style">
      <a href="javascript:fn_egov_downFile('FILE_000000000023166','0')">공고문.hwp</a></td></tr></table>"""
    assert extract_attachments_html(view, rows[0].url, d["attachment_selector"], d["attachment_regex"],
                                    d["attachment_url_template"]) == [
        "https://lib.yangsan.go.kr/cmm/fms/FileDown.do?atchFileId=FILE_000000000023166&fileSn=0"]


def test_category_keywords_pick_rows_without_title_keyword():
    """직종 칸이 '결원대체강사'면 제목에 키워드가 없어도 고른다. '강사 제외' 직종은 고르지 않는다 (gne, 2026-11-02)."""
    from datetime import date

    from gia.collectors.html_list import parse_list_html
    from tests.conftest import make_source

    def row(n, cate, title):
        return (f'<tr><td class="tl"><span class="cate">{cate}</span><span class="tit">'
                f'<a onclick="openDetail(\'{n}\');">{title}</a></span></td>'
                '<td><span class="cate">모집기관</span><span>장유고</span></td>'
                '<td><span class="cate">접수기간</span><span>2026.10.24 ~ 2026.10.27</span></td></tr>')
    html = ('<table class="frmbd-list-tbl"><tbody>' + row(1, "김해  ｜ 결원대체강사", "계약제교원(전일제) 채용 공고")
            + row(2, "진주  ｜ 기간제교원(강사 제외) 중등기간제교사", "문산중학교 기간제교사(체육) 채용 공고")
            + row(3, "통영  ｜ 기타", "2026 방과후학교 외부강사 모집") + "</tbody></table>")
    cfg = make_source("gne", "edu_office", type="html_list", list_url="https://www.gne.go.kr/l")
    a = {"row_selector": "table.frmbd-list-tbl tr", "title_selector": "td.tl span.tit", "link_selector": "td.tl a",
         "link_attr": "onclick", "link_regex": r"openDetail\('(\d+)'\)",
         "link_url_template": "https://www.gne.go.kr/d?regSn={1}", "region_selector": "td.tl span.cate",
         "keywords": ["강사", "방과후"], "category_keywords": ["결원대체강사", "기타각종강사", "방과후학교강사"]}
    rows, _ = parse_list_html(html, "https://www.gne.go.kr/l", a, cfg, date(2026, 10, 1))
    assert [r.title for r in rows] == ["계약제교원(전일제) 채용 공고", "2026 방과후학교 외부강사 모집"]
