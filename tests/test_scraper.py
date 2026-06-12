"""
Tests for scraper.py — fetch_series_index, IndexFetchWorker, SeriesFetchWorker.
"""
from unittest.mock import MagicMock, patch

import pytest

from translation_assistant.scraper import (
    fetch_series_index,
    IndexFetchWorker,
    SeriesFetchWorker,
)
from translation_assistant.scraper import _para_text
from bs4 import BeautifulSoup


def _p(html: str):
    """Parse a bare <p> tag for use in _para_text tests."""
    return BeautifulSoup(f"<p>{html}</p>", "html.parser").find("p")

_TOC_HTML = """
<html><body>
<div class="p-eplist__sublist">
  <a href="/n7696mg/1/">第一話　始まり</a>
</div>
<div class="p-eplist__sublist">
  <a href="/n7696mg/2/">第二話　出会い</a>
</div>
<div class="p-eplist__sublist">
  <a href="/n7696mg/3/">第三話　決意</a>
</div>
</body></html>
"""

_TOC_HTML_OLD = """
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


def test_fetch_series_index_parses_chapters_old_format():
    mock_resp = MagicMock()
    mock_resp.text = _TOC_HTML_OLD
    mock_resp.raise_for_status = MagicMock()

    with patch("translation_assistant.scraper.requests.get", return_value=mock_resp):
        chapters = fetch_series_index("https://novel18.syosetu.com/n7696mg/")

    assert len(chapters) == 3
    assert chapters[0] == {
        "num": 1,
        "title": "第一話　始まり",
        "url": "https://novel18.syosetu.com/n7696mg/1/",
    }


def test_fetch_series_index_follows_pagination():
    page1_html = """
<html><body>
<div class="p-eplist__sublist"><a href="/n0280z/1/">第一話</a></div>
<div class="p-eplist__sublist"><a href="/n0280z/2/">第二話</a></div>
<a class="c-pager__item c-pager__item--next" href="/n0280z/?p=2">次へ</a>
</body></html>
"""
    page2_html = """
<html><body>
<div class="p-eplist__sublist"><a href="/n0280z/3/">第三話</a></div>
</body></html>
"""
    responses = [
        MagicMock(text=page1_html, raise_for_status=MagicMock()),
        MagicMock(text=page2_html, raise_for_status=MagicMock()),
    ]

    with patch("translation_assistant.scraper.requests.get", side_effect=responses):
        chapters = fetch_series_index("https://novel18.syosetu.com/n0280z/")

    assert len(chapters) == 3
    assert [c["num"] for c in chapters] == [1, 2, 3]


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
        worker.chapter_done.connect(lambda n, t, c, u: done.append((n, t, c)))
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


class TestParaText:
    def test_plain_text_unchanged(self):
        assert _para_text(_p("普通のテキスト")) == "普通のテキスト"

    def test_ruby_rendered_as_parenthesis(self):
        assert _para_text(_p("<ruby>文章<rt>ぶんしょう</rt></ruby>")) == "文章(ぶんしょう)"

    def test_ruby_with_rb_tag(self):
        assert _para_text(_p("<ruby><rb>漢字</rb><rt>かんじ</rt></ruby>")) == "漢字(かんじ)"

    def test_ruby_without_rt_emits_base_only(self):
        assert _para_text(_p("<ruby>テスト</ruby>")) == "テスト"

    def test_ruby_inline_with_surrounding_text(self):
        result = _para_text(_p("彼は<ruby>魔王<rt>まおう</rt></ruby>だ"))
        assert result == "彼は魔王(まおう)だ"

    def test_multiple_ruby_in_one_paragraph(self):
        result = _para_text(_p(
            "<ruby>山<rt>やま</rt></ruby>と<ruby>川<rt>かわ</rt></ruby>"
        ))
        assert result == "山(やま)と川(かわ)"

    def test_empty_paragraph(self):
        assert _para_text(_p("")) == ""

    def test_rp_tags_ignored(self):
        result = _para_text(_p("<ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp></ruby>"))
        assert result == "漢(かん)"


_CHAPTER_HTML_RUBY = """
<html><body>
<h1 class="p-novel__title--rensai">第一話　始まり</h1>
<div class="js-novel-text p-novel__text">
  <p>彼は<ruby>魔王<rt>まおう</rt></ruby>だった。</p>
  <p>普通のテキスト</p>
</div>
</body></html>
"""


def test_fetch_syosetu_renders_ruby_as_parenthesis():
    mock_resp = MagicMock()
    mock_resp.text = _CHAPTER_HTML_RUBY
    mock_resp.raise_for_status = MagicMock()

    from translation_assistant.scraper import fetch_syosetu
    with patch("translation_assistant.scraper.requests.get", return_value=mock_resp):
        title, content = fetch_syosetu("https://ncode.syosetu.com/n1234ab/1/")

    assert title == "第一話　始まり"
    assert "魔王(まおう)" in content
    assert "普通のテキスト" in content


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
        worker.chapter_done.connect(lambda n, t, c, u: done.append(n))
        worker.error.connect(lambda n, m: errors.append(n))
        worker.run()

    assert 1 in errors
    assert 2 in done
    assert 3 in done


def test_series_fetch_worker_emits_url_in_chapter_done(qapp):
    chapters = [{"num": 1, "title": "Ch1", "url": "https://ncode.syosetu.com/n1234ab/1/"}]
    done = []

    with patch("translation_assistant.scraper.fetch_syosetu", return_value=("Title", "Content")), \
         patch("translation_assistant.scraper.QThread.sleep"):
        worker = SeriesFetchWorker(chapters)
        worker.chapter_done.connect(lambda n, t, c, u: done.append(u))
        worker.run()

    assert done == ["https://ncode.syosetu.com/n1234ab/1/"]
