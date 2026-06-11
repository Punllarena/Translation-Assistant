# Syosetu Fetch Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three related improvements to syosetu chapter fetching: ruby text rendered as `base(reading)`, chapter title included as first translatable line and auto-filled in the metadata field, and a Re-fetch action to retroactively re-apply these changes to existing documents.

**Architecture:** Changes layer cleanly: `scraper.py` gains a `_para_text()` helper used by all fetch paths; `db.py` gains a `source_url` column migration and `replace_raw_content()` method; UI dialogs (`dlg_new`, `dlg_fetch_series`, `dlg_open`) wire up title prepending, URL storage, and the Re-fetch button.

**Tech Stack:** Python 3.11+, PySide6, BeautifulSoup4, SQLite (via `db.py`), pytest with in-memory DB fixture (`_conn` injection seam).

---

## File Map

| File | What changes |
|------|-------------|
| `translation_assistant/scraper.py` | Add `_para_text()` helper; update `fetch_syosetu()` to use it; add `str` (url) to `SeriesFetchWorker.chapter_done` signal |
| `translation_assistant/db.py` | Idempotent `source_url` column migration; `source_url` in `create_document` / `get_document` / `list_documents`; new `replace_raw_content()` method |
| `translation_assistant/ui/dlg_new.py` | `_on_fetch_done` auto-fills `_chapter_edit`; add `source_url` property |
| `translation_assistant/ui/dlg_fetch_series.py` | `_on_chapter_done` prepends title to content; receives URL from signal; passes `source_url` to `create_document` |
| `translation_assistant/ui/main_widget.py` | `load_content()` accepts `source_url`; `_on_new_doc` passes `dlg.source_url` |
| `translation_assistant/ui/dlg_open.py` | Add `_source_urls` dict; Re-fetch button; `_on_refetch()` flow |
| `tests/test_scraper.py` | Tests for `_para_text` and ruby-aware `fetch_syosetu` |
| `tests/test_db.py` | Tests for `source_url` column, `create_document` param, `replace_raw_content` |
| `tests/test_dialogs.py` | Tests for `dlg_new` auto-fill and `source_url` property; `dlg_fetch_series` title-in-content |
| `tests/test_main_window.py` | Test `load_content` stores `source_url` in DB |
| `tests/test_dlg_open.py` | Tests for Re-fetch button enable/disable and `_on_refetch_done` DB effect |

---

## Task 1: Ruby text as parenthesis

**Spec reference:** Feature 1 — `scraper.py`

**Files:**
- Modify: `translation_assistant/scraper.py`
- Test: `tests/test_scraper.py`

- [ ] **Step 1: Write failing tests for `_para_text`**

Add to `tests/test_scraper.py`:

```python
from translation_assistant.scraper import _para_text
from bs4 import BeautifulSoup


def _p(html: str):
    """Parse a bare <p> tag for use in _para_text tests."""
    return BeautifulSoup(f"<p>{html}</p>", "html.parser").find("p")


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
        # <rp> tags are parenthesis hints for non-ruby browsers — should be stripped
        result = _para_text(_p("<ruby>漢<rp>(</rp><rt>かん</rt><rp>)</rp></ruby>"))
        assert result == "漢(かん)"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/pun/workspace/TranslationAssistant-PySide6-Port && source .venv/bin/activate && pytest tests/test_scraper.py::TestParaText -v 2>&1 | tail -15
```

Expected: `ImportError` or `FAILED` (function not yet defined).

- [ ] **Step 3: Add `_para_text` to `scraper.py` and update `fetch_syosetu`**

In `translation_assistant/scraper.py`, replace the existing `fetch_syosetu` function (lines 23–39) with:

```python
def _para_text(p) -> str:
    """Extract text from a <p> tag, rendering <ruby> as base(reading)."""
    parts = []
    for node in p.children:
        if hasattr(node, "name"):
            if node.name == "ruby":
                rb = node.find("rb")
                if rb is not None:
                    base = rb.get_text()
                else:
                    base = "".join(
                        str(c) for c in node.children
                        if not (hasattr(c, "name") and c.name in ("rt", "rp"))
                    )
                rt = node.find("rt")
                reading = rt.get_text() if rt else ""
                parts.append(f"{base}({reading})" if reading else base)
            else:
                parts.append(node.get_text())
        else:
            parts.append(str(node))
    return "".join(parts).strip()


def fetch_syosetu(url: str) -> tuple[str, str]:
    validate_url(url)
    resp = requests.get(url, timeout=10, headers={"User-Agent": _UA}, cookies={"over18": "yes"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = soup.find(class_=lambda c: c and "p-novel__title--rensai" in c.split())
    title = title_el.get_text(strip=True) if title_el else ""

    content_el = soup.find(
        class_=lambda c: c and "js-novel-text" in c.split() and "p-novel__text" in c.split()
    )
    if not content_el:
        raise ValueError("Could not find novel text on page")
    content = "\n".join(_para_text(p) for p in content_el.find_all("p"))

    return title, content
```

- [ ] **Step 4: Write a failing integration test for `fetch_syosetu` ruby handling**

Add to `tests/test_scraper.py` (after the `TestParaText` class):

```python
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
```

- [ ] **Step 5: Run all scraper tests**

```bash
pytest tests/test_scraper.py -v 2>&1 | tail -25
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/scraper.py tests/test_scraper.py
git commit -m "feat(scraper): render ruby annotations as base(reading) in fetched content"
```

---

## Task 2: DB — `source_url` column and `replace_raw_content`

**Spec reference:** Feature 3 — DB layer

**Files:**
- Modify: `translation_assistant/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db.py` (after the existing series-column tests around line 410):

```python
# ---------------------------------------------------------------------------
# source_url column and replace_raw_content
# ---------------------------------------------------------------------------

def test_source_url_column_exists(db):
    cols = _doc_columns(db)
    assert "source_url" in cols


def test_create_document_stores_source_url(db):
    doc_id = db.create_document("Story", source_url="https://ncode.syosetu.com/n1234ab/1/")
    doc = db.get_document(doc_id)
    assert doc["source_url"] == "https://ncode.syosetu.com/n1234ab/1/"


def test_create_document_source_url_defaults_empty(db):
    doc_id = db.create_document("Story")
    doc = db.get_document(doc_id)
    assert doc["source_url"] == ""


def test_list_documents_includes_source_url(db):
    db.create_document("Story", source_url="https://ncode.syosetu.com/n1234ab/1/")
    docs = db.list_documents()
    assert "source_url" in docs[0]
    assert docs[0]["source_url"] == "https://ncode.syosetu.com/n1234ab/1/"


def test_replace_raw_content_replaces_lines(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old A", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "Old B", "translated_text": ""},
    ])
    db.replace_raw_content(doc_id, ["%New A", "%New B"])
    lines = db.get_lines(doc_id)
    assert lines[0]["raw_text"] == "New A"
    assert lines[1]["raw_text"] == "New B"


def test_replace_raw_content_preserves_translations_by_index(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old A", "translated_text": "Trans A"},
        {"line_number": 1, "prefix": "%", "raw_text": "Old B", "translated_text": "Trans B"},
    ])
    db.replace_raw_content(doc_id, ["%New A", "%New B"])
    lines = db.get_lines(doc_id)
    assert lines[0]["translated_text"] == "Trans A"
    assert lines[1]["translated_text"] == "Trans B"


def test_replace_raw_content_extra_new_lines_get_empty_translation(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old", "translated_text": "Trans"},
    ])
    db.replace_raw_content(doc_id, ["%Old", "%Brand New Line"])
    lines = db.get_lines(doc_id)
    assert lines[0]["translated_text"] == "Trans"
    assert lines[1]["translated_text"] == ""


def test_replace_raw_content_fewer_new_lines_drops_excess_translations(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Trans A"},
        {"line_number": 1, "prefix": "%", "raw_text": "B", "translated_text": "Trans B"},
    ])
    db.replace_raw_content(doc_id, ["%A"])
    lines = db.get_lines(doc_id)
    assert len(lines) == 1
    assert lines[0]["translated_text"] == "Trans A"


def test_replace_raw_content_handles_prefix_variants(db):
    doc_id = db.create_document("Story")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "Old", "translated_text": "T"},
    ])
    db.replace_raw_content(doc_id, ["$Continuation line"])
    lines = db.get_lines(doc_id)
    assert lines[0]["prefix"] == "$"
    assert lines[0]["raw_text"] == "Continuation line"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_db.py::test_source_url_column_exists tests/test_db.py::test_replace_raw_content_replaces_lines -v 2>&1 | tail -15
```

Expected: FAIL — column missing, method missing.

- [ ] **Step 3: Add idempotent `source_url` migration in `db.py`**

In `translation_assistant/db.py`, `_apply_schema` method, after the existing `series_profiles` migration block (after line 107), add:

```python
        # Idempotent column migration for source_url on documents
        doc_existing = {r[1] for r in self._conn.execute("PRAGMA table_info(documents)").fetchall()}
        if "source_url" not in doc_existing:
            self._conn.execute(
                "ALTER TABLE documents ADD COLUMN source_url TEXT NOT NULL DEFAULT ''"
            )
        self._conn.commit()
```

- [ ] **Step 4: Update `create_document` to accept `source_url`**

In `translation_assistant/db.py`, replace `create_document` (lines 234–244):

```python
    def create_document(self, title: str, *,
                        series_title: str = "",
                        series_order: int = 0,
                        chapter_title: str = "",
                        source_url: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO documents (title, series_title, series_order, chapter_title, source_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, series_title, series_order, chapter_title, source_url),
        )
        self._conn.commit()
        return cur.lastrowid
```

- [ ] **Step 5: Update `get_document` to return `source_url`**

In `translation_assistant/db.py`, replace the `get_document` SELECT (lines 341–350):

```python
    def get_document(self, doc_id: int) -> dict:
        row = self._conn.execute(
            "SELECT id, title, series_title, series_order, chapter_title, "
            "source_language, created_at, updated_at, last_position, source_url "
            "FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Document {doc_id} not found")
        return dict(row)
```

- [ ] **Step 6: Update `list_documents` to include `source_url`**

In `translation_assistant/db.py`, replace the `list_documents` SELECT (lines 218–232). Add `d.source_url,` after `d.last_position,`:

```python
    def list_documents(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT d.id, d.title, d.series_title, d.series_order, d.chapter_title,
                   d.updated_at, d.last_position, d.source_url,
                   CAST(COALESCE(
                       SUM(CASE WHEN TRIM(l.raw_text) != '' AND l.translated_text != '' THEN 1 ELSE 0 END) * 100
                       / NULLIF(SUM(CASE WHEN TRIM(l.raw_text) != '' THEN 1 ELSE 0 END), 0), 0
                   ) AS INTEGER) AS progress
            FROM documents d
            LEFT JOIN lines l ON l.document_id = d.id
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 7: Add `replace_raw_content` method to `Database`**

In `translation_assistant/db.py`, add after `save_lines` (after line 388):

```python
    def replace_raw_content(self, doc_id: int, new_raw_lines: list[str]) -> None:
        """Replace raw lines, preserving translated_text by line index."""
        existing = self.get_lines(doc_id)
        old_translations = [r["translated_text"] for r in existing]
        rows = []
        for i, ln in enumerate(new_raw_lines):
            if not ln:
                prefix, raw_text = "", ""
            elif ln[0] in ("%", "$"):
                prefix, raw_text = ln[0], ln[1:]
            else:
                prefix, raw_text = "%", ln
            rows.append({
                "line_number": i,
                "prefix": prefix,
                "raw_text": raw_text,
                "translated_text": old_translations[i] if i < len(old_translations) else "",
            })
        self.save_lines(doc_id, rows)
```

- [ ] **Step 8: Run all DB tests**

```bash
pytest tests/test_db.py -v 2>&1 | tail -30
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add source_url column and replace_raw_content method"
```

---

## Task 3: Title as first translatable line

**Spec reference:** Feature 2

**Files:**
- Modify: `translation_assistant/ui/dlg_new.py`
- Modify: `translation_assistant/ui/dlg_fetch_series.py`
- Test: `tests/test_dialogs.py`

- [ ] **Step 1: Write failing test — `dlg_new._on_fetch_done` auto-fills Chapter Title**

Add to `tests/test_dialogs.py` inside `class TestNewFileDialog`:

```python
    def test_on_fetch_done_fills_chapter_title_field(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._on_fetch_done("第一話　始まり", "Some content here.")
        assert dlg._chapter_edit.text() == "第一話　始まり"

    def test_on_fetch_done_does_not_overwrite_when_title_empty(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._chapter_edit.setText("Already Set")
        dlg._on_fetch_done("", "Content only.")
        assert dlg._chapter_edit.text() == "Already Set"

    def test_on_fetch_done_puts_title_in_fetch_box(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._on_fetch_done("Chapter Title", "Body text.")
        assert "Chapter Title" in dlg._fetch_box.toPlainText()
        assert "Body text." in dlg._fetch_box.toPlainText()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest "tests/test_dialogs.py::TestNewFileDialog::test_on_fetch_done_fills_chapter_title_field" -v 2>&1 | tail -10
```

Expected: FAIL — chapter edit not set.

- [ ] **Step 3: Update `_on_fetch_done` in `dlg_new.py`**

In `translation_assistant/ui/dlg_new.py`, replace `_on_fetch_done` (lines 176–181):

```python
    def _on_fetch_done(self, title: str, content: str) -> None:
        combined = f"{title}\n\n{content}" if title else content
        self._fetch_box.setPlainText(combined)
        if title:
            self._chapter_edit.setText(title)
        self._fetch_status.setText("Done")
        self._fetch_btn.setEnabled(True)
        self._worker = None
```

- [ ] **Step 4: Write failing test — `dlg_fetch_series._on_chapter_done` prepends title**

Add to `tests/test_dialogs.py` (new class after `TestNewFileDialog`):

```python
# ---------------------------------------------------------------------------
# FetchSeriesDialog
# ---------------------------------------------------------------------------

class TestFetchSeriesDialog:
    def test_on_chapter_done_prepends_title_to_raw_content(self, qapp, mem_db):
        from unittest.mock import patch
        from translation_assistant.ui.dlg_fetch_series import FetchSeriesDialog

        with patch("translation_assistant.ui.dlg_fetch_series.IndexFetchWorker"):
            dlg = FetchSeriesDialog(mem_db, "My Novel", "https://ncode.syosetu.com/n1234ab/")

        dlg._on_chapter_done(1, "第一話　始まり", "本文です。", "https://ncode.syosetu.com/n1234ab/1/")

        lines = mem_db.get_lines(mem_db.list_documents()[0]["id"])
        assert lines[0]["raw_text"] == "第一話　始まり"

    def test_on_chapter_done_no_title_does_not_prepend_blank(self, qapp, mem_db):
        from unittest.mock import patch
        from translation_assistant.ui.dlg_fetch_series import FetchSeriesDialog

        with patch("translation_assistant.ui.dlg_fetch_series.IndexFetchWorker"):
            dlg = FetchSeriesDialog(mem_db, "My Novel", "https://ncode.syosetu.com/n1234ab/")

        dlg._on_chapter_done(1, "", "本文だけです。", "https://ncode.syosetu.com/n1234ab/1/")

        lines = mem_db.get_lines(mem_db.list_documents()[0]["id"])
        # First content line should not be empty (no blank title prepended)
        assert lines[0]["raw_text"].strip() != ""
```

Note: `_on_chapter_done` currently has signature `(num, title, content)`. We're extending it to `(num, title, content, url)` in Task 4. For now, write the test to call the updated signature directly — the test will fail until both this task AND Task 4 are done. Add a placeholder `url` arg:

```python
        dlg._on_chapter_done(1, "第一話　始まり", "本文です。", "https://ncode.syosetu.com/n1234ab/1/")
```

- [ ] **Step 5: Update `_on_chapter_done` in `dlg_fetch_series.py`**

In `translation_assistant/ui/dlg_fetch_series.py`, replace `_on_chapter_done` (lines 142–152):

```python
    def _on_chapter_done(self, num: int, title: str, content: str, url: str) -> None:
        formatted = build_new_file(f"{title}\n\n{content}" if title else content)
        raw_lines, translated_lines, _ = parse_file_content(formatted)
        rows = lines_to_db_rows(raw_lines, translated_lines)
        doc_id = self._db.create_document(
            title,
            series_title=self._series_title,
            series_order=num,
            chapter_title=title,
            source_url=url,
        )
        self._db.save_lines(doc_id, rows)
        self._added += 1
```

- [ ] **Step 6: Run dialog tests**

```bash
pytest tests/test_dialogs.py::TestNewFileDialog::test_on_fetch_done_fills_chapter_title_field tests/test_dialogs.py::TestNewFileDialog::test_on_fetch_done_does_not_overwrite_when_title_empty tests/test_dialogs.py::TestNewFileDialog::test_on_fetch_done_puts_title_in_fetch_box -v 2>&1 | tail -15
```

Expected: all three PASS. (FetchSeriesDialog tests will fail until Task 4.)

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/dlg_new.py translation_assistant/ui/dlg_fetch_series.py tests/test_dialogs.py
git commit -m "feat(ui): prepend chapter title to raw content; auto-fill chapter title field on fetch"
```

---

## Task 4: Source URL propagation

**Spec reference:** Feature 3 — URL storage on all create paths

**Files:**
- Modify: `translation_assistant/scraper.py` (signal signature)
- Modify: `translation_assistant/ui/dlg_new.py` (property)
- Modify: `translation_assistant/ui/main_widget.py` (pass-through)
- Modify: `translation_assistant/ui/dlg_fetch_series.py` (signal connection)
- Test: `tests/test_dialogs.py`, `tests/test_scraper.py`, `tests/test_main_window.py`

- [ ] **Step 1: Write failing test — `SeriesFetchWorker` emits URL in signal**

Add to `tests/test_scraper.py`:

```python
def test_series_fetch_worker_emits_url_in_chapter_done(qapp):
    chapters = [{"num": 1, "title": "Ch1", "url": "https://ncode.syosetu.com/n1234ab/1/"}]
    done = []

    with patch("translation_assistant.scraper.fetch_syosetu", return_value=("Title", "Content")), \
         patch("translation_assistant.scraper.QThread.sleep"):
        worker = SeriesFetchWorker(chapters)
        worker.chapter_done.connect(lambda n, t, c, u: done.append(u))
        worker.run()

    assert done == ["https://ncode.syosetu.com/n1234ab/1/"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_scraper.py::test_series_fetch_worker_emits_url_in_chapter_done -v 2>&1 | tail -10
```

Expected: FAIL — signal only emits 3 args.

- [ ] **Step 3: Update `SeriesFetchWorker` signal and `run()` in `scraper.py`**

In `translation_assistant/scraper.py`, replace `SeriesFetchWorker` (lines 133–156):

```python
class SeriesFetchWorker(QThread):
    chapter_done = Signal(int, str, str, str)  # num, title, content, url
    progress = Signal(int, int)                # current, total
    error = Signal(int, str)                   # chapter_num, message
    finished = Signal()

    def __init__(self, chapters_to_fetch: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._chapters_to_fetch = chapters_to_fetch

    def run(self) -> None:
        total = len(self._chapters_to_fetch)
        for i, ch in enumerate(self._chapters_to_fetch):
            if self.isInterruptionRequested():
                break
            try:
                title, content = fetch_syosetu(ch["url"])
                self.chapter_done.emit(ch["num"], title, content, ch["url"])
            except Exception as exc:
                self.error.emit(ch["num"], str(exc))
            self.progress.emit(i + 1, total)
            if i < total - 1:
                QThread.sleep(5)
        self.finished.emit()
```

- [ ] **Step 4: Update `_fetch_worker.chapter_done.connect` in `dlg_fetch_series.py`**

The signal connection in `_on_action` (line 136) uses `self._on_chapter_done`. Since `_on_chapter_done` now takes 4 args (num, title, content, url) matching the new signal (int, str, str, str), no change needed to the `connect` line. Verify the existing line reads:

```python
self._fetch_worker.chapter_done.connect(self._on_chapter_done)
```

No change needed — PySide6 routes all four signal args to the four method params automatically.

- [ ] **Step 5: Update existing `test_series_fetch_worker_emits_chapter_done` to use 4-arg lambda**

In `tests/test_scraper.py`, the existing test at line ~170 uses a 3-arg lambda:

```python
worker.chapter_done.connect(lambda n, t, c: done.append((n, t, c)))
```

Replace with:

```python
worker.chapter_done.connect(lambda n, t, c, u: done.append((n, t, c)))
```

And update the assertion (unchanged — `done[0]` is still `(1, "Title", "Content")`).

Also update `test_series_fetch_worker_error_continues` lambda at line ~218:

```python
worker.chapter_done.connect(lambda n, t, c, u: done.append(n))
```

- [ ] **Step 6: Write failing test — `dlg_new.source_url` property**

Add to `tests/test_dialogs.py` inside `class TestNewFileDialog`:

```python
    def test_source_url_property_returns_url_on_fetch_tab(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._tabs.setCurrentIndex(1)
        dlg._url_edit.setText("https://ncode.syosetu.com/n1234ab/1/")
        assert dlg.source_url == "https://ncode.syosetu.com/n1234ab/1/"

    def test_source_url_property_returns_empty_on_paste_tab(self, qapp, mem_db):
        dlg = NewFileDialog(mem_db)
        dlg._tabs.setCurrentIndex(0)
        assert dlg.source_url == ""
```

- [ ] **Step 7: Run to confirm failure**

```bash
pytest "tests/test_dialogs.py::TestNewFileDialog::test_source_url_property_returns_url_on_fetch_tab" -v 2>&1 | tail -10
```

Expected: FAIL — `AttributeError: 'NewFileDialog' object has no attribute 'source_url'`.

- [ ] **Step 8: Add `source_url` property to `dlg_new.py`**

In `translation_assistant/ui/dlg_new.py`, add after the existing `linked_profile` property (after line 231):

```python
    @property
    def source_url(self) -> str:
        if self._tabs.currentIndex() == 1:
            return self._url_edit.text().strip()
        return ""
```

- [ ] **Step 9: Write failing test — `load_content` stores `source_url` in DB**

Add to `tests/test_main_window.py` inside `class TestSaveToDB`:

```python
    def test_load_content_stores_source_url_in_db(self, win):
        content = _sep_file("%A\n")
        win.load_content(content, source_url="https://ncode.syosetu.com/n1234ab/1/")
        doc = win._db.get_document(win._doc_id)
        assert doc["source_url"] == "https://ncode.syosetu.com/n1234ab/1/"

    def test_load_content_source_url_defaults_empty(self, win):
        content = _sep_file("%A\n")
        win.load_content(content)
        doc = win._db.get_document(win._doc_id)
        assert doc["source_url"] == ""
```

- [ ] **Step 10: Run to confirm failure**

```bash
pytest "tests/test_main_window.py::TestSaveToDB::test_load_content_stores_source_url_in_db" -v 2>&1 | tail -10
```

Expected: FAIL.

- [ ] **Step 11: Update `load_content` and `_on_new_doc` in `main_widget.py`**

In `translation_assistant/ui/main_widget.py`, replace `load_content` signature and `create_document` call (lines 383–406):

```python
    def load_content(self, text: str, *, title: str = "Untitled",
                     series_title: str = "", series_order: int = 0,
                     chapter_title: str = "", source_url: str = "") -> None:
        from translation_assistant.core import parse_file_content
        raw_lines, translated_lines, raw_section = parse_file_content(text)
        self._raw_lines = raw_lines
        self._translated_lines = translated_lines
        self._raw_section = raw_section
        self._array_pointer = 0

        doc_id = self._db.create_document(
            title,
            series_title=series_title,
            series_order=series_order,
            chapter_title=chapter_title,
            source_url=source_url,
        )
        self._db.save_lines(doc_id, self._lines_as_db_rows())
        self._doc_id = doc_id
        if series_title:
            linked = self._db.get_series_profile(series_title)
            if linked and self._db.get_profile_id(linked) is not None:
                self._settings.profile_used = linked
                self._load_glossary_for_profile()
        self._finish_load()
```

In `_on_new_doc` (lines 800–812), add `source_url=dlg.source_url`:

```python
    def _on_new_doc(self) -> None:
        from translation_assistant.ui.dlg_new import NewFileDialog
        with self._topmost_suspended():
            dlg = NewFileDialog(self._db, parent=self)
            if dlg.exec():
                display = dlg.chapter_title or "New Document"
                self.load_content(
                    dlg.raw_output_text,
                    title=display,
                    series_title=dlg.series_title,
                    series_order=dlg.series_order,
                    chapter_title=dlg.chapter_title,
                    source_url=dlg.source_url,
                )
```

- [ ] **Step 12: Run all modified test files**

```bash
pytest tests/test_scraper.py tests/test_dialogs.py tests/test_main_window.py tests/test_db.py -v 2>&1 | tail -30
```

Expected: all PASS.

- [ ] **Step 13: Commit**

```bash
git add translation_assistant/scraper.py translation_assistant/ui/dlg_new.py translation_assistant/ui/main_widget.py translation_assistant/ui/dlg_fetch_series.py tests/test_scraper.py tests/test_dialogs.py tests/test_main_window.py
git commit -m "feat(ui): store source_url on all syosetu fetch paths"
```

---

## Task 5: Re-fetch UI in `dlg_open.py`

**Spec reference:** Feature 3 — Re-fetch UI

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`
- Test: `tests/test_dlg_open.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_dlg_open.py` inside `class TestOpenDocumentDialog`:

```python
    def test_refetch_btn_exists(self, qapp, mem_db):
        dlg = OpenDocumentDialog(mem_db)
        assert hasattr(dlg, "_refetch_btn")

    def test_refetch_btn_disabled_with_no_selection(self, qapp, mem_db):
        mem_db.create_document("Doc", source_url="https://ncode.syosetu.com/n1234ab/1/")
        dlg = OpenDocumentDialog(mem_db)
        assert not dlg._refetch_btn.isEnabled()

    def test_refetch_btn_disabled_when_doc_has_no_url(self, qapp, mem_db):
        mem_db.create_document("Doc")  # no source_url
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        assert not dlg._refetch_btn.isEnabled()

    def test_refetch_btn_enabled_when_doc_has_url_and_selected(self, qapp, mem_db):
        mem_db.create_document("Doc", source_url="https://ncode.syosetu.com/n1234ab/1/")
        dlg = OpenDocumentDialog(mem_db)
        leaf = _first_leaf(dlg)
        dlg._tree.setCurrentItem(leaf)
        assert dlg._refetch_btn.isEnabled()

    def test_on_refetch_done_replaces_raw_content_in_db(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        doc_id = mem_db.create_document(
            "Ch1", source_url="https://ncode.syosetu.com/n1234ab/1/"
        )
        mem_db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Old line", "translated_text": "Trans"},
        ])

        dlg = OpenDocumentDialog(mem_db)
        with patch.object(QMessageBox, "information"):
            dlg._on_refetch_done(doc_id, "New Title", "New body text.")

        lines = mem_db.get_lines(doc_id)
        # First line should be the new title
        assert lines[0]["raw_text"] == "New Title"

    def test_on_refetch_done_preserves_translations(self, qapp, mem_db):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        doc_id = mem_db.create_document(
            "Ch1", source_url="https://ncode.syosetu.com/n1234ab/1/"
        )
        mem_db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "Old Title", "translated_text": "MyTrans"},
        ])

        dlg = OpenDocumentDialog(mem_db)
        with patch.object(QMessageBox, "information"):
            dlg._on_refetch_done(doc_id, "Old Title", "Same body.")

        lines = mem_db.get_lines(doc_id)
        assert lines[0]["translated_text"] == "MyTrans"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_dlg_open.py::TestOpenDocumentDialog::test_refetch_btn_exists tests/test_dlg_open.py::TestOpenDocumentDialog::test_on_refetch_done_replaces_raw_content_in_db -v 2>&1 | tail -15
```

Expected: FAIL — attribute missing.

- [ ] **Step 3: Add `_source_urls` dict and Re-fetch button to `dlg_open.py`**

In `translation_assistant/ui/dlg_open.py`, in `__init__` before `_setup_ui`, add the instance variable initialization. Replace the `__init__` method:

```python
    def __init__(self, db: Database, parent=None, *, current_doc_id: int | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._selected_doc_id: int | None = None
        self._doc_ids: dict[int, int] = {}
        self._source_urls: dict[int, str] = {}
        self._refetch_worker = None
        self._setup_ui()
        self._load_documents()
        if current_doc_id is not None:
            self._select_doc(current_doc_id)
```

- [ ] **Step 4: Add Re-fetch button to `_setup_ui` in `dlg_open.py`**

In `_setup_ui`, replace the button row block (lines 63–80):

```python
        btn_row = QHBoxLayout()
        self._open_btn = QPushButton("Open")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._on_open)
        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        self._refetch_btn = QPushButton("Re-fetch")
        self._refetch_btn.setEnabled(False)
        self._refetch_btn.clicked.connect(self._on_refetch)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._edit_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addWidget(self._refetch_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
```

- [ ] **Step 5: Update `_load_documents` to populate `_source_urls`**

In `translation_assistant/ui/dlg_open.py`, replace `_load_documents` (lines 82–109):

```python
    def _load_documents(self) -> None:
        self._tree.clear()
        self._doc_ids.clear()
        self._source_urls.clear()

        docs = self._db.list_documents()
        if not docs:
            return

        groups: dict[str, QTreeWidgetItem] = {}

        for doc in sorted(docs, key=lambda d: (d["series_title"], d["series_order"])):
            series = doc["series_title"] or _NO_SERIES
            if series not in groups:
                group_item = QTreeWidgetItem(self._tree, [series, "", ""])
                group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                font = group_item.font(0)
                font.setBold(True)
                group_item.setFont(0, font)
                groups[series] = group_item

            display = doc["chapter_title"] if doc["chapter_title"] else doc["title"]
            progress = f"{doc['progress']}%"
            last_edited = _fmt_date(doc.get("updated_at", ""))
            leaf = QTreeWidgetItem(groups[series], [display, progress, last_edited])
            leaf.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._doc_ids[id(leaf)] = doc["id"]
            self._source_urls[id(leaf)] = doc.get("source_url", "")

        self._tree.expandAll()
```

- [ ] **Step 6: Update `_on_selection_changed` to control Re-fetch button**

Replace `_on_selection_changed` (lines 128–132):

```python
    def _on_selection_changed(self) -> None:
        leaf = self._current_leaf()
        is_leaf = leaf is not None
        self._open_btn.setEnabled(is_leaf)
        self._edit_btn.setEnabled(is_leaf)
        self._delete_btn.setEnabled(is_leaf)
        has_url = is_leaf and bool(self._source_urls.get(id(leaf), ""))
        self._refetch_btn.setEnabled(has_url)
```

- [ ] **Step 7: Add `_on_refetch`, `_on_refetch_done`, `_on_refetch_error` methods, and update `closeEvent`**

Add after `_on_edit` (after line 176) in `translation_assistant/ui/dlg_open.py`:

```python
    def _on_refetch(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from translation_assistant.scraper import FetchWorker

        leaf = self._current_leaf()
        if leaf is None:
            return
        doc_id = self._doc_ids[id(leaf)]
        url = self._source_urls.get(id(leaf), "")
        if not url:
            return
        answer = QMessageBox.question(
            self,
            "Re-fetch",
            f"Re-fetch content from:\n{url}\n\nExisting translations will be preserved by line position.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._refetch_btn.setEnabled(False)
        self._refetch_worker = FetchWorker(url, parent=self)
        self._refetch_worker.finished.connect(
            lambda title, content: self._on_refetch_done(doc_id, title, content)
        )
        self._refetch_worker.error.connect(self._on_refetch_error)
        self._refetch_worker.start()

    def _on_refetch_done(self, doc_id: int, title: str, content: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        from translation_assistant.core import build_new_file, parse_file_content

        formatted = build_new_file(f"{title}\n\n{content}" if title else content)
        raw_lines, _, _ = parse_file_content(formatted)
        self._db.replace_raw_content(doc_id, raw_lines)
        self._refetch_worker = None
        self._load_documents()
        QMessageBox.information(self, "Re-fetch", "Content re-fetched successfully.")

    def _on_refetch_error(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        self._refetch_worker = None
        self._refetch_btn.setEnabled(True)
        QMessageBox.warning(self, "Re-fetch Failed", f"Error: {msg}")

    def closeEvent(self, event) -> None:
        if self._refetch_worker is not None:
            self._refetch_worker.wait(3000)
        super().closeEvent(event)
```

- [ ] **Step 8: Run all dlg_open tests**

```bash
pytest tests/test_dlg_open.py -v 2>&1 | tail -30
```

Expected: all PASS.

- [ ] **Step 9: Run the full test suite**

```bash
pytest -q 2>&1 | tail -20
```

Expected: all existing + new tests PASS, no regressions.

- [ ] **Step 10: Commit**

```bash
git add translation_assistant/ui/dlg_open.py tests/test_dlg_open.py
git commit -m "feat(ui): add Re-fetch button to Open Document dialog"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| Ruby text as `base(reading)` | Task 1 |
| Title as first translatable line — single fetch | Task 3 (`dlg_new._on_fetch_done` text box already prepends; confirmed) |
| Title as first translatable line — batch fetch | Task 3 (`dlg_fetch_series._on_chapter_done`) |
| Auto-fill Chapter Title field on single fetch | Task 3 (`dlg_new._on_fetch_done`) |
| `source_url` DB column + migration | Task 2 |
| `replace_raw_content` DB method | Task 2 |
| `source_url` stored on single fetch | Task 4 (`dlg_new.source_url` → `load_content`) |
| `source_url` stored on batch fetch | Tasks 3+4 (`dlg_fetch_series` + signal) |
| Re-fetch button in Open dialog | Task 5 |
| Re-fetch preserves translations by line index | Task 5 (uses `replace_raw_content`) |
| Re-fetch uses same title+ruby content format | Task 5 (`_on_refetch_done` calls `build_new_file(f"{title}\n\n{content}")`) |

**No placeholders found.**

**Type consistency:**
- `replace_raw_content(doc_id: int, new_raw_lines: list[str])` — defined Task 2, called Task 5. ✓
- `SeriesFetchWorker.chapter_done = Signal(int, str, str, str)` — defined Task 4, connected in Task 3 (method signature updated in Task 3). ✓
- `dlg_new.source_url` property — defined Task 4, referenced in `main_widget._on_new_doc` Task 4. ✓
- `_source_urls: dict[int, str]` — populated Task 5 Step 5, read Task 5 Step 6. ✓
- `_on_refetch_done(doc_id, title, content)` — defined Task 5 Step 7, connected via lambda Task 5 Step 7. ✓
