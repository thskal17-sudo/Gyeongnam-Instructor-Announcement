"""JSONL 저장소 (docs/DESIGN.md 8절)."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .extract.deadline import KST, in_deadline_window
from .models import DeadlineType, Posting, RunLog, Status


def sanitize_deadline(p: Posting) -> bool:
    """게시일 기준 유효 구간을 벗어난 마감일을 미상으로 되돌린다. 바꿨으면 True.

    마감일 창 검증이 들어오기 전에 저장된 기록에는 계약기간 종료일이나 근거 규정의
    연도가 마감일로 남아 있다. 원문에 다시 닿을 수 없는 소스도 있어(국내 IP 차단)
    재파싱으로는 고칠 수 없으므로, 읽을 때마다 걸러 낸다. 지금 파서는 이런 값을
    애초에 만들지 않으므로 새 기록에는 걸리지 않는다.
    """
    if not p.deadline or not p.posted_at:
        return False
    if in_deadline_window(p.deadline.astimezone(KST).date(), p.posted_at):
        return False
    p.deadline = None
    p.deadline_type = DeadlineType.unknown
    p.deadline_text = None
    if "마감일무효" not in p.flags:
        p.flags.append("마감일무효")
    return True


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.postings_dir = self.data_dir / "postings"
        self.index_dir = self.data_dir / "index"
        self.runs_dir = self.data_dir / "runs"
        self.postings: dict[str, Posting] = {}
        self.seen_urls: dict[str, str] = {}
        self.excluded_urls: dict[str, str] = {}  # url → 제외 판정일 (규칙 점수 미달)
        self.state: dict = {}

    # ---- load / save -------------------------------------------------
    def load(self) -> "Store":
        self.postings.clear()
        if self.postings_dir.exists():
            for f in sorted(self.postings_dir.glob("*.jsonl")):
                with f.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            p = Posting.model_validate(json.loads(line))
                            sanitize_deadline(p)
                            self.postings[p.canonical_key] = p
        self.seen_urls = self._read_json(self.index_dir / "seen_urls.json", {})
        self.excluded_urls = self._read_json(self.index_dir / "excluded_urls.json", {})
        self.state = self._read_json(self.data_dir / "state.json", {})
        for p in self.postings.values():
            for s in p.sources:
                self.seen_urls[s.url] = p.canonical_key
        return self

    def save(self) -> None:
        self.postings_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        by_month: dict[str, list[Posting]] = defaultdict(list)
        for p in self.postings.values():
            by_month[p.first_seen_at.strftime("%Y-%m")].append(p)
        for f in self.postings_dir.glob("*.jsonl"):
            if f.stem not in by_month:
                f.unlink()
        for month, items in by_month.items():
            items.sort(key=lambda p: (p.first_seen_at, p.id))
            with (self.postings_dir / f"{month}.jsonl").open("w", encoding="utf-8") as fh:
                for p in items:
                    fh.write(json.dumps(p.model_dump(mode="json"), ensure_ascii=False) + "\n")
        self._write_json(self.index_dir / "seen_urls.json", self.seen_urls)
        self._write_json(self.index_dir / "excluded_urls.json", self.excluded_urls)
        canonical = {
            k: {"first_seen": p.first_seen_at.isoformat(), "last_seen": p.last_seen_at.isoformat(), "status": p.status.value}
            for k, p in self.postings.items()
        }
        self._write_json(self.index_dir / "canonical.json", canonical)
        self._write_json(self.data_dir / "state.json", self.state)

    def save_run(self, run: RunLog) -> Path:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{run.run_id}.json"
        self._write_json(path, run.model_dump(mode="json"))
        return path

    def last_run(self) -> RunLog | None:
        if not self.runs_dir.exists():
            return None
        files = sorted(self.runs_dir.glob("*.json"))
        if not files:
            return None
        with files[-1].open(encoding="utf-8") as fh:
            return RunLog.model_validate(json.load(fh))

    def drop(self, key: str) -> Posting | None:
        """공고를 저장소에서 지우고 그 주소를 제외 목록으로 옮긴다.

        제외 목록에 넣지 않으면 다음 수집이 같은 글을 새 공고로 다시 주워 온다.
        """
        p = self.postings.pop(key, None)
        if p is None:
            return None
        today = datetime.now(KST).date().isoformat()
        for src in p.sources:
            self.seen_urls.pop(src.url, None)
            self.excluded_urls[src.url] = today
        return p

    # ---- access ------------------------------------------------------
    def get(self, key: str) -> Posting | None:
        return self.postings.get(key)

    def by_url(self, url: str) -> Posting | None:
        key = self.seen_urls.get(url)
        return self.postings.get(key) if key else None

    def upsert(self, p: Posting) -> None:
        self.postings[p.canonical_key] = p
        for s in p.sources:
            self.seen_urls[s.url] = p.canonical_key

    def mark_excluded(self, url: str, when: datetime) -> None:
        self.excluded_urls[url] = when.date().isoformat()

    def values(self) -> Iterable[Posting]:
        return self.postings.values()

    # ---- state machine -----------------------------------------------
    def refresh_statuses(self, now: datetime, closing_days: int) -> None:
        """docs/DESIGN.md 8.2. 우선순위: expired > (미보고 new/updated) > closing_soon > active."""
        for p in self.postings.values():
            if p.deadline and p.deadline < now:
                p.status = Status.expired
                continue
            if p.status in (Status.new, Status.updated) and (p.last_reported_at is None or p.last_reported_at < p.last_seen_at):
                continue  # 아직 보고되지 않은 신규/변경 건은 유지
            if p.deadline and p.deadline <= now + timedelta(days=closing_days):
                p.status = Status.closing_soon
            else:
                p.status = Status.active

    def mark_reported(self, keys: Iterable[str], now: datetime, closing_days: int) -> None:
        for k in keys:
            p = self.postings.get(k)
            if not p:
                continue
            p.last_reported_at = now
            if p.status in (Status.new, Status.updated):
                p.status = Status.active
        self.refresh_statuses(now, closing_days)
        self.state["last_report_at"] = now.isoformat()

    def reported_today(self, now: datetime) -> bool:
        """오늘(한국 날짜) 이미 보고를 보냈으면 True.

        예약 실행이 밀리는 탓에 수집이 끝나면 곧바로 보고하도록(workflow_run) 바꾸면서,
        예비 예약까지 걸어 두었다. 둘 다 돌면 같은 날 메일이 두 번 간다. 날짜로 센다 —
        '24시간 지났나'로 세면 밀린 시각이 다음 날 기준이 되어 하루씩 뒤로 끌린다.
        """
        stamp = self.state.get("last_report_at")
        if not stamp:
            return False
        try:
            last = datetime.fromisoformat(stamp)
        except ValueError:
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=KST)
        return last.astimezone(KST).date() == now.astimezone(KST).date()

    # ---- helpers -----------------------------------------------------
    @staticmethod
    def _read_json(path: Path, default):
        if not path.exists():
            return default
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _write_json(path: Path, obj) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
