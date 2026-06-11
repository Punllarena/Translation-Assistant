# Onboarding Wizard + Release Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-launch setup guide dialog for MeCab and JParser, and GitHub Actions CI that produces an AppImage (Linux) and NSIS installer (Windows) on version tag push.

**Architecture:** The wizard is a new `QDialog` (`dlg_setup.py`) that detects tool availability and shows platform-specific install instructions. It triggers once on first launch via an `AppSettings` boolean flag and is re-accessible from a new Help menu. The release pipeline uses two GitHub Actions jobs: one on Ubuntu producing an AppImage via `appimagetool`, one on Windows producing an NSIS `.exe` via `makensis`.

**Tech Stack:** PySide6 (QDialog, QDesktopServices), PyInstaller, appimagetool (AppImage), NSIS (Windows installer), GitHub Actions.

---

> **Note:** The wizard (Tasks 1–6) and release pipeline (Tasks 7–10) are fully independent — they can be implemented in any order or in parallel.

---

## File Map

**Wizard:**
- Modify: `translation_assistant/settings.py` — add `setup_wizard_shown` bool property
- Create: `translation_assistant/ui/dlg_setup.py` — `SetupGuideDialog` QDialog
- Modify: `translation_assistant/main.py` — first-launch trigger
- Modify: `translation_assistant/ui/combined_window.py` — new Help menu
- Modify: `ta/translators/mecab.py` — add Setup Guide hint to error HTML
- Modify: `ta/translators/jparser.py` — add Setup Guide hint to error HTML

**Release:**
- Create: `appimage/AppRun` — shell launcher for AppImage
- Create: `appimage/TranslationAssistant.desktop` — XDG desktop entry
- Create: `appimage/TranslationAssistant.png` — fallback icon
- Create: `installer.nsi` — NSIS Windows installer script
- Create: `.github/workflows/release.yml` — CI workflow

---

## Task 1: Add setup_wizard_shown to AppSettings

**Files:**
- Modify: `translation_assistant/settings.py` (after `tm_visible` property, ~line 136)
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py`:

```python
def test_default_setup_wizard_shown(tmp_settings):
    assert tmp_settings.setup_wizard_shown is False


def test_setup_wizard_shown_roundtrip(tmp_settings):
    tmp_settings.setup_wizard_shown = True
    assert tmp_settings.setup_wizard_shown is True


def test_setup_wizard_shown_reset(tmp_settings):
    tmp_settings.setup_wizard_shown = True
    tmp_settings.setup_wizard_shown = False
    assert tmp_settings.setup_wizard_shown is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source .venv/bin/activate && pytest tests/test_settings.py::test_default_setup_wizard_shown tests/test_settings.py::test_setup_wizard_shown_roundtrip tests/test_settings.py::test_setup_wizard_shown_reset -v
```

Expected: FAIL — `AttributeError: 'AppSettings' object has no attribute 'setup_wizard_shown'`

- [ ] **Step 3: Add the property to AppSettings**

In `translation_assistant/settings.py`, add after the `tm_visible` setter (~line 136), before the `last_doc_id` property:

```python
    # --- setup wizard shown ---

    @property
    def setup_wizard_shown(self) -> bool:
        return self._qs.value("SetupWizardShown", False, type=bool)

    @setup_wizard_shown.setter
    def setup_wizard_shown(self, value: bool) -> None:
        self._qs.setValue("SetupWizardShown", value)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_settings.py::test_default_setup_wizard_shown tests/test_settings.py::test_setup_wizard_shown_roundtrip tests/test_settings.py::test_setup_wizard_shown_reset -v
```

Expected: 3 PASSED

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```

Expected: all green

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/settings.py tests/test_settings.py
git commit -m "feat(settings): add setup_wizard_shown property"
```

---

## Task 2: Create SetupGuideDialog

**Files:**
- Create: `translation_assistant/ui/dlg_setup.py`
- Modify: `tests/test_dialogs.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dialogs.py` (after the existing import block and before the first test class):

```python
# ---------------------------------------------------------------------------
# SetupGuideDialog
# ---------------------------------------------------------------------------

class TestSetupGuideDialog:
    def test_instantiates(self, qapp):
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        dlg = SetupGuideDialog()
        assert dlg.windowTitle() == "Setup Guide — Optional Tools"

    def test_has_close_button(self, qapp):
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        from PySide6.QtWidgets import QDialogButtonBox
        dlg = SetupGuideDialog()
        bb = dlg.findChild(QDialogButtonBox)
        assert bb is not None
        assert bb.button(QDialogButtonBox.StandardButton.Close) is not None

    def test_has_mecab_group(self, qapp):
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        from PySide6.QtWidgets import QGroupBox
        dlg = SetupGuideDialog()
        titles = [g.title() for g in dlg.findChildren(QGroupBox)]
        assert any("MeCab" in t for t in titles)

    def test_has_jparser_group(self, qapp):
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        from PySide6.QtWidgets import QGroupBox
        dlg = SetupGuideDialog()
        titles = [g.title() for g in dlg.findChildren(QGroupBox)]
        assert any("JParser" in t for t in titles)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dialogs.py::TestSetupGuideDialog -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'translation_assistant.ui.dlg_setup'`

- [ ] **Step 3: Create dlg_setup.py**

Create `translation_assistant/ui/dlg_setup.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from translation_assistant.settings import _get_app_root
from ta.translators.mecab import MeCabTranslator
from ta.translators.jparser import JParserTranslator

_EDRDG_URL = "https://www.edrdg.org/jmdict/edict.html"


class SetupGuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Setup Guide — Optional Tools")
        self.setMinimumWidth(520)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(self._build_mecab_group())
        layout.addWidget(self._build_jparser_group())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _status_label(self, available: bool) -> QLabel:
        if available:
            lbl = QLabel("✓ Installed")
            lbl.setStyleSheet("color: green; font-weight: bold;")
        else:
            lbl = QLabel("✗ Not installed")
            lbl.setStyleSheet("color: red; font-weight: bold;")
        return lbl

    def _build_mecab_group(self) -> QGroupBox:
        available = MeCabTranslator.is_available()
        box = QGroupBox("MeCab — Morphological Analysis")
        layout = QVBoxLayout(box)
        layout.addWidget(self._status_label(available))
        if not available:
            layout.addWidget(QLabel("Install via pip:"))
            cmd_row = QHBoxLayout()
            cmd_edit = QLineEdit("pip install fugashi unidic-lite")
            cmd_edit.setReadOnly(True)
            copy_btn = QPushButton("Copy")
            copy_btn.setMaximumWidth(60)
            copy_btn.clicked.connect(
                lambda: QApplication.clipboard().setText(cmd_edit.text())
            )
            cmd_row.addWidget(cmd_edit)
            cmd_row.addWidget(copy_btn)
            layout.addLayout(cmd_row)
            if sys.platform.startswith("win"):
                note = "Run this in the same Python environment used to launch the app."
            else:
                note = "No system MeCab library needed — fugashi includes its own."
            lbl = QLabel(note)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
        return box

    def _build_jparser_group(self) -> QGroupBox:
        available = JParserTranslator.is_available()
        box = QGroupBox("JParser — Japanese Dictionary")
        layout = QVBoxLayout(box)
        layout.addWidget(self._status_label(available))
        if not available:
            instr = QLabel(
                "1. Download edict2 from edrdg.org\n"
                "2. Extract the .gz file to get edict2\n"
                "3. Place edict2 in the dictionaries/ folder next to the app"
            )
            instr.setWordWrap(True)
            layout.addWidget(instr)
            btn_row = QHBoxLayout()
            visit_btn = QPushButton("Visit edrdg.org")
            visit_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(_EDRDG_URL))
            )
            btn_row.addWidget(visit_btn)
            dict_dir = _get_app_root() / "dictionaries"
            dict_dir.mkdir(exist_ok=True)
            open_btn = QPushButton("Open dictionaries folder")
            open_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(dict_dir)))
            )
            btn_row.addWidget(open_btn)
            layout.addLayout(btn_row)
        return box
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_dialogs.py::TestSetupGuideDialog -v
```

Expected: 4 PASSED

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```

Expected: all green

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/dlg_setup.py tests/test_dialogs.py
git commit -m "feat(ui): add SetupGuideDialog for MeCab and JParser setup"
```

---

## Task 3: First-launch trigger in main.py

**Files:**
- Modify: `translation_assistant/main.py`

No unit tests — `main.py` is the entry point; verified in the manual smoke test (Task 6).

- [ ] **Step 1: Add trigger after window.show()**

In `translation_assistant/main.py`, the current `main()` body is:

```python
def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Translation Assistant")
    app.setOrganizationName("joeglens")

    settings = AppSettings()
    db = Database(settings.db_path)
    run_startup_migration(profile_dir=_get_app_root() / "Profile", db=db)

    window = CombinedMainWindow(_settings=settings, _db=db)
    window.show()
    sys.exit(app.exec())
```

Replace with:

```python
def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Translation Assistant")
    app.setOrganizationName("joeglens")

    settings = AppSettings()
    db = Database(settings.db_path)
    run_startup_migration(profile_dir=_get_app_root() / "Profile", db=db)

    window = CombinedMainWindow(_settings=settings, _db=db)
    window.show()

    if not settings.setup_wizard_shown:
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        settings.setup_wizard_shown = True
        SetupGuideDialog(window).exec()

    sys.exit(app.exec())
```

- [ ] **Step 2: Run full suite to verify no regressions**

```bash
pytest -q
```

Expected: all green

- [ ] **Step 3: Commit**

```bash
git add translation_assistant/main.py
git commit -m "feat(main): show setup guide on first launch"
```

---

## Task 4: Add Help menu to CombinedMainWindow

**Files:**
- Modify: `translation_assistant/ui/combined_window.py`
- Modify: `tests/test_dialogs.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dialogs.py` (after `TestSetupGuideDialog`):

```python
class TestCombinedWindowHelpMenu:
    def test_has_help_menu(self, qapp, tmp_path):
        import sqlite3
        from translation_assistant.ui.combined_window import CombinedMainWindow
        from translation_assistant.db import Database
        conn = sqlite3.connect(":memory:")
        db = Database(":memory:", _conn=conn)
        db.create_profile("Default", is_default=True)
        settings = make_settings(tmp_path)
        window = CombinedMainWindow(_settings=settings, _db=db)
        menu_titles = [a.text() for a in window.menuBar().actions()]
        assert "Help" in menu_titles
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_dialogs.py::TestCombinedWindowHelpMenu -v
```

Expected: FAIL — `AssertionError: assert 'Help' in ['File', 'Settings', 'Special Punctuations', 'View', 'Clipboard', 'Tools']`

- [ ] **Step 3: Add Help menu to _setup_menubar**

In `translation_assistant/ui/combined_window.py`, at the end of `_setup_menubar` (after the Tools menu block, before the method closes), add:

```python
        # Help
        help_menu = mb.addMenu("Help")
        setup_guide_action = QAction("Setup Guide…", self)
        setup_guide_action.triggered.connect(self._open_setup_guide)
        help_menu.addAction(setup_guide_action)
```

Add the handler method to `CombinedMainWindow` (after `_toggle_topmost`):

```python
    def _open_setup_guide(self) -> None:
        from translation_assistant.ui.dlg_setup import SetupGuideDialog
        SetupGuideDialog(self).exec()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_dialogs.py::TestCombinedWindowHelpMenu -v
```

Expected: PASS

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```

Expected: all green

- [ ] **Step 6: Commit**

```bash
git add translation_assistant/ui/combined_window.py tests/test_dialogs.py
git commit -m "feat(ui): add Help → Setup Guide menu item"
```

---

## Task 5: Improve inline error HTML

**Files:**
- Modify: `ta/translators/mecab.py` (lines 110–116)
- Modify: `ta/translators/jparser.py` (lines 395–405)

- [ ] **Step 1: Update mecab.py _err_html**

In `ta/translators/mecab.py`, replace the `_err_html` static method (currently lines 110–116):

```python
    @staticmethod
    def _err_html(detail: str) -> str:
        return (
            '<html><body style="background:#282a36;color:#ff5555;'
            'font-family:monospace;font-size:11pt;margin:8px">'
            f'<b>MeCab unavailable.</b><br><br>{detail}'
            '<br><br><span style="color:#6272a4">See <b>Help → Setup Guide</b> for instructions.</span>'
            '</body></html>'
        )
```

- [ ] **Step 2: Update jparser.py missing-dict return**

In `ta/translators/jparser.py`, replace the `return` block in `_do_translate` when `self._index is None` (currently lines 397–405):

```python
        if self._index is None:
            return (
                '<html><body style="background:#282a36;color:#ff5555;'
                'font-family:monospace;font-size:11pt;margin:8px">'
                '<b>JParser: no dictionary found.</b><br><br>'
                'Download <code>edict2</code> from '
                '<a href="https://www.edrdg.org/jmdict/edict.html" style="color:#8be9fd">edrdg.org</a>'
                ' and place it in <code>dictionaries/edict2</code>'
                '<br><br><span style="color:#6272a4">See <b>Help → Setup Guide</b> for instructions.</span>'
                '</body></html>'
            )
```

- [ ] **Step 3: Run full suite**

```bash
pytest -q
```

Expected: all green

- [ ] **Step 4: Commit**

```bash
git add ta/translators/mecab.py ta/translators/jparser.py
git commit -m "feat(translators): add Setup Guide hint to MeCab and JParser error messages"
```

---

## Task 6: Manual smoke test of wizard

- [ ] **Step 1: Reset the setup_wizard_shown flag**

```bash
source .venv/bin/activate
python -c "
from PySide6.QtCore import QSettings
qs = QSettings('joeglens', 'TranslationAssistant')
qs.remove('SetupWizardShown')
qs.sync()
print('Flag cleared')
"
```

Expected output: `Flag cleared`

- [ ] **Step 2: Launch app — wizard should appear**

```bash
python -m translation_assistant.main
```

Expected: Setup Guide dialog opens on top of main window. Verify:
- MeCab section shows correct status (✓ or ✗ depending on whether fugashi is installed)
- JParser section shows correct status (✓ if `dictionaries/edict2` exists, ✗ if not)
- If JParser ✗: "Open dictionaries folder" button opens a file manager
- "Visit edrdg.org" button opens the browser
- Close button dismisses dialog; main window is usable afterward

- [ ] **Step 3: Relaunch — wizard should NOT appear**

Close and relaunch:

```bash
python -m translation_assistant.main
```

Expected: No dialog — main window opens directly.

- [ ] **Step 4: Verify Help → Setup Guide**

With app running, click `Help → Setup Guide`. Expected: dialog opens. Close and reopen — works every time.

---

## Task 7: AppImage packaging assets

**Files:**
- Create: `appimage/AppRun`
- Create: `appimage/TranslationAssistant.desktop`
- Create: `appimage/TranslationAssistant.png`

These are packaging assets; verification is in Task 10 (CI run).

- [ ] **Step 1: Create appimage/AppRun**

Create `appimage/AppRun`:

```bash
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "$HERE/usr/bin/TranslationAssistant/TranslationAssistant" "$@"
```

- [ ] **Step 2: Create appimage/TranslationAssistant.desktop**

Create `appimage/TranslationAssistant.desktop`:

```ini
[Desktop Entry]
Name=Translation Assistant
Exec=TranslationAssistant
Icon=TranslationAssistant
Type=Application
Categories=Utility;
```

- [ ] **Step 3: Create fallback PNG icon**

The CI step converts `TA.ico` to PNG via ImageMagick. This fallback PNG is used if that conversion fails.

```bash
python - <<'EOF'
import struct, zlib

def write_png(path):
    w, h = 64, 64
    # #282a36 opaque RGBA
    pixel = b'\x28\x2a\x36\xff'
    raw = b''.join(b'\x00' + pixel * w for _ in range(h))
    compressed = zlib.compress(raw, 9)

    def chunk(name, data):
        c = struct.pack('>I', len(data)) + name + data
        return c + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', ihdr)
           + chunk(b'IDAT', compressed)
           + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)
    print(f"Created {path}")

write_png("appimage/TranslationAssistant.png")
EOF
```

Expected output: `Created appimage/TranslationAssistant.png`

- [ ] **Step 4: Commit**

```bash
git add appimage/
git commit -m "feat(appimage): add AppImage packaging assets"
```

---

## Task 8: NSIS installer script

**Files:**
- Create: `installer.nsi`

- [ ] **Step 1: Create installer.nsi**

Create `installer.nsi` at repo root:

```nsis
!include "MUI2.nsh"

Name "Translation Assistant"
OutFile "TranslationAssistant-Setup.exe"
InstallDir "$PROGRAMFILES\TranslationAssistant"
InstallDirRegKey HKCU "Software\TranslationAssistant" ""

RequestExecutionLevel admin

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "MainSection" SEC01
    SetOutPath "$INSTDIR"
    File /r "dist\TranslationAssistant\*.*"

    CreateDirectory "$SMPROGRAMS\Translation Assistant"
    CreateShortCut "$SMPROGRAMS\Translation Assistant\Translation Assistant.lnk" "$INSTDIR\TranslationAssistant.exe" "" "$INSTDIR\TranslationAssistant.exe"
    CreateShortCut "$DESKTOP\Translation Assistant.lnk" "$INSTDIR\TranslationAssistant.exe" "" "$INSTDIR\TranslationAssistant.exe"

    WriteUninstaller "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationAssistant" \
        "DisplayName" "Translation Assistant"
    WriteRegStr HKCU \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationAssistant" \
        "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationAssistant" \
        "DisplayVersion" "1.0"
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\Translation Assistant\Translation Assistant.lnk"
    RMDir "$SMPROGRAMS\Translation Assistant"
    Delete "$DESKTOP\Translation Assistant.lnk"
    DeleteRegKey HKCU \
        "Software\Microsoft\Windows\CurrentVersion\Uninstall\TranslationAssistant"
SectionEnd
```

- [ ] **Step 2: Commit**

```bash
git add installer.nsi
git commit -m "feat(release): add NSIS installer script for Windows"
```

---

## Task 9: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Create release.yml**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build-linux:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install system dependencies
        run: sudo apt-get install -y libenchant-2-dev hunspell-en-us imagemagick

      - name: Install Python dependencies
        run: pip install -r requirements.txt fugashi unidic-lite

      - name: Build with PyInstaller
        run: ./build.sh --skip-tests

      - name: Extract version from tag
        id: version
        run: echo "VERSION=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT

      - name: Assemble AppDir
        run: |
          mkdir -p AppDir/usr/bin
          cp -r dist/TranslationAssistant AppDir/usr/bin/TranslationAssistant
          cp appimage/AppRun AppDir/AppRun
          chmod +x AppDir/AppRun
          cp appimage/TranslationAssistant.desktop AppDir/TranslationAssistant.desktop
          convert translation_assistant/resources/TA.ico AppDir/TranslationAssistant.png \
            || cp appimage/TranslationAssistant.png AppDir/TranslationAssistant.png

      - name: Download appimagetool
        run: |
          wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
          chmod +x appimagetool-x86_64.AppImage

      - name: Build AppImage
        run: |
          ARCH=x86_64 ./appimagetool-x86_64.AppImage AppDir \
            TranslationAssistant-${{ steps.version.outputs.VERSION }}-x86_64.AppImage

      - name: Upload to GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: TranslationAssistant-${{ steps.version.outputs.VERSION }}-x86_64.AppImage
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Python dependencies
        run: pip install -r requirements.txt fugashi unidic-lite

      - name: Extract version from tag
        id: version
        shell: bash
        run: echo "VERSION=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT

      - name: Stamp version
        shell: bash
        run: |
          sed -i "s/^BUILD_DATE = .*/BUILD_DATE = \"${{ steps.version.outputs.VERSION }}\"/" \
            translation_assistant/_version.py

      - name: Build with PyInstaller
        run: pyinstaller translation_assistant.spec --noconfirm

      - name: Install NSIS
        run: choco install nsis --no-progress -y

      - name: Build installer
        run: makensis installer.nsi

      - name: Rename installer with version
        shell: bash
        run: |
          mv TranslationAssistant-Setup.exe \
            TranslationAssistant-${{ steps.version.outputs.VERSION }}-Setup.exe

      - name: Upload to GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: TranslationAssistant-${{ steps.version.outputs.VERSION }}-Setup.exe
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat(ci): add GitHub Actions release workflow for AppImage and NSIS installer"
```

---

## Task 10: Trigger a test release

- [ ] **Step 1: Verify GitHub remote**

```bash
git remote -v
```

If no remote exists, push to GitHub first:

```bash
git remote add origin https://github.com/<your-username>/TranslationAssistant-PySide6-Port.git
git push -u origin main
```

- [ ] **Step 2: Push a release tag**

```bash
git tag v2026.06.11
git push origin v2026.06.11
```

- [ ] **Step 3: Monitor CI**

Go to `https://github.com/<your-username>/TranslationAssistant-PySide6-Port/actions`.

Expected: both `build-linux` and `build-windows` jobs succeed. Under the auto-created release for tag `v2026.06.11`, two artifacts appear:
- `TranslationAssistant-2026.06.11-x86_64.AppImage`
- `TranslationAssistant-2026.06.11-Setup.exe`
