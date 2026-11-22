@echo off
cd /d "%~dp0"
title MetinBotu derleme

echo [1/5] Gerekli paketler kuruluyor...
python -m pip install --upgrade pyinstaller mss opencv-python numpy pytesseract pywin32 keyboard windows-capture
if errorlevel 1 goto hata

echo [2/5] Tesseract araniyor...
set "TESS=C:\Program Files\Tesseract-OCR"
if not exist "%TESS%\tesseract.exe" set "TESS=C:\Program Files (x86)\Tesseract-OCR"
if not exist "%TESS%\tesseract.exe" set "TESS=%LOCALAPPDATA%\Programs\Tesseract-OCR"
if not exist "%TESS%\tesseract.exe" (
  echo Tesseract bulunamadi. Bu bilgisayarda Tesseract kurulu olmali.
  goto hata
)
echo     %TESS%

echo [3/5] Derleniyor (birkac dakika surer)...
if exist "dist\MetinBotu" rmdir /S /Q "dist\MetinBotu"
python -m PyInstaller --noconfirm --clean --windowed --onedir --uac-admin --name MetinBotu --collect-all windows_capture --hidden-import win32timezone --hidden-import sablon --hidden-import sablon_kes --hidden-import ek_tiklama --hidden-import cekme_vurma --hidden-import pelerin_islem gui.py
if errorlevel 1 goto hata
set "HEDEF=dist\MetinBotu"

echo [4/5] Tesseract ve ayarlar pakete ekleniyor...
robocopy "%TESS%" "%HEDEF%\Tesseract-OCR" /E /XD tessdata /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto hata
mkdir "%HEDEF%\Tesseract-OCR\tessdata" 2>nul
for %%L in (eng tur osd) do if exist "%TESS%\tessdata\%%L.traineddata" copy /Y "%TESS%\tessdata\%%L.traineddata" "%HEDEF%\Tesseract-OCR\tessdata\" >nul
python paket_ayar.py "%HEDEF%"
if errorlevel 1 goto hata
copy /Y OKUBENI.txt "%HEDEF%\" >nul
copy /Y boss_logo*.png "%HEDEF%\" >nul 2>nul
if exist BOSS_KURULUM.md copy /Y BOSS_KURULUM.md "%HEDEF%\" >nul
rem resimle bulma sablonlari ve ek tiklama resimleri de pakete girsin
if exist sablonlar robocopy sablonlar "%HEDEF%\sablonlar" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto hata
if exist olum robocopy olum "%HEDEF%\olum" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto hata
if exist tiklanacaklar robocopy tiklanacaklar "%HEDEF%\tiklanacaklar" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto hata

echo [5/5] Zip hazirlaniyor...
if exist MetinBotu_paylas.zip del MetinBotu_paylas.zip
powershell -NoProfile -Command "Compress-Archive -Path dist\MetinBotu -DestinationPath MetinBotu_paylas.zip -Force"
if errorlevel 1 goto hata

echo.
echo TAMAM: MetinBotu_paylas.zip hazir. Arkadaslarina bunu gonder.
pause
exit /b 0

:hata
echo.
echo HATA olustu, yukaridaki mesaja bakin.
pause
exit /b 1
