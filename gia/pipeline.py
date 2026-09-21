"""수집·판별·저장 파이프라인 (docs/DESIGN.md 11.2)."""
from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .classify.rules import score_posting
from .collectors.base import FetchError, HttpClient, UnconfiguredSource
from .collectors.registry import build_adapter
from .config import ConfigBundle, MissingSecret, SourceConfig
from .dedupe import canonical_key, find_duplicate, merge
from .extract.deadline import KST, DeadlineType, parse_deadline, parse_known_format
from .models import Posting, RawPosting, RunLog, SourceRef, SourceRunResult, Status
from .normalize import clean_url, extract_regions, mask_pii, normalize_title, standardize_org
from .store import Store

log = logging.getLogger("gia")


@dataclass
class SourceOutcome:
    result: SourceRunResult
    postings: list[Posting] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)  # 이미 알던 URL (last_seen 갱신)
    excluded: list[str] = field(default_factory=list)  # 규칙 점수 미달 URL


def build_posting(raw: RawPosting, cfg: SourceConfig, bundle: ConfigBundle, now: datetime) -> Posting | None:
    """RawPosting → Posting. 관련성이 낮으면 None."""
    cs = bundle.settings.classifier
    title, flags = normalize_title(raw.title)
    org = standardize_org(raw.org_name or cfg.name, bundle.aliases)
    body = mask_pii(raw.body_text or "")
    rule = score_posting(title, body, raw.region_text)
    if rule.score < cs.review_threshold:
        return None
    if rule.score < cs.include_threshold:
        if not (cs.include_review_without_llm and not cs.llm_enabled):
            return None
        flags.append("판별유보")

    posted = raw.posted_at
    inferred = posted is None
    ref = posted or now.date()
    deadline_dt, dtype, dtext = None, DeadlineType.unknown, None
    if raw.deadline_text:
        deadline_dt = parse_known_format(raw.deadline_text)
        if deadline_dt:
            dtype, dtext = DeadlineType.fixed, raw.deadline_text
        else:
            res = parse_deadline(raw.deadline_text, ref)
            deadline_dt, dtype, dtext = res.deadline, res.deadline_type, res.text
    if deadline_dt is None and dtype != DeadlineType.until_filled:
        res = parse_deadline(body, ref)
        if res.deadline is None and res.deadline_type == DeadlineType.unknown:
            res = parse_deadline(title, ref)
        deadline_dt, dtype, dtext = res.deadline, res.deadline_type, res.text

    regions = extract_regions(" ".join([title, raw.region_text or "", body[:3000]]))
    if not regions and cfg.region_hint and cfg.org_type.value != "portal":
        regions = [r if r != "경상남도" else "경남" for r in cfg.region_hint][:1]

    key = canonical_key(org, title)
    content_hash = hashlib.sha1(f"{title}|{deadline_dt.isoformat() if deadline_dt else ''}|{body[:5000]}".encode()).hexdigest()
    return Posting(
        id=key[:12], canonical_key=key, title=title, org_name=org, org_type=cfg.org_type,
        field=rule.field, employment_type=rule.employment_type, region=regions,
        posted_at=posted, posted_at_inferred=inferred,
        deadline=deadline_dt, deadline_type=dtype, deadline_text=dtext,
        relevance_score=rule.score, score_reasons=rule.reasons, flags=flags,
        sources=[SourceRef(source_id=cfg.id, url=clean_url(raw.url), fetched_at=raw.fetched_at or now)],
        attachments=list(raw.attachments), content_hash=content_hash,
        first_seen_at=now, last_seen_at=now, status=Status.new,
    )


def run_source(cfg: SourceConfig, bundle: ConfigBundle, store: Store, http: HttpClient, now: datetime, since: date | None) -> SourceOutcome:
    cs = bundle.settings.collector
    res = SourceRunResult(source_id=cfg.id)
    out = SourceOutcome(result=res)
    t0 = time.monotonic()
    try:
        adapter = build_adapter(cfg, http, cs, since=since)
    except UnconfiguredSource as e:
        res.status, res.errors = "unconfigured", [str(e)]
        return out
    try:
        listings = adapter.fetch_list()
    except MissingSecret as e:
        res.status, res.errors = "unconfigured", [str(e)]
        return out
    except (FetchError, Exception) as e:  # noqa: BLE001 - 소스 격리
        res.status, res.errors = "fail", [f"목록 실패: {type(e).__name__}: {e}"[:300]]
        log.warning("[%s] %s", cfg.id, res.errors[0])
        return out
    res.listed = len(listings)
    if not listings:
        res.status = "empty"
    recheck_before = now - timedelta(days=bundle.settings.report.recheck_active_days)
    for l in listings:
        if time.monotonic() - t0 > cs.source_time_budget_sec:
            res.errors.append("시간 예산 초과: 나머지 목록 건너뜀")
            break
        url = clean_url(l.url)
        if url in store.excluded_urls:
            continue
        existing = store.by_url(url)
        if existing and not (existing.status != Status.expired and existing.last_seen_at < recheck_before):
            out.touched.append(existing.canonical_key)
            continue
        try:
            raw = adapter.fetch_detail(l)
        except (FetchError, Exception) as e:  # noqa: BLE001
            res.errors.append(f"상세 실패 {url}: {e}"[:300])
            if len(res.errors) >= cs.max_detail_errors_per_source:
                res.errors.append("상세 오류 누적으로 소스 중단")
                res.status = "fail"
                break
            continue
        res.detail_fetched += 1
        p = build_posting(raw, cfg, bundle, now)
        if p:
            out.postings.append(p)
        else:
            out.excluded.append(url)
    res.duration_ms = int((time.monotonic() - t0) * 1000)
    return out


def collect(bundle: ConfigBundle, store: Store, http: HttpClient, only: list[str] | None = None,
            dry_run: bool = False, backfill_days: int | None = None, now: datetime | None = None,
            light: bool = False) -> RunLog:
    now = now or datetime.now(KST)
    cs = bundle.settings.collector
    since = now.date() - timedelta(days=backfill_days if backfill_days else cs.default_days)
    selected = [s for s in bundle.sources if s.enabled and (only is None or s.id in only) and (not light or s.schedule == "daily_light")]
    run = RunLog(run_id=now.strftime("%Y-%m-%dT%H-%M"), started_at=now)
    if backfill_days:
        run.notes.append(f"백필 {backfill_days}일")

    with ThreadPoolExecutor(max_workers=max(1, cs.concurrency)) as ex:
        outcomes = list(ex.map(lambda c: run_source(c, bundle, store, http, now, since), selected))

    counts = {"new": 0, "updated": 0, "merged": 0}
    batch: list[Posting] = []
    for oc in outcomes:
        for u in oc.excluded:
            store.mark_excluded(u, now)
        for k in oc.touched:
            p = store.get(k)
            if p:
                p.last_seen_at = now
        for p in oc.postings:
            dup = find_duplicate(p, list(store.values()) + batch)
            if dup is None:
                batch.append(p)
                store.upsert(p)
                counts["new"] += 1
                oc.result.new += 1
                continue
            if dup.status == Status.expired and "재공고" in p.flags:
                p.reannouncement_of = dup.id
                batch.append(p)
                store.upsert(p)
                counts["new"] += 1
                oc.result.new += 1
                continue
            merged, changed = merge(dup, p, now)
            if changed and merged.last_reported_at is not None:
                merged.status = Status.updated
                counts["updated"] += 1
                oc.result.updated += 1
            counts["merged"] += 1
            store.upsert(merged)
            if dup in batch:
                batch[batch.index(dup)] = merged
        run.sources.append(oc.result)

    store.refresh_statuses(now, bundle.settings.report.closing_soon_days)
    counts["closing_soon"] = sum(1 for p in store.values() if p.status == Status.closing_soon)
    counts["expired"] = sum(1 for p in store.values() if p.status == Status.expired)
    run.totals = counts
    run.finished_at = datetime.now(KST)
    store.state["last_run_at"] = now.isoformat()
    if not dry_run:
        store.save()
        store.save_run(run)
    return run
