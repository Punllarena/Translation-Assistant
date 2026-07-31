"""
WordPress publish — payload builder and HTTP client. No Qt imports.
"""
import base64
import json
import mimetypes
import re
import secrets
import string
from datetime import datetime, time, timedelta, timezone, tzinfo
import urllib.request
import urllib.parse
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


def _encode_image(row: dict) -> dict:
    mime = mimetypes.guess_type(row["src_path"])[0] or "application/octet-stream"
    return {
        "filename": row["src_path"],
        "mime": mime,
        "data_base64": base64.b64encode(row["data"]).decode("ascii"),
    }


def build_image_payload(lines: list[dict], images: list[dict]) -> list[dict]:
    """Map document_images rows (line-indexed anchor_position) onto the
    paragraph-indexed `position` the WP payload's `images` list uses.

    Mirrors build_chapter_body's grouping loop so `position` always lands
    on a paragraph boundary matching the <p> blocks that function emits.
    Relies on anchor_position always sitting at a paragraph-group boundary
    (never mid-$-continuation-run) — guaranteed by the EPUB importer.
    """
    if not images:
        return []

    sorted_images = sorted(images, key=lambda im: (im["anchor_position"], im["id"]))

    boundaries: dict[int, int] = {}
    emitted = 0
    i = 0
    n = len(lines)
    while i < n:
        boundaries[i] = emitted
        if lines[i].get("prefix") == "$":
            i += 1
            continue
        group = [lines[i]["translated_text"]]
        i += 1
        while i < n and lines[i].get("prefix") == "$":
            group.append(lines[i]["translated_text"])
            i += 1
        text = " ".join(t for t in group if t.strip())
        if text:
            emitted += 1
    boundaries[n] = emitted

    result = []
    for im in sorted_images:
        position = boundaries.get(im["anchor_position"], emitted)
        result.append({"position": position, **_encode_image(im)})
    return result


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


_WP_DATE_FMT = "%Y-%m-%dT%H:%M:%SZ"


def compute_auto_schedule(
    prev_wp_date: str,
    wp_dates: list[str],
    chapters_per_day: int,
    default_time: str,
    tz: tzinfo | None = None,
) -> datetime:
    """Pick the schedule slot for the next chapter after a scheduled one.

    Dates are UTC strings in WP format; "same day" is judged in ``tz``
    (system local when None).  Returns a naive datetime in ``tz``: while the
    predecessor's day holds fewer than ``chapters_per_day`` entries of
    ``wp_dates``, one hour after that day's latest slot; otherwise the next
    day at ``default_time`` (falling back to the predecessor's time).
    """
    def to_local(s: str) -> datetime:
        return (
            datetime.strptime(s, _WP_DATE_FMT)
            .replace(tzinfo=timezone.utc)
            .astimezone(tz)
        )

    prev_local = to_local(prev_wp_date)
    target = prev_local.date()
    same_day = [d for d in map(to_local, wp_dates) if d.date() == target]
    if len(same_day) < chapters_per_day:
        latest = max(same_day, default=prev_local)
        return (latest + timedelta(hours=1)).replace(
            tzinfo=None, second=0, microsecond=0
        )
    next_day = target + timedelta(days=1)
    if default_time:
        try:
            h, m = map(int, default_time.split(":"))
            return datetime.combine(next_day, time(h, m))
        except ValueError:
            pass
    return datetime.combine(
        next_day, prev_local.time().replace(second=0, microsecond=0)
    )


def build_payload(
    doc_meta: dict,
    series_meta: dict,
    lines: list[dict],
    api_key: str,
    password: str | None = None,
    unlock_chapter_index: int | None = None,
    scheduled_date: str | None = None,
    attribution: bool = True,
    images: list[dict] | None = None,
    cover: dict | None = None,
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
    if attribution and doc_meta["series_order"] != 0:
        payload["chapter_body"] += (
            '\n<hr />'
            '<p><em>This post is automatically published by '
            '<a href="https://github.com/Punllarena/Translation-Assistant">Translation Assistant</a>'
            ' and <a href="https://github.com/Punllarena/translation-assistant-publisher">Translation Assistant Publisher</a>.</em></p>'
        )
    if doc_meta["series_order"] != 0:
        payload["first_line"] = get_first_line(lines)
    if password is not None:
        payload["password"] = password
    if unlock_chapter_index is not None:
        payload["unlock_chapter_index"] = unlock_chapter_index
    if scheduled_date is not None:
        payload["publish_date"] = scheduled_date
    if images:
        payload["images"] = build_image_payload(lines, images)
    if cover is not None:
        payload["cover"] = _encode_image(cover)
    return payload


_ENDPOINT_PATH = "/wp-json/ta-publisher/v1/publish"


def normalize_endpoint_url(url: str) -> str:
    url = url.rstrip("/")
    if not url.endswith(_ENDPOINT_PATH):
        url += _ENDPOINT_PATH
    return url


def toc_page_url(endpoint_url: str, series_slug: str) -> str:
    """Series TOC page URL — site root + slug, same shape as the server's page_url."""
    base = endpoint_url.rstrip("/")
    if base.endswith(_ENDPOINT_PATH):
        base = base[: -len(_ENDPOINT_PATH)]
    return f"{base}/{series_slug}/"


_STATUS_PATH = "/wp-json/ta-publisher/v1/status"


def check_status(
    endpoint_url: str,
    api_key: str,
    series_slug: str,
    chapter: int,
    timeout: int = 10,
) -> dict:
    base = endpoint_url.rstrip("/")
    if base.endswith(_ENDPOINT_PATH):
        base = base[: -len(_ENDPOINT_PATH)]
    params = urllib.parse.urlencode({
        "api_key": api_key,
        "series_slug": series_slug,
        "chapter": chapter,
    })
    url = f"{base}{_STATUS_PATH}?{params}"
    req = urllib.request.Request(url, method="GET")
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
        try:
            body = json.loads(exc.read())
            msg = body.get("message", str(exc))
        except Exception:
            msg = str(exc)
        raise WPPublishError(msg, status_code=exc.code) from exc
    except URLError as exc:
        raise WPPublishError(
            f"Could not reach {base}{_STATUS_PATH}: {exc.reason}", status_code=None
        ) from exc


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
