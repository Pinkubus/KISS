@echo off
REM ============================================
REM KISS Startup Installer
REM Adds KISS.exe to Windows Startup
REM ============================================

echo.
echo ============================================
echo  KISS Startup Installer
echo ============================================
echo.

REM Get the startup folder path
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

REM Check if KISS.exe exists
set "KISS_PATH="

REM First check dist folder (if run from build folder)
if exist "%~dp0dist\KISS.exe" (
    set "KISS_PATH=%~dp0dist\KISS.exe"
    goto :found
)

REM Check current folder
if exist "%~dp0KISS.exe" (
    set "KISS_PATH=%~dp0KISS.exe"
    goto :found
)

echo ERROR: KISS.exe not found!
echo.
echo Please either:
echo   1. Run build.bat first to create KISS.exe
echo   2. Copy KISS.exe to this folder
echo.
pause
exit /b 1

:found
echo Found KISS.exe at:
echo   %KISS_PATH%
echo.
echo Startup folder:
echo   %STARTUP%
echo.

REM Ask user what to do
echo Choose an option:
echo   [1] Add KISS to Windows Startup (recommended)
echo   [2] Remove KISS from Windows Startup
echo   [3] Open Startup folder
echo   [4] Cancel
echo.
set /p CHOICE="> "

if "%CHOICE%"=="1" goto :install
if "%CHOICE%"=="2" goto :uninstall
if "%CHOICE%"=="3" goto :openfolder
goto :cancel

:install
echo.
echo Creating startup shortcut...

REM Create a VBS script to make the shortcut (cleanest method)
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP%\CreateKISSShortcut.vbs"
echo sLinkFile = "%STARTUP%\KISS.lnk" >> "%TEMP%\CreateKISSShortcut.vbs"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%TEMP%\CreateKISSShortcut.vbs"
echo oLink.TargetPath = "%KISS_PATH%" >> "%TEMP%\CreateKISSShortcut.vbs"
echo oLink.WorkingDirectory = "%~dp0dist" >> "%TEMP%\CreateKISSShortcut.vbs"
echo oLink.Description = "KISS - Speed Reader and Strategy Analyzer" >> "%TEMP%\CreateKISSShortcut.vbs"
echo oLink.WindowStyle = 7 >> "%TEMP%\CreateKISSShortcut.vbs"
echo oLink.Save >> "%TEMP%\CreateKISSShortcut.vbs"

cscript //nologo "%TEMP%\CreateKISSShortcut.vbs"
del "%TEMP%\CreateKISSShortcut.vbs"

if exist "%STARTUP%\KISS.lnk" (
    echo.
    echo ============================================
    echo  SUCCESS! KISS added to Windows Startup
    echo ============================================
    echo.
    echo KISS will now start automatically when Windows boots.
    echo It will run in the background with a tray icon.
    echo.
    echo Press F3 anytime to open the speed reader.
    echo Press Ctrl+Shift+A for AI Strategy Analysis.
    echo.
) else (
    echo.
    echo ERROR: Failed to create startup shortcut.
    echo Try running this script as Administrator.
    echo.
)
pause
exit /b 0

:uninstall
echo.
echo Removing KISS from Windows Startup...
if exist "%STARTUP%\KISS.lnk" (
    del "%STARTUP%\KISS.lnk"
    echo.
    echo SUCCESS! KISS removed from Windows Startup.
    echo.
) else (
    echo.
    echo KISS was not found in Windows Startup.
    echo.
)
pause
exit /b 0

:openfolder
echo.
echo Opening Startup folder...
start "" "%STARTUP%"
exit /b 0

:cancel
echo.
echo Cancelled.
exit /b 0
