# Onboarding Wizard + Release Packaging Design

**Date:** 2026-06-11

## Overview

Two related features:
1. A first-launch setup guide dialog directing new users to install MeCab and JParser.
2. GitHub Actions CI producing platform installers (AppImage for Linux, NSIS `.exe` for Windows) on version tag push.

MeCab and JParser are intentionally **not bundled** in releases — they are optional, licensed separately, and users install them post-download.

---

## Part 1: Setup Guide Wizard

### Trigger

- **First launch**: `main.py` checks `settings.setup_wizard_shown` (new `bool` property on `AppSettings`) after `window.show()`. If False, opens `SetupGuideDialog`, then sets `settings.setup_wizard_shown = True`.
- **Re-open**: `Help → Setup Guide` menu item in `combined_window.py` opens it anytime. (Help menu is new — `combined_window.py` currently has File and Settings menus only.)

### New file: `translation_assistant/ui/dlg_setup.py`

Class: `SetupGuideDialog(QDialog)`

Single scrollable dialog. Two `QGroupBox` sections, one per tool.

#### MeCab Section

- **Status badge**: calls `MeCabTranslator.is_available()` at open.
  - Installed: green "✓ Installed"
  - Missing: red "✗ Not installed"
- **If missing**: read-only `QLineEdit` containing `pip install fugashi unidic-lite` + Copy button.
- **Platform note** (auto-detected via `sys.platform`):
  - Linux: "No system MeCab library needed — fugashi includes its own."
  - Windows: "Run this command in the same Python environment used to launch the app."

#### JParser Section

- **Status badge**: calls `JParserTranslator.is_available()` at open.
  - Found: green "✓ Dictionary found"
  - Missing: red "✗ Dictionary not found"
- **If missing**: numbered steps:
  1. Click "Visit edrdg.org" (opens browser to the edict2 download page).
  2. Download `edict2.gz` and extract to get `edict2`.
  3. Place `edict2` in the `dictionaries/` folder next to the app.
- **"Open dictionaries folder"** button: `QDesktopServices.openUrl(QUrl.fromLocalFile(path))` — path is `_get_app_root() / "dictionaries"` (module-level function imported from `translation_assistant.settings`), created if missing.
- **"Visit edrdg.org"** button: opens `https://www.edrdg.org/jmdict/edict.html` in browser.

#### Footer

- Single **Close** button.
- No "don't show again" checkbox — dialog only auto-shows once; subsequent opens are via Help menu.

### Changes to existing files

| File | Change |
|------|--------|
| `translation_assistant/main.py` | Check `setup_wizard_shown` flag after `window.show()`; open dialog if False; set True. |
| `translation_assistant/ui/combined_window.py` | Add `Help → Setup Guide` menu action. |
| `translation_assistant/settings.py` | Add `setup_wizard_shown` typed bool property. |
| `ta/translators/mecab.py` | Append `"See Help → Setup Guide for instructions."` to `_err_html()`. |
| `ta/translators/jparser.py` | Append `"See Help → Setup Guide for instructions."` to the missing-dict error HTML. |

---

## Part 2: Release Packaging

### Tag convention

Format: `v<YYYY.MM.DD>` (e.g. `v2026.06.11`). Matches the existing `BUILD_DATE` pattern in `_version.py`. The build script already stamps `_version.py` from the current date; the workflow extracts the version from the git tag.

### New file: `.github/workflows/release.yml`

Triggers on `push` to tags matching `v*`. Two parallel jobs.

#### `build-linux` (`ubuntu-22.04`)

1. Install system deps: `sudo apt-get install -y libenchant-2-dev hunspell-en-us`
2. `pip install -r requirements.txt fugashi unidic-lite`
3. `./build.sh --skip-tests` → `dist/TranslationAssistant/`
4. Assemble `AppDir/`:
   - `AppDir/AppRun` (shell script, see below)
   - `AppDir/TranslationAssistant.desktop`
   - `AppDir/TranslationAssistant.png` (copy of `translation_assistant/resources/TA.ico` converted to PNG, or placeholder)
   - `AppDir/usr/bin/` → symlink or copy of PyInstaller output
5. Download `appimagetool-x86_64.AppImage` from GitHub (linuxdeploy/appimagetool releases).
6. `chmod +x appimagetool && ./appimagetool AppDir TranslationAssistant-x86_64.AppImage`
7. Upload `TranslationAssistant-x86_64.AppImage` to GitHub Release via `softprops/action-gh-release`.

#### `build-windows` (`windows-latest`)

1. `pip install -r requirements.txt fugashi unidic-lite`
2. `pyinstaller translation_assistant.spec --noconfirm` → `dist\TranslationAssistant\`
3. Stamp `_version.py` with tag date (same logic as `build.sh`).
4. `choco install nsis --no-progress`
5. `makensis installer.nsi` → `TranslationAssistant-Setup.exe`
6. Upload `TranslationAssistant-Setup.exe` to GitHub Release.

### New file: `appimage/AppRun`

```bash
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "$HERE/usr/bin/TranslationAssistant/TranslationAssistant" "$@"
```

### New file: `appimage/TranslationAssistant.desktop`

```ini
[Desktop Entry]
Name=Translation Assistant
Exec=TranslationAssistant
Icon=TranslationAssistant
Type=Application
Categories=Utility;
```

### New file: `installer.nsi`

NSIS script covering:
- `InstallDir "$PROGRAMFILES\TranslationAssistant"`
- Install all files from `dist\TranslationAssistant\`
- Create Start Menu shortcut
- Write uninstaller to install dir
- `Section "Uninstall"` removes all installed files and shortcut

---

## File Summary

| File | Status |
|------|--------|
| `translation_assistant/ui/dlg_setup.py` | New |
| `.github/workflows/release.yml` | New |
| `installer.nsi` | New |
| `appimage/AppRun` | New |
| `appimage/TranslationAssistant.desktop` | New |
| `translation_assistant/main.py` | Modified |
| `translation_assistant/ui/combined_window.py` | Modified |
| `translation_assistant/settings.py` | Modified (maybe) |
| `ta/translators/mecab.py` | Modified |
| `ta/translators/jparser.py` | Modified |

---

## Out of Scope

- Bundling MeCab/fugashi or edict2 inside the release artifacts.
- macOS builds.
- Auto-update mechanism.
- Code-signing of Windows installer.
