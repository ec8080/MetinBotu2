@echo off
cd /d "%~dp0"
title MetinBotu2

rem ---- yonetici olarak yeniden ac ----
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process '%~f0' -WorkingDirectory '%~dp0.' -Verb RunAs"
  exit /b
)

rem ---- 1) Python var mi? (kurmaz, sadece bulur) ----
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY python3 -c "import sys" >nul 2>&1 && set "PY=python3"

if not defined PY (
  echo.
  echo  ============================================================
  echo   Python kurulu degil.
  echo  ============================================================
  echo.
  echo   Bot Python ile calisiyor. Once Python 3.12 kurun:
  echo   https://www.python.org/downloads/
  echo.
  echo   KURARKEN EN ALTTAKI "Add python.exe to PATH" KUTUSUNU ISARETLEYIN.
  echo   Kurduktan sonra Baslat.bat'i yeniden calistirin.
  echo  ============================================================
  echo.
  pause
  exit /b
)

rem ---- 2) Gerekli eklentiler (eksikse kurar) ----
%PY% -c "import cv2, mss, numpy, pytesseract, win32gui, keyboard" >nul 2>&1
if not errorlevel 1 goto :baslat
echo.
echo  Gerekli eklentiler kuruluyor (ilk acilista bir kez, birkac dakika)...
%PY% -m pip install --upgrade pip >nul 2>&1
%PY% -m pip install -r requirements.txt
%PY% -c "import cv2, mss, numpy, pytesseract, win32gui, keyboard" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  ! Eklentiler kurulamadi. Yukaridaki hatayi kontrol edin.
  pause
  exit /b
)
echo  Eklentiler kuruldu.

rem ---- 3) Guncelle ve baslat ----
:baslat
%PY% guncelle.py
%PY% gui.py
if errorlevel 1 pause
