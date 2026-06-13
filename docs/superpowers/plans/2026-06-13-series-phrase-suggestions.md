# Series Phrase Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Tools → Series Phrase Suggestions…` dialog that uses MeCab to surface frequently occurring Japanese nouns from a series' raw text, filtered against the active profile's glossary, so the user can add them with translations directly to the profile.

**Architecture:** Pure function `extract_frequent_nouns` in `core.py` handles all MeCab tokenization (no Qt, `_tagger` injection seam for tests). `SeriesPhrasesDialog` owns the UI: series/profile pickers, results table, inline translation input. `main_window.py` gets a new Tools menu that opens the dialog pre-seeded with the current document's series.

**Tech Stack:** PySide6, `mecab-python3`, existing `Database`/`AppSettings` injection seams.

---

### Task 1: Add `extract_frequent_nouns` to `core.py`

**Files:**
- Modify: `translation_assistant/core.py` (append function at end)
- Modify: `requirements.txt` (add `mecab-python3`)
- Modify: `tests/test_core.py` (append tests at end)

- [ ] **Step 1: Add `mecab-python3` to `requirements.txt`**

Open `requirements.txt` and add:
```
mecab-python3>=1.0
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_core.py`:

```python
# ---------------------------------------------------------------------------
# extract_frequent_nouns
# ---------------------------------------------------------------------------

from translation_assistant.core import extract_frequent_nouns


class _FakeTagger:
    """Replays pre-baked MeCab output strings, round-robining through the list."""
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self._idx = 0

    def parse(self, text: str) -> str:
        out = self._outputs[self._idx % len(self._outputs)]
        self._idx += 1
        return out


# Minimal MeCab output fragments (surface TAB POS-csv NEWLINE EOS NEWLINE)
_OUT_TARO    = "太郎\t名詞,固有名詞,人名,名,*,*,太郎,タロウ,タロウ\nEOS\n"
_OUT_HANAKO  = "花子\t名詞,固有名詞,人名,名,*,*,花子,ハナコ,ハナコ\nEOS\n"
_OUT_BOTH    = (
    "太郎\t名詞,固有名詞,人名,名,*,*,太郎,タロウ,タロウ\n"
    "花子\t名詞,固有名詞,人名,名,*,*,花子,ハナコ,ハナコ\n"
    "EOS\n"
)
_OUT_NUMBER  = "100\t名詞,数,*,*,*,*,*\nEOS\n"
_OUT_SINGLE  = "私\t名詞,代名詞,一般,*,*,*,私,ワタシ,ワタシ\nEOS\n"
_OUT_VERB    = "走る\t動詞,自立,*,*,五段・ラ行,基本形,走る,ハシル,ハシル\nEOS\n"


def test_extract_returns_noun_with_count():
    tagger = _FakeTagger([_OUT_TARO, _OUT_TARO])
    result = extract_frequent_nouns(["太郎", "太郎"], set(), min_freq=2, _tagger=tagger)
    assert result == [("太郎", 2)]


def test_extract_skips_verb():
    tagger = _FakeTagger([_OUT_VERB, _OUT_VERB])
    result = extract_frequent_nouns(["走る", "走る"], set(), min_freq=1, _tagger=tagger)
    assert result == []


def test_extract_skips_number_noun():
    tagger = _FakeTagger([_OUT_NUMBER, _OUT_NUMBER])
    result = extract_frequent_nouns(["100", "100"], set(), min_freq=1, _tagger=tagger)
    assert result == []


def test_extract_skips_single_char_noun():
    tagger = _FakeTagger([_OUT_SINGLE, _OUT_SINGLE])
    result = extract_frequent_nouns(["私", "私"], set(), min_freq=1, _tagger=tagger)
    assert result == []


def test_extract_filters_glossary_terms():
    tagger = _FakeTagger([_OUT_TARO, _OUT_TARO])
    result = extract_frequent_nouns(["太郎", "太郎"], {"太郎"}, min_freq=1, _tagger=tagger)
    assert result == []


def test_extract_sorted_by_count_descending():
    tagger = _FakeTagger([_OUT_BOTH, _OUT_TARO])
    result = extract_frequent_nouns(["太郎花子", "太郎"], set(), min_freq=1, _tagger=tagger)
    assert result[0] == ("太郎", 2)
    assert ("花子", 1) in result


def test_extract_min_freq_filters_low_count():
    tagger = _FakeTagger([_OUT_BOTH])
    result = extract_frequent_nouns(["太郎花子"], set(), min_freq=2, _tagger=tagger)
    assert result == []


def test_extract_skips_blank_lines():
    tagger = _FakeTagger(["EOS\n"])
    result = extract_frequent_nouns(["", "  "], set(), min_freq=1, _tagger=tagger)
    assert result == []
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
source .venv/bin/activate
pytest tests/test_core.py -k "test_extract" -v
```

Expected: `FAILED` with `ImportError: cannot import name 'extract_frequent_nouns'`

- [ ] **Step 4: Implement `extract_frequent_nouns` in `core.py`**

Append to the end of `translation_assistant/core.py`:

```python
def extract_frequent_nouns(
    raw_lines: list[str],
    already_in_glossary: set[str],
    min_freq: int = 2,
    *,
    _tagger=None,
) -> list[tuple[str, int]]:
    """
    Tokenize raw_lines with MeCab, return (noun, count) pairs sorted by count desc.

    Skips: verbs, numbers (名詞,数), single-char tokens, terms in already_in_glossary.
    _tagger: injection seam — any object with .parse(str) -> str; defaults to MeCab.Tagger().
    Raises ImportError if mecab-python3 is not installed and _tagger is None.
    """
    if _tagger is None:
        import MeCab as _MeCab
        _tagger = _MeCab.Tagger()

    counts: dict[str, int] = {}
    for line in raw_lines:
        if not line.strip():
            continue
        parsed = _tagger.parse(line)
        for token_line in parsed.split("\n"):
            if not token_line or token_line.startswith("EOS"):
                continue
            parts = token_line.split("\t")
            if len(parts) < 2:
                continue
            surface = parts[0]
            features = parts[1].split(",")
            if not features or features[0] != "名詞":
                continue
            if len(features) > 1 and features[1] == "数":
                continue
            if len(surface) < 2:
                continue
            if surface in already_in_glossary:
                continue
            counts[surface] = counts.get(surface, 0) + 1

    return sorted(
        [(term, cnt) for term, cnt in counts.items() if cnt >= min_freq],
        key=lambda x: x[1],
        reverse=True,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/test_core.py -k "test_extract" -v
```

Expected: all 8 `test_extract_*` tests PASS

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
pytest tests/test_core.py -q
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add requirements.txt translation_assistant/core.py tests/test_core.py
git commit -m "feat: add extract_frequent_nouns to core with MeCab tokenization"
```

---

### Task 2: Add `get_document_ids_by_series` to `db.py`

**Files:**
- Modify: `translation_assistant/db.py` (add method to `Database` class)
- Modify: `tests/test_db.py` (append test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db.py`:

```python
# ---------------------------------------------------------------------------
# get_document_ids_by_series
# ---------------------------------------------------------------------------

def test_get_document_ids_by_series_returns_matching_ids(db):
    db.create_profile("Default", is_default=True)
    id1 = db.create_document("Ch1", series_title="Isekai")
    id2 = db.create_document("Ch2", series_title="Isekai")
    _other = db.create_document("Other", series_title="Romance")
    result = db.get_document_ids_by_series("Isekai")
    assert set(result) == {id1, id2}


def test_get_document_ids_by_series_empty_when_no_match(db):
    db.create_profile("Default", is_default=True)
    db.create_document("Ch1", series_title="Isekai")
    result = db.get_document_ids_by_series("Nonexistent")
    assert result == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_db.py -k "test_get_document_ids_by_series" -v
```

Expected: `FAILED` with `AttributeError: 'Database' object has no attribute 'get_document_ids_by_series'`

- [ ] **Step 3: Implement the method in `db.py`**

In `translation_assistant/db.py`, inside the `Database` class, append after `get_series_chapters`:

```python
def get_document_ids_by_series(self, series_title: str) -> list[int]:
    rows = self._conn.execute(
        "SELECT id FROM documents WHERE series_title = ? ORDER BY series_order",
        (series_title,),
    ).fetchall()
    return [r[0] for r in rows]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_db.py -k "test_get_document_ids_by_series" -v
```

Expected: both PASS

- [ ] **Step 5: Run full DB test suite**

```bash
pytest tests/test_db.py -q
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat: add get_document_ids_by_series to Database"
```

---

### Task 3: Create `SeriesPhrasesDialog`

**Files:**
- Create: `translation_assistant/ui/dlg_series_phrases.py`
- Create: `tests/test_dlg_series_phrases.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dlg_series_phrases.py`:

```python
"""Tests for SeriesPhrasesDialog."""
import sqlite3
import pytest

from translation_assistant.db import Database
from translation_assistant.ui.dlg_series_phrases import SeriesPhrasesDialog


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_with_series(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.create_profile("Default", is_default=True)
    db.create_profile("Isekai")
    doc_id = db.create_document("Ch1", series_title="My Series")
    db.save_lines(doc_id, [
        {"line_number": 0, "prefix": "%", "raw_text": "太郎", "translated_text": ""},
        {"line_number": 1, "prefix": "%", "raw_text": "花子", "translated_text": ""},
    ])
    db.set_series_profile("My Series", "Isekai")
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_series_combo_populated_and_preselected(qapp, tmp_settings, db_with_series):
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    series = [dlg._series_combo.itemText(i) for i in range(dlg._series_combo.count())]
    assert "My Series" in series
    assert dlg._series_combo.currentText() == "My Series"


def test_profile_defaults_to_series_profile(qapp, tmp_settings, db_with_series):
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    assert dlg._profile_combo.currentText() == "Isekai"


def test_no_series_disables_analyze_button(qapp, tmp_settings):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    dlg = SeriesPhrasesDialog(db, tmp_settings)
    assert not dlg._analyze_btn.isEnabled()
    assert dlg._status_label.text() == "No series found"


def test_analyze_populates_table(qapp, tmp_settings, db_with_series, monkeypatch):
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5), ("花子", 3)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    dlg._on_analyze()
    assert dlg._table.rowCount() == 2
    assert dlg._table.item(0, 0).text() == "太郎"
    assert dlg._table.item(0, 1).text() == "5"


def test_analyze_no_lines_shows_status(qapp, tmp_settings):
    conn = sqlite3.connect(":memory:")
    db = Database(":memory:", _conn=conn)
    db.create_profile("Default", is_default=True)
    db.create_document("Ch1", series_title="Empty Series")
    dlg = SeriesPhrasesDialog(db, tmp_settings, current_series="Empty Series")
    dlg._on_analyze()
    assert dlg._table.rowCount() == 0
    assert "No lines found" in dlg._status_label.text()


def test_row_selection_enables_translation_field(qapp, tmp_settings, db_with_series, monkeypatch):
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    dlg._on_analyze()
    assert not dlg._translation_edit.isEnabled()
    dlg._table.selectRow(0)
    dlg._on_selection_changed()
    assert dlg._translation_edit.isEnabled()
    assert not dlg._add_btn.isEnabled()  # no translation text yet


def test_add_btn_enabled_when_translation_non_empty(qapp, tmp_settings, db_with_series, monkeypatch):
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    dlg._on_analyze()
    dlg._table.selectRow(0)
    dlg._on_selection_changed()
    dlg._translation_edit.setText("Taro")
    dlg._on_translation_changed("Taro")
    assert dlg._add_btn.isEnabled()


def test_add_saves_phrase_and_removes_row(qapp, tmp_settings, db_with_series, monkeypatch):
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    dlg._on_analyze()
    dlg._table.selectRow(0)
    dlg._on_selection_changed()
    dlg._translation_edit.setText("Taro")
    dlg._on_add()
    assert dlg._table.rowCount() == 0
    assert ("太郎", "Taro") in db_with_series.get_glossary("Isekai")


def test_profile_change_refilters_results(qapp, tmp_settings, db_with_series, monkeypatch):
    db_with_series.add_phrase("Isekai", "太郎", "Taro")
    monkeypatch.setattr(
        "translation_assistant.ui.dlg_series_phrases.extract_frequent_nouns",
        lambda lines, glossary, min_freq, **kw: [("太郎", 5), ("花子", 3)],
    )
    dlg = SeriesPhrasesDialog(db_with_series, tmp_settings, current_series="My Series")
    # Analyze with Default profile (empty glossary) — both terms visible
    dlg._profile_combo.setCurrentText("Default")
    dlg._on_profile_changed("Default")
    dlg._on_analyze()
    assert dlg._table.rowCount() == 2
    # Switch to Isekai (has 太郎) — 太郎 filtered out
    dlg._profile_combo.setCurrentText("Isekai")
    dlg._on_profile_changed("Isekai")
    terms = [dlg._table.item(r, 0).text() for r in range(dlg._table.rowCount())]
    assert "太郎" not in terms
    assert "花子" in terms
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_dlg_series_phrases.py -v
```

Expected: `FAILED` / `ModuleNotFoundError` for `dlg_series_phrases`

- [ ] **Step 3: Implement `SeriesPhrasesDialog`**

Create `translation_assistant/ui/dlg_series_phrases.py`:

```python
"""Series Phrase Suggestions dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from translation_assistant.core import extract_frequent_nouns
from translation_assistant.db import Database
from translation_assistant.settings import AppSettings


class SeriesPhrasesDialog(QDialog):
    def __init__(
        self,
        db: Database,
        settings: AppSettings,
        current_series: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._raw_results: list[tuple[str, int]] = []
        self._current_glossary: set[str] = set()
        self.setWindowTitle("Series Phrase Suggestions")
        self.setMinimumSize(500, 480)
        self._setup_ui()
        self._populate_series(current_series)
        self._populate_profiles()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._series_combo = QComboBox()
        self._series_combo.currentTextChanged.connect(self._on_series_changed)
        form.addRow("Series:", self._series_combo)

        self._profile_combo = QComboBox()
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)
        form.addRow("Add to profile:", self._profile_combo)

        self._min_freq_spin = QSpinBox()
        self._min_freq_spin.setRange(1, 999)
        self._min_freq_spin.setValue(2)
        form.addRow("Min frequency:", self._min_freq_spin)

        layout.addLayout(form)

        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_analyze)
        layout.addWidget(self._analyze_btn)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Term", "Count"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

        add_row = QHBoxLayout()
        self._translation_edit = QLineEdit()
        self._translation_edit.setPlaceholderText("Enter translation…")
        self._translation_edit.setEnabled(False)
        self._translation_edit.textChanged.connect(self._on_translation_changed)
        add_row.addWidget(self._translation_edit, 1)
        self._add_btn = QPushButton("Add to Profile")
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._add_btn)
        layout.addLayout(add_row)

        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        layout.addWidget(close_btns)

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _populate_series(self, current_series: str) -> None:
        series = self._db.get_series_list()
        self._series_combo.clear()
        if not series:
            self._analyze_btn.setEnabled(False)
            self._status_label.setText("No series found")
            return
        for s in series:
            self._series_combo.addItem(s)
        idx = self._series_combo.findText(current_series)
        self._series_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _populate_profiles(self) -> None:
        profiles = self._db.list_profiles()
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        for p in profiles:
            self._profile_combo.addItem(p)
        self._profile_combo.blockSignals(False)
        series = self._series_combo.currentText()
        default = self._db.get_series_profile(series) or self._settings.profile_used
        idx = self._profile_combo.findText(default)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        self._reload_glossary()

    def _reload_glossary(self) -> None:
        profile = self._profile_combo.currentText()
        self._current_glossary = {p for p, _ in self._db.get_glossary(profile)}

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_series_changed(self, _: str) -> None:
        series = self._series_combo.currentText()
        default = self._db.get_series_profile(series) or self._settings.profile_used
        idx = self._profile_combo.findText(default)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)

    def _on_profile_changed(self, _: str) -> None:
        self._reload_glossary()
        self._refresh_table()

    def _on_analyze(self) -> None:
        series = self._series_combo.currentText()
        if not series:
            return
        doc_ids = self._db.get_document_ids_by_series(series)
        raw_lines: list[str] = []
        for doc_id in doc_ids:
            raw_lines.extend(
                ln["raw_text"]
                for ln in self._db.get_lines(doc_id)
                if ln["raw_text"].strip()
            )
        if not raw_lines:
            self._status_label.setText("No lines found for this series")
            self._table.setRowCount(0)
            return
        try:
            results = extract_frequent_nouns(
                raw_lines,
                self._current_glossary,
                self._min_freq_spin.value(),
            )
        except (ImportError, RuntimeError) as exc:
            QMessageBox.warning(
                self,
                "MeCab Not Available",
                "MeCab is required for phrase analysis.\n"
                "Install it with: pip install mecab-python3\n\n"
                f"Error: {exc}",
            )
            self._table.setRowCount(0)
            return
        self._raw_results = results
        self._refresh_table()

    def _refresh_table(self) -> None:
        visible = [(t, c) for t, c in self._raw_results if t not in self._current_glossary]
        self._table.setRowCount(0)
        for term, count in visible:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(term))
            self._table.setItem(row, 1, QTableWidgetItem(str(count)))
        if visible:
            self._status_label.setText(f"{len(visible)} candidates found")
        elif self._raw_results:
            n = len(self._raw_results)
            self._status_label.setText(
                f"No new candidates ({n} terms already in glossary)"
            )
        self._translation_edit.setEnabled(False)
        self._translation_edit.clear()
        self._add_btn.setEnabled(False)

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._table.selectedItems())
        self._translation_edit.setEnabled(has_sel)
        if has_sel:
            self._translation_edit.setFocus()
        self._update_add_btn()

    def _on_translation_changed(self, _: str) -> None:
        self._update_add_btn()

    def _update_add_btn(self) -> None:
        has_sel = bool(self._table.selectedItems())
        has_text = bool(self._translation_edit.text().strip())
        self._add_btn.setEnabled(has_sel and has_text)

    def _on_add(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        term = self._table.item(row, 0).text()
        translation = self._translation_edit.text().strip()
        if not translation:
            return
        profile = self._profile_combo.currentText()
        self._db.add_phrase(profile, term, translation)
        self._current_glossary.add(term)
        self._table.removeRow(row)
        self._translation_edit.clear()
        self._translation_edit.setEnabled(False)
        self._add_btn.setEnabled(False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_dlg_series_phrases.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest -q
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_series_phrases.py tests/test_dlg_series_phrases.py
git commit -m "feat: add SeriesPhrasesDialog with MeCab noun extraction"
```

---

### Task 4: Wire `Tools → Series Phrase Suggestions…` in `main_window.py`

**Files:**
- Modify: `translation_assistant/ui/main_window.py`

- [ ] **Step 1: Add Tools menu to `_setup_menubar`**

In `translation_assistant/ui/main_window.py`, find this line in `_setup_menubar`:

```python
        # Special punctuations
        punct_menu = mb.addMenu("Special Punctuations")
```

Insert the following block immediately before it:

```python
        # Tools
        tools_menu = mb.addMenu("Tools")
        self._action_series_phrases = tools_menu.addAction(
            "Series Phrase Suggestions… (Ctrl+Shift+P)"
        )
        self._action_series_phrases.triggered.connect(self._on_series_phrases)
        self._action_series_phrases.setShortcut("Ctrl+Shift+P")

```

- [ ] **Step 2: Add the handler method**

In `translation_assistant/ui/main_window.py`, find the `_on_manage_series` method:

```python
    def _on_manage_series(self) -> None:
        from translation_assistant.ui.dlg_series import SeriesManagerDialog
        with self._topmost_suspended():
            dlg = SeriesManagerDialog(self._db, parent=self)
            dlg.exec()
```

Append the following method directly after it:

```python
    def _on_series_phrases(self) -> None:
        from translation_assistant.ui.dlg_series_phrases import SeriesPhrasesDialog
        series = ""
        if self._doc_id is not None:
            try:
                doc = self._db.get_document(self._doc_id)
                series = doc.get("series_title", "")
            except Exception:
                pass
        with self._topmost_suspended():
            dlg = SeriesPhrasesDialog(
                self._db, self._settings, current_series=series, parent=self
            )
            dlg.exec()
```

- [ ] **Step 3: Run the full test suite**

```bash
pytest -q
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add translation_assistant/ui/main_window.py
git commit -m "feat: add Tools menu with Series Phrase Suggestions action"
```
