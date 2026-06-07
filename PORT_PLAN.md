# Translation Assistant — .NET/WPF to Python/PySide6 Port Plan

**Source project:** `/home/pun/workspace/JoeGlensTranslationAssistant`
**Target stack:** Python 3.11+, PySide6 (Qt6)
**Original author:** joeglens (VB.NET / WPF)

---

## Application Overview

Translation Assistant is a desktop tool for Japanese/Chinese→English text translation. Key behaviours:

- Opens `.txt` files with a `---SEPERATOR---` format (raw source text above, blank translation lines below)
- Displays one line at a time for translation, auto-copying the raw text to clipboard
- Applies glossary phrase-substitution from per-profile CSV files before displaying raw text
- Saves translated lines back into the same file on Enter or Ctrl+S
- Provides sentence-level parse navigation (Ctrl+Left/Right) using configurable split characters
- Supports TTS read-aloud for Japanese and Chinese via Microsoft.Speech (Windows-only)
- Custom spellcheck dictionary per profile (`.lex` files)
- Always-on-top toggle, progress tracking, special Japanese punctuation shortcuts (F1–F8)

---

## Technology Mapping

| .NET / WPF | Python / PySide6 |
|---|---|
| `Window` / XAML | `QMainWindow` + `.ui` file or pure code layout |
| `TextBox` (editable) | `QPlainTextEdit` / `QTextEdit` |
| `TextBox` (read-only) | `QTextEdit` (read-only) |
| `DataGrid` | `QTableWidget` / `QTableView` + model |
| `ComboBox` | `QComboBox` |
| `MenuItem` / menu bar | `QMenuBar` + `QAction` |
| `StatusBar` | `QStatusBar` |
| `DispatcherTimer` | `QTimer` |
| `My.Settings` | `QSettings` (ini-backed) |
| `Microsoft.Speech` | `pyttsx3` (cross-platform TTS) |
| `SpellCheck.IsEnabled` | `pyenchant` + `enchant` dicts |
| `Clipboard` (Win32 interop) | `QApplication.clipboard()` |
| `OpenFileDialog` / `SaveFileDialog` | `QFileDialog` |
| `MessageBox` (`MsgBox`) | `QMessageBox` |
| `My.Computer.FileSystem` | `pathlib.Path` |
| `My.Application.Info.Version` | `importlib.metadata` / hardcoded constant |

---

## Stage Status

| Stage | Status | Notes |
|---|---|---|
| 1 — Environment Setup | ✅ Complete | PySide6 6.11.1, pyttsx3 2.99, pyenchant 3.3.0; pip bootstrapped via `get-pip.py`; `settings.py` typed getters/setters implemented early |
| 2 — Settings & Config | ✅ Complete | `_get_app_root()`, `get_profile_dir()`, `ensure_profile_defaults()`; `_qs` test seam; pytest suite passing |
| 3 — Core Logic | ✅ Complete | All 8 functions implemented; 55-test suite passing; round-trip verified |
| 4 — Dialog Windows | ✅ Complete | All 4 dialogs implemented; 35-test suite passing; no regressions (106 total) |
| 5 — Main Window | ✅ Complete | Full QMainWindow; all nav keys; timers; double-click; 58 new tests (164 total) |
| 6 — Clipboard | ✅ Complete | Integrated in Stage 5 (debounce timer, export, Ctrl+I/F) |
| 7 — TTS | ⏭ Skipped | pyttsx3 stub present in MainWindow; deferred — espeak-ng JP/CN support too limited on Linux |
| 8 — Spellcheck | ✅ Complete | `SpellHighlighter` with enchant + custom `.lex`; 26 new tests (190 total) |
| 9 — Special Punctuation | ✅ Complete | F1–F8 + menu actions implemented in Stage 5 |
| 10 — Testing & Packaging | ✅ Complete | 46 integration tests; auto-save timer; PyInstaller spec + build.sh; 236 total tests |

---

## Stage 1 — Environment Setup & Project Scaffolding

**Goal:** reproducible dev environment, proper package layout.

### Tasks

1. Create a Python virtual environment:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   ```

2. Create `requirements.txt`:
   ```
   PySide6>=6.6
   pyttsx3>=2.90
   pyenchant>=3.2
   ```

3. Establish the source layout:
   ```
   TranslationAssistant-PySide6-Port/
   ├── translation_assistant/
   │   ├── __init__.py
   │   ├── main.py            # entry point
   │   ├── settings.py        # QSettings wrapper
   │   ├── core.py            # text processing logic
   │   ├── tts.py             # TTS abstraction
   │   ├── spellcheck.py      # enchant wrapper
   │   ├── ui/
   │   │   ├── main_window.py
   │   │   ├── dlg_new.py
   │   │   ├── dlg_phrase.py
   │   │   ├── dlg_profile.py
   │   │   └── dlg_profile_name.py
   │   └── resources/
   │       └── TA.ico
   ├── Profile/               # default profile directory (shipped with app)
   │   ├── Default.csv
   │   └── Default.lex
   ├── requirements.txt
   └── PORT_PLAN.md
   ```

4. Create `main.py` entry-point boilerplate:
   ```python
   import sys
   from PySide6.QtWidgets import QApplication
   from translation_assistant.ui.main_window import MainWindow

   def main():
       app = QApplication(sys.argv)
       app.setApplicationName("Translation Assistant")
       app.setOrganizationName("joeglens")
       window = MainWindow()
       window.show()
       sys.exit(app.exec())

   if __name__ == "__main__":
       main()
   ```

### Acceptance criteria
- `python -m translation_assistant.main` launches without error (blank window is fine at this stage).

### Implementation notes (completed 2026-06-06)
- `python3 -m venv .venv --without-pip`; pip seeded via `get-pip.py` because system `ensurepip` was stripped.
- Installed: PySide6 6.11.1, pyttsx3 2.99, pyenchant 3.3.0.
- `settings.py` was fully implemented (not stubbed) to unblock every downstream stage.
- `requirements-dev.txt` added alongside `requirements.txt` to keep pytest/PyInstaller out of production installs.

---

## Stage 2 — Settings & Configuration Module

**Goal:** replicate `My.Settings` persistence using `QSettings`.

### Existing settings to port

| Setting | Type | Default |
|---|---|---|
| `ParseChar` | str | `"、 。 ？ ！ 「 」 …… "` |
| `ProfileUsed` | str | `"Default"` |
| `ShowProgress` | bool | `True` |
| `AutoSave` | int | `5` |
| `OnTop` | bool | `True` |
| `TTS` | bool | `False` |
| `TTSLang` | int | `0` (0=JP, 1=CN) |

### Implementation notes

- `settings.py` wraps `QSettings` with typed getters/setters so the rest of the app never calls `QSettings` directly.
- Profile directory defaults to `<exe_dir>/Profile/`; override via a setting for portability on Linux.
- On first run, create `Profile/Default.csv` and `Profile/Default.lex` if absent.

### Acceptance criteria
- Settings persist across app restarts.
- Missing profile directory is auto-created with Default files.

### Implementation notes (completed 2026-06-06)
- `_get_app_root()` detects dev (`Path(__file__).parent.parent`) vs PyInstaller bundle (`Path(sys.executable).parent`) via `sys.frozen`.
- `get_profile_dir()` returns `_get_app_root() / "Profile"` — single source of truth.
- `ensure_profile_defaults()` is idempotent; called from `AppSettings.__init__`.
- `AppSettings.__init__` accepts optional `_qs: QSettings` injection seam so tests can use a temp INI file without writing to the real user config.
- `profile_dir` property added to `AppSettings` for use by dialogs and main window.
- `tests/conftest.py` provides `qapp` (session-scoped) and `tmp_settings` fixtures.
- `tests/test_settings.py` covers: defaults, persistence, profile dir auto-creation, idempotency.

---

## Stage 3 — Core Text Processing Module

**Goal:** port all pure logic from `MainWindow.xaml.vb` and `frmNew.xaml.vb` into a framework-agnostic `core.py`.

### Functions to implement

#### `parse_file_content(text: str) -> tuple[list[str], list[str]]`
Splits on `---SEPERATOR---`, returns `(raw_lines, translated_lines)`.
- Strips trailing empty lines.
- Strips `\r\n` line endings from each element.

#### `build_new_file(raw_input: str) -> str`
Equivalent to `btnCreate_Click` in `frmNew`.
- Splits on `\n`.
- For each line, splits on `。` to produce `%first_sentence。\n$continuation。\n` entries.
- Appends `---SEPERATOR---` and blank translation block.

#### `replace_and_parse(text: str, glossary: list[tuple[str,str]], parse_chars: list[str]) -> tuple[str, list[str]]`
Equivalent to `replaceAndParse` + `parseCount`.
- Strips `$` and `%` markers.
- Applies glossary substitutions.
- Splits result by parse characters to produce a sentence list.
- Returns `(display_text, sentences)`.

#### `build_review_text(raw_lines, translated_lines, start, end) -> tuple[str, dict]`
Equivalent to `updateReview`.
- Groups lines that begin with `$` with their preceding `%` line.
- Returns the display string and a character-offset map for double-click navigation.

#### `calculate_progress(raw_lines, translated_lines) -> tuple[int, int]`
Returns `(completion_percent, word_count)`.

#### `build_clipboard_output(raw_lines, translated_lines) -> str`
Equivalent to the clipboard assembly in `menuClipboard_Click`.

#### `load_glossary(path: Path) -> list[tuple[str,str]]`
Reads a CSV profile; returns list of `(phrase, translation)` pairs.

#### `save_file(filepath: Path, raw_section: str, translated_lines: list[str])`
Writes the file in `---SEPERATOR---` format.

### Acceptance criteria
- Unit tests cover round-trip: `build_new_file` output can be parsed by `parse_file_content`.
- `replace_and_parse` correctly applies glossary entries.

### Implementation notes (completed 2026-06-06)
- `parse_file_content` returns a 3-tuple `(raw_lines, translated_lines, raw_section)` — `raw_section` is needed by `save_file` and not in the original plan signature; updated here.
- `replace_and_parse` returns a 3-tuple `(display_text, sentences, replaced)` — `replaced` is needed by Ctrl+Left parse navigation to know whether a pre-substitution state exists.
- `build_review_text` does **not** mutate `raw_lines` (the VB original stripped `%` markers in-place; Python version keeps the array clean).
- Blank input lines in `build_new_file` become `"%"` entries (VB: `"%" & "" & vbNewLine`), not empty strings — this is the correct VB-matching behaviour.
- `tests/test_core.py`: 55 tests across all 8 functions including round-trip and offset-map navigation tests.

---

## Stage 4 — Dialog Windows

**Goal:** implement the four modal dialogs.

### 4a — `dlg_profile_name.py` (`QDialog`)

Equivalent to `frmProfileName`.
- Single `QLineEdit` for profile name.
- OK button disabled until text length > 0.
- Sanitizes forbidden filename characters on accept: `\ / * : ? " < > |` → `_`.

### 4b — `dlg_phrase.py` (`QDialog`)

Equivalent to `frmPhrase`.
- Two `QLineEdit` widgets: Phrase and Translation.
- OK button disabled until Translation has text.
- On accept: appends `phrase,translation` (spaces in translation replaced with `_`) to active profile CSV.
- Returns the full updated CSV content to caller.

### 4c — `dlg_new.py` (`QDialog`)

Equivalent to `frmNew`.
- Large `QPlainTextEdit` for raw input.
- Create button calls `core.build_new_file()`, opens `QFileDialog.getSaveFileName`, writes the file.
- Returns `(file_content, filepath)` on accept.

### 4d — `dlg_profile.py` (`QDialog`)

Equivalent to `frmProfile`.
- `QComboBox` listing all `*.csv` files in Profile directory.
- `QTableWidget` with Phrase/Translation columns; rows editable in-place.
- Parse characters `QLineEdit`.
- New / Delete / Save buttons.
  - New → opens `dlg_profile_name`, creates blank `.csv` + `.lex`.
  - Delete → disabled for Default; deletes `.csv` + `.lex`.
  - Save → writes table back to CSV; stores `ProfileUsed` and `ParseChar` in settings.
- Double-click row → confirm-delete that row.

### Acceptance criteria
- All four dialogs open and close correctly from MainWindow.
- Data entered in dialogs reflects in the calling window.

---

## Stage 5 — Main Window

**Goal:** full `MainWindow` equivalent in `main_window.py`.

### Layout

```
QMainWindow
├── QMenuBar
│   ├── File
│   │   ├── New  (Ctrl+N)
│   │   ├── Open (Ctrl+O)
│   │   └── Save (Ctrl+S)  [initially disabled]
│   ├── Settings
│   │   ├── Profile (Ctrl+P)
│   │   ├── Phrase  (Ctrl+L)
│   │   ├── Show Progress  [checkable]
│   │   ├── Always On Top  [checkable]
│   │   └── Text-To-Speech
│   │       ├── Japanese  [checkable, initially disabled]
│   │       └── Chinese   [checkable, initially disabled]
│   ├── Special Punctuations
│   │   ├── Single Quote 「」  (F1)
│   │   ├── Double Quote 『』  (F2)
│   │   ├── Lenticular 【】   (F3)
│   │   ├── Ellipsis …        (F4)
│   │   ├── Wave Dash 〜      (F5)
│   │   ├── Single Title 〈〉 (F6)
│   │   ├── Double Title 《》 (F7)
│   │   └── Long Dash ー      (F8)
│   ├── Clipboard (Ctrl+I)  [initially disabled]
│   └── About
├── QSplitter (vertical) or manual DockPanel equivalent
│   ├── reviewTop     QTextEdit (read-only, resizable)
│   ├── currentRawLine    QTextEdit (read-only, fixed height ~52px)
│   ├── currentTranslatedLine  QTextEdit (editable, spellcheck, fixed height ~52px)
│   └── reviewBottom  QTextEdit (read-only, fixed height ~137px)
└── QStatusBar
    ├── completionStatus  "0% Complete"
    ├── lineStatus        "Line: xxxx/xxxx"
    ├── wordCountStatus   "xxxx Words"
    └── fileSaved         "File saved…" (right-aligned)
```

### State variables

```python
raw_lines: list[str]
translated_lines: list[str]
glossary: list[tuple[str, str]]
array_pointer: int
parse_sentences: list[str]
parse_pointer: int
replaced: bool
filepath: Path | None
txt_output: str          # raw section preserved for saving
total_raw_lines: int
tl_complete: int
line_number_map: dict    # {index: (start_offset, end_offset)} for double-click nav
```

### Key behaviours to port

#### Navigation (all key presses route through a single handler)

| Key | Behaviour |
|---|---|
| Enter / PgDn | Save current translation, advance to next non-empty line, auto-save file |
| PgUp | Save current translation, move to previous non-empty line |
| Ctrl+Home | Jump to line 0 |
| Ctrl+End | Jump to next untranslated line |
| Ctrl+Right | Advance parse pointer; highlight next parsed sentence in raw box |
| Ctrl+Left | Retreat parse pointer; highlight previous sentence or revert to original |
| Ctrl+S | Save file |
| Ctrl+L | Open Phrase dialog |
| Ctrl+P | Open Profile dialog |
| Ctrl+O | Open file |
| Ctrl+I | Copy translated output to clipboard |
| Ctrl+J | Add selected text to custom `.lex` dictionary |
| Ctrl+A | Select all in translation box |
| Ctrl+F | Copy current translated line to clipboard |
| F1–F8 | Insert special punctuation at cursor |

**Implementation note:** install an event filter on the `QMainWindow` and forward `keyPressEvent` from all child widgets to a single `_handle_key` method, mirroring the VB approach of routing all key events to `currentTranslatedLine_PreviewKeyDown`.

#### Clipboard auto-copy timer

- `QTimer` (400 ms, single-shot) fires `_write_to_clipboard`.
- On navigation, timer restarts rather than writing immediately (debounce).

#### File-saved status timer

- `QTimer` (2000 ms, single-shot) clears the "File saved…" status bar label.

#### Double-click navigation in review panels

- Use `mouseDoubleClickEvent` override on the `QTextEdit` subclass.
- Get cursor position character offset via `QTextCursor.position()`.
- Look up offset in `line_number_map` to find corresponding `array_pointer` value.

#### Window resize

Proportional resize of `reviewTop` and `reviewBottom` using `resizeEvent`; mirror the logic from `MainWindow_SizeChanged`.

### Acceptance criteria
- Can open a `---SEPERATOR---` format file, navigate with Enter/PgDn/PgUp, type a translation, and save.
- Progress status updates correctly.
- All keyboard shortcuts from the original are functional.

---

## Stage 6 — Clipboard Integration

**Goal:** replace Win32 clipboard interop with Qt clipboard.

### Notes

- `QApplication.clipboard().setText(text)` replaces the `NativeMethods` P/Invoke calls.
- No busy-wait loop needed; Qt clipboard is synchronous.
- The debounce `QTimer` (400 ms) still applies so that rapid navigation does not flood the clipboard.

### Acceptance criteria
- Current raw line is in system clipboard within 400 ms of navigation.
- Selected text is used if a selection exists; full line otherwise.

---

## Stage 7 — Text-to-Speech

**Goal:** replace `Microsoft.Speech.Synthesis.SpeechSynthesizer` with `pyttsx3`.

### Implementation (`tts.py`)

```python
class TTSEngine:
    def __init__(self): ...
    def available_voices(self) -> list[str]: ...
    def set_voice(self, name: str): ...
    def speak_async(self, text: str): ...
    def stop(self): ...
```

- At startup, enumerate `pyttsx3` voices; enable the JP/CN menu items if voices matching Japanese/Chinese locale are found.
- `speak_async` runs in a `QThread` (or `concurrent.futures.ThreadPoolExecutor`) to avoid blocking the UI.
- Cancel in-progress speech before starting a new utterance.

### Known gap

`pyttsx3` on Linux uses `espeak-ng`; availability of Japanese/Chinese voices depends on the system. Document this in-app via the "No TTS Engine Installed" fallback message.

### Acceptance criteria
- TTS reads the current raw line aloud when enabled.
- TTS does not block the UI thread.

---

## Stage 8 — Spellcheck Integration

**Goal:** replace WPF built-in spellcheck + `.lex` custom dictionaries.

### Options (choose one)

| Option | Pros | Cons |
|---|---|---|
| `pyenchant` + `enchant` | Close to WPF feature set, real-time underlines via subclassed QTextEdit | Requires system `enchant` lib; custom dict format differs |
| `pyspellchecker` | Pure Python, no system dep | No real-time underline without extra work |
| Defer | Quickest path to parity on core features | Translators lose spell assist |

**Recommended:** implement with `pyenchant`. Subclass `QTextEdit` as `SpellCheckEdit`; override `paintEvent` to draw red underlines using `QSyntaxHighlighter`.

### Custom dictionary

- `.lex` files in the original are WPF-specific. For the Python port, use a plain text word-list file (one word per line) per profile, same `.lex` filename.
- On Ctrl+J or "Add to Dictionary": append word to the `.lex` file and reload the highlighter's word list.

### Acceptance criteria
- Misspelled English words are underlined in red in the translation box.
- Right-click context menu offers spell suggestions and "Add to Dictionary".
- Custom dictionary words are not flagged.

---

## Stage 9 — Special Punctuation System

**Goal:** port F1–F8 punctuation insertion.

### Punctuation table

| Key | Character(s) | Inserted at cursor |
|---|---|---|
| F1 | `「」` | Both; cursor positioned between them |
| F2 | `『』` | Both; cursor between |
| F3 | `【】` | Both; cursor between |
| F4 | `…` | Single |
| F5 | `〜` | Single |
| F6 | `〈〉` | Both; cursor between |
| F7 | `《》` | Both; cursor between |
| F8 | `ー` | Single |

### Implementation note

- For paired characters, insert the pair then move the cursor back one position using `QTextCursor.movePosition(QTextCursor.Left)`.
- Both menu and F-key trigger the same `_insert_punctuation(index)` method.

### Acceptance criteria
- Each F-key and menu item inserts the correct character(s) at the cursor.
- Cursor is positioned between paired brackets.

---

## Stage 10 — Testing, Polish & Packaging

**Goal:** verify feature parity, harden edge cases, produce a distributable.

### Testing checklist

- [ ] Round-trip file test: create → translate → save → re-open preserves content
- [ ] Glossary substitution applies correctly on load and after profile change
- [ ] Parse navigation (Ctrl+Left/Right) highlights correct sentence segments
- [ ] Double-click in review panels jumps to correct line
- [ ] Progress percentage and word count update on every navigation step
- [ ] Always-on-top toggle persists after restart
- [ ] TTS enable/disable persists after restart
- [ ] Profile create / delete / rename
- [ ] Custom dictionary word survives app restart
- [ ] Large file (1000+ lines) performance is acceptable

### Edge cases inherited from original

- Lines beginning with `$` are continuations of the preceding line; they display grouped in the review panels.
- Lines beginning with `%` have the marker stripped for display/clipboard but preserved in the file.
- Empty lines in the source produce blank lines in the review panels and are skipped during navigation.
- The `---SEPERATOR---` marker must be present; files without it are rejected.

### Platform notes

| Feature | Linux | macOS | Windows |
|---|---|---|---|
| TTS | espeak-ng voices (limited JP/CN) | AVSpeechSynthesizer via pyttsx3 | SAPI5 voices |
| Spellcheck | needs `libenchant-2` | needs `enchant` via Homebrew | needs `pyenchant` wheel |
| Clipboard | works via Qt | works via Qt | works via Qt |

### Packaging

- Use **PyInstaller** to produce a single-folder distribution:
  ```
  pyinstaller --name "TranslationAssistant" \
              --windowed \
              --icon translation_assistant/resources/TA.ico \
              translation_assistant/main.py
  ```
- Include the `Profile/` directory in the bundle via `--add-data "Profile:Profile"`.
- Test the packaged binary on a clean machine.

### Acceptance criteria
- All checklist items pass.
- Application launches from the PyInstaller bundle without a Python installation.

---

## Dependency Reference

```
PySide6>=6.6         # Qt6 GUI framework
pyttsx3>=2.90        # cross-platform TTS
pyenchant>=3.2       # spellcheck (requires system enchant)
PyInstaller>=6.0     # packaging (dev dependency)
pytest>=8.0          # testing (dev dependency)
```

---

## Notes & Known Gaps vs Original

1. **Auto-save timer** (`tmrAutoSave`) exists in the settings but the original VB code does not wire it up. Port should implement it properly: save every N minutes when a file is open and the translated array has changed.
2. **Spellcheck on Linux** requires `libenchant-2-dev` and a language pack (e.g., `hunspell-en-us`) to be installed system-wide.
3. **Font** — The original uses `Microsoft YaHei` (a CJK font). The Python port should set a fallback font list: `["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"]` to ensure CJK characters render on all platforms.
4. **`.lex` format** — WPF's `.lex` requires `#LID 1033` as the first line. The Python custom dictionary does not need this; the port can safely ignore it on read and omit it on write.
5. **TTS voice names** — The original hardcodes Microsoft Server Speech voice names. The port should do a best-effort match on locale (`ja-JP`, `zh-CN`) rather than exact name matching.
