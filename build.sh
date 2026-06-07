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

# ── Test ──────────────────────────────────────────────────────────────────────
if [[ "${1:-}" != "--skip-tests" ]]; then
    echo "=== Running test suite ==="
    python -m pytest -q
    echo ""
fi

# ── Build ─────────────────────────────────────────────────────────────────────
echo "=== Building with PyInstaller ==="
pyinstaller translation_assistant.spec --clean --noconfirm

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
