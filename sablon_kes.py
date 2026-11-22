# -*- coding: utf-8 -*-
"""
Ekrandan sablon kesme araci.

  python sablon_kes.py --hwnd 123456       (arayuzdeki dugme bunu acar)

1) Secilen oyun penceresinin resmi alinir (arka planda olsa da).
2) Acilan pencerede fareyle tasin ISIM YAZISINI kutu icine al -> ENTER/SPACE.
   Birden fazla yazi secebilirsin; bitince ESC.
3) Her kutu icin isim sorulur (orn. "Karanlik Metin") ve sablonlar klasorune
   kaydedilir. Resim otomatik olarak yazinin etrafina daraltilir.

Ipucu: Sadece YAZIYI sec, tasin govdesini degil. Farkli zeminlerde (kar,
cimen, karanlik) birer tane daha kesmek netligi arttirir.
"""

import os
import sys
import time

import cv2
import numpy as np

import ayar
import girdi
import sablon
from vision import Goz

PENCERE = "Sablon kes - yaziyi sec, ENTER: ekle, ESC: bitir"


def kare_al(hwnd, cfg):
    try:
        from vision import wgc_al, wgc_birak
        y = wgc_al(hwnd)
        try:
            k = y.kare(bekle=3.0)
        finally:
            wgc_birak(hwnd)
        if k is not None and not Goz.kare_bos_mu(k):
            return k
    except Exception:
        pass
    try:
        k = Goz.yakala_pencere(hwnd)
        if not Goz.kare_bos_mu(k):
            return k
    except Exception:
        pass
    girdi.one_getir(hwnd)
    time.sleep(0.4)
    import mss
    sol, ust, sag, alt = girdi.istemci_alani(hwnd)
    with mss.mss() as sct:
        ham = np.array(sct.grab({"left": sol, "top": ust, "width": sag - sol, "height": alt - ust}))
    from vision import Kare
    return Kare(cv2.cvtColor(ham, cv2.COLOR_BGRA2BGR), sol, ust)


def isim_sor(varsayilan):
    import tkinter as tk
    from tkinter import simpledialog
    kok = tk.Tk()
    kok.withdraw()
    kok.attributes("-topmost", True)
    ad = simpledialog.askstring("Resim adi", "Adi (orn. Karanlik Metin / Tamam).\n"
                                "Ek tiklamada sonuna _sag = sag tik, _cift = cift tik:",
                                initialvalue=varsayilan, parent=kok)
    kok.destroy()
    return (ad or "").strip()


def guvenli_ad(ad):
    yasak = '<>:"/\\|?*'
    return "".join("_" if k in yasak else k for k in ad).strip(" .") or "sablon"


def main():
    if "--hwnd" not in sys.argv:
        print("Kullanim: python sablon_kes.py --hwnd <pencere>")
        return 1
    hwnd = int(sys.argv[sys.argv.index("--hwnd") + 1])
    cfg = ayar.pencere_icin_hazirla(hwnd)
    olum = "--olum" in sys.argv      # olum ekrani resmi (orn. 'Burada yeniden basla')
    ek = "--ek" in sys.argv or olum  # ek gorsel tiklama resmi (buton, simge...)
    if ek:
        import ek_tiklama
        klasor = ek_tiklama.klasor_yolu(cfg, "olum_kontrol" if olum else "ek_tiklama")
    else:
        klasor = sablon.klasor_yolu(cfg)
    kare = kare_al(hwnd, cfg)
    yukseklik = kare.bgr.shape[0]

    cv2.namedWindow(PENCERE, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(PENCERE, min(1600, kare.bgr.shape[1]), min(900, kare.bgr.shape[0]))
    kutular = cv2.selectROIs(PENCERE, kare.bgr, showCrosshair=False, fromCenter=False)
    cv2.destroyAllWindows()
    if kutular is None or len(kutular) == 0:
        print("Secim yapilmadi.")
        return 0

    isimler = [i for i in (cfg["ocr"].get("hedef_isimler") or []) if str(i).strip()]
    kaydedilen = 0
    for n, (x, y, w, h) in enumerate(kutular):
        if w < 8 or h < 4:
            continue
        parca = kare.bgr[y:y + h, x:x + w]
        if not ek:
            parca = sablon.yaziya_kirp(parca, cfg["isim_etiketi"])
            varsayilan = isimler[0] if isimler else "Metin"
        else:
            varsayilan = "Burada yeniden basla" if olum else "Buton"
        ad = isim_sor(varsayilan if len(kutular) == 1 else "%s %d" % (varsayilan, n + 1))
        if not ad:
            continue
        dosya = guvenli_ad(ad) + ".png"
        yol = os.path.join(klasor, dosya)
        i = 2
        while os.path.exists(yol):
            dosya = "%s (%d).png" % (guvenli_ad(ad), i)
            yol = os.path.join(klasor, dosya)
            i += 1
        sablon.resim_yaz(yol, parca)
        sablon.olcek_kaydet(klasor, dosya, yukseklik)
        kaydedilen += 1
        print("Kaydedildi: %s  (%dx%d)" % (yol, parca.shape[1], parca.shape[0]))
    print("%d sablon kaydedildi. Calisan botlar 2 sn icinde otomatik yukler." % kaydedilen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
