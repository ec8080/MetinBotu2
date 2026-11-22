@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MetinBotu temizlik

echo Asagidakiler GERI DONUSUM KUTUSUNA atilacak (gerekirse geri alinabilir):
echo.
echo   debug\, debug_teshis\, debug_boss\   eski hata ayiklama kareleri (bot gerekirse yeniden olusturur)
echo   debug_arkaplan.png, debug_sablon.png eski test resimleri
echo   build\, dist\, __pycache__\          eski derleme / gecici dosyalar (derle.bat yeniden olusturur)
echo   MetinBotu_paylas.zip                 Eylul'den kalma eski paket (137 MB)
echo   MetinBotu.spec                       eski derleme ayari (derle.bat kullanmiyor)
echo   boss_durum_*.json                    eski PID'lerin boss sayaclari
echo                                        (11072, 25504 ve 11584 KORUNUR)
echo.
echo DOKUNULMAYANLAR: BossBotu\, Metinbbb\, MemoryReadTest.cpp, kod dosyalari,
echo   config.json, sablonlar\, tiklanacaklar\, boss_logo.png, belgeler.
echo.
set /p ONAY="Devam edilsin mi? (E/H): "
if /I not "%ONAY%"=="E" (
  echo Iptal edildi, hicbir sey silinmedi.
  pause
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Add-Type -AssemblyName Microsoft.VisualBasic;" ^
  "$fs=[Microsoft.VisualBasic.FileIO.FileSystem];" ^
  "$ui=[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs;" ^
  "$cop=[Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin;" ^
  "$klasorler='debug','debug_teshis','debug_boss','build','dist','__pycache__';" ^
  "$dosyalar=@('debug_arkaplan.png','debug_sablon.png','MetinBotu_paylas.zip','MetinBotu.spec');" ^
  "$koru='boss_durum_11072.json','boss_durum_25504.json','boss_durum_11584.json';" ^
  "$dosyalar+=Get-ChildItem -File -Filter 'boss_durum_*.json' | Where-Object { $koru -notcontains $_.Name } | ForEach-Object { $_.Name };" ^
  "foreach($k in $klasorler){ if(Test-Path -LiteralPath $k){ try{ $fs::DeleteDirectory((Resolve-Path -LiteralPath $k).Path,$ui,$cop); Write-Host ('  atildi: '+$k+'\') } catch { Write-Host ('  ATILAMADI: '+$k+' - '+$_.Exception.Message) } } };" ^
  "foreach($d in $dosyalar){ if(Test-Path -LiteralPath $d){ try{ $fs::DeleteFile((Resolve-Path -LiteralPath $d).Path,$ui,$cop); Write-Host ('  atildi: '+$d) } catch { Write-Host ('  ATILAMADI: '+$d+' - '+$_.Exception.Message) } } }"

echo.
echo Bitti. Hepsi Geri Donusum Kutusu'nda; emin olunca kutuyu bosaltabilirsin.
echo Yeni exe icin simdi derle.bat'i calistir.
pause
