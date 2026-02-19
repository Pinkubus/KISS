@echo off
REM ============================================
REM KISS Build Script
REM Builds the standalone .exe using PyInstaller
REM ============================================

echo.
echo ============================================
echo  KISS Build Script
echo ============================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if we're in the right directory
if not exist "KISS.py" (
    echo ERROR: KISS.py not found. Run this script from the KISS folder.
    pause
    exit /b 1
)

echo [1/4] Installing/upgrading build dependencies...
pip install --upgrade pyinstaller pystray pillow >nul 2>&1

echo [2/4] Installing application dependencies...
pip install -r requirements.txt >nul 2>&1

echo [3/4] Cleaning previous build...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

echo [4/4] Building KISS.exe...
echo     This may take 1-2 minutes...
echo.

pyinstaller KISS.spec --noconfirm

if errorlevel 1 (
    echo.
    echo ============================================
    echo  BUILD FAILED
    echo ============================================
    echo Check the output above for errors.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  BUILD SUCCESSFUL!
echo ============================================
echo.
echo Output: dist\KISS.exe
echo.
echo Next steps:
echo   1. Copy KISS.exe to your desired location
echo   2. Run 'install_startup.bat' to add to Windows startup
echo   3. Or run KISS.exe manually
echo.

REM Copy .env to dist folder if it exists
if exist ".env" (
    echo Copying .env to dist folder...
    copy ".env" "dist\.env" >nul
)

REM Copy settings.json to dist folder if it exists
if exist "settings.json" (
    echo Copying settings.json to dist folder...
    copy "settings.json" "dist\settings.json" >nul
)

echo.
echo Would you like to run KISS.exe now? (Y/N)
set /p RUNEXE="> "
if /i "%RUNEXE%"=="Y" (
    start "" "dist\KISS.exe"
)

pause
