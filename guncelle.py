# -*- coding: utf-8 -*-
"""
Otomatik guncelleyici (Baslat.bat her acilista once bunu calistirir).

GitHub'daki depoyla bu klasoru karsilastirir; degisen / yeni dosyalari indirir.
- Kullanicinin ayarlari (config.json, konumlar.json ...) ASLA ezilmez.
- Sablon resimleri (sablonlar, olum, tiklanacaklar) sadece eksikse indirilir.
- Internet yoksa ya da GitHub'a ulasilamazsa sessizce atlanir, bot yine acilir.
- Klasorde '.gelistirici' dosyasi varsa hic guncelleme yapilmaz (gelistiricinin
  kendi bilgisayari: yuklenmemis degisiklikleri ezilmesin).
"""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request

DEPO = "ec8080/MetinBotu2"
DAL = "main"
KLASOR = os.path.dirname(os.path.abspath(__file__))

# hic dokunulmayanlar
KORUNAN = {"config.json", "konumlar.json", ".gelistirici"}
KORUNAN_ON_EK = ("boss_durum_", "gunluk")
# sadece eksikse indirilen klasorler (kullanici kendi resmini koymus olabilir)
SADECE_EKSIKSE = ("sablonlar/", "olum/", "tiklanacaklar/")
# calisirken degistirilemeyen dosya (Windows .bat'i satir satir okur)
SADECE_EKSIK_DOSYA = {"Baslat.bat"}


def _git_sha(yol):
    with open(yol, "rb") as f:
        veri = f.read()
    return hashlib.sha1(b"blob %d\0" % len(veri) + veri).hexdigest()


def _getir(url, zaman=8):
    istek = urllib.request.Request(url, headers={"User-Agent": "MetinBotu2-guncelleyici"})
    with urllib.request.urlopen(istek, timeout=zaman) as y:
        return y.read()


def guncelle():
    if os.path.exists(os.path.join(KLASOR, ".gelistirici")):
        print("[guncelleme] gelistirici bilgisayari, atlandi.")
        return
    try:
        agac = json.loads(_getir("https://api.github.com/repos/%s/git/trees/%s?recursive=1"
                                 % (DEPO, DAL)))
    except Exception as e:
        print("[guncelleme] GitHub'a ulasilamadi, atlandi (%s)" % e)
        return

    degisen = []
    for o in agac.get("tree", []):
        if o.get("type") != "blob":
            continue
        yol = o["path"]
        ad = yol.split("/")[-1]
        if yol in KORUNAN or ad.startswith(KORUNAN_ON_EK):
            continue
        yerel = os.path.join(KLASOR, *yol.split("/"))
        if os.path.exists(yerel):
            if yol.startswith(SADECE_EKSIKSE) or yol in SADECE_EKSIK_DOSYA:
                continue
            try:
                if _git_sha(yerel) == o["sha"]:
                    continue
            except OSError:
                pass
        degisen.append(yol)

    if not degisen:
        print("[guncelleme] bot guncel.")
        return

    print("[guncelleme] %d dosya guncelleniyor..." % len(degisen))
    tamam = []
    for yol in degisen:
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (
            DEPO, DAL, urllib.request.quote(yol))
        try:
            veri = _getir(url, 20)
        except Exception as e:
            print("  ! %s indirilemedi (%s)" % (yol, e))
            continue
        hedef = os.path.join(KLASOR, *yol.split("/"))
        os.makedirs(os.path.dirname(hedef), exist_ok=True)
        gecici = hedef + ".yeni"
        with open(gecici, "wb") as f:
            f.write(veri)
        os.replace(gecici, hedef)          # yarim dosya kalmasin
        tamam.append(yol)
        print("  + %s" % yol)

    if "requirements.txt" in tamam:
        print("[guncelleme] yeni kutuphaneler kuruluyor...")
        subprocess.call([sys.executable, "-m", "pip", "install", "-q", "-r",
                         os.path.join(KLASOR, "requirements.txt")])
    print("[guncelleme] bitti (%d/%d)." % (len(tamam), len(degisen)))


if __name__ == "__main__":
    try:
        guncelle()
    except Exception as e:                 # guncelleyici hatasi botu asla engellemesin
        print("[guncelleme] hata, atlandi: %s" % e)
