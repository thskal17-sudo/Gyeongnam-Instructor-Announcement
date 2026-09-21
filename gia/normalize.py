"""정규화 규칙 (docs/DESIGN.md 6.1)."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FLAG_WORDS = ["재공고", "재모집", "재채용", "긴급", "수정", "연장", "정정", "추가", "변경"]
SIGUN = [
    "창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산",
    "의령", "함안", "창녕", "고성", "남해", "하동", "산청", "함양", "거창", "합천",
]
GYEONGNAM_WORDS = ["경남", "경상남도"]
ORG_PREFIX_RE = re.compile(r"^\s*(?:\(재\)|\(사\)|\(주\)|재단법인|사단법인|주식회사)\s*")
_BRACKET_RE = re.compile(r"[\[\(【〔]([^\]\)】〕]{1,20})[\]\)】〕]")
_WS_RE = re.compile(r"\s+")
_KEY_RE = re.compile(r"[^0-9a-z가-힣]")
_PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-.\s)]?\d{3,4}[-.\s]?\d{4}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def normalize_title(title: str) -> tuple[str, list[str]]:
    """제목 정리 + 재공고/긴급 등 플래그 분리."""
    t = _WS_RE.sub(" ", nfkc(title)).strip()
    flags: set[str] = set()

    def _sub(m: re.Match) -> str:
        inner = m.group(1).strip()
        hit = [w for w in FLAG_WORDS if w in inner]
        if hit and len(inner) <= 8:
            flags.update(hit)
            return " "
        return m.group(0)

    t = _BRACKET_RE.sub(_sub, t)
    for w in FLAG_WORDS:
        if t.startswith(w + " ") or t.endswith(" " + w):
            flags.add(w)
            t = t.removeprefix(w + " ").removesuffix(" " + w)
    t = _WS_RE.sub(" ", t).strip(" -·:")
    return t, sorted(flags)


def norm_key(s: str) -> str:
    t = nfkc(s).lower()
    for w in FLAG_WORDS:
        t = t.replace(w, "")
    return _KEY_RE.sub("", t)


def standardize_org(name: str, aliases: dict[str, list[str]]) -> str:
    raw = ORG_PREFIX_RE.sub("", _WS_RE.sub(" ", nfkc(name)).strip())
    key = norm_key(raw)
    for canonical, alist in aliases.items():
        if key == norm_key(canonical):
            return canonical
        for a in alist:
            if key == norm_key(a):
                return canonical
    return raw


def extract_regions(text: str) -> list[str]:
    t = nfkc(text)
    out: list[str] = []
    if any(w in t for w in GYEONGNAM_WORDS):
        out.append("경남")
    for s in SIGUN:
        if s in t and s not in out:
            out.append(s)
    return out


def mask_pii(text: str) -> str:
    t = _EMAIL_RE.sub("[이메일]", text or "")
    return _PHONE_RE.sub("[전화번호]", t)


def clean_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(q), ""))
