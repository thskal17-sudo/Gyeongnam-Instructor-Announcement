"""이메일 발송 (SMTP). docs/DESIGN.md 10절."""
from __future__ import annotations

import re
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Callable

# Gmail 앱 비밀번호는 "abcd efgh ijkl mnop" 처럼 4자씩 끊어 보여주지만 공백은 값의 일부가 아니다.
_APP_PASSWORD = re.compile(r"^[a-z]{4}( [a-z]{4}){3}$", re.I)


def _clean(v: str | None) -> str | None:
    """Secrets 에 붙여넣을 때 딸려온 앞뒤 공백·줄바꿈을 떼어낸다."""
    return v.strip() if isinstance(v, str) else v


def _clean_password(v: str | None) -> str | None:
    v = _clean(v)
    return v.replace(" ", "") if v and _APP_PASSWORD.match(v) else v


@dataclass
class SmtpConfig:
    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    sender: str | None = None
    to: list[str] = field(default_factory=list)
    use_ssl: bool | None = None  # None이면 포트 465일 때 SSL

    @classmethod
    def from_env(cls, env: dict) -> "SmtpConfig | None":
        host = _clean(env.get("SMTP_HOST"))
        to = [x.strip() for x in (env.get("EMAIL_TO") or "").split(",") if x.strip()]
        if not host or not to:
            return None
        user = _clean(env.get("SMTP_USER"))
        return cls(
            host=host, port=int(_clean(env.get("SMTP_PORT")) or 587), user=user,
            password=_clean_password(env.get("SMTP_PASSWORD")), sender=_clean(env.get("EMAIL_FROM")) or user, to=to,
        )


def build_message(cfg: SmtpConfig, subject: str, html: str, text: str,
                  attachments: list[tuple[str, bytes]] | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"경남 강사공고 알림 <{cfg.sender}>" if cfg.sender else "경남 강사공고 알림"
    msg["To"] = ", ".join(cfg.to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for name, blob in attachments or []:
        # add_attachment 를 set_content 뒤에 부르면 multipart/mixed 로 올려 주므로
        # 본문 대체(text/plain + text/html) 구조는 그대로 유지된다
        msg.add_attachment(blob, maintype="application", filename=name,
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return msg


def send_email(cfg: SmtpConfig, subject: str, html: str, text: str,
               smtp_factory: Callable | None = None,
               attachments: list[tuple[str, bytes]] | None = None) -> int:
    """메일을 보내고 수신자 수를 돌려준다. smtp_factory는 테스트용 주입점."""
    msg = build_message(cfg, subject, html, text, attachments)
    use_ssl = cfg.use_ssl if cfg.use_ssl is not None else cfg.port == 465
    factory = smtp_factory or (smtplib.SMTP_SSL if use_ssl else smtplib.SMTP)
    with factory(cfg.host, cfg.port, timeout=30) as smtp:
        if not use_ssl and smtp_factory is None:
            smtp.starttls()
        if cfg.user and cfg.password:
            smtp.login(cfg.user, cfg.password)
        smtp.send_message(msg)
    return len(cfg.to)
