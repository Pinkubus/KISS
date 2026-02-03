@echo off
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting Spreeder...
echo Press F3 to open the speed reader window
echo Press Ctrl+C to exit
echo.
python spreeder.py
pause
