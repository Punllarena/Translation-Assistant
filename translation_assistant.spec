# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Translation Assistant.

Single-folder distribution (COLLECT, not onefile) so the Profile/
directory is easy to update without rebuilding.

Tested on Linux x86-64 with PySide6 6.11, pyenchant 3.3, pyttsx3 2.99.
Platform-specific sections are marked; adjust for macOS / Windows.
"""

import os
import sys
from pathlib import Path

block_cipher = None
HERE = Path(SPECPATH)           # directory containing this .spec file


# ---------------------------------------------------------------------------
# enchant system libraries (Linux)
# ---------------------------------------------------------------------------
# On macOS: enchant is usually in /usr/local/lib or /opt/homebrew/lib
# On Windows: enchant ships as a wheel bundle; collect_dynamic_libs works.

def _collect_enchant_linux():
    binaries = []
    datas = []

    # Main enchant shared library
    import ctypes.util
    lib = ctypes.util.find_library("enchant-2")
    if lib:
        import ctypes
        try:
            full = ctypes.cdll.LoadLibrary(lib)._name
        except Exception:
            full = f"/lib/x86_64-linux-gnu/{lib}"
        if os.path.exists(full):
            binaries.append((full, "."))

    # enchant backend plugins (hunspell, aspell, …)
    plugin_dirs = [
        "/usr/lib/x86_64-linux-gnu/enchant-2",
        "/usr/lib/enchant-2",
        "/usr/local/lib/enchant-2",
    ]
    for d in plugin_dirs:
        if os.path.isdir(d):
            for f in Path(d).glob("*.so"):
                binaries.append((str(f), "enchant-2"))
            break

    # Hunspell English dictionary (required for en_US spell-check)
    dict_dirs = [
        "/usr/share/hunspell",
        "/usr/share/myspell",
        "/usr/local/share/hunspell",
    ]
    for d in dict_dirs:
        for ext in ("en_US.aff", "en_US.dic"):
            path = os.path.join(d, ext)
            if os.path.exists(path):
                datas.append((path, "enchant/data"))

    return binaries, datas


if sys.platform.startswith("linux"):
    _enchant_bins, _enchant_datas = _collect_enchant_linux()
else:
    # macOS / Windows: pyenchant wheels self-contain the library; use hooks.
    try:
        from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
        _enchant_datas = collect_data_files("enchant")
        _enchant_bins = collect_dynamic_libs("enchant")
    except Exception:
        _enchant_datas = []
        _enchant_bins = []


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

_extra_datas = []

# Optional: JParser edict2 dictionary
_dict_dir = HERE / "dictionaries"
if _dict_dir.is_dir():
    _extra_datas.append((str(_dict_dir), "dictionaries"))

a = Analysis(
    [str(HERE / "translation_assistant" / "main.py")],
    pathex=[str(HERE)],
    binaries=_enchant_bins,
    datas=[
        # Application icon
        (str(HERE / "translation_assistant" / "resources" / "TA.ico"),
         "translation_assistant/resources"),
        # Default profiles shipped with the app
        (str(HERE / "Profile"), "Profile"),
        *_enchant_datas,
        *_extra_datas,
    ],
    hiddenimports=[
        # pyttsx3 discovers its drivers at runtime
        "pyttsx3",
        "pyttsx3.drivers",
        "pyttsx3.drivers.espeak",   # Linux
        "pyttsx3.drivers.nsss",     # macOS
        "pyttsx3.drivers.sapi5",    # Windows
        # enchant
        "enchant",
        "enchant.checker",
        "enchant.tokenize",
        "enchant.tokenize.en",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the bundle small — these are unused
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "PIL",
        "cv2",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TranslationAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                          # no console window
    icon=str(HERE / "translation_assistant" / "resources" / "TA.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TranslationAssistant",
)
