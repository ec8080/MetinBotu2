@echo off
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c python guncelle.py & python gui.py || pause' -WorkingDirectory '%~dp0.' -Verb RunAs"
  exit /b
)
python guncelle.py
python gui.py
if errorlevel 1 pause
