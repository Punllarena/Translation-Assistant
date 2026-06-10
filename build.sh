#!/usr/bin/env bash
# Build script for Translation Assistant.
# Runs the test suite, then produces dist/TranslationAssistant/ via PyInstaller.
#
# Usage:
#   ./build.sh          — test + build
#   ./build.sh --skip-tests  — build only (for iterating on the spec)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
elif [[ -f "venv/bin/activate" ]]; then
    source venv/bin/activate
else
    echo "ERROR: no .venv or venv directory found. Run: python3 -m venv .venv && pip install -r requirements-dev.txt"
    exit 1
fi

# ── Optional dependency checks ────────────────────────────────────────────────
echo "=== Checking optional dependencies ==="

if python -c "import fugashi" 2>/dev/null; then
    echo "  MeCab (fugashi): OK"
else
    echo "  MeCab (fugashi): NOT INSTALLED — MeCab panel will show setup prompt"
    echo "    To enable: pip install fugashi unidic-lite"
fi

if [[ -f "dictionaries/edict2" ]]; then
    echo "  JParser (edict2): OK"
else
    echo "  JParser (edict2): NOT FOUND — JParser panel will show setup prompt"
    echo "    To enable: download edict2 from https://www.edrdg.org/jmdict/edict.html"
    echo "                place it at dictionaries/edict2"
fi
echo ""

# ── Test ──────────────────────────────────────────────────────────────────────
if [[ "${1:-}" != "--skip-tests" ]]; then
    echo "=== Running test suite ==="
    python -m pytest -q
    echo ""
fi

# ── Build ─────────────────────────────────────────────────────────────────────
# Preserve ta.db across the build — PyInstaller --noconfirm wipes the output dir
DB_BACKUP=""
if [[ -f "dist/TranslationAssistant/ta.db" ]]; then
    DB_BACKUP="$(mktemp --suffix=.db)"
    cp "dist/TranslationAssistant/ta.db" "$DB_BACKUP"
    echo "=== Backed up ta.db before build ==="
fi

echo "=== Building with PyInstaller ==="
pyinstaller translation_assistant.spec --clean --noconfirm

if [[ -n "$DB_BACKUP" ]]; then
    cp "$DB_BACKUP" "dist/TranslationAssistant/ta.db"
    rm "$DB_BACKUP"
    echo "=== Restored ta.db after build ==="
fi

echo ""
echo "=== Build complete ==="
echo "Output: dist/TranslationAssistant/"
echo ""

# Quick sanity: verify the executable exists
if [[ -f "dist/TranslationAssistant/TranslationAssistant" ]]; then
    echo "Executable: dist/TranslationAssistant/TranslationAssistant  ✓"
elif [[ -f "dist/TranslationAssistant/TranslationAssistant.exe" ]]; then
    echo "Executable: dist/TranslationAssistant/TranslationAssistant.exe  ✓"
else
    echo "WARNING: expected executable not found in dist/TranslationAssistant/"
fi
