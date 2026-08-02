# Image Card Collapse & Export Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each inline illustration in the card list a collapse/expand chevron and an "Export" checkbox that omits it from both EPUB export and WordPress publish.

**Architecture:** A new `ImageCard(QWidget)` replaces the bare `QLabel` currently used for illustrations, adding a header row (chevron + "Image N" + checkbox). The export flag persists in a new `document_images.exclude_export` column and is honoured by both export call sites. Collapse is session-only view state, with a global default in `AppSettings`.

**Tech Stack:** Python 3, PySide6, SQLite (via `translation_assistant/db.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-03-image-card-collapse-export-design.md`

## Global Constraints

- Activate the venv before any command: `source .venv/bin/activate`.
- All SQLite access goes through the `Database` class in `db.py`. Never import `sqlite3` elsewhere.
- Schema changes use the idempotent `PRAGMA table_info` + `ALTER TABLE` pattern already in `Database._apply_schema()`.
- Never write to `QSettings` directly — go through `AppSettings` in `settings.py`.
- Do not modify `translation_assistant/ui/main_window.py` — it is legacy and not launched.
- Cover images (`is_cover = 1`) are out of scope: they are already filtered out of the card list and their export path must not change.
- Existing tests construct image dicts without `"id"` or `"exclude_export"` keys. New code must read both with `.get()` so those tests keep passing unmodified.
- Run the full suite (`pytest -q`) before the final commit of each task that touches shared widgets.

---

### Task 1: Database column and setter

**Files:**
- Modify: `translation_assistant/db.py` (`_apply_schema`, add `set_image_exclude_export`)
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `document_images.exclude_export` INTEGER NOT NULL DEFAULT 0, returned in every `get_document_images()` row dict
  - `Database.set_image_exclude_export(image_id: int, exclude: bool) -> None`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`, after `test_get_document_images_scoped_to_document` (around line 346):

```python
def test_image_exclude_export_defaults_to_zero(db):
    doc_id = db.create_document("doc")
    db.add_document_image(doc_id, 0, False, "images/pic.png", b"fakebytes")
    images = db.get_document_images(doc_id)
    assert images[0]["exclude_export"] == 0


def test_set_image_exclude_export_round_trips(db):
    doc_id = db.create_document("doc")
    img_id = db.add_document_image(doc_id, 0, False, "images/pic.png", b"fakebytes")
    db.set_image_exclude_export(img_id, True)
    assert db.get_document_images(doc_id)[0]["exclude_export"] == 1
    db.set_image_exclude_export(img_id, False)
    assert db.get_document_images(doc_id)[0]["exclude_export"] == 0


def test_set_image_exclude_export_scoped_to_one_image(db):
    doc_id = db.create_document("doc")
    a = db.add_document_image(doc_id, 0, False, "a.png", b"a")
    db.add_document_image(doc_id, 1, False, "b.png", b"b")
    db.set_image_exclude_export(a, True)
    images = db.get_document_images(doc_id)
    assert images[0]["exclude_export"] == 1
    assert images[1]["exclude_export"] == 0


def test_exclude_export_column_added_to_preexisting_table(db):
    """The migration must add the column to a document_images table that
    predates it, leaving existing rows exporting (0)."""
    db._conn.execute("DROP TABLE document_images")
    db._conn.execute(
        "CREATE TABLE document_images ("
        " id INTEGER PRIMARY KEY,"
        " document_id INTEGER NOT NULL,"
        " anchor_position INTEGER NOT NULL DEFAULT 0,"
        " is_cover INTEGER NOT NULL DEFAULT 0,"
        " src_path TEXT NOT NULL,"
        " data BLOB NOT NULL)"
    )
    db._conn.execute(
        "INSERT INTO document_images (document_id, anchor_position, is_cover, src_path, data)"
        " VALUES (1, 0, 0, 'old.png', X'00')"
    )
    db._conn.commit()
    db._apply_schema()
    assert db.get_document_images(1)[0]["exclude_export"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_db.py -k exclude_export -q
```

Expected: FAIL — `KeyError: 'exclude_export'` and `AttributeError: 'Database' object has no attribute 'set_image_exclude_export'`.

- [ ] **Step 3: Add the column to the DDL**

In `translation_assistant/db.py`, inside the `document_images` table in `_DDL` (around line 70), add a final column after `data`:

```sql
CREATE TABLE IF NOT EXISTS document_images (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    anchor_position INTEGER NOT NULL DEFAULT 0,
    is_cover        INTEGER NOT NULL DEFAULT 0,
    src_path        TEXT    NOT NULL,
    data            BLOB    NOT NULL,
    exclude_export  INTEGER NOT NULL DEFAULT 0
);
```

- [ ] **Step 4: Add the idempotent migration**

In `_apply_schema()`, after the `series_profiles` migrations block (after the `wp_password_enabled` group, before the method ends), add:

```python
        # Idempotent column migration for document_images
        di_existing = {
            r[1] for r in self._conn.execute("PRAGMA table_info(document_images)").fetchall()
        }
        if "exclude_export" not in di_existing:
            self._conn.execute(
                "ALTER TABLE document_images ADD COLUMN exclude_export INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.commit()
```

- [ ] **Step 5: Return the column and add the setter**

In `get_document_images` (around line 465), add `exclude_export` to the SELECT list:

```python
    def get_document_images(self, document_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, anchor_position, is_cover, src_path, data, exclude_export "
            "FROM document_images "
            "WHERE document_id = ? ORDER BY anchor_position, id",
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]
```

Directly after that method, add:

```python
    def set_image_exclude_export(self, image_id: int, exclude: bool) -> None:
        self._conn.execute(
            "UPDATE document_images SET exclude_export = ? WHERE id = ?",
            (1 if exclude else 0, image_id),
        )
        self._conn.commit()
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_db.py -q
```

Expected: PASS, all of `test_db.py` green.

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/db.py tests/test_db.py
git commit -m "feat(db): add exclude_export column and setter for document_images"
```

---

### Task 2: AppSettings global collapse default

**Files:**
- Modify: `translation_assistant/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: nothing
- Produces: `AppSettings.images_collapsed` property (bool, default `False`), backed by the `ImagesCollapsed` QSettings key

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py` (append at the end of the file):

```python
def test_images_collapsed_defaults_false(tmp_settings):
    assert tmp_settings.images_collapsed is False


def test_images_collapsed_round_trips(tmp_settings):
    tmp_settings.images_collapsed = True
    assert tmp_settings.images_collapsed is True
    tmp_settings.images_collapsed = False
    assert tmp_settings.images_collapsed is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_settings.py -k images_collapsed -q
```

Expected: FAIL — `AttributeError: 'AppSettings' object has no attribute 'images_collapsed'`.

- [ ] **Step 3: Add the property**

In `translation_assistant/settings.py`, following the `tm_visible` pattern (around line 119), add:

```python
    @property
    def images_collapsed(self) -> bool:
        return self._qs.value("ImagesCollapsed", False, type=bool)

    @images_collapsed.setter
    def images_collapsed(self, value: bool) -> None:
        self._qs.setValue("ImagesCollapsed", value)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_settings.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add images_collapsed global default"
```

---

### Task 3: ImageCard widget

**Files:**
- Modify: `translation_assistant/ui/card_list.py` (imports; new `ImageCard` class placed immediately before `class CardListView`)
- Test: `tests/test_card_list.py`

**Interfaces:**
- Consumes: `Database.set_image_exclude_export` exists (Task 1) but is not called here
- Produces:
  - `ImageCard(image: dict, number: int, parent=None)` — `image` is a `get_document_images()` row dict; `number` is the 1-based inline-image index
  - `ImageCard.export_toggled = Signal(int, bool)` emitting `(image_id, exclude)`
  - `ImageCard.set_collapsed(collapsed: bool) -> None`
  - Attributes used by later tasks and tests: `.chevron` (QToolButton), `.export_box` (QCheckBox), `.image_label` (QLabel)

**Note on visibility assertions:** the `view` fixture's widgets are not necessarily shown, so `isVisible()` is unreliable in tests. Use `isVisibleTo(parent)`, which reports the widget's own hidden/shown state independent of its ancestors.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_card_list.py`, immediately before `class TestCardListViewImages` (the `_TINY_PNG` constant defined above it is reused):

```python
class TestImageCard:
    def _card(self, image=None, number=1):
        from translation_assistant.ui.card_list import ImageCard
        image = image or {"id": 7, "anchor_position": 0, "data": _TINY_PNG,
                          "exclude_export": 0}
        return ImageCard(image, number)

    def test_shows_image_number(self):
        card = self._card(number=3)
        labels = [w.text() for w in card.findChildren(QLabel) if w.text()]
        assert "Image 3" in labels

    def test_pixmap_loaded(self):
        card = self._card()
        assert not card.image_label.pixmap().isNull()

    def test_starts_expanded(self):
        card = self._card()
        assert card.image_label.isVisibleTo(card)
        assert not card.chevron.isChecked()

    def test_chevron_collapses_image_but_keeps_header(self):
        card = self._card()
        card.chevron.setChecked(True)
        assert not card.image_label.isVisibleTo(card)
        assert card.export_box.isVisibleTo(card)

    def test_chevron_expands_again(self):
        card = self._card()
        card.chevron.setChecked(True)
        card.chevron.setChecked(False)
        assert card.image_label.isVisibleTo(card)

    def test_set_collapsed_matches_chevron(self):
        card = self._card()
        card.set_collapsed(True)
        assert card.chevron.isChecked()
        assert not card.image_label.isVisibleTo(card)
        card.set_collapsed(False)
        assert not card.chevron.isChecked()
        assert card.image_label.isVisibleTo(card)

    def test_export_checked_by_default(self):
        card = self._card()
        assert card.export_box.isChecked()

    def test_export_unchecked_when_excluded(self):
        card = self._card({"id": 7, "anchor_position": 0, "data": _TINY_PNG,
                           "exclude_export": 1})
        assert not card.export_box.isChecked()

    def test_unchecking_emits_exclude_true(self):
        card = self._card()
        seen = []
        card.export_toggled.connect(lambda img_id, exc: seen.append((img_id, exc)))
        card.export_box.setChecked(False)
        assert seen == [(7, True)]

    def test_rechecking_emits_exclude_false(self):
        card = self._card({"id": 9, "anchor_position": 0, "data": _TINY_PNG,
                           "exclude_export": 1})
        seen = []
        card.export_toggled.connect(lambda img_id, exc: seen.append((img_id, exc)))
        card.export_box.setChecked(True)
        assert seen == [(9, False)]

    def test_image_without_id_does_not_emit(self):
        card = self._card({"anchor_position": 0, "data": _TINY_PNG})
        seen = []
        card.export_toggled.connect(lambda img_id, exc: seen.append((img_id, exc)))
        card.export_box.setChecked(False)
        assert seen == []
```

If `QLabel` is not already imported in `tests/test_card_list.py`, add `from PySide6.QtWidgets import QLabel` to its imports.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_card_list.py::TestImageCard -q
```

Expected: FAIL — `ImportError: cannot import name 'ImageCard'`.

- [ ] **Step 3: Extend the imports**

In `translation_assistant/ui/card_list.py`, extend the `QtWidgets` import (line 12) with `QCheckBox` and `QToolButton`:

```python
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QScrollArea, QToolButton, QVBoxLayout, QWidget,
)
```

- [ ] **Step 4: Write the ImageCard class**

Insert immediately before `class CardListView(QScrollArea):` (around line 282):

```python
class ImageCard(QWidget):
    """Illustration row — chevron collapse, "Image N" label, export checkbox.

    Deliberately not a LineCard: no line index, and no participation in
    navigation, spellcheck or progress counting.
    """

    export_toggled = Signal(int, bool)   # (image_id, exclude)

    def __init__(self, image: dict, number: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CardImage")
        # Older callers (and existing tests) pass image dicts without an id.
        self._image_id = image.get("id")

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.chevron = QToolButton()
        self.chevron.setObjectName("CardImageChevron")
        self.chevron.setAutoRaise(True)
        self.chevron.setCheckable(True)
        self.chevron.setText("▾")
        self.chevron.toggled.connect(self._on_chevron)
        header.addWidget(self.chevron)
        header.addWidget(QLabel(f"Image {number}"))
        header.addStretch(1)
        self.export_box = QCheckBox("Export")
        self.export_box.setChecked(not image.get("exclude_export", 0))
        self.export_box.toggled.connect(self._on_export)
        header.addWidget(self.export_box)
        vbox.addLayout(header)

        self.image_label = QLabel()
        pixmap = QPixmap()
        pixmap.loadFromData(image["data"])
        if not pixmap.isNull():
            pixmap = pixmap.scaledToWidth(400, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(self.image_label)

    def _on_chevron(self, collapsed: bool) -> None:
        self.chevron.setText("▸" if collapsed else "▾")
        self.image_label.setVisible(not collapsed)

    def _on_export(self, checked: bool) -> None:
        if self._image_id is not None:
            self.export_toggled.emit(self._image_id, not checked)

    def set_collapsed(self, collapsed: bool) -> None:
        self.chevron.setChecked(collapsed)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_card_list.py::TestImageCard -q
```

Expected: PASS, 12 tests.

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/card_list.py tests/test_card_list.py
git commit -m "feat(cards): add ImageCard with collapse chevron and export checkbox"
```

---

### Task 4: CardListView builds ImageCards

**Files:**
- Modify: `translation_assistant/ui/card_list.py` (`CardListView` signal, `__init__`, `_build_batch`, delete `_make_image_widget`, add `set_images_collapsed`)
- Test: `tests/test_card_list.py`

**Interfaces:**
- Consumes: `ImageCard(image, number)`, `.export_toggled`, `.set_collapsed` (Task 3)
- Produces:
  - `CardListView.image_export_toggled = Signal(int, bool)` — relays every child `ImageCard.export_toggled`
  - `CardListView.set_images_collapsed(collapsed: bool) -> None` — applies to existing cards and becomes the default for cards built later
  - `CardListView._image_widgets` is now `list[ImageCard]`

- [ ] **Step 1: Write the failing tests**

Add these methods inside the existing `class TestCardListViewImages` in `tests/test_card_list.py`. They use `QLabel`, which Task 3 added to the file's imports — confirm `from PySide6.QtWidgets import QLabel` is present before running them.

```python
    def test_images_are_image_cards(self, view):
        from translation_assistant.ui.card_list import ImageCard
        images = [{"id": 1, "anchor_position": 1, "data": _TINY_PNG}]
        view.load(["%A"], [""], [], images)
        assert isinstance(view._image_widgets[0], ImageCard)

    def test_images_numbered_in_anchor_order(self, view):
        images = [
            {"id": 1, "anchor_position": 0, "data": _TINY_PNG},
            {"id": 2, "anchor_position": 1, "data": _TINY_PNG},
        ]
        view.load(["%A", "%B"], ["", ""], [], images)
        texts = []
        for card in view._image_widgets:
            texts += [w.text() for w in card.findChildren(QLabel) if w.text()]
        assert "Image 1" in texts
        assert "Image 2" in texts

    def test_numbering_restarts_on_reload(self, view):
        images = [{"id": 1, "anchor_position": 0, "data": _TINY_PNG}]
        view.load(["%A"], [""], [], images)
        view.load(["%A"], [""], [], images)
        card = view._image_widgets[0]
        texts = [w.text() for w in card.findChildren(QLabel) if w.text()]
        assert "Image 1" in texts

    def test_export_toggle_relayed(self, view):
        images = [{"id": 42, "anchor_position": 0, "data": _TINY_PNG}]
        view.load(["%A"], [""], [], images)
        seen = []
        view.image_export_toggled.connect(lambda i, e: seen.append((i, e)))
        view._image_widgets[0].export_box.setChecked(False)
        assert seen == [(42, True)]

    def test_set_images_collapsed_applies_to_all(self, view):
        images = [
            {"id": 1, "anchor_position": 0, "data": _TINY_PNG},
            {"id": 2, "anchor_position": 1, "data": _TINY_PNG},
        ]
        view.load(["%A", "%B"], ["", ""], [], images)
        view.set_images_collapsed(True)
        assert all(c.chevron.isChecked() for c in view._image_widgets)
        view.set_images_collapsed(False)
        assert not any(c.chevron.isChecked() for c in view._image_widgets)

    def test_collapsed_state_applies_to_later_loads(self, view):
        images = [{"id": 1, "anchor_position": 0, "data": _TINY_PNG}]
        view.set_images_collapsed(True)
        view.load(["%A"], [""], [], images)
        assert view._image_widgets[0].chevron.isChecked()

    def test_collapsed_state_survives_chunked_build(self, view, qapp):
        """Images past the first 100-entry batch must also start collapsed."""
        raws = [f"%line {i}" for i in range(250)]
        images = [{"id": 1, "anchor_position": 200, "data": _TINY_PNG}]
        view.set_images_collapsed(True)
        view.load(raws, [""] * 250, [], images)
        for _ in range(10):
            qapp.processEvents()
        assert view._image_widgets[0].chevron.isChecked()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_card_list.py::TestCardListViewImages -q
```

Expected: FAIL — `AttributeError: 'CardListView' object has no attribute 'image_export_toggled'` / `set_images_collapsed`.

- [ ] **Step 3: Add the signal and state field**

In `class CardListView`, add the signal beside `card_clicked` (line 285):

```python
    card_clicked = Signal(int)
    image_export_toggled = Signal(int, bool)   # (image_id, exclude)
```

In `__init__`, beside `self._image_widgets` (line 307), add:

```python
        self._image_widgets: list["ImageCard"] = []
        self._images_collapsed = False
```

- [ ] **Step 4: Build ImageCards in _build_batch**

Replace the `else:` branch of `_build_batch` (lines 399-404) with:

```python
            else:
                _, image = entry
                widget = ImageCard(image, len(self._image_widgets) + 1)
                widget.set_collapsed(self._images_collapsed)
                widget.export_toggled.connect(self.image_export_toggled)
                self._vbox.insertWidget(insert_at, widget)
                insert_at += 1
                self._image_widgets.append(widget)
```

Numbering is `len(self._image_widgets) + 1`, so it stays correct across chunked builds and restarts at 1 on every `load()` (which clears the list).

- [ ] **Step 5: Delete the old factory and add set_images_collapsed**

Delete the whole `_make_image_widget` method (lines 416-427) — nothing else calls it. In its place put:

```python
    def set_images_collapsed(self, collapsed: bool) -> None:
        """Apply to every existing ImageCard and make it the default for cards
        built later (including the remaining chunks of an in-flight load)."""
        self._images_collapsed = collapsed
        for widget in self._image_widgets:
            widget.set_collapsed(collapsed)
```

- [ ] **Step 6: Run the card-list tests**

```bash
source .venv/bin/activate && pytest tests/test_card_list.py -q
```

Expected: PASS — the pre-existing `TestCardListViewImages` tests (which pass id-less dicts) still pass because `ImageCard` reads `id` and `exclude_export` with `.get()`.

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/card_list.py tests/test_card_list.py
git commit -m "feat(cards): build ImageCards in CardListView with collapse-all support"
```

---

### Task 5: Wire the toggle and the View-menu action

**Files:**
- Modify: `translation_assistant/ui/main_widget.py` (`_build_actions`, the `CardListView` construction site, new `_on_image_export_toggled` and `_on_toggle_collapse_images`)
- Modify: `translation_assistant/ui/combined_window.py` (`_setup_menubar`, View menu)
- Test: `tests/test_main_window.py`, `tests/test_combined_window.py`

**Interfaces:**
- Consumes: `Database.set_image_exclude_export` (Task 1), `AppSettings.images_collapsed` (Task 2), `CardListView.image_export_toggled` / `set_images_collapsed` (Task 4)
- Produces: `TranslationAssistantWidget.action_collapse_images` (checkable `QAction`, text `"Collapse Images"`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main_window.py` (append as a new class at the end of the file):

```python
class TestImageCollapseAndExport:
    def test_action_collapse_images_exists_and_is_checkable(self, win):
        assert win.action_collapse_images.isCheckable()
        assert win.action_collapse_images.text() == "Collapse Images"

    def test_action_initialised_from_settings(self, qapp, tmp_path):
        from translation_assistant.ui.main_widget import TranslationAssistantWidget
        settings = _make_settings(tmp_path)
        settings.images_collapsed = True
        w = TranslationAssistantWidget(_settings=settings, _db=_make_db())
        assert w.action_collapse_images.isChecked()
        assert w._card_view._images_collapsed is True
        w.destroy()

    def test_toggling_action_persists_and_applies(self, win):
        win.action_collapse_images.setChecked(True)
        win.action_collapse_images.triggered.emit(True)
        assert win._settings.images_collapsed is True
        assert win._card_view._images_collapsed is True

    def test_export_toggle_writes_to_db(self, win):
        doc_id = win._db.create_document("doc")
        img_id = win._db.add_document_image(doc_id, 0, False, "pic.png", b"x")
        win._card_view.image_export_toggled.emit(img_id, True)
        assert win._db.get_document_images(doc_id)[0]["exclude_export"] == 1
        win._card_view.image_export_toggled.emit(img_id, False)
        assert win._db.get_document_images(doc_id)[0]["exclude_export"] == 0
```

Add to `tests/test_combined_window.py`, inside the class that holds `test_action_publish_wp_in_file_menu`:

```python
    def test_collapse_images_in_view_menu(self, win):
        mb = win.menuBar()
        for action in mb.actions():
            if action.text() == "View":
                view_menu = action.menu()
                break
        else:
            view_menu = None
        assert view_menu is not None
        action_texts = [a.text() for a in view_menu.actions()]
        assert "Collapse Images" in action_texts
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py::TestImageCollapseAndExport tests/test_combined_window.py -k "collapse or Collapse" -q
```

Expected: FAIL — `AttributeError: 'TranslationAssistantWidget' object has no attribute 'action_collapse_images'`.

- [ ] **Step 3: Add the action**

In `translation_assistant/ui/main_widget.py`, in `_build_actions()` directly after the `action_tm` block (around line 234):

```python
        self.action_collapse_images = QAction("Collapse Images", self)
        self.action_collapse_images.setCheckable(True)
        self.action_collapse_images.setChecked(self._settings.images_collapsed)
        self.action_collapse_images.triggered.connect(self._on_toggle_collapse_images)
```

- [ ] **Step 4: Add the handlers**

In `main_widget.py`, next to `_on_toggle_tm` (around line 1723), add:

```python
    def _on_toggle_collapse_images(self) -> None:
        collapsed = self.action_collapse_images.isChecked()
        self._settings.images_collapsed = collapsed
        self._card_view.set_images_collapsed(collapsed)

    def _on_image_export_toggled(self, image_id: int, exclude: bool) -> None:
        self._db.set_image_exclude_export(image_id, exclude)
```

- [ ] **Step 5: Connect the view at construction**

Find where `CardListView` is constructed in `main_widget.py`:

```bash
source .venv/bin/activate && grep -n "CardListView(" translation_assistant/ui/main_widget.py
```

Directly after the line that assigns `self._card_view`, add:

```python
        self._card_view.image_export_toggled.connect(self._on_image_export_toggled)
        self._card_view.set_images_collapsed(self._settings.images_collapsed)
```

If `_build_actions()` runs before that construction, this ordering is still correct: the action reads settings, the view reads settings, neither reads the other.

- [ ] **Step 6: Add the menu entry**

In `translation_assistant/ui/combined_window.py`, in the View menu block (around line 163), after `view_menu.addAction(ta.action_tm)`:

```python
        view_menu.addAction(ta.action_collapse_images)
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py tests/test_combined_window.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add translation_assistant/ui/main_widget.py translation_assistant/ui/combined_window.py tests/test_main_window.py tests/test_combined_window.py
git commit -m "feat(ui): wire image export toggle to DB and add Collapse Images action"
```

---

### Task 6: Honour exclude_export in both exports

**Files:**
- Modify: `translation_assistant/ui/main_widget.py:1261` (EPUB export), `translation_assistant/ui/main_widget.py:1452` (WordPress publish)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `exclude_export` in `get_document_images()` rows (Task 1)
- Produces: no new API — behaviour change only

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main_window.py`, inside `class TestExportEpubSeries` (it already has the monkeypatch scaffolding these need):

```python
    def test_excluded_inline_image_is_not_exported(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        db.add_document_image(doc_id, 1, False, "images/keep.png", b"keep-bytes")
        drop = db.add_document_image(doc_id, 1, False, "images/drop.png", b"drop-bytes")
        db.set_image_exclude_export(drop, True)
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert any(n.endswith("keep.png") for n in names)
        assert not any(n.endswith("drop.png") for n in names)

    def test_cover_still_exported_when_inline_image_excluded(self, win, tmp_path, monkeypatch):
        db = win._db
        doc_id = db.create_document(
            "Ch 1", series_title="S", series_order=1, chapter_title="Ch 1", volume_title="Vol 1"
        )
        db.save_lines(doc_id, [
            {"line_number": 0, "prefix": "%", "raw_text": "A", "translated_text": "Alpha"},
        ])
        db.add_document_image(doc_id, 0, True, "images/cover.jpg", b"fake-cover-bytes")
        drop = db.add_document_image(doc_id, 1, False, "images/drop.png", b"drop-bytes")
        db.set_image_exclude_export(drop, True)
        win._doc_id = doc_id
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path),
        )
        with patch("translation_assistant.ui.main_widget.QMessageBox.information"):
            win._on_export_epub_series()
        import zipfile
        out = tmp_path / "S" / "Vol 1.epub"
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "cover-image" in opf
```

For the WordPress side, add this test to the class that contains `test_status_ok_preserves_cached_chapter_index` (it uses the same fake-dialog/fake-worker scaffolding as the `previous_chapter_index` test around line 1234):

```python
    def test_excluded_image_not_in_wp_payload(self, win, monkeypatch):
        win.load_content(_sep_file("Hello\n", "Bonjour\n"))
        keep = win._db.add_document_image(win._doc_id, 0, False, "keep.png", b"keep-bytes")
        drop = win._db.add_document_image(win._doc_id, 0, False, "drop.png", b"drop-bytes")
        win._db.set_image_exclude_export(drop, True)
        win._settings.wp_endpoint_url = "https://example.com"
        win._settings.wp_api_key = "key123"
        doc = win._db.get_document(win._doc_id)
        win._db.set_series_wp_meta(
            doc["series_title"], series_slug="s", series_title_short="S",
        )

        from PySide6.QtWidgets import QDialog as _RealQDialog

        class _FakeDialog(_RealQDialog):
            def exec(self):
                return 1  # Accept

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget.QDialog", _FakeDialog,
        )

        class _FakeThread:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def quit(self):
                pass

            def wait(self, *a, **k):
                pass

            def connect(self, *a, **k):
                pass

            @property
            def succeeded(self):
                return self

            @property
            def error(self):
                return self

        monkeypatch.setattr(
            "translation_assistant.ui.main_widget._StatusCheckWorker", _FakeThread,
        )
        monkeypatch.setattr(
            "translation_assistant.ui.main_widget._PublishWorker", _FakeThread,
        )

        captured = {}
        import translation_assistant.wp_publisher as wp_publisher
        _real_build_payload = wp_publisher.build_payload

        def _spy_build_payload(*args, **kwargs):
            captured["kwargs"] = kwargs
            return _real_build_payload(*args, **kwargs)

        monkeypatch.setattr(wp_publisher, "build_payload", _spy_build_payload)

        win._on_publish_wp()

        sent_ids = [im["id"] for im in captured["kwargs"]["images"]]
        assert keep in sent_ids
        assert drop not in sent_ids
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py -k "excluded or cover_still" -q
```

Expected: FAIL — the excluded image is still present in the EPUB zip and in the WP payload.

- [ ] **Step 3: Filter the EPUB export**

In `translation_assistant/ui/main_widget.py`, change line 1261:

```python
                inline_images = [im for im in all_images
                                 if not im["is_cover"] and not im["exclude_export"]]
```

Leave the cover lookup on the next lines reading the unfiltered `all_images` — an excluded inline image must never suppress the cover.

- [ ] **Step 4: Filter the WordPress publish**

Change line 1452:

```python
        inline_images = [im for im in doc_images
                         if not im["is_cover"] and not im["exclude_export"]]
```

Leave `cover_image = next((im for im in doc_images if im["is_cover"]), None)` on the following line unchanged.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
source .venv/bin/activate && pytest tests/test_main_window.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the full suite**

```bash
source .venv/bin/activate && pytest -q
```

Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add translation_assistant/ui/main_widget.py tests/test_main_window.py
git commit -m "feat(export): omit images marked exclude_export from EPUB and WP"
```

---

## Self-Review Notes

Spec coverage check:

| Spec section | Task |
|---|---|
| `exclude_export` column, migration, `set_image_exclude_export` | 1 |
| `AppSettings.images_collapsed` | 2 |
| `ImageCard` structure, signals, `.get()` compatibility | 3 |
| `CardListView` integration, `set_images_collapsed`, `_build_batch` default | 4 |
| View-menu action, settings persistence, DB write on toggle | 5 |
| EPUB + WP filtering, cover unaffected | 6 |
| Testing section | tests inside tasks 1-6 |
