"""CLI: gia collect | report | probe | status."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .collectors.base import HttpClient
from .collectors.registry import build_adapter
from .config import load_bundle
from .extract.deadline import KST, parse_deadline
from .classify.rules import score_posting
from .models import Status
from .pipeline import build_posting, collect
from .report.build import render_markdown, render_telegram, select_postings, write_report
from .store import Store


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gia", description="경남 강사 구인공고 수집·일일 요약")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="수집·판별·저장")
    c.add_argument("--sources", help="쉼표로 구분한 source id 목록")
    c.add_argument("--dry-run", action="store_true", help="저장하지 않음")
    c.add_argument("--backfill-days", type=int, default=0)
    c.add_argument("--light", action="store_true", help="schedule=daily_light 소스만")

    r = sub.add_parser("report", help="요약본 생성(및 발송)")
    r.add_argument("--send", action="store_true", help="채널로 발송하고 보고 상태를 기록")
    r.add_argument("--mark", action="store_true", help="발송 없이 보고 상태만 기록")
    r.add_argument("--print", dest="print_md", action="store_true", help="Markdown을 표준출력으로")

    pr = sub.add_parser("probe", help="소스 하나를 시험 수집")
    pr.add_argument("source_id")
    pr.add_argument("--limit", type=int, default=5)
    pr.add_argument("--detail", action="store_true", help="첫 건의 상세·마감일·점수까지 표시")

    sub.add_parser("status", help="저장소 요약")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    bundle = load_bundle(Path(args.config_dir))
    store = Store(Path(args.data_dir)).load()
    now = datetime.now(KST)

    if args.cmd == "collect":
        http = HttpClient(bundle.settings.collector)
        try:
            only = [s.strip() for s in args.sources.split(",")] if args.sources else None
            run = collect(bundle, store, http, only=only, dry_run=args.dry_run, backfill_days=args.backfill_days or None, now=now, light=args.light)
        finally:
            http.close()
        c = run.counts()
        print(f"[collect] 소스 정상 {c['ok']} / 0건 {c['empty']} / 실패 {c['fail']} / 미설정 {c['unconfigured']} · 신규 {run.totals.get('new',0)} · 병합 {run.totals.get('merged',0)}")
        for s in run.sources:
            if s.status in ("fail", "unconfigured"):
                print(f"  - {s.source_id}: {s.status} {s.errors[0] if s.errors else ''}")
        return 0

    if args.cmd == "report":
        data = select_postings(bundle, store, now)
        md = render_markdown(data, now)
        path = write_report(md, Path(args.reports_dir), now)
        if args.print_md or not (args.send or args.mark):
            print(md)
        print(f"[report] {path} · 신규 {len(data.new)} · 마감임박 {len(data.closing)} · 변경 {len(data.updated)}", file=sys.stderr)
        failures: list[str] = []
        if args.send:
            channels = bundle.settings.notify.channels
            if "telegram" in channels:
                token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
                if not token or not chat:
                    failures.append("telegram: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 없음")
                else:
                    from .notify.telegram import send_telegram
                    try:
                        n = send_telegram(token, chat, render_telegram(data, now))
                        print(f"[report] 텔레그램 {n}개 메시지 전송", file=sys.stderr)
                    except Exception as e:  # noqa: BLE001
                        failures.append(f"telegram: {e}")
            for ch in channels:
                if ch not in ("telegram",):
                    failures.append(f"{ch}: Phase 1에서는 미구현")
            for f in failures:
                print(f"[report] 발송 실패 {f}", file=sys.stderr)
        if args.send or args.mark:
            store.mark_reported(data.keys(), now, bundle.settings.report.closing_days)
            store.save()
        sent_any = args.send and len(failures) < len(bundle.settings.notify.channels)
        return 0 if (not args.send or sent_any) else 1

    if args.cmd == "probe":
        cfg = next((s for s in bundle.sources if s.id == args.source_id), None)
        if cfg is None:
            print(f"소스 없음: {args.source_id}", file=sys.stderr)
            return 2
        http = HttpClient(bundle.settings.collector)
        try:
            adapter = build_adapter(cfg, http, bundle.settings.collector, since=now.date() - timedelta(days=bundle.settings.collector.default_days))
            listings = adapter.fetch_list()
            print(f"[probe] {cfg.name}: 목록 {len(listings)}건")
            for l in listings[: args.limit]:
                print(f"  - {l.posted_at or '????-??-??'} | {l.org_name or ''} | {l.title} | {l.url}")
            if args.detail and listings:
                raw = adapter.fetch_detail(listings[0])
                res = parse_deadline(raw.body_text, raw.posted_at)
                rule = score_posting(raw.title, raw.body_text, raw.region_text)
                print(f"[detail] 본문 {len(raw.body_text)}자 · 마감 {res.deadline} ({res.deadline_type.value}, '{res.text}') · 점수 {rule.score} {rule.reasons} · 분야 {rule.field}")
                p = build_posting(raw, cfg, bundle, now)
                print(f"[posting] {'포함' if p else '제외'}: {p.title if p else ''}")
        finally:
            http.close()
        return 0

    if args.cmd == "status":
        by = {s.value: 0 for s in Status}
        for p in store.values():
            by[p.status.value] += 1
        print(f"공고 {len(store.postings)}건 · " + " · ".join(f"{k} {v}" for k, v in by.items()))
        print(f"마지막 수집 {store.state.get('last_run_at', '-')} · 마지막 보고 {store.state.get('last_report_at', '-')}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
