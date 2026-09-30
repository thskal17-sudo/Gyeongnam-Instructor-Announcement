"""수집이 한꺼번에 무너진 날 첫 발송을 미루는지 (--hold-if-degraded)."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from gia.extract.deadline import KST
from gia.models import RunLog, SourceRunResult
from gia.store import Store, new_failures


def _run(at: datetime, fails: list[str], ok: list[str]) -> RunLog:
    return RunLog(run_id=at.strftime("%Y-%m-%dT%H-%M"), started_at=at,
                  sources=[SourceRunResult(source_id=s, status="fail", errors=["timed out"]) for s in fails]
                  + [SourceRunResult(source_id=s, status="ok") for s in ok])


def test_new_failures_ignores_sources_that_were_already_failing():
    before = _run(datetime(2026, 9, 29, 13, 2, tzinfo=KST), ["hadong"], ["changwon", "gimhae"])
    now = _run(datetime(2026, 9, 30, 5, 51, tzinfo=KST), ["hadong", "changwon", "gimhae"], [])
    assert new_failures(now, [before]) == ["changwon", "gimhae"]


def test_new_failures_uses_each_sources_latest_status():
    """소스 하나만 다시 돌린 기록이 끼어 있어도, 나머지 소스는 그 전 기록의 상태로 본다."""
    full = _run(datetime(2026, 9, 29, 5, 0, tzinfo=KST), ["hadong"], ["changwon"])
    partial = _run(datetime(2026, 9, 29, 13, 0, tzinfo=KST), [], ["gimhae"])
    now = _run(datetime(2026, 9, 30, 5, 0, tzinfo=KST), ["hadong", "changwon"], [])
    assert new_failures(now, [full, partial]) == ["changwon"]


def _workspace(tmp_path, monkeypatch, sent: list[str]):
    import gia.notify.email as email_mod
    from gia import __main__ as cli

    monkeypatch.setattr(email_mod, "send_email",
                        lambda cfg, subject, html, text, smtp_factory=None, attachments=None: sent.append(subject) or 1)
    for k, v in {"SMTP_HOST": "smtp.example.org", "EMAIL_TO": "me@example.org"}.items():
        monkeypatch.setenv(k, v)
    repo = Path(cli.__file__).resolve().parents[1]
    work = tmp_path / "work"
    shutil.copytree(repo / "config", work / "config")
    (work / "data").mkdir()
    f = work / "config" / "settings.yaml"
    f.write_text(re.sub(r"channels:\s*\[[^\]]*\]", "channels: [email]", f.read_text(encoding="utf-8")), encoding="utf-8")
    monkeypatch.chdir(work)
    return cli, Store(work / "data")


def test_first_degraded_collect_holds_then_second_collect_sends(tmp_path, monkeypatch):
    sent: list[str] = []
    cli, store = _workspace(tmp_path, monkeypatch, sent)
    day = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)  # 자정 직후에 돌아도 날짜가 안 바뀌게
    many = ["changwon", "tongyeong", "sacheon", "gimhae"]
    store.save_run(_run(day - timedelta(hours=11), ["hadong"], many))
    store.save_run(_run(day + timedelta(minutes=1), ["hadong", *many], []))

    # 오늘 첫 수집이 무너졌다 → 보내지 않고 보고 기록도 남기지 않는다
    assert cli.main(["report", "--send", "--once-daily", "--hold-if-degraded", "3"]) == 0
    assert sent == []
    assert not Store(Path("data")).load().reported_on(day.date())

    # 두 번째 수집 뒤에는 (또 무너졌어도) 있는 대로 보낸다
    store.save_run(_run(day + timedelta(minutes=2), ["hadong", *many], []))
    assert cli.main(["report", "--send", "--once-daily", "--hold-if-degraded", "3"]) == 0
    assert len(sent) == 1


def test_chronic_failures_do_not_hold(tmp_path, monkeypatch):
    """늘 막히는 곳(하동 등)만 실패한 날은 첫 수집 뒤에 바로 보낸다."""
    sent: list[str] = []
    cli, store = _workspace(tmp_path, monkeypatch, sent)
    day = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    chronic = ["hadong", "gojobs", "geochang"]
    store.save_run(_run(day - timedelta(hours=11), chronic, ["changwon"]))
    store.save_run(_run(day + timedelta(minutes=1), chronic, ["changwon"]))
    assert cli.main(["report", "--send", "--once-daily", "--hold-if-degraded", "3"]) == 0
    assert len(sent) == 1


def test_without_flag_degraded_collect_still_sends(tmp_path, monkeypatch):
    """예비 예약(플래그 없음)은 수집 상태와 상관없이 보낸다."""
    sent: list[str] = []
    cli, store = _workspace(tmp_path, monkeypatch, sent)
    day = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    store.save_run(_run(day + timedelta(minutes=1), ["a", "b", "c", "d"], []))
    assert cli.main(["report", "--send", "--once-daily"]) == 0
    assert len(sent) == 1
