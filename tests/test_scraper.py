"""
Tests for scraper.py — fetch_series_index, IndexFetchWorker, SeriesFetchWorker.
"""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from translation_assistant.scraper import (
    fetch_series_index,
    IndexFetchWorker,
    SeriesFetchWorker,
)

_TOC_HTML = """
<html><body>
<div class="index_box">
  <dl class="novel_sublist2">
    <dd class="subtitle"><a href="/n7696mg/1/">第一話　始まり</a></dd>
    <dd class="subtitle"><a href="/n7696mg/2/">第二話　出会い</a></dd>
    <dd class="subtitle"><a href="/n7696mg/3/">第三話　決意</a></dd>
  </dl>
</div>
</body></html>
"""


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# fetch_series_index
# ---------------------------------------------------------------------------

def test_fetch_series_index_rejects_chapter_url():
    with pytest.raises(ValueError, match="series root"):
        fetch_series_index("https://ncode.syosetu.com/n7696mg/1/")


def test_fetch_series_index_rejects_non_syosetu():
    with pytest.raises(ValueError):
        fetch_series_index("https://example.com/n7696mg/")


def test_fetch_series_index_parses_chapters():
    mock_resp = MagicMock()
    mock_resp.text = _TOC_HTML
    mock_resp.raise_for_status = MagicMock()

    with patch("translation_assistant.scraper.requests.get", return_value=mock_resp):
        chapters = fetch_series_index("https://novel18.syosetu.com/n7696mg/")

    assert len(chapters) == 3
    assert chapters[0] == {
        "num": 1,
        "title": "第一話　始まり",
        "url": "https://novel18.syosetu.com/n7696mg/1/",
    }
    assert chapters[2]["num"] == 3
    assert chapters[2]["title"] == "第三話　決意"


def test_fetch_series_index_empty_toc():
    empty_html = "<html><body></body></html>"
    mock_resp = MagicMock()
    mock_resp.text = empty_html
    mock_resp.raise_for_status = MagicMock()

    with patch("translation_assistant.scraper.requests.get", return_value=mock_resp):
        result = fetch_series_index("https://ncode.syosetu.com/n1234ab/")

    assert result == []


# ---------------------------------------------------------------------------
# IndexFetchWorker
# ---------------------------------------------------------------------------

def test_index_fetch_worker_emits_finished(qapp):
    chapters = [{"num": 1, "title": "Ch1", "url": "https://ncode.syosetu.com/n1234ab/1/"}]
    results = []
    errors = []

    with patch("translation_assistant.scraper.fetch_series_index", return_value=chapters):
        worker = IndexFetchWorker("https://ncode.syosetu.com/n1234ab/")
        worker.finished.connect(results.append)
        worker.error.connect(errors.append)
        worker.run()

    assert results == [chapters]
    assert errors == []


def test_index_fetch_worker_emits_error(qapp):
    errors = []

    with patch(
        "translation_assistant.scraper.fetch_series_index",
        side_effect=ValueError("bad url"),
    ):
        worker = IndexFetchWorker("https://ncode.syosetu.com/n1234ab/")
        worker.error.connect(errors.append)
        worker.run()

    assert errors == ["bad url"]


# ---------------------------------------------------------------------------
# SeriesFetchWorker
# ---------------------------------------------------------------------------

_CHAPTERS = [
    {"num": 1, "title": "Ch1", "url": "https://ncode.syosetu.com/n1234ab/1/"},
    {"num": 2, "title": "Ch2", "url": "https://ncode.syosetu.com/n1234ab/2/"},
    {"num": 3, "title": "Ch3", "url": "https://ncode.syosetu.com/n1234ab/3/"},
]


def test_series_fetch_worker_emits_chapter_done(qapp):
    done = []
    errors = []

    with patch("translation_assistant.scraper.fetch_syosetu", return_value=("Title", "Content")), \
         patch("translation_assistant.scraper.QThread.sleep"):
        worker = SeriesFetchWorker(_CHAPTERS)
        worker.chapter_done.connect(lambda n, t, c: done.append((n, t, c)))
        worker.error.connect(lambda n, m: errors.append((n, m)))
        worker.run()

    assert len(done) == 3
    assert done[0] == (1, "Title", "Content")
    assert errors == []


def test_series_fetch_worker_sleeps_between_chapters(qapp):
    with patch("translation_assistant.scraper.fetch_syosetu", return_value=("T", "C")), \
         patch("translation_assistant.scraper.QThread.sleep") as mock_sleep:
        worker = SeriesFetchWorker(_CHAPTERS)
        worker.run()

    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(5)


def test_series_fetch_worker_no_sleep_single_chapter(qapp):
    single = [{"num": 1, "title": "Ch1", "url": "https://ncode.syosetu.com/n1234ab/1/"}]
    with patch("translation_assistant.scraper.fetch_syosetu", return_value=("T", "C")), \
         patch("translation_assistant.scraper.QThread.sleep") as mock_sleep:
        worker = SeriesFetchWorker(single)
        worker.run()

    assert mock_sleep.call_count == 0


def test_series_fetch_worker_error_continues(qapp):
    done = []
    errors = []

    def fake_fetch(url):
        if "1/" in url:
            raise ValueError("timeout")
        return ("Title", "Content")

    with patch("translation_assistant.scraper.fetch_syosetu", side_effect=fake_fetch), \
         patch("translation_assistant.scraper.QThread.sleep"):
        worker = SeriesFetchWorker(_CHAPTERS)
        worker.chapter_done.connect(lambda n, t, c: done.append(n))
        worker.error.connect(lambda n, m: errors.append(n))
        worker.run()

    assert 1 in errors
    assert 2 in done
    assert 3 in done
