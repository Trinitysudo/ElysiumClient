@echo off
echo ===========================================
echo     Elysium Application Launcher
echo ===========================================

REM 1. Check for Python
echo.
echo 🔎 Checking for Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
echo ❌ Python is not found.
echo Please install Python 3.6 or higher from https://www.python.org/downloads/
echo Make sure to check the "Add Python to PATH" option during installation.
echo.
pause
exit
)
echo ✅ Python is found.

REM 2. Install dependencies
echo.
echo 📦 Installing required libraries...
pip install eel keyboard mss pywin32 Pillow opencv-python numpy pyautogui
if %errorlevel% neq 0 (
echo ❌ Failed to install dependencies. Check your internet connection.
echo You may need to run this script as an administrator.
echo.
pause
exit
)
echo ✅ All dependencies are installed.

REM 3. Run the main application
echo.
echo 🚀 Launching Elysium...
start "" /B python app.py
exit