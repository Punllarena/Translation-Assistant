"""
WordPress publish — payload builder and HTTP client. No Qt imports.
"""
import json
import re
import secrets
import string
import urllib.request
from urllib.error import HTTPError, URLError


class WPPublishError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text).strip("-")


def build_chapter_body(lines: list[dict]) -> str:
    parts = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.get("prefix") == "$":
            i += 1
            continue
        group = [ln["translated_text"]]
        i += 1
        while i < len(lines) and lines[i].get("prefix") == "$":
            group.append(lines[i]["translated_text"])
            i += 1
        text = " ".join(t for t in group if t.strip())
        if text:
            parts.append(f"<p>{text}</p>")
    return "\n".join(parts)


def get_first_line(lines: list[dict]) -> str:
    for ln in lines:
        if ln.get("prefix") != "$" and ln["translated_text"].strip():
            return ln["translated_text"]
    return ""


_ALPHANUM = string.ascii_letters + string.digits


def resolve_wp_password_enabled(pw_settings: dict, global_enabled: bool) -> bool:
    """Resolve password-protection enablement for a publish operation.

    ``pw_settings`` is the dict returned by
    ``db.get_series_wp_password_settings()``.  A series-level override of
    ``"1"`` or ``"0"`` takes precedence; ``None`` falls back to the global
    AppSettings value.
    """
    pw_enabled_raw = pw_settings["wp_password_enabled"]
    if pw_enabled_raw is not None:
        return pw_enabled_raw == "1"
    return global_enabled


def compute_password_fields(
    chapter_index: int, unlock_after: int
) -> tuple[str | None, int | None]:
    if chapter_index == 0 or chapter_index <= unlock_after:
        return None, None
    password = "".join(secrets.choice(_ALPHANUM) for _ in range(12))
    unlock_idx = chapter_index - unlock_after
    return password, (unlock_idx if unlock_idx > unlock_after else None)


def build_payload(
    doc_meta: dict,
    series_meta: dict,
    lines: list[dict],
    api_key: str,
    password: str | None = None,
    unlock_chapter_index: int | None = None,
    scheduled_date: str | None = None,
) -> dict:
    if not series_meta.get("series_slug"):
        raise ValueError("series_slug is required — set it in Series Manager")
    if not series_meta.get("series_title_short"):
        raise ValueError("series_title_short is required — set it in Series Manager")

    payload: dict = {
        "api_key":            api_key,
        "series_title":       doc_meta["series_title"],
        "series_slug":        series_meta["series_slug"],
        "series_title_short": series_meta["series_title_short"],
        "series_link":        series_meta["syosetu_url"],
        "chapter_index":      doc_meta["series_order"],
        "chapter_title":      f"{series_meta['series_title_short']} {doc_meta['chapter_title']}",
        "chapter_body":       build_chapter_body(lines),
    }
    if doc_meta["series_order"] != 0:
        payload["first_line"] = get_first_line(lines)
    if password is not None:
        payload["password"] = password
    if unlock_chapter_index is not None:
        payload["unlock_chapter_index"] = unlock_chapter_index
    if scheduled_date is not None:
        payload["publish_date"] = scheduled_date
    return payload


_ENDPOINT_PATH = "/wp-json/ta-publisher/v1/publish"


def normalize_endpoint_url(url: str) -> str:
    url = url.rstrip("/")
    if not url.endswith(_ENDPOINT_PATH):
        url += _ENDPOINT_PATH
    return url


def publish(endpoint_url: str, payload: dict, timeout: int = 15) -> dict:
    endpoint_url = normalize_endpoint_url(endpoint_url)
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise WPPublishError(
                    f"Server returned non-JSON response: {body[:200]!r}",
                    status_code=None,
                )
    except HTTPError as exc:
        if exc.code == 409:
            try:
                return json.loads(exc.read())
            except Exception:
                return {"created": False}
        try:
            body = json.loads(exc.read())
            msg = body.get("message", str(exc))
        except Exception:
            msg = str(exc)
        raise WPPublishError(msg, status_code=exc.code) from exc
    except URLError as exc:
        raise WPPublishError(f"Could not reach {endpoint_url}: {exc.reason}", status_code=None) from exc
