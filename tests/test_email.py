from gia.notify.email import SmtpConfig, send_email


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.logged_in = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        FakeSMTP.sent.append((self.host, self.port, self.logged_in, msg))


def test_from_env_requires_host_and_to():
    assert SmtpConfig.from_env({}) is None
    cfg = SmtpConfig.from_env({"SMTP_HOST": "smtp.example.org", "EMAIL_TO": "a@x.org, b@x.org", "SMTP_USER": "u", "SMTP_PASSWORD": "p"})
    assert cfg.to == ["a@x.org", "b@x.org"] and cfg.sender == "u" and cfg.port == 587


def test_send_email_builds_multipart():
    cfg = SmtpConfig(host="smtp.example.org", port=465, user="u", password="p", sender="u@x.org", to=["a@x.org"])
    n = send_email(cfg, "[경남 강사공고] 09/21", "<p>html</p>", "text", smtp_factory=FakeSMTP)
    assert n == 1
    host, port, login, msg = FakeSMTP.sent[-1]
    assert (host, port, login) == ("smtp.example.org", 465, ("u", "p"))
    assert msg["Subject"] == "[경남 강사공고] 09/21" and "a@x.org" in msg["To"]
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts and "text/html" in parts


def test_smtp_env_is_cleaned():
    """Secrets 에 딸려온 공백·줄바꿈과 Gmail 앱 비밀번호의 표시용 공백을 떼어낸다."""
    from gia.notify.email import SmtpConfig

    cfg = SmtpConfig.from_env({
        "SMTP_HOST": " smtp.gmail.com\n",
        "SMTP_PORT": " 465 ",
        "SMTP_USER": "  me@gmail.com\n",
        "SMTP_PASSWORD": "abcd efgh ijkl mnop\n",
        "EMAIL_FROM": " me@gmail.com ",
        "EMAIL_TO": " you@gmail.com , other@gmail.com ",
    })
    assert cfg is not None
    assert cfg.host == "smtp.gmail.com"
    assert cfg.port == 465
    assert cfg.user == "me@gmail.com"
    assert cfg.password == "abcdefghijklmnop"
    assert cfg.sender == "me@gmail.com"
    assert cfg.to == ["you@gmail.com", "other@gmail.com"]


def test_non_app_password_keeps_inner_spaces():
    """앱 비밀번호 형태가 아닌 암호는 가운데 공백도 값의 일부이므로 건드리지 않는다."""
    from gia.notify.email import SmtpConfig

    cfg = SmtpConfig.from_env({
        "SMTP_HOST": "mail.example.org",
        "SMTP_PASSWORD": "  correct horse battery staple  ",
        "EMAIL_TO": "you@example.org",
    })
    assert cfg is not None
    assert cfg.password == "correct horse battery staple"
