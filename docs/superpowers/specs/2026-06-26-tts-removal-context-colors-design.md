# Design: TTS Removal + Color-Coded Context Panels

**Date:** 2026-06-26  
**Status:** Approved

---

## Feature 1 — TTS Removal

Remove all TTS code. It was a stub (`tts.py` raised `NotImplementedError` everywhere) and the menu items were disabled. No user-visible functionality is lost.

### Files changed

| File | Change |
|------|--------|
| `translation_assistant/tts.py` | Delete |
| `translation_assistant/main_widget.py` | Remove `action_tts_jp`, `action_tts_cn`, `_try_init_tts()`, `_tts_engine`, `_on_toggle_tts_jp`, `_on_toggle_tts_cn` |
| `translation_assistant/ui/combined_window.py` | Remove `tts_menu` from Settings menu |
| `translation_assistant/settings.py` | Remove `tts` and `tts_lang` properties and their `_DEFAULTS` entries |

### Out of scope

No test files reference TTS — nothing to clean up there.

---

## Feature 2 — Color-Coded Context Panels

The `_review_top` and `_review_bottom` panels currently show all lines in plain text with no visual distinction between translated and untranslated entries. This feature adds green/red background banding per visual group.

### Architecture

**`core.py` — extend `build_review_text`**

New return type:
```python
tuple[str, dict[int, tuple[int, int]], list[tuple[int, int, bool]]]
```

- Element 0: display string (unchanged)
- Element 1: `offset_map` for double-click navigation (unchanged)
- Element 2: `color_ranges` — `[(group_char_start, group_char_end, is_translated), ...]`, one entry per visual group

`is_translated` is `True` when all lines in the group have a non-empty `translated_lines` entry.

`group_char_start` = char position of the first character of the raw line block.  
`group_char_end` = char position after the trailing `\n\n` separator (i.e. the full extent of the visual group).

**`main_widget.py` — apply formatting**

- Update 4 `build_review_text` call sites (2 in `_finish_load`, 2 in `_update_ui_for_pointer`) to unpack 3 values.
- New private helper `_apply_review_colors(widget: QTextEdit, ranges: list[tuple[int, int, bool]])`:
  - Iterates `ranges`; for each entry creates a `QTextCursor`, selects `start→end`, applies `QTextCharFormat` with background color.
  - **Translated:** `QColor(100, 200, 100, 60)` — muted green, semi-transparent
  - **Untranslated:** `QColor(220, 80, 80, 60)` — muted red, semi-transparent
- Call `_apply_review_colors` immediately after every `setPlainText` on `_review_top` / `_review_bottom`.

### Data flow

```
build_review_text(raw_lines, translated_lines, start, end)
  └── returns (text, offset_map, color_ranges)
        │
        ├── widget.setPlainText(text)
        │
        └── _apply_review_colors(widget, color_ranges)
              └── QTextCursor per range → QTextCharFormat.setBackground(color)
```

### Testing

- 7 existing `test_core.py` call sites use 2-value unpacking — update all to 3-value.
- Add 2 new assertions:
  - Translated group: `color_ranges[i][2] is True`
  - Untranslated group: `color_ranges[i][2] is False`

### Not in scope

- Theme-aware colors (dark mode not supported yet)
- Coloring the source (`_raw_line`) or translation (`_translated_line`) panels
