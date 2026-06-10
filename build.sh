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
# Preserve ta.db across the build — PyInstaller --noconfirm wipes the output dir.
# Checkpoint WAL into the main file first so the backup is self-contained.
DB_BACKUP_DIR=""
if [[ -f "dist/TranslationAssistant/ta.db" ]]; then
    DB_BACKUP_DIR="$(mktemp -d)"
    # Checkpoint WAL into main db (no-op if db is locked by the running app)
    python -c "
import sqlite3
try:
    con = sqlite3.connect('dist/TranslationAssistant/ta.db', timeout=2)
    con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    con.close()
except Exception:
    pass
" 2>/dev/null || true
    # Copy all WAL-related files so nothing is lost even if app is open
    for f in ta.db ta.db-shm ta.db-wal; do
        [[ -f "dist/TranslationAssistant/$f" ]] && cp "dist/TranslationAssistant/$f" "$DB_BACKUP_DIR/$f"
    done
    echo "=== Backed up ta.db before build ==="
fi

echo "=== Stamping build date ==="
BUILD_DATE="$(date +%Y.%m.%d)"
sed -i "s/^BUILD_DATE = .*/BUILD_DATE = \"$BUILD_DATE\"/" translation_assistant/_version.py
echo "  Version: $BUILD_DATE"

echo "=== Building with PyInstaller ==="
pyinstaller translation_assistant.spec --clean --noconfirm

if [[ -n "$DB_BACKUP_DIR" ]]; then
    for f in ta.db ta.db-shm ta.db-wal; do
        [[ -f "$DB_BACKUP_DIR/$f" ]] && cp "$DB_BACKUP_DIR/$f" "dist/TranslationAssistant/$f"
    done
    rm -rf "$DB_BACKUP_DIR"
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
