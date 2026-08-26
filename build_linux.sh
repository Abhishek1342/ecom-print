#!/usr/bin/env bash
# =============================================================================
# build_linux.sh — Build the Linux executable for InvoicePrinter
# =============================================================================
# Requirements (install manually if not present):
#   pip install PyMuPDF Pillow customtkinter tkinterdnd2 pyinstaller
#
# Usage:
#   chmod +x build_linux.sh
#   ./build_linux.sh
# =============================================================================
set -e

PYTHON=${PYTHON:-python3}
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== InvoicePrinter — Linux Build ==="
echo "Project: $PROJECT_DIR"
echo "Python : $($PYTHON --version)"
echo ""

# ── Check required packages ──────────────────────────────────────────────────
check_pkg() {
    $PYTHON -c "import $1" 2>/dev/null && echo "  ✔ $1" || { echo "  ✘ $1 NOT FOUND — run: pip install $2"; MISSING=1; }
}

echo "Checking dependencies..."
MISSING=0
check_pkg fitz      PyMuPDF
check_pkg PIL       Pillow
check_pkg customtkinter customtkinter
check_pkg tkinterdnd2  tkinterdnd2
check_pkg PyInstaller  pyinstaller

if [ "$MISSING" = "1" ]; then
    echo ""
    echo "ERROR: Missing packages. Install them with:"
    echo "  pip install PyMuPDF Pillow customtkinter tkinterdnd2 pyinstaller"
    exit 1
fi

echo ""
echo "=== Cleaning previous build ==="
rm -rf "$PROJECT_DIR/build" "$PROJECT_DIR/dist"

echo "=== Running PyInstaller ==="
cd "$PROJECT_DIR"
$PYTHON -m PyInstaller ecom_print.spec

echo ""
echo "✅ Build complete!"
echo "   Executable: $PROJECT_DIR/dist/InvoicePrinter"
echo ""
echo "NOTE: On Linux, printing to printer is not supported (Windows-only feature)."
echo "      The 'Save as PDF' button works on all platforms."
