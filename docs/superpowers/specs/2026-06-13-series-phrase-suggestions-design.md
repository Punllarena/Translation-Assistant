# Series Phrase Suggestions — Design Spec

**Date:** 2026-06-13

## Summary

A standalone dialog (`Tools → Series Phrase Suggestions…`) that analyzes all raw Japanese
text in a chosen series using MeCab morphological analysis, surfaces frequently occurring
nouns not already in the active profile's glossary, and lets the user add them (with a
translation) directly to the profile.

---

## Components

### 1. `translation_assistant/core.py` — new function

```python
def extract_frequent_nouns(
    raw_lines: list[str],
    already_in_glossary: set[str],
    min_freq: int = 2,
) -> list[tuple[str, int]]:
```

- Uses `MeCab.Tagger()` from `mecab-python3`
- Tokenizes each line; keeps tokens whose POS starts with `名詞`
- Skips: numbers (`名詞,数`), single-character tokens, tokens already in `already_in_glossary`
- Returns `[(term, count), ...]` sorted by count descending
- No Qt imports — fully unit testable
- Callers catch `ImportError`/`RuntimeError` if MeCab is not installed

### 2. `translation_assistant/ui/dlg_series_phrases.py` — new dialog

**Class:** `SeriesPhrasesDialog(QDialog)`

**Constructor args:** `db: Database, settings: AppSettings, current_series: str = ""`

**Controls:**
| Widget | Purpose |
|---|---|
| Series `QComboBox` | Populated from `db.get_series_list()`; pre-selects `current_series` |
| Profile `QComboBox` | Populated from `db.list_profiles()`; default = `db.get_series_profile(series)` → fallback `settings.profile_used` |
| Min-frequency `QSpinBox` | Default 2 |
| **Analyze** `QPushButton` | Triggers analysis; disabled if no series in DB |
| Status `QLabel` | Shows result count / error / "No new candidates" message |
| Results `QTableWidget` | Two columns: Term (JP) \| Count; read-only |
| Translation `QLineEdit` | Activated on row selection |
| **Add to [Profile]** `QPushButton` | Enabled when row selected + translation non-empty |

**Behavior:**
- Analyze: fetch all `lines.raw_text` for series docs → `core.extract_frequent_nouns` → populate table
- Row select: activates translation field + Add button
- Add: `db.add_phrase(profile, term, translation)` → remove row → update local `already_in_glossary` set
- Profile change: re-filter cached raw term counts against new glossary (no MeCab re-run)
- MeCab missing: `QMessageBox.warning` with `pip install mecab-python3` hint; table stays empty

### 3. `translation_assistant/ui/main_window.py` — menu wiring

Add to `Tools` menu:
```
Tools → Series Phrase Suggestions…   (Ctrl+Shift+P)
```

Handler passes `current_series_title` from the currently open document (empty string if none).

---

## Data Flow

```
Dialog opens
  └─ db.get_series_list() → series dropdown
  └─ db.list_profiles()   → profile dropdown

User clicks Analyze
  └─ SELECT id FROM documents WHERE series_title = ?
  └─ db.get_lines(doc_id) for each doc → collect raw_text
  └─ db.get_glossary(profile) → already_in_glossary set
  └─ core.extract_frequent_nouns(lines, already_in_glossary, min_freq)
  └─ populate QTableWidget

User selects row
  └─ translation QLineEdit enabled
  └─ Add button enabled

User types translation → clicks Add
  └─ db.add_phrase(profile, term, translation)
  └─ remove row from table
  └─ add term to local already_in_glossary set

Profile dropdown changes
  └─ reload glossary for new profile
  └─ re-filter cached raw results (hide already-glossarized terms)
  └─ no MeCab re-run
```

---

## Error Handling

| Condition | Behavior |
|---|---|
| MeCab not installed | `QMessageBox.warning` with install hint; table empty |
| Series has no documents | Status: "No lines found for this series" |
| All candidates already in glossary | Status: "No new candidates (N terms already in glossary)" |
| No series exist in DB | Analyze button disabled; status: "No series found" |
| Duplicate add (UI guard) | Impossible — row removed on first Add |

---

## Constraints

- No new DB tables or schema changes
- `core.extract_frequent_nouns` has no Qt dependency
- MeCab is an optional runtime dependency; absence shows a clear error, does not crash
- Keyboard shortcut: `Ctrl+Shift+P`
