#!/usr/bin/env python3
"""부산/울산/경남 대학 평생교육원 강사모집 공고 수집기.

data/institutions.json 에 등록된 각 기관의 게시판을 읽어
강사모집·강좌개설 관련 게시글을 찾아 data/announcements.json 에 병합한다.

사용법:
    python scraper/collect.py            # 전체 기관 수집
    python scraper/collect.py --only pia-edu ulsan-cec   # 특정 기관만
    python scraper/collect.py --dry-run  # 파일을 쓰지 않고 결과만 출력
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
INSTITUTIONS = ROOT / "data" / "institutions.json"
ANNOUNCEMENTS = ROOT / "data" / "announcements.json"

# 제목에 이 표현이 있으면 강사모집 계열 공고로 본다.
KEYWORDS = re.compile(
    r"(강사\s*(모집|채용|초빙|공개\s*모집|위수탁|인증|공지|등록)"
    r"|교\s*·?\s*강사\s*(모집|채용|초빙)"
    r"|강좌\s*(개설|공모)\s*(신청|제안|공모|안내)?"
    r"|개설\s*강좌\s*(공모|모집)"
    r"|신규\s*강좌"
    r"|강좌\s*제안)",
)
# 수강생 모집 등 학습자 대상 글은 제외한다.
EXCLUDE = re.compile(r"(수강생|교육생|학습자|참가자|장학생|수료식)\s*(모집|안내)|신규\s*강좌\s*안내"
    r"|.+\s강좌\s*개설\s*제안$")  # '성인 태권도 강좌 개설제안' 같은 이용자 제안 글
MENU_MAX_LEN = 14  # 이보다 짧고 연도가 없는 링크는 게시글이 아니라 상시 접수 메뉴로 본다
DATE = re.compile(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 instructor-announcement-bot"
    ),
    "Accept-Language": "ko,en;q=0.8",
}


def clean_title(text: str) -> str:
    """앵커 텍스트에서 첫 줄만 남기고 뒤에 붙은 날짜·조회수·작성자를 떼어낸다."""
    first = text.replace("\xa0", " ").strip().splitlines()[0]
    first = re.sub(r"\s+", " ", first).strip()
    # 목록 셀에 제목과 본문 요약이 한 줄로 붙어 오면 제목이 두 번 나타난다 → 두 번째 등장 전까지만 남긴다.
    first = re.split(r"\s+[※▶▷★☆]", first, maxsplit=1)[0]  # 제목 뒤에 이어지는 부가 안내문 제거
    head = first[:12]
    if len(head) == 12 and first.count(head) > 1:
        first = first[: first.index(head, 1)].strip()
    for pat in (r"\s+\d{1,6}$",                                             # 조회수
                r"\s*20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\.?(\s*\d{1,2}:\d{2})?$",  # 날짜(시각)
                r"\s+\S*\*+\S*$",                                         # 마스킹된 작성자(류**)
                r"\s*20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\.?(\s*\d{1,2}:\d{2})?$"):
        first = re.sub(pat, "", first)
    return first.strip()[:120]


def is_menu_link(title: str) -> bool:
    return len(title) <= MENU_MAX_LEN and not re.search(r"20\d{2}", title)


def classify(title: str) -> str:
    if re.search(r"강사\s*(모집|채용|초빙|위수탁|공개\s*모집)", title):
        return "강사모집"
    if re.search(r"강좌\s*(개설|공모)|개설\s*강좌|신규\s*강좌|강좌\s*제안", title):
        return "강좌개설신청"
    if re.search(r"인증|등록", title):
        return "강사인증/등록"
    if re.search(r"강사\s*공지", title):
        return "강사공지"
    return "강사모집"


def find_date(node) -> str:
    """앵커가 속한 행(tr/li/div) 텍스트에서 날짜를 찾는다."""
    for _ in range(4):
        if node is None:
            break
        m = DATE.search(node.get_text(" ", strip=True))
        if m:
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        node = node.parent
    return ""


def fetch(url: str, timeout: int = 20) -> str | None:
    try:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
        except requests.exceptions.SSLError:
            # 일부 대학 사이트는 중간 인증서를 내려주지 않아 검증에 실패한다.
            # 공개 게시판 읽기 용도이므로 이 경우에만 검증 없이 재시도한다.
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print(f"  ~ ssl verify failed, retrying without verification: {url}", file=sys.stderr)
            resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
        resp.raise_for_status()
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text
    except requests.RequestException as exc:  # 네트워크/HTTP 오류
        print(f"  ! fetch failed: {url} ({exc})", file=sys.stderr)
        return None


def scrape_board(inst: dict, board: dict) -> list[dict]:
    html = fetch(board["url"])
    if html is None:
        return []
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, dict] = {}
    for a in soup.find_all("a"):
        raw = a.get_text("\n", strip=True)
        if not raw or len(raw) < 6:
            continue
        title = clean_title(raw)
        if not KEYWORDS.search(title) or EXCLUDE.search(title):
            continue
        menu = is_menu_link(title)
        href = a.get("href") or ""
        if href.startswith("javascript") or not href:
            # onclick 기반 게시판은 목록 URL을 남긴다.
            url = board["url"]
        else:
            url = urljoin(board["url"], href)
        if url in found:
            continue
        found[url] = {
            "institution_id": inst["id"],
            "region": inst["region"],
            "university": inst["university"],
            "center": inst["center"],
            "title": f"{title} (홈페이지 상시 접수 메뉴)" if menu else title,
            "url": url,
            "posted_date": "" if menu else find_date(a),
            "category": "강좌개설제안(상시)" if menu else classify(title),
            "summary": "",
            "board": board["name"],
            "source": "scraper",
            "confidence": "high" if href and not href.startswith("javascript") else "medium",
            "collected_at": dt.date.today().isoformat(),
        }
    return list(found.values())


def norm(title: str) -> str:
    """대괄호 말머리·날짜·공백·기호를 제거한 비교용 제목."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", title)
    t = re.sub(r"20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}", "", t)
    return re.sub(r"[\s\W_]+", "", t)


def merge(existing: list[dict], new: list[dict]) -> tuple[list[dict], int]:
    by_url = {a["url"]: a for a in existing}
    by_key = {(a["institution_id"], norm(a["title"])): a for a in existing}
    added = 0
    for item in new:
        key = (item["institution_id"], norm(item["title"]))
        if item["url"] in by_url or key in by_key:
            old = by_url.get(item["url"]) or by_key[key]
            # 수동 수집분에 날짜/URL 정보가 비어 있으면 보완한다.
            if not old.get("posted_date") and item["posted_date"]:
                old["posted_date"] = item["posted_date"]
            if old.get("source") != "scraper" and item["url"] != old["url"] and old["url"].rstrip("/") in item["url"]:
                old["url"] = item["url"]
            continue
        n = sum(1 for a in existing if a["institution_id"] == item["institution_id"]) + 1
        item["id"] = f"{item['institution_id']}-{n:02d}"
        existing.append(item)
        by_url[item["url"]] = item
        by_key[key] = item
        added += 1
    return existing, added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="수집할 institution id 목록")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    institutions = json.loads(INSTITUTIONS.read_text(encoding="utf-8"))
    announcements = json.loads(ANNOUNCEMENTS.read_text(encoding="utf-8")) if ANNOUNCEMENTS.exists() else []

    collected: list[dict] = []
    for inst in institutions:
        if args.only and inst["id"] not in args.only:
            continue
        if not inst.get("boards"):
            print(f"- {inst['university']} {inst['center']}: 게시판 URL 미등록, 건너뜀")
            continue
        print(f"- {inst['university']} {inst['center']}")
        for board in inst["boards"]:
            items = scrape_board(inst, board)
            for it in items:
                print(f"    [{it['category']}] {it['posted_date'] or '????-??-??'} {it['title']}")
            collected.extend(items)

    merged, added = merge(announcements, collected)
    print(f"\n수집 {len(collected)}건, 신규 {added}건, 누적 {len(merged)}건")
    if args.dry_run:
        return 0
    ANNOUNCEMENTS.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from build_reports import build  # noqa: E402  (같은 폴더)
    build()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
