"""
WordPress publish — payload builder and HTTP client. No Qt imports.
"""
import base64
import json
import mimetypes
import posixpath
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


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _bold_to_html(text: str) -> str:
    """Converts **bold** markers to <strong> tags (same convention as epub._paragraph_to_html)."""
    parts = _BOLD_RE.split(text)
    return "".join(f"<strong>{p}</strong>" if i % 2 == 1 else p for i, p in enumerate(parts))


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
            parts.append(f"<p>{_bold_to_html(text)}</p>")
    return "\n".join(parts)


def get_first_line(lines: list[dict]) -> str:
    for ln in lines:
        if ln.get("prefix") != "$" and ln["translated_text"].strip():
            return ln["translated_text"]
    return ""


def _encode_image(row: dict) -> dict:
    mime = mimetypes.guess_type(row["src_path"])[0] or "application/octet-stream"
    return {
        "filename": posixpath.basename(row["src_path"]) or row["src_path"],
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
        anchor = im["anchor_position"]
        if anchor in boundaries:
            position = boundaries[anchor]
        else:
            preceding = [k for k in boundaries if k <= anchor]
            position = boundaries[max(preceding)] if preceding else emitted
        result.append({"position": position, **_encode_image(im)})
    return result


_ILLUS_BATCH_BYTES = 800_000


def build_illustrations_payloads(
    doc_meta: dict,
    series_meta: dict,
    images: list[dict],
    api_key: str,
    cover: dict | None = None,
) -> list[dict]:
    """Split a volume's illustrations into per-request payloads.

    The WP host's proxy resets bodies over ~1 MB, so a volume's art cannot
    ship in one JSON POST. Element 0 carries ``mode: "replace"`` (plus the
    cover, if any); the rest carry ``mode: "append"``. Images arrive
    already downscaled by the caller (``imageopt.shrink_image``) — this
    function only groups them under ``_ILLUS_BATCH_BYTES`` of base64.
    """
    if not series_meta.get("series_slug"):
        raise ValueError("series_slug is required — set it in Series Manager")
    if not series_meta.get("series_title_short"):
        raise ValueError("series_title_short is required — set it in Series Manager")

    base = {
        "api_key":            api_key,
        "series_title":       doc_meta["series_title"],
        "series_slug":        series_meta["series_slug"],
        "series_title_short": series_meta["series_title_short"],
        "series_link":        series_meta.get("syosetu_url") or "",
    }
    if doc_meta.get("volume_title"):
        base["volume_title"] = doc_meta["volume_title"]

    enc_cover = _encode_image(cover) if cover is not None else None
    encoded = [_encode_image(im) for im in images]

    batches: list[list[dict]] = [[]]
    size = len(enc_cover["data_base64"]) if enc_cover else 0
    for e in encoded:
        b = len(e["data_base64"])
        # Split when the running batch already has content, OR when batch 0 is
        # still empty but already carries the cover's bytes — so a big cover and
        # the first image never share a single over-budget request body.
        if (batches[-1] or (enc_cover is not None and len(batches) == 1)) and size + b > _ILLUS_BATCH_BYTES:
            batches.append([])
            size = 0
        batches[-1].append(e)
        size += b

    payloads = []
    for i, batch in enumerate(batches):
        p = {**base, "images": batch, "mode": "replace" if i == 0 else "append"}
        if i == 0 and enc_cover is not None:
            p["cover"] = enc_cover
        payloads.append(p)
    return payloads


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
    previous_chapter_index: int | None = None,
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
        if images:
            payload["images"] = build_image_payload(lines, images)
        if cover is not None and doc_meta["series_order"] == 1:
            # Cover only rides along on chapter 1 — repeating a ~1 MB base64
            # blob on every chapter blew the WP host's request-body limit.
            payload["cover"] = _encode_image(cover)
    if password is not None:
        payload["password"] = password
    if unlock_chapter_index is not None:
        payload["unlock_chapter_index"] = unlock_chapter_index
    if scheduled_date is not None:
        payload["publish_date"] = scheduled_date
    if previous_chapter_index is not None and previous_chapter_index != doc_meta["series_order"]:
        payload["previous_chapter_index"] = previous_chapter_index
    if doc_meta.get("volume_title"):
        payload["volume_title"] = doc_meta["volume_title"]
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
            msg = body.get("error") or body.get("message") or str(exc)
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
            msg = body.get("error") or body.get("message") or str(exc)
        except Exception:
            msg = str(exc)
        raise WPPublishError(msg, status_code=exc.code) from exc
    except URLError as exc:
        raise WPPublishError(f"Could not reach {endpoint_url}: {exc.reason}", status_code=None) from exc


_ILLUSTRATIONS_PATH = "/wp-json/ta-publisher/v1/illustrations"


def publish_illustrations(endpoint_url: str, payload: dict, timeout: int = 60) -> dict:
    base = endpoint_url.rstrip("/")
    if base.endswith(_ENDPOINT_PATH):
        base = base[: -len(_ENDPOINT_PATH)]
    url = base + _ILLUSTRATIONS_PATH
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise WPPublishError(
                    f"Server returned non-JSON response: {body[:200]!r}", status_code=None
                )
    except HTTPError as exc:
        try:
            body = json.loads(exc.read())
            msg = body.get("error") or body.get("message") or str(exc)
        except Exception:
            msg = str(exc)
        raise WPPublishError(msg, status_code=exc.code) from exc
    except URLError as exc:
        raise WPPublishError(
            f"Could not reach {url}: {exc.reason}", status_code=None
        ) from exc
