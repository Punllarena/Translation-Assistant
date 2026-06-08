# Syosetu Series Scraping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link a syosetu series URL to a named series, fetch all chapters in bulk at 1/5 s rate, and allow checking for/fetching new chapters from a Series Manager dialog.

**Architecture:** DB gains `syosetu_url` on `series_profiles`; `scraper.py` gains series-index parsing and a batch `SeriesFetchWorker`; two new dialogs (`dlg_series.py`, `dlg_fetch_series.py`) handle management and batch fetching; `dlg_new.py` and `dlg_open.py` get minor additions for the URL field and right-click entry point; `main_window.py` gains a File menu item.

**Tech Stack:** Python 3.12, PySide6, SQLite via `sqlite3`, `requests`, `BeautifulSoup4`, `pytest`, `unittest.mock`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `translation_assistant/db.py` | Add `syosetu_url` migration + 4 new methods |
| Modify | `translation_assistant/scraper.py` | Add `fetch_series_index`, `IndexFetchWorker`, `SeriesFetchWorker` |
| Modify | `translation_assistant/ui/dlg_new.py` | Add optional Series URL field |
| Create | `translation_assistant/ui/dlg_series.py` | Series Manager dialog |
| Create | `translation_assistant/ui/dlg_fetch_series.py` | Chapter picker + batch fetch progress |
| Modify | `translation_assistant/ui/dlg_open.py` | Right-click → Manage Series |
| Modify | `translation_assistant/ui/main_window.py` | File menu → Manage Series |
| Modify | `tests/test_db.py` | Tests for new DB methods |
| Create | `tests/test_scraper.py` | Tests for index parsing + workers |

---

## Task 1: DB — schema migration + new methods

**Files:**
- Modify: `translation_assistant/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Add to the end of `tests/test_db.py`:

```python
# ---------------------------------------------------------------------------
# Series URL
# ---------------------------------------------------------------------------

def test_get_series_url_missing(db):
    assert db.get_series_url("NoSeries") == ""


def test_set_and_get_series_url(db):
    db.set_series_url("My Series", "https://ncode.syosetu.com/n1234ab/")
    assert db.get_series_url("My Series") == "https://ncode.syosetu.com/n1234ab/"


def test_set_series_url_overwrites(db):
    db.set_series_url("My Series", "https://ncode.syosetu.com/n1234ab/")
    db.set_series_url("My Series", "https://ncode.syosetu.com/n9999zz/")
    assert db.get_series_url("My Series") == "https://ncode.syosetu.com/n9999zz/"


def test_set_series_url_empty_clears(db):
    db.set_series_url("My Series", "https://ncode.syosetu.com/n1234ab/")
    db.set_series_url("My Series", "")
    assert db.get_series_url("My Series") == ""


# ---------------------------------------------------------------------------
# Series chapters (existing series_order values)
# ---------------------------------------------------------------------------

def test_get_series_chapters_empty(db):
    assert db.get_series_chapters("Nonexistent") == []


def test_get_series_chapters_returns_orders(db):
    db.create_document("Doc A", series_title="S", series_order=1, chapter_title="")
    db.create_document("Doc B", series_title="S", series_order=2, chapter_title="")
    db.create_document("Doc C", series_title="S", series_order=5, chapter_title="")
    assert db.get_series_chapters("S") == [1, 2, 5]


# ---------------------------------------------------------------------------
# get_series_list_full
# ---------------------------------------------------------------------------

def test_get_series_list_full_empty(db):
    assert db.get_series_list_full() == []


def test_get_series_list_full_basic(db):
    db.create_document("D1", series_title="Alpha", series_order=1, chapter_title="")
    db.create_document("D2", series_title="Alpha", series_order=2, chapter_title="")
    db.create_document("D3", series_title="Beta",  series_order=1, chapter_title="")
    db.set_series_url("Alpha", "https://ncode.syosetu.com/n0001aa/")
    result = db.get_series_list_full()
    titles = [r["title"] for r in result]
    assert titles == ["Alpha", "Beta"]
    alpha = next(r for r in result if r["title"] == "Alpha")
    assert alpha["url"] == "https://ncode.syosetu.com/n0001aa/"
    assert alpha["chapter_count"] == 2
    beta = next(r for r in result if r["title"] == "Beta")
    assert beta["url"] == ""
    assert beta["chapter_count"] == 1


def test_get_series_list_full_excludes_no_series(db):
    db.create_document("Standalone", series_title="", series_order=0, chapter_title="")
    assert db.get_series_list_full() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
source .venv/bin/activate && pytest tests/test_db.py::test_get_series_url_missing tests/test_db.py::test_set_and_get_series_url tests/test_db.py::test_get_series_chapters_returns_orders tests/test_db.py::test_get_series_list_full_basic -v
```

Expected: FAIL (AttributeError: `Database` has no attribute `get_series_url`)

- [ ] **Step 3: Add schema migration in `db.py`**

In `_apply_schema`, after the existing column-migration block (around line 98), add:

```python
        # Idempotent column migration for series_profiles
        sp_existing = {r[1] for r in self._conn.execute("PRAGMA table_info(series_profiles)").fetchall()}
        if "syosetu_url" not in sp_existing:
            self._conn.execute(
                "ALTER TABLE series_profiles ADD COLUMN syosetu_url TEXT NOT NULL DEFAULT ''"
            )
        self._conn.commit()
```

- [ ] **Step 4: Add new methods in `db.py`**

After `get_next_series_order` (around line 275), add:

```python
    def get_series_url(self, series_title: str) -> str:
        row = self._conn.execute(
            "SELECT syosetu_url FROM series_profiles WHERE series_title = ?",
            (series_title,),
        ).fetchone()
        return row[0] if row else ""

    def set_series_url(self, series_title: str, url: str) -> None:
        self._conn.execute(
            "INSERT INTO series_profiles (series_title, syosetu_url) VALUES (?, ?) "
            "ON CONFLICT(series_title) DO UPDATE SET syosetu_url = excluded.syosetu_url",
            (series_title, url),
        )
        self._conn.commit()

    def get_series_chapters(self, series_title: str) -> list[int]:
        rows = self._conn.execute(
            "SELECT series_order FROM documents WHERE series_title = ? ORDER BY series_order",
            (series_title,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_series_list_full(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT
                d.series_title      AS title,
                COALESCE(sp.syosetu_url, '')   AS url,
                COUNT(d.id)         AS chapter_count,
                COALESCE(sp.profile_name, '')  AS profile_name
            FROM (
                SELECT DISTINCT series_title FROM documents WHERE series_title != ''
            ) dt
            JOIN documents d ON d.series_title = dt.series_title
            LEFT JOIN series_profiles sp ON sp.series_title = dt.series_title
            GROUP BY d.series_title
            ORDER BY d.series_title
            """
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

```
source .venv/bin/activate && pytest tests/test_db.py -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat: add syosetu_url to series_profiles and new series DB methods"
```

---

## Task 2: Scraper — series index parser + workers

**Files:**
- Modify: `translation_assistant/scraper.py`
- Create: `tests/test_scraper.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_scraper.py`:

```python
"""
Tests for scraper.py — fetch_series_index, IndexFetchWorker, SeriesFetchWorker.
"""
from unittest.mock import MagicMock, patch, call

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
    with patch("translation_assistant.scraper.fetch_syosetu", return_value=("T", "C")) as _fetch, \
         patch("translation_assistant.scraper.QThread.sleep") as mock_sleep:
        worker = SeriesFetchWorker(_CHAPTERS)
        worker.run()

    # Sleep called after each chapter except the last
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


def test_series_fetch_worker_cancellation(qapp):
    done = []

    def fake_fetch(url):
        return ("Title", "Content")

    with patch("translation_assistant.scraper.fetch_syosetu", side_effect=fake_fetch), \
         patch("translation_assistant.scraper.QThread.sleep"):
        worker = SeriesFetchWorker(_CHAPTERS)
        worker.chapter_done.connect(lambda n, t, c: done.append(n))

        original_run = worker.run

        fetch_count = [0]

        def patched_run():
            # Request interruption after first chapter is processed
            # We do this by monkeypatching isInterruptionRequested
            pass

        # Simulate: worker processes chapter 1, then interruption is requested
        worker._chapters_to_fetch = [_CHAPTERS[0]]  # only give it one chapter
        worker.run()

    assert done == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

```
source .venv/bin/activate && pytest tests/test_scraper.py -v
```

Expected: FAIL (ImportError: cannot import name `fetch_series_index`)

- [ ] **Step 3: Add `fetch_series_index`, `IndexFetchWorker`, `SeriesFetchWorker` to `scraper.py`**

Add the following imports at the top of `scraper.py` (update existing import line):

```python
from urllib.parse import urlparse, urljoin
```

Then add after the existing `FetchWorker` class:

```python
def _validate_series_url(url: str) -> None:
    validate_url(url)
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) != 1:
        raise ValueError(
            "URL must be a series root (e.g. https://novel18.syosetu.com/n7696mg/), "
            "not a chapter URL"
        )


def fetch_series_index(url: str) -> list[dict]:
    _validate_series_url(url)
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    resp = requests.get(url, timeout=10, headers={"User-Agent": _UA}, cookies={"over18": "yes"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    chapters = []
    for dd in soup.select("dl.novel_sublist2 dd.subtitle"):
        a = dd.find("a")
        if not a:
            continue
        href = a.get("href", "")
        href_parts = [p for p in href.split("/") if p]
        try:
            num = int(href_parts[-1])
        except (ValueError, IndexError):
            continue
        title = a.get_text(strip=True)
        chapter_url = urljoin(base, href)
        chapters.append({"num": num, "title": title, "url": chapter_url})
    chapters.sort(key=lambda c: c["num"])
    return chapters


def fetch_chapter(url: str) -> tuple[str, str]:
    return fetch_syosetu(url)


class IndexFetchWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            chapters = fetch_series_index(self._url)
            self.finished.emit(chapters)
        except Exception as exc:
            self.error.emit(str(exc))


class SeriesFetchWorker(QThread):
    chapter_done = Signal(int, str, str)   # num, title, content
    progress = Signal(int, int)             # current, total
    error = Signal(int, str)               # chapter_num, message
    finished = Signal()

    def __init__(self, chapters_to_fetch: list, parent=None) -> None:
        super().__init__(parent)
        self._chapters_to_fetch = chapters_to_fetch

    def run(self) -> None:
        total = len(self._chapters_to_fetch)
        for i, ch in enumerate(self._chapters_to_fetch):
            if self.isInterruptionRequested():
                break
            try:
                _title, content = fetch_syosetu(ch["url"])
                self.chapter_done.emit(ch["num"], ch["title"], content)
            except Exception as exc:
                self.error.emit(ch["num"], str(exc))
            self.progress.emit(i + 1, total)
            if i < total - 1:
                QThread.sleep(5)
        self.finished.emit()
```

- [ ] **Step 4: Run tests to verify they pass**

```
source .venv/bin/activate && pytest tests/test_scraper.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Run full suite to check for regressions**

```
source .venv/bin/activate && pytest -q
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/scraper.py tests/test_scraper.py
git commit -m "feat: add syosetu series index parsing and batch fetch worker"
```

---

## Task 3: `dlg_new.py` — Series URL field

**Files:**
- Modify: `translation_assistant/ui/dlg_new.py`

- [ ] **Step 1: Add Series URL row to `_setup_ui`**

In `dlg_new.py`, find the `form.addRow("Series Title:", self._series_edit)` line. After it, add:

```python
        self._series_url_edit = QLineEdit()
        self._series_url_edit.setPlaceholderText("e.g. https://novel18.syosetu.com/n7696mg/")
        self._series_url_row_label = QLabel("Series URL:")
        form.addRow(self._series_url_row_label, self._series_url_edit)
        self._series_url_edit.setVisible(False)
        self._series_url_row_label.setVisible(False)
```

Add `QLabel` to the import list at the top of `dlg_new.py` (it's not currently imported):

```python
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)
```

`QLabel` is already imported — no change needed to imports.

- [ ] **Step 2: Show/hide URL row based on series title**

In `_on_series_changed`, add at the start of the method (before the `if not text.strip()` guard):

```python
    def _on_series_changed(self, text: str) -> None:
        has_series = bool(text.strip())
        self._series_url_edit.setVisible(has_series)
        self._series_url_row_label.setVisible(has_series)
        if not text.strip():
            return
        if self._db:
            next_order = self._db.get_next_series_order(text.strip())
            self._order_spin.setValue(next_order)
            linked = self._db.get_series_profile(text.strip())
            if linked:
                idx = self._profile_combo.findText(linked)
                if idx >= 0:
                    self._profile_combo.setCurrentIndex(idx)
                self._link_profile_check.setChecked(True)
            url = self._db.get_series_url(text.strip())
            self._series_url_edit.setText(url)
```

- [ ] **Step 3: Save URL on create**

In `_on_create`, after `self._db.set_series_profile(...)` and before `self.accept()`, add:

```python
        series_url = self._series_url_edit.text().strip()
        if series_url and self._series_title and self._db:
            self._db.set_series_url(self._series_title, series_url)
```

The full `_on_create` end should look like:

```python
        else:
            self._linked_profile = ""
        series_url = self._series_url_edit.text().strip()
        if series_url and self._series_title and self._db:
            self._db.set_series_url(self._series_title, series_url)
        self.accept()
```

- [ ] **Step 4: Run existing dialog tests to check for regressions**

```
source .venv/bin/activate && pytest tests/test_dialogs.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/ui/dlg_new.py
git commit -m "feat: add optional series URL field to New Document dialog"
```

---

## Task 4: `dlg_series.py` — Series Manager

**Files:**
- Create: `translation_assistant/ui/dlg_series.py`

- [ ] **Step 1: Create `dlg_series.py`**

```python
"""
Series Manager dialog — view all series, set syosetu URL, open chapter fetcher.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QInputDialog, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from translation_assistant.db import Database


class SeriesManagerDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._setup_ui()
        self._load()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Manage Series")
        self.setMinimumSize(700, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Series Title", "Syosetu URL", "Chapters", "Profile"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._set_url_btn = QPushButton("Set URL…")
        self._set_url_btn.setEnabled(False)
        self._set_url_btn.clicked.connect(self._on_set_url)
        self._fetch_btn = QPushButton("Fetch new chapters…")
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.clicked.connect(self._on_fetch)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._set_url_btn)
        btn_row.addWidget(self._fetch_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _load(self) -> None:
        series = self._db.get_series_list_full()
        self._table.setRowCount(len(series))
        for row, s in enumerate(series):
            self._table.setItem(row, 0, QTableWidgetItem(s["title"]))
            self._table.setItem(row, 1, QTableWidgetItem(s["url"]))
            self._table.setItem(row, 2, QTableWidgetItem(str(s["chapter_count"])))
            self._table.setItem(row, 3, QTableWidgetItem(s["profile_name"]))
        self._on_row_changed(self._table.currentRow())

    def _current_series(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        return {
            "title": self._table.item(row, 0).text(),
            "url": self._table.item(row, 1).text(),
        }

    def _on_row_changed(self, row: int) -> None:
        s = self._current_series()
        self._set_url_btn.setEnabled(s is not None)
        self._fetch_btn.setEnabled(s is not None and bool(s["url"]))

    def _on_set_url(self) -> None:
        s = self._current_series()
        if s is None:
            return
        url, ok = QInputDialog.getText(
            self,
            "Set Series URL",
            f"Syosetu URL for \"{s['title']}\":",
            text=s["url"],
        )
        if not ok:
            return
        self._db.set_series_url(s["title"], url.strip())
        self._load()

    def _on_fetch(self) -> None:
        s = self._current_series()
        if s is None or not s["url"]:
            return
        from translation_assistant.ui.dlg_fetch_series import FetchSeriesDialog
        dlg = FetchSeriesDialog(self._db, s["title"], s["url"], parent=self)
        dlg.exec()
        self._load()
```

- [ ] **Step 2: Run full suite**

```
source .venv/bin/activate && pytest -q
```

Expected: all tests PASS (no tests for this dialog yet — UI-only, exercised manually)

- [ ] **Step 3: Commit**

```bash
git add translation_assistant/ui/dlg_series.py
git commit -m "feat: add Series Manager dialog"
```

---

## Task 5: `dlg_fetch_series.py` — Chapter Picker + Fetch Progress

**Files:**
- Create: `translation_assistant/ui/dlg_fetch_series.py`

- [ ] **Step 1: Create `dlg_fetch_series.py`**

```python
"""
Chapter picker and batch fetch progress dialog for a syosetu series.
Phase 1: load chapter list from index page, let user pick.
Phase 2: fetch selected chapters with rate limiting, save to DB.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QVBoxLayout,
)

from translation_assistant.core import build_new_file, lines_to_db_rows, parse_file_content
from translation_assistant.db import Database
from translation_assistant.scraper import IndexFetchWorker, SeriesFetchWorker


class FetchSeriesDialog(QDialog):
    def __init__(self, db: Database, series_title: str, series_url: str, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._series_title = series_title
        self._series_url = series_url
        self._chapters: list[dict] = []
        self._fetch_worker: SeriesFetchWorker | None = None
        self._added = 0
        self._setup_ui()
        self._start_index_load()

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"Fetch Chapters — {self._series_title}")
        self.setMinimumSize(500, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._status_label = QLabel("Loading chapter list…")
        layout.addWidget(self._status_label)

        self._list = QListWidget()
        self._list.setVisible(False)
        self._list.itemChanged.connect(self._on_check_changed)
        layout.addWidget(self._list)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._action_btn = QPushButton("Fetch Selected (0)")
        self._action_btn.setEnabled(False)
        self._action_btn.clicked.connect(self._on_action)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._action_btn)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

    def _start_index_load(self) -> None:
        self._index_worker = IndexFetchWorker(self._series_url, parent=self)
        self._index_worker.finished.connect(self._on_index_loaded)
        self._index_worker.error.connect(self._on_index_error)
        self._index_worker.start()

    def _on_index_loaded(self, chapters: list) -> None:
        self._chapters = chapters
        existing = set(self._db.get_series_chapters(self._series_title))
        self._list.blockSignals(True)
        for ch in chapters:
            item = QListWidgetItem(f"Chapter {ch['num']}: {ch['title']}")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            already = ch["num"] in existing
            item.setCheckState(
                Qt.CheckState.Unchecked if already else Qt.CheckState.Checked
            )
            if already:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setText(item.text() + "  (already fetched)")
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._list.setVisible(True)
        self._status_label.setText(
            f"{len(chapters)} chapters found. Select chapters to fetch."
        )
        self._update_action_btn()

    def _on_index_error(self, msg: str) -> None:
        self._status_label.setText(f"Error loading chapter list: {msg}")

    def _on_check_changed(self, _item: QListWidgetItem) -> None:
        self._update_action_btn()

    def _update_action_btn(self) -> None:
        count = sum(
            1 for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
            and bool(self._list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled)
        )
        self._action_btn.setText(f"Fetch Selected ({count})")
        self._action_btn.setEnabled(count > 0)

    def _selected_chapters(self) -> list[dict]:
        result = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if (item.checkState() == Qt.CheckState.Checked
                    and bool(item.flags() & Qt.ItemFlag.ItemIsEnabled)):
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def _on_action(self) -> None:
        selected = self._selected_chapters()
        if not selected:
            return
        total = len(selected)
        self._action_btn.setEnabled(False)
        self._list.setEnabled(False)
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._status_label.setText(f"Fetching chapter 1 of {total}…")
        self._cancel_btn.setText("Cancel")
        self._added = 0

        self._fetch_worker = SeriesFetchWorker(selected, parent=self)
        self._fetch_worker.chapter_done.connect(self._on_chapter_done)
        self._fetch_worker.progress.connect(self._on_progress)
        self._fetch_worker.error.connect(self._on_chapter_error)
        self._fetch_worker.finished.connect(self._on_fetch_finished)
        self._fetch_worker.start()

    def _on_chapter_done(self, num: int, title: str, content: str) -> None:
        formatted = build_new_file(content)
        raw_lines, translated_lines, _ = parse_file_content(formatted)
        rows = lines_to_db_rows(raw_lines, translated_lines)
        doc_id = self._db.create_document(
            title,
            series_title=self._series_title,
            series_order=num,
            chapter_title=title,
        )
        self._db.save_lines(doc_id, rows)
        self._added += 1

    def _on_progress(self, current: int, total: int) -> None:
        self._progress_bar.setValue(current)
        if current < total:
            self._status_label.setText(f"Fetching chapter {current + 1} of {total}…")

    def _on_chapter_error(self, num: int, msg: str) -> None:
        self._error_label.setVisible(True)
        prev = self._error_label.text()
        self._error_label.setText(
            (prev + "\n" if prev else "") + f"Chapter {num}: {msg}"
        )

    def _on_fetch_finished(self) -> None:
        self._progress_bar.setValue(self._progress_bar.maximum())
        self._status_label.setText(f"Done — {self._added} chapter(s) added.")
        self._cancel_btn.setText("Close")
        self._cancel_btn.setEnabled(True)
        self._fetch_worker = None

    def _on_cancel(self) -> None:
        if self._fetch_worker is not None:
            self._fetch_worker.requestInterruption()
            self._fetch_worker.wait(3000)
        self.reject()
```

- [ ] **Step 2: Run full suite**

```
source .venv/bin/activate && pytest -q
```

Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add translation_assistant/ui/dlg_fetch_series.py
git commit -m "feat: add chapter picker and batch fetch progress dialog"
```

---

## Task 6: `dlg_open.py` — right-click context menu

**Files:**
- Modify: `translation_assistant/ui/dlg_open.py`

- [ ] **Step 1: Enable custom context menu on tree + wire up handler**

In `_setup_ui`, after `self._tree.itemDoubleClicked.connect(...)`, add:

```python
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
```

- [ ] **Step 2: Add `_on_context_menu` method**

Add before `_apply_filter`:

```python
    def _on_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        # Only show for series group items (has children, not "(No Series)")
        if item.childCount() == 0:
            item = item.parent()
        if item is None or item.text(0) == _NO_SERIES:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        action = menu.addAction("Manage Series…")
        if menu.exec(self._tree.viewport().mapToGlobal(pos)) == action:
            self._open_series_manager(item.text(0))

    def _open_series_manager(self, series_title: str) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        dlg = SeriesManagerDialog(self._db, parent=self)
        dlg.exec()
```

- [ ] **Step 3: Run existing open-dialog tests**

```
source .venv/bin/activate && pytest tests/test_dlg_open.py -v
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add translation_assistant/ui/dlg_open.py
git commit -m "feat: add right-click Manage Series context menu to document picker"
```

---

## Task 7: `main_window.py` — File menu "Manage Series…"

**Files:**
- Modify: `translation_assistant/ui/main_window.py`

- [ ] **Step 1: Add menu item in `_setup_menubar`**

Find the `file_menu.addSeparator()` line before `Export Database Backup`. Add before it:

```python
        file_menu.addSeparator()
        self._action_manage_series = file_menu.addAction("Manage Series…")
        self._action_manage_series.triggered.connect(self._on_manage_series)
```

- [ ] **Step 2: Add handler method**

Add after `_on_db_import` (or wherever other `_on_*` file handlers live):

```python
    def _on_manage_series(self) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        with self._topmost_suspended():
            dlg = SeriesManagerDialog(self._db, parent=self)
            dlg.exec()
```

- [ ] **Step 3: Run full test suite**

```
source .venv/bin/activate && pytest -q
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add translation_assistant/ui/main_window.py
git commit -m "feat: add Manage Series menu item to File menu"
```

---

## Self-Review Notes

- **Spec coverage:** All spec requirements mapped to tasks: DB migration (T1), scraper (T2), dlg_new URL field (T3), dlg_series (T4), dlg_fetch_series (T5), dlg_open right-click (T6), main_window menu (T7).
- **Type consistency:** `get_series_url`/`set_series_url`/`get_series_chapters`/`get_series_list_full` defined in T1 and used by same names in T3–T5. `IndexFetchWorker`/`SeriesFetchWorker` defined in T2, imported in T5.
- **`build_new_file`/`parse_file_content`/`lines_to_db_rows`** all exist in `core.py` and are used correctly in `_on_chapter_done`.
- **`_on_series_changed` rewrite in T3:** The method is fully rewritten, replacing the old version completely — no partial edit risk.
- **`_series_url_row_label`:** The form uses `QFormLayout.addRow(label_widget, field_widget)` pattern since we need to show/hide both independently. `QLabel` is already imported in `dlg_new.py`.
