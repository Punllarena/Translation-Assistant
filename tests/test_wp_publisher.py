import json
import pytest
from unittest.mock import patch, MagicMock
from urllib.error import URLError, HTTPError
from translation_assistant.wp_publisher import (
    slugify, build_chapter_body, get_first_line, build_payload,
    publish, WPPublishError,
)


def test_slugify_basic():
    assert slugify("Sword of the Wanderer") == "sword-of-the-wanderer"

def test_slugify_special_chars():
    assert slugify("Héros & Villain!") == "hros-villain"

def test_slugify_extra_dashes():
    assert slugify("  hello   world  ") == "hello-world"

def test_build_chapter_body_basic():
    lines = [
        {"translated_text": "Hello world"},
        {"translated_text": ""},
        {"translated_text": "Second line"},
    ]
    result = build_chapter_body(lines)
    assert result == "<p>Hello world</p>\n<p>Second line</p>"

def test_build_chapter_body_all_empty():
    lines = [{"translated_text": ""}, {"translated_text": "   "}]
    assert build_chapter_body(lines) == ""

def test_build_chapter_body_merges_continuations():
    lines = [
        {"prefix": "%", "translated_text": "「That makes it sound like all we do is sex."},
        {"prefix": "$", "translated_text": "That's not our relationship」"},
        {"prefix": "%", "translated_text": "Mikiri shows a wide smile."},
    ]
    result = build_chapter_body(lines)
    assert result == (
        "<p>「That makes it sound like all we do is sex. That's not our relationship」</p>\n"
        "<p>Mikiri shows a wide smile.</p>"
    )

def test_get_first_line_skips_continuation():
    lines = [
        {"prefix": "$", "translated_text": "orphan continuation"},
        {"prefix": "%", "translated_text": "Real first"},
    ]
    assert get_first_line(lines) == "Real first"

def test_get_first_line_returns_first_nonempty():
    lines = [
        {"translated_text": ""},
        {"translated_text": "First real line"},
        {"translated_text": "Second line"},
    ]
    assert get_first_line(lines) == "First real line"

def test_get_first_line_all_empty():
    lines = [{"translated_text": ""}, {"translated_text": "   "}]
    assert get_first_line(lines) == ""

def _sample_meta():
    doc_meta = {
        "series_title": "Sword of the Wanderer",
        "series_order": 1,
        "chapter_title": "The Beginning",
    }
    series_meta = {
        "series_slug": "sword-of-the-wanderer",
        "series_title_short": "SotW",
        "syosetu_url": "https://ncode.syosetu.com/n1234ab/",
    }
    lines = [{"translated_text": "Hello"}, {"translated_text": "World"}]
    return doc_meta, series_meta, lines

def test_build_payload_chapter():
    doc_meta, series_meta, lines = _sample_meta()
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123")
    assert payload["api_key"] == "key123"
    assert payload["series_title"] == "Sword of the Wanderer"
    assert payload["series_slug"] == "sword-of-the-wanderer"
    assert payload["series_title_short"] == "SotW"
    assert payload["series_link"] == "https://ncode.syosetu.com/n1234ab/"
    assert payload["chapter_index"] == 1
    assert payload["chapter_title"] == "SotW The Beginning"
    assert payload["chapter_body"].startswith("<p>Hello</p>\n<p>World</p>")
    assert "Translation Assistant" in payload["chapter_body"]
    assert payload["first_line"] == "Hello"

def test_build_payload_synopsis_omits_first_line():
    doc_meta, series_meta, lines = _sample_meta()
    doc_meta["series_order"] = 0
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123")
    assert "first_line" not in payload

def test_build_payload_attribution_disabled():
    doc_meta, series_meta, lines = _sample_meta()
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123", attribution=False)
    assert payload["chapter_body"] == "<p>Hello</p>\n<p>World</p>"

def test_build_payload_missing_series_slug_raises():
    doc_meta, series_meta, lines = _sample_meta()
    series_meta["series_slug"] = ""
    with pytest.raises(ValueError, match="series_slug"):
        build_payload(doc_meta, series_meta, lines, api_key="key123")

def test_build_payload_missing_series_title_short_raises():
    doc_meta, series_meta, lines = _sample_meta()
    series_meta["series_title_short"] = ""
    with pytest.raises(ValueError, match="series_title_short"):
        build_payload(doc_meta, series_meta, lines, api_key="key123")

def test_publish_success():
    response_data = {"created": True, "page_url": "https://site.com/series/", "post_url": "https://site.com/ch1/"}
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = json.dumps(response_data).encode()
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = publish("https://example.com/endpoint", {"api_key": "k"})
    assert result["created"] is True

def test_publish_http_error_raises_wp_publish_error():
    err = HTTPError("url", 401, "Unauthorized", {}, None)
    err.read = lambda: b'{"message": "bad key"}'
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(WPPublishError) as exc_info:
            publish("https://example.com/endpoint", {"api_key": "k"})
    assert exc_info.value.status_code == 401

def test_publish_connection_error_raises_wp_publish_error():
    with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
        with pytest.raises(WPPublishError) as exc_info:
            publish("https://example.com/endpoint", {"api_key": "k"})
    assert exc_info.value.status_code is None

def test_publish_409_treated_as_success():
    response_data = {"created": False, "page_url": "https://site.com/series/"}
    err = HTTPError("url", 409, "Conflict", {}, None)
    err.read = lambda: json.dumps(response_data).encode()
    with patch("urllib.request.urlopen", side_effect=err):
        result = publish("https://example.com/endpoint", {"api_key": "k"})
    assert result["created"] is False
    assert result["page_url"] == "https://site.com/series/"


import secrets as _secrets

from translation_assistant.wp_publisher import compute_password_fields, build_payload


@pytest.mark.parametrize("chapter_index,unlock_after,expect_pw,expect_unlock", [
    (0,  3, False, None),   # synopsis — always free
    (1,  3, False, None),   # within free window
    (3,  3, False, None),   # boundary — still free
    (4,  3, True,  None),   # first locked chapter, no unlock yet
    (6,  3, True,  None),   # 6-3=3, 3>3 is False — no unlock
    (7,  3, True,  4),      # 7-3=4, 4>3 — unlock ch4
    (11, 5, True,  6),      # 11-5=6, 6>5 — unlock ch6
])
def test_compute_password_fields(chapter_index, unlock_after, expect_pw, expect_unlock):
    pw, unlock_idx = compute_password_fields(chapter_index, unlock_after)
    assert (pw is not None) == expect_pw
    assert unlock_idx == expect_unlock
    if expect_pw:
        assert len(pw) > 0


def test_compute_password_fields_password_is_random():
    pw1, _ = compute_password_fields(5, 3)
    pw2, _ = compute_password_fields(5, 3)
    assert pw1 != pw2


def test_compute_password_fields_password_is_alphanumeric():
    import string
    pw, _ = compute_password_fields(5, 3)
    assert pw is not None
    assert len(pw) == 12
    assert all(c in string.ascii_letters + string.digits for c in pw)


def test_build_payload_includes_password_and_unlock():
    doc_meta = {"series_title": "T", "series_order": 7, "chapter_title": "Ch7"}
    series_meta = {"series_slug": "t", "series_title_short": "T", "syosetu_url": ""}
    lines = [{"prefix": "%", "translated_text": "Hello"}]
    payload = build_payload(doc_meta, series_meta, lines, "key",
                            password="abc123", unlock_chapter_index=4)
    assert payload["password"] == "abc123"
    assert payload["unlock_chapter_index"] == 4


def test_build_payload_omits_password_fields_when_none():
    doc_meta = {"series_title": "T", "series_order": 1, "chapter_title": "Ch1"}
    series_meta = {"series_slug": "t", "series_title_short": "T", "syosetu_url": ""}
    lines = [{"prefix": "%", "translated_text": "Hello"}]
    payload = build_payload(doc_meta, series_meta, lines, "key")
    assert "password" not in payload
    assert "unlock_chapter_index" not in payload


# ---------------------------------------------------------------------------
# resolve_wp_password_enabled — series override vs. global fallback
# ---------------------------------------------------------------------------

from translation_assistant.wp_publisher import resolve_wp_password_enabled


def test_publish_wp_password_resolution_series_on():
    """Series override "1" → enabled regardless of global setting."""
    pw_settings = {"wp_password_enabled": "1", "wp_unlock_after": -1}
    assert resolve_wp_password_enabled(pw_settings, global_enabled=False) is True


def test_publish_wp_password_resolution_series_off():
    """Series override "0" → disabled regardless of global setting."""
    pw_settings = {"wp_password_enabled": "0", "wp_unlock_after": -1}
    assert resolve_wp_password_enabled(pw_settings, global_enabled=True) is False


def test_publish_wp_password_resolution_inherit_global_on():
    """Series override None → falls back to global=True."""
    pw_settings = {"wp_password_enabled": None, "wp_unlock_after": -1}
    assert resolve_wp_password_enabled(pw_settings, global_enabled=True) is True


def test_publish_wp_password_resolution_inherit_global_off():
    """Series override None → falls back to global=False."""
    pw_settings = {"wp_password_enabled": None, "wp_unlock_after": -1}
    assert resolve_wp_password_enabled(pw_settings, global_enabled=False) is False


from translation_assistant.wp_publisher import check_status


def test_check_status_success():
    response_data = {"status": "future", "post_url": "https://example.com/series-c1/"}
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(response_data).encode()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        result = check_status(
            "https://example.com/wp-json/ta-publisher/v1/publish",
            "key123", "my-series", 1,
        )
    assert result == {"status": "future", "post_url": "https://example.com/series-c1/"}
    called_url = mock_open.call_args[0][0].full_url
    assert "/wp-json/ta-publisher/v1/status" in called_url
    assert "series_slug=my-series" in called_url
    assert "chapter=1" in called_url


def test_check_status_derives_url_strips_publish_suffix():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps({"status": "publish", "post_url": None}).encode()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        check_status(
            "https://example.com/wp-json/ta-publisher/v1/publish",
            "k", "s", 0,
        )
    url = mock_open.call_args[0][0].full_url
    assert url.startswith("https://example.com/wp-json/ta-publisher/v1/status")


def test_check_status_401_raises():
    exc = HTTPError("url", 401, "Unauthorized", {}, None)
    exc.read = lambda: b'{"message": "Invalid API key"}'
    with patch("urllib.request.urlopen", side_effect=exc):
        with pytest.raises(WPPublishError) as info:
            check_status(
                "https://example.com/wp-json/ta-publisher/v1/publish",
                "bad", "s", 1,
            )
    assert info.value.status_code == 401


def test_check_status_network_error_raises():
    with patch("urllib.request.urlopen", side_effect=URLError("refused")):
        with pytest.raises(WPPublishError):
            check_status(
                "https://example.com/wp-json/ta-publisher/v1/publish",
                "k", "s", 1,
            )


# ---------------------------------------------------------------------------
# toc_page_url
# ---------------------------------------------------------------------------

from translation_assistant.wp_publisher import toc_page_url


def test_toc_page_url_from_bare_site():
    assert toc_page_url("https://site.com", "my-series") == "https://site.com/my-series/"


def test_toc_page_url_strips_endpoint_path_and_trailing_slash():
    assert (
        toc_page_url("https://site.com/wp-json/ta-publisher/v1/publish/", "my-series")
        == "https://site.com/my-series/"
    )


# ---------------------------------------------------------------------------
# compute_auto_schedule
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from translation_assistant.wp_publisher import compute_auto_schedule

UTC = timezone.utc


def test_auto_schedule_joins_same_day_when_capacity_left():
    dt = compute_auto_schedule(
        "2026-07-20T12:00:00Z", ["2026-07-20T12:00:00Z"], 2, "20:00", tz=UTC
    )
    assert dt == datetime(2026, 7, 20, 13, 0)


def test_auto_schedule_staggers_from_latest_same_day_slot():
    dt = compute_auto_schedule(
        "2026-07-20T12:00:00Z",
        ["2026-07-20T12:00:00Z", "2026-07-20T15:00:00Z"],
        3, "20:00", tz=UTC,
    )
    assert dt == datetime(2026, 7, 20, 16, 0)


def test_auto_schedule_overflows_to_next_day_at_default_time():
    dt = compute_auto_schedule(
        "2026-07-20T12:00:00Z",
        ["2026-07-20T10:00:00Z", "2026-07-20T12:00:00Z"],
        2, "20:00", tz=UTC,
    )
    assert dt == datetime(2026, 7, 21, 20, 0)


def test_auto_schedule_overflow_falls_back_to_prev_time_without_default():
    dt = compute_auto_schedule(
        "2026-07-20T12:30:00Z", ["2026-07-20T12:30:00Z"], 1, "", tz=UTC
    )
    assert dt == datetime(2026, 7, 21, 12, 30)


def test_auto_schedule_bad_default_time_falls_back_to_prev_time():
    dt = compute_auto_schedule(
        "2026-07-20T12:30:00Z", ["2026-07-20T12:30:00Z"], 1, "bogus", tz=UTC
    )
    assert dt == datetime(2026, 7, 21, 12, 30)


def test_auto_schedule_empty_dates_uses_prev_plus_hour():
    dt = compute_auto_schedule("2026-07-20T12:00:00Z", [], 1, "20:00", tz=UTC)
    assert dt == datetime(2026, 7, 20, 13, 0)


def test_auto_schedule_ignores_other_days_in_count():
    dt = compute_auto_schedule(
        "2026-07-20T12:00:00Z",
        ["2026-07-19T12:00:00Z", "2026-07-20T12:00:00Z", "2026-07-21T12:00:00Z"],
        2, "20:00", tz=UTC,
    )
    assert dt == datetime(2026, 7, 20, 13, 0)
