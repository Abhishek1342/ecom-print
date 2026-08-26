# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ecom-print.
Works for both Linux and Windows — run from the correct OS to get that platform's binary.

Usage:
  Linux : pyinstaller ecom_print.spec
  Windows: pyinstaller ecom_print.spec
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Collect data files from third-party packages ─────────────────────────────
datas = []

# customtkinter ships its themes and images as data files
datas += collect_data_files("customtkinter")

# tkinterdnd2 ships native .so / .dll files as data
datas += collect_data_files("tkinterdnd2")

# Bundle config.json next to the exe
datas += [("config.json", ".")]

# ── Hidden imports ─────────────────────────────────────────────────────────────
hidden_imports = [
    "PIL._tkinter_finder",
    "fitz",
]

# Windows-only printing
if sys.platform == "win32":
    hidden_imports += ["win32print", "win32ui", "win32con", "PIL.ImageWin"]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pandas", "jupyter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="InvoicePrinter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                  # No terminal window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows-only icon (ignored on Linux)
    icon=None,
)
