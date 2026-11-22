@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MetinBotu2

rem ---- yonetici olarak yeniden ac ----
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process '%~f0' -WorkingDirectory '%~dp0.' -Verb RunAs"
  exit /b
)

rem ---- 1) Python var mi? ----
set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
  py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  echo.
  echo  ============================================================
  echo   Python bilgisayarinizda bulunamadi.
  echo  ============================================================
  echo.
  echo   Bot Python ile calisiyor, once Python kurmaniz gerekiyor.
  echo.
  echo   [1] Otomatik kur  (birkac dakika surer)
  echo   [2] Indirme sayfasini ac, kendim kurarim
  echo   [3] Cik
  echo.
  choice /c 123 /n /m "  Seciminiz (1/2/3): "
  if errorlevel 3 exit /b
  if errorlevel 2 goto :py_sayfa
  goto :py_otomatik
)
goto :kutuphane

:py_otomatik
where winget >nul 2>&1
if errorlevel 1 goto :py_sayfa
echo.
echo  Python kuruluyor, lutfen bekleyin...
winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
echo.
echo  ============================================================
echo   Python kuruldu. Bu pencereyi kapatip Baslat.bat'i
echo   YENIDEN calistirin. (Gerekli eklentiler o zaman kurulacak.)
echo  ============================================================
pause
exit /b

:py_sayfa
start "" "https://www.python.org/downloads/"
echo.
echo  ============================================================
echo   Python indirme sayfasi acildi.
echo   KURARKEN EN ALTTAKI "Add python.exe to PATH" KUTUSUNU ISARETLEYIN!
echo   Kurulum bitince Baslat.bat'i yeniden calistirin.
echo  ============================================================
pause
exit /b

rem ---- 2) Gerekli eklentiler (ilk acilista ya da eksikse) ----
:kutuphane
%PY% -c "import cv2, mss, numpy, pytesseract, win32gui, keyboard" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Gerekli eklentiler kuruluyor ^(ilk acilista bir kez, birkac dakika^)...
  %PY% -m pip install --upgrade pip >nul 2>&1
  %PY% -m pip install -r requirements.txt
  %PY% -c "import cv2, mss, numpy, pytesseract, win32gui, keyboard" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo  ! Eklentiler kurulamadi. Internet baglantinizi kontrol edip tekrar deneyin.
    pause
    exit /b
  )
  echo  Eklentiler kuruldu.
)

rem ---- 3) Tesseract (metin farmi icin yazi okuma) ----
set "TESS="
if exist "%~dp0Tesseract-OCR\tesseract.exe" set "TESS=1"
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESS=1"
if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" set "TESS=1"
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set "TESS=1"
if not defined TESS if not exist "%~dp0.tesseract_sorma" (
  echo.
  echo  Tesseract bulunamadi. Metin farmi tas isimlerini okumak icin bunu kullanir
  echo  ^(At ustu cekme vurma icin gerekmez^).
  echo.
  echo   [1] Otomatik kur   [2] Simdi degil   [3] Bir daha sorma
  choice /c 123 /n /m "  Seciminiz (1/2/3): "
  if errorlevel 3 (
    echo.> "%~dp0.tesseract_sorma"
  ) else if not errorlevel 2 (
    winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
  )
)

rem ---- 4) Guncelle ve baslat ----
%PY% guncelle.py
%PY% gui.py
if errorlevel 1 pause
