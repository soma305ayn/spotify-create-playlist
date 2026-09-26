@echo off
cd /d "%~dp0"
python -m setlist2spotify %*
pause
