#!/usr/bin/env python3
"""data/announcements.json 을 CSV 와 Markdown 표로 내보낸다."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "announcements.json"
CSV = ROOT / "data" / "announcements.csv"
MD = ROOT / "data" / "announcements.md"
FIELDS = ["id", "region", "university", "center", "category", "title", "posted_date", "url", "summary", "board", "source", "confidence", "collected_at", "institution_id"]
REGION_ORDER = {"부산": 0, "울산": 1, "경남": 2}


def build() -> None:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    rows.sort(key=lambda r: (REGION_ORDER.get(r["region"], 9), r["university"], r.get("posted_date") or "", r["title"]))

    with CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    main_rows = [r for r in rows if not r["category"].startswith("일반강사채용")]
    ref_rows = [r for r in rows if r["category"].startswith("일반강사채용")]
    latest = max((r.get("collected_at") or "" for r in rows), default="")

    out = ["# 부산·울산·경남 대학 평생교육원 강사모집 공고", "",
           f"최종 수집일: {latest} · 평생교육원 공고 {len(main_rows)}건 · 참고(대학 본부 강사채용) {len(ref_rows)}건", "",
           "> `confidence`: high = 게시글 URL까지 확인, medium = 제목·게시판은 확인했으나 상세 URL 미확보, low = 검색 스니펫으로만 확인.", ""]

    by_region: dict[str, list[dict]] = defaultdict(list)
    for r in main_rows:
        by_region[r["region"]].append(r)
    for region in sorted(by_region, key=lambda k: REGION_ORDER.get(k, 9)):
        out += [f"## {region}", "", "| 대학 | 기관 | 구분 | 공고 제목 | 게시일 | 신뢰도 | 요약 |", "|---|---|---|---|---|---|---|"]
        for r in by_region[region]:
            title = f"[{r['title']}]({r['url']})" if r.get("url") else r["title"]
            out.append(f"| {r['university']} | {r['center']} | {r['category']} | {title} | {r.get('posted_date') or '-'} | {r['confidence']} | {r['summary'].replace('|', '/')} |")
        out.append("")

    if ref_rows:
        out += ["## 참고: 대학 본부 강사·교원 채용(평생교육원 공고 아님)", "", "| 지역 | 대학 | 공고 제목 | 게시일 | 비고 |", "|---|---|---|---|---|"]
        for r in ref_rows:
            out.append(f"| {r['region']} | {r['university']} | [{r['title']}]({r['url']}) | {r.get('posted_date') or '-'} | {r['summary'].replace('|', '/')} |")
        out.append("")
    MD.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {CSV.relative_to(ROOT)} and {MD.relative_to(ROOT)} ({len(rows)} rows)")
    try:
        from build_xlsx import build as build_xlsx
        build_xlsx()
    except ImportError as exc:  # openpyxl 미설치 시 xlsx 만 건너뜀
        print(f"skip xlsx: {exc}")


if __name__ == "__main__":
    build()
