# WordPress Password Protection — Design Spec

**Date:** 2026-06-26
**Status:** Approved

## Overview

Add per-chapter password protection to the WordPress publish flow. When enabled for a series, each new chapter beyond the first N is published password-protected. A random password is generated at publish time and shown to the user as copyable text. When the (N+1)th chapter after a locked chapter is published, that earlier chapter is automatically unlocked (keeping exactly N chapters locked at any time).

## Requirements

- Chapter 0 (synopsis, `series_order == 0`): always published unlocked regardless of settings.
- Chapters 1..N: always unlocked — no password applied.
- Chapter N+1 and beyond: published with a password.
- When publishing chapter X (X > N), unlock chapter X−N if and only if X−N > N (i.e. X > 2N). This means the unlock list starts only once the window fills up.
- Example (N=5): chapters 1–5 free, ch6 first locked, ch11 published → ch6 unlocked (5 locked: 7–11).
- Password is auto-generated per chapter using `secrets.token_urlsafe(8)`. Never stored.
- After publish, success dialog shows the password in a selectable/copyable field, plus which chapter (if any) was unlocked.
- Settings are per-series with global defaults. Series can inherit global, override on, or override off.

## Data Model

### AppSettings (`settings.py`)

Two new `QSettings` keys:

| Property | Type | Default |
|---|---|---|
| `wp_password_enabled` | `bool` | `False` |
| `wp_unlock_after` | `int` | `3` |

### `series_profiles` table (`db.py`)

Two new columns via idempotent `ALTER TABLE` migration in `_apply_schema()`:

| Column | Type | Default | Meaning |
|---|---|---|---|
| `wp_password_enabled` | `TEXT` | `NULL` | `"1"` = on, `"0"` = off, `NULL` = inherit global |
| `wp_unlock_after` | `INTEGER` | `-1` | positive = override; `-1` = inherit global |

### DB methods

```python
def get_series_wp_password_settings(self, series_title: str) -> dict:
    # returns {"wp_password_enabled": "1"|"0"|None, "wp_unlock_after": int}

def set_series_wp_password_settings(
    self, series_title: str,
    enabled: str | None,   # "1", "0", or None
    unlock_after: int,     # positive or -1
) -> None:
    # UPSERT into series_profiles
```

## Payload & Publish Logic

### New helper: `wp_publisher.compute_password_fields()`

```python
import secrets

def compute_password_fields(
    chapter_index: int, unlock_after: int
) -> tuple[str | None, int | None]:
    """Returns (password, unlock_chapter_index). Either may be None."""
    if chapter_index == 0 or chapter_index <= unlock_after:
        return None, None
    password = secrets.token_urlsafe(8)
    unlock_idx = chapter_index - unlock_after
    return password, (unlock_idx if unlock_idx > unlock_after else None)
```

### `build_payload()` signature change

Add optional `password: str | None = None` and `unlock_chapter_index: int | None = None`. When not `None`, include in payload dict.

### `main_widget._on_publish_wp()` additions

After resolving `doc_meta` and `series_meta`, before building payload:

1. Fetch `series_pw_settings = db.get_series_wp_password_settings(series_title)`
2. Resolve effective settings:
   ```python
   enabled = (
       series_pw_settings["wp_password_enabled"] == "1"
       if series_pw_settings["wp_password_enabled"] is not None
       else settings.wp_password_enabled
   )
   unlock_after = (
       series_pw_settings["wp_unlock_after"]
       if series_pw_settings["wp_unlock_after"] != -1
       else settings.wp_unlock_after
   )
   ```
3. If `enabled`: call `compute_password_fields(doc_meta["series_order"], unlock_after)` → `(password, unlock_chapter_index)`
4. Pass `password` and `unlock_chapter_index` to `build_payload()`.
5. Pass `password` and `unlock_chapter_index` through `_PublishWorker` signal so `_on_publish_done` can display them.

## UI

### `dlg_wp_settings.py` — global defaults section

Below the API key field, add:

```
[ ] Enable password protection by default
    Keep [3 ▲▼] chapters locked
```

Spinbox range 1–99, enabled only when checkbox checked. Saved on Save button.

### `dlg_series.py` — "Set WP Fields" mini-dialog

Below Slug / Short Title:

```
Password protection: [Use global ▼]   (QComboBox: "Use global" / "Always on" / "Always off")
Keep locked:         [3 ▲▼]            (QSpinBox, disabled when "Use global")
```

- "Use global" → saves `NULL` / `-1`
- "Always on" → saves `"1"` / spinbox value
- "Always off" → saves `"0"` / `-1`

### `_on_publish_done()` — success dialog

Replace `QMessageBox.information` with a small `QDialog`:

```
Published!

Page:  https://…
Post:  https://…

Password (copy this):  [abc12XYZ        ]   ← read-only QLineEdit, selected on show
Chapter 7 is now unlocked.                  ← only shown if unlock happened
```

If `created is False` (already published): "Already published" label, no password field.

## Error Handling

- WP plugin error about `unlock_chapter_index` not found: non-fatal warning shown below success info.
- All existing `WPPublishError` paths unchanged.

## Testing

### `test_wp_publisher.py` — `compute_password_fields` table

| chapter_index | N | password | unlock_idx |
|---|---|---|---|
| 0 | 3 | None | None |
| 3 | 3 | None | None |
| 4 | 3 | str | None |
| 6 | 3 | str | None |
| 7 | 3 | str | 4 |
| 11 | 5 | str | 6 |

### `test_settings.py`

Two tests: getter returns default, setter round-trips for both new properties.

### `test_db.py`

`get_series_wp_password_settings` returns defaults for unknown series; `set` + `get` round-trips all three states (`"1"`, `"0"`, `NULL`/`-1`).
