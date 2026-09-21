"""중복 제거·병합 (docs/DESIGN.md 6.3)."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Iterable

from rapidfuzz import fuzz

from .models import Posting, Status
from .normalize import nfkc, norm_key

SIMILARITY_THRESHOLD = 90
POSTED_WINDOW_DAYS = 7


def canonical_key(org_name: str, title: str) -> str:
    return hashlib.sha1(f"{norm_key(org_name)}|{norm_key(title)}".encode()).hexdigest()


def title_similarity(a: str, b: str) -> float:
    return fuzz.token_set_ratio(nfkc(a).lower(), nfkc(b).lower())


def find_duplicate(cand: Posting, pool: Iterable[Posting]) -> Posting | None:
    org_key = norm_key(cand.org_name)
    best: Posting | None = None
    best_sim = 0.0
    for p in pool:
        if p is cand:
            continue
        if p.canonical_key == cand.canonical_key:
            return p
        if norm_key(p.org_name) != org_key:
            continue
        if cand.posted_at and p.posted_at and abs((cand.posted_at - p.posted_at).days) > POSTED_WINDOW_DAYS:
            continue
        sim = title_similarity(cand.title, p.title)
        if sim >= SIMILARITY_THRESHOLD and sim > best_sim:
            best, best_sim = p, sim
    return best


def merge(existing: Posting, incoming: Posting, now: datetime) -> tuple[Posting, bool]:
    """incoming을 existing에 합친다. 반환: (병합 결과, 의미 있는 변경 여부)."""
    changed = False
    p = existing.model_copy(deep=True)
    known = {(s.source_id, s.url) for s in p.sources}
    for s in incoming.sources:
        if (s.source_id, s.url) not in known:
            p.sources.append(s)
            known.add((s.source_id, s.url))
    p.last_seen_at = max(p.last_seen_at, now)
    if incoming.deadline and (p.deadline is None or incoming.deadline > p.deadline):
        if p.deadline is not None:
            changed = True
        p.deadline = incoming.deadline
        p.deadline_type = incoming.deadline_type
        p.deadline_text = incoming.deadline_text
    for f in incoming.flags:
        if f not in p.flags:
            p.flags.append(f)
            if f in ("연장", "수정", "정정", "변경"):
                changed = True
    if not p.region and incoming.region:
        p.region = list(incoming.region)
    if p.relevance_score < incoming.relevance_score:
        p.relevance_score = incoming.relevance_score
        p.score_reasons = list(incoming.score_reasons)
    if p.field == "other" and incoming.field != "other":
        p.field = incoming.field
    if p.employment_type == "기타" and incoming.employment_type != "기타":
        p.employment_type = incoming.employment_type
    if p.status == Status.expired and changed:
        p.status = Status.updated
    return p, changed
