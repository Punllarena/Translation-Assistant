# Syosetu Fetch Enhancements

**Date:** 2026-06-12

## Overview

Three related improvements to how chapters are fetched from syosetu.com:

1. **Ruby text as parenthesis** — preserve furigana reading in `base(reading)` format instead of stripping or concatenating it
2. **Title as first translatable line** — prepend chapter title to raw document content; auto-fill Chapter Title metadata field on single fetch
3. **Re-fetch** — per-document action to re-fetch from stored source URL, preserving translations by line index

---

## Feature 1: Ruby Text as Parenthesis

### Problem

`fetch_syosetu()` uses `p.get_text(strip=True)` which flattens `<ruby>` tags, concatenating base and reading text directly (e.g. `振ふる` instead of `振(ふ)る`). This makes the raw text harder to read and loses pronunciation context that aids translation.

### Solution

Add `_para_text(p) -> str` helper in `scraper.py` that walks `<p>` children:

- `<ruby>` node → extract base text (NavigableStrings + non-`<rt>`/`<rp>` children), extract `<rt>` text → emit `base(reading)` if reading present, else just `base`
- Other tag nodes → `.get_text()`
- NavigableString → string as-is

`fetch_syosetu()` uses `"\n".join(_para_text(p).strip() for p in content_el.find_all("p"))` instead of the current comprehension.

**Files changed:** `scraper.py`

---

## Feature 2: Title as First Translatable Line + Auto-fill Metadata

### Problem

- **Single fetch (`dlg_new.py`):** Fetch box already prepends `title\n\ncontent`, but the Chapter Title metadata field is not auto-filled — user must retype it.
- **Batch fetch (`dlg_fetch_series.py`):** `build_new_file(content)` omits the title from raw document content. Title is only stored as metadata, not visible as a translatable line.

### Solution

**`dlg_new.py`** — in `_on_fetch_done(title, content)`, add:
```python
if title:
    self._chapter_edit.setText(title)
```
The text box already has `f"{title}\n\n{content}"`, so no other change needed.

**`dlg_fetch_series.py`** — in `_on_chapter_done(num, title, content)`, change:
```python
formatted = build_new_file(content)
```
to:
```python
formatted = build_new_file(f"{title}\n\n{content}" if title else content)
```

**Files changed:** `dlg_new.py`, `dlg_fetch_series.py`

---

## Feature 3: Re-fetch

### Problem

No way to retroactively re-fetch document content after scraper improvements (e.g. ruby fix, title inclusion). Source URL not stored, so no way to know where content came from.

### Solution

#### DB Layer (`db.py`)

**Schema migration** (idempotent, via existing `_apply_schema` pattern):
```sql
ALTER TABLE documents ADD COLUMN source_url TEXT NOT NULL DEFAULT ''
```

**`create_document()`**: add `source_url: str = ""` keyword parameter.

**`get_document()`**: include `source_url` in SELECT.

**`list_documents()`**: include `source_url` in SELECT.

**New method `replace_raw_content(doc_id, new_raw_lines)`**:
1. Call `get_lines(doc_id)` to retrieve existing translations
2. Rebuild rows: for each new line at index `i`, preserve `translated_text` from index `i` of old rows (empty string if index out of range)
3. Call `save_lines(doc_id, rows)`

The prefix-splitting logic (`%`/`$` prefix detection) is inlined in this method (mirrors `core.lines_to_db_rows`, but `db.py` does not import `core`).

#### Source URL Storage

**`dlg_new.py`**: add `source_url` property:
```python
@property
def source_url(self) -> str:
    if self._tabs.currentIndex() == 1:  # Fetch from URL tab
        return self._url_edit.text().strip()
    return ""
```

**`main_widget.py`**:
- `load_content()` gets `source_url: str = ""` parameter, passes to `create_document()`
- `_on_new_doc()` passes `source_url=dlg.source_url`

**`dlg_fetch_series.py`**:
- `_on_chapter_done` passes `source_url=ch["url"]` to `create_document()`

#### Re-fetch UI (`dlg_open.py`)

- Add `_source_urls: dict[int, str]` (keyed by `id(leaf)`) populated in `_load_documents()` from `source_url` returned by `list_documents()`
- Add "Re-fetch" button in button row — enabled only when selected leaf has non-empty source_url
- `_on_selection_changed()` also updates Re-fetch button enabled state

**`_on_refetch()` flow:**
1. Get `doc_id` and `source_url` from selection
2. Confirm dialog: "Re-fetch from `<url>`? Existing translations will be preserved by line position."
3. Disable Re-fetch button, show "Fetching…" in status (or reuse existing status label pattern)
4. Start `FetchWorker(source_url)`
5. `_on_refetch_done(doc_id, title, content)`:
   - Build `formatted = build_new_file(f"{title}\n\n{content}" if title else content)`
   - `raw_lines, _, _ = parse_file_content(formatted)`
   - `self._db.replace_raw_content(doc_id, raw_lines)`
   - Re-enable button, reload list, show brief success message

**Files changed:** `db.py`, `dlg_new.py`, `main_widget.py`, `dlg_fetch_series.py`, `dlg_open.py`

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `scraper.py` | Add `_para_text()`, use in `fetch_syosetu()` |
| `db.py` | Migration, `source_url` in create/get/list, new `replace_raw_content()` |
| `dlg_new.py` | Auto-fill chapter title field on fetch done; `source_url` property |
| `dlg_fetch_series.py` | Prepend title to content; pass `source_url` to `create_document()` |
| `main_widget.py` | `load_content()` accepts `source_url`; pass through from `_on_new_doc()` |
| `dlg_open.py` | Re-fetch button + `_source_urls` dict + `_on_refetch()` flow |

---

## Testing Notes

- `scraper.py` changes are testable with a mock `<p>` tag containing `<ruby>` elements
- DB migration is idempotent — existing databases gain `source_url = ''` on all docs
- Re-fetch with no existing translations: all lines get empty `translated_text` (no regression)
- Re-fetch with fewer new lines than old: excess old translations silently dropped (acceptable — raw content changed)
- Re-fetch with more new lines than old: new lines get empty `translated_text`
