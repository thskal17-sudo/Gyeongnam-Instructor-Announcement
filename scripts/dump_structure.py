#!/usr/bin/env python3
"""게시판 목록 페이지의 HTML 구조를 요약 출력한다 (셀렉터 결정용).

사용법: python scripts/dump_structure.py URL [URL ...]
네트워크가 열린 환경(GitHub Actions 등)에서 실행하고 로그를 읽는다.
"""
from __future__ import annotations

import re
import sys
import urllib3

import requests
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def sel(tag) -> str:
    cls = ".".join(tag.get("class", [])) if tag.get("class") else ""
    i = f"#{tag.get('id')}" if tag.get("id") else ""
    return f"{tag.name}{i}{'.' + cls if cls else ''}"


def path(tag) -> str:
    parts = []
    while tag is not None and tag.name not in ("body", "[document]"):
        parts.append(sel(tag))
        tag = tag.parent
    return " > ".join(reversed(parts))


def dump(url: str) -> None:
    print("=" * 100)
    print("URL:", url)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    except requests.exceptions.SSLError:
        print("  (ssl verify failed, retrying without verification)")
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25, verify=False)
    except Exception as exc:  # noqa: BLE001
        print("  FETCH ERROR:", exc)
        return
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    print(f"status={r.status_code} final={r.url} encoding={r.encoding} bytes={len(r.content)}")
    soup = BeautifulSoup(r.text, "lxml")
    print("title:", (soup.title.get_text(strip=True) if soup.title else "")[:80])
    robots = re.findall(r'<meta[^>]+name=["\']robots["\'][^>]*>', r.text, re.I)
    if robots:
        print("robots meta:", robots[0][:120])

    # 표 형태 게시판
    for t in soup.find_all("table")[:6]:
        rows = t.find_all("tr")
        print(f"\n[TABLE] {path(t)}  rows={len(rows)}")
        for tr in rows[:3]:
            cells = tr.find_all(["th", "td"])
            desc = " | ".join(f"{sel(c)}:{c.get_text(' ', strip=True)[:28]}" for c in cells[:8])
            print("   row:", sel(tr), "->", desc)
            for a in tr.find_all("a")[:2]:
                print("      a:", sel(a), "href=", (a.get("href") or "")[:100], "onclick=", (a.get("onclick") or "")[:80], "text=", a.get_text(" ", strip=True)[:50])

    # 목록(ul/ol) 형태 게시판: 항목이 3개 이상이고 링크가 있는 것만
    for ul in soup.find_all(["ul", "ol"]):
        lis = ul.find_all("li", recursive=False)
        if len(lis) < 3 or not ul.find("a"):
            continue
        texts = [li.get_text(" ", strip=True) for li in lis]
        if sum(len(t) for t in texts) < 60:
            continue
        print(f"\n[LIST] {path(ul)}  items={len(lis)}")
        for li in lis[:2]:
            print("   li:", sel(li), "->", li.get_text(" ", strip=True)[:90])
            for a in li.find_all("a")[:1]:
                print("      a:", sel(a), "href=", (a.get("href") or "")[:100], "onclick=", (a.get("onclick") or "")[:80])
            for child in li.find_all(True, recursive=False)[:6]:
                print("      child:", sel(child), ":", child.get_text(" ", strip=True)[:40])

    # 페이지 이동 링크
    pag = [a for a in soup.find_all("a") if re.search(r"(page|Page|cpage|pageIndex|startPage|pageNo)=\d+", a.get("href") or "")]
    if pag:
        print("\n[PAGING]", (pag[0].get("href") or "")[:140])
    dates = re.findall(r"20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}", soup.get_text(" "))
    print("[DATES] sample:", dates[:5])


if __name__ == "__main__":
    import os
    urls = sys.argv[1:] or os.environ.get("URLS", "").split()
    for u in urls:
        dump(u)
