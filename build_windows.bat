@echo off
REM =============================================================================
REM build_windows.bat — Build the Windows .exe for InvoicePrinter
REM =============================================================================
REM Requirements (auto-installed by this script):
REM   Python 3.10+ must be installed and on PATH.
REM   Internet connection needed on first run.
REM
REM Usage: Double-click this file, or run from Command Prompt / PowerShell.
REM =============================================================================
setlocal enabledelayedexpansion

echo === InvoicePrinter — Windows Build ===
echo.

REM Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH.
    echo Install Python 3.10+ from https://python.org and add it to PATH.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Python: %%v
echo.

REM Install / upgrade packages
echo === Installing dependencies ===
python -m pip install --upgrade pip --quiet
python -m pip install PyMuPDF Pillow customtkinter tkinterdnd2 pyinstaller pywin32 --quiet
if errorlevel 1 (
    echo ERROR: Package installation failed. Check your internet connection.
    pause
    exit /b 1
)
echo   Done.
echo.

REM Clean previous build
echo === Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
echo   Done.
echo.

REM Build
echo === Running PyInstaller ===
python -m PyInstaller ecom_print.spec
if errorlevel 1 (
    echo ERROR: PyInstaller failed. Check the output above for details.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete!
echo  Executable: dist\InvoicePrinter.exe
echo ============================================================
echo.
pause
