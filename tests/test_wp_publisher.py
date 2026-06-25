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
    assert payload["chapter_title"] == "The Beginning"
    assert payload["chapter_body"] == "<p>Hello</p>\n<p>World</p>"
    assert payload["first_line"] == "Hello"

def test_build_payload_synopsis_omits_first_line():
    doc_meta, series_meta, lines = _sample_meta()
    doc_meta["series_order"] = 0
    payload = build_payload(doc_meta, series_meta, lines, api_key="key123")
    assert "first_line" not in payload

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
