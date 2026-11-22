# -*- coding: utf-8 -*-
"""
Kalibrasyon araci.
Oyunu acin, metin taslarina bakin, sonra bu araci calistirin.

Ekranda canli goruntu acilir:
  - Yesil kutu  : isim yazisi olarak bulunan blok
  - Turuncu kutu: uzerinde mavi isin algilanan tas (kesiliyor)
  - Kutunun ustundeki yazi: OCR sonucu + isin orani

Kaydirma cubuklariyla esikleri ayarlayin.
  s = ayarlari config.json'a kaydet
  b = fare ile bir kutu cizip "isin" rengini ornekle (HSV araligini otomatik ayarla)
  q = cik
"""

import json
import os
import sys

import cv2
import numpy as np

import ayar
import girdi
from vision import Goz, HedefBari

from yol import BURASI
CFG_YOLU = os.path.join(BURASI, "config.json")
PENCERE = "Kalibrasyon (h=can bari bolgesi, b=isin rengi, s=kaydet, q=cik)"

secim = {"aktif": False, "baslangic": None, "kutu": None}


def fare(olay, x, y, bayrak, param):
    if olay == cv2.EVENT_LBUTTONDOWN:
        secim["aktif"] = True
        secim["baslangic"] = (x, y)
        secim["kutu"] = None
    elif olay == cv2.EVENT_MOUSEMOVE and secim["aktif"]:
        x0, y0 = secim["baslangic"]
        secim["kutu"] = (min(x0, x), min(y0, y), abs(x - x0), abs(y - y0))
    elif olay == cv2.EVENT_LBUTTONUP:
        secim["aktif"] = False


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if "--hwnd" in sys.argv:
            hwnd = int(sys.argv[sys.argv.index("--hwnd") + 1])
            cfg = ayar.pencere_icin_hazirla(hwnd)
        else:
            cfg, hwnd, baslik = ayar.hazirla(sor=True)
    except Exception as hata:
        print("Pencere secilemedi:", hata)
        return 1
    girdi.one_getir(hwnd)

    goz = Goz(cfg)
    bar = HedefBari(goz)
    if not goz.ocr_hazir:
        print("!" * 60)
        print("UYARI: Tesseract calismiyor -> isimler okunamiyor.")
        print("Sebep:", goz.son_ocr_hatasi)
        print("Kutular gorunur ama hepsi GRI kalir ve bot hedef bulamaz.")
        print("!" * 60)
    e, i = cfg["isim_etiketi"], cfg["isin"]

    cv2.namedWindow(PENCERE, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(PENCERE, fare)
    cv2.createTrackbar("parlaklik", PENCERE, e["parlaklik_esigi"], 255, lambda v: None)
    cv2.createTrackbar("max doygunluk", PENCERE, e["max_doygunluk"], 255, lambda v: None)
    cv2.createTrackbar("min genislik", PENCERE, e["min_genislik"], 400, lambda v: None)
    cv2.createTrackbar("max yukseklik", PENCERE, e["max_yukseklik"], 60, lambda v: None)
    cv2.createTrackbar("isin H alt", PENCERE, i["hsv_alt"][0], 180, lambda v: None)
    cv2.createTrackbar("isin H ust", PENCERE, i["hsv_ust"][0], 180, lambda v: None)
    cv2.createTrackbar("isin S alt", PENCERE, i["hsv_alt"][1], 255, lambda v: None)
    cv2.createTrackbar("isin oran x1000", PENCERE, int(i["min_oran"] * 1000), 300, lambda v: None)

    while True:
        e["parlaklik_esigi"] = cv2.getTrackbarPos("parlaklik", PENCERE)
        e["max_doygunluk"] = cv2.getTrackbarPos("max doygunluk", PENCERE)
        e["min_genislik"] = max(5, cv2.getTrackbarPos("min genislik", PENCERE))
        e["max_yukseklik"] = max(6, cv2.getTrackbarPos("max yukseklik", PENCERE))
        i["hsv_alt"][0] = cv2.getTrackbarPos("isin H alt", PENCERE)
        i["hsv_ust"][0] = cv2.getTrackbarPos("isin H ust", PENCERE)
        i["hsv_alt"][1] = cv2.getTrackbarPos("isin S alt", PENCERE)
        i["min_oran"] = cv2.getTrackbarPos("isin oran x1000", PENCERE) / 1000.0

        rect = girdi.istemci_alani(hwnd)
        kare = goz.yakala(rect)
        gorsel = kare.bgr.copy()

        x1, y1, x2, y2 = goz.arama_bolgesi(kare)
        cv2.rectangle(gorsel, (x1, y1), (x2, y2), (90, 90, 90), 1)

        for etiket in goz.etiketleri_bul(kare):
            yazi = goz.oku(kare, etiket, onbellek_suresi=0.8)
            hedef = goz.hedef_mi(yazi)
            goz.isin_kontrol(kare, etiket)
            if etiket.isin_var:
                renk = (0, 170, 255)
            elif hedef:
                renk = (0, 255, 0)
            else:
                renk = (120, 120, 120)
            cv2.rectangle(gorsel, (etiket.x, etiket.y),
                          (etiket.x + etiket.w, etiket.y + etiket.h), renk, 1)
            cv2.putText(gorsel, "%s | %.3f" % (yazi[:28] or "<OCR BOS>", etiket.isin_orani),
                        (etiket.x, max(12, etiket.y - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, renk, 1)

        # hedef can bari bolgesi + canli okuma
        if cfg["hedef_bari"]["kullan"]:
            bx1, by1, bx2, by2 = bar.bolge(kare)
            cv2.rectangle(gorsel, (bx1, by1), (bx2, by2), (255, 0, 255), 1)
            d = bar.oku(kare)
            bilgi = "BAR: %s  metin=%s  can=%s  %r" % (
                "VAR" if d.var else "yok", d.metin_mi,
                "?" if d.yuzde is None else "%.0f%%" % d.yuzde, d.isim[:26])
            cv2.putText(gorsel, bilgi, (bx1, max(14, by1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 0, 255) if d.var else (150, 150, 150), 1)
            if getattr(d, "uyari", ""):
                cv2.putText(gorsel, "! " + d.uyari[:60], (bx1, min(gorsel.shape[0] - 6, by2 + 16)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)

        if secim["kutu"]:
            sx, sy, sw, sh = secim["kutu"]
            cv2.rectangle(gorsel, (sx, sy), (sx + sw, sy + sh), (0, 255, 255), 1)

        cv2.imshow(PENCERE, gorsel)
        tus = cv2.waitKey(60) & 0xFF

        if tus == ord("q"):
            break
        if tus == ord("b") and secim["kutu"]:
            sx, sy, sw, sh = secim["kutu"]
            if sw > 3 and sh > 3:
                kirp = cv2.cvtColor(kare.bgr[sy:sy + sh, sx:sx + sw], cv2.COLOR_BGR2HSV)
                h = kirp[:, :, 0].reshape(-1)
                s = kirp[:, :, 1].reshape(-1)
                v = kirp[:, :, 2].reshape(-1)
                gecerli = (s > 60) & (v > 80)
                if gecerli.sum() > 20:
                    hh = h[gecerli]
                    i["hsv_alt"] = [int(np.percentile(hh, 5)) - 5,
                                    int(np.percentile(s[gecerli], 10)),
                                    int(np.percentile(v[gecerli], 10))]
                    i["hsv_ust"] = [int(np.percentile(hh, 95)) + 5, 255, 255]
                    i["hsv_alt"][0] = max(0, i["hsv_alt"][0])
                    i["hsv_ust"][0] = min(180, i["hsv_ust"][0])
                    print("Isin rengi ornekledi ->", i["hsv_alt"], i["hsv_ust"])
                    cv2.setTrackbarPos("isin H alt", PENCERE, i["hsv_alt"][0])
                    cv2.setTrackbarPos("isin H ust", PENCERE, i["hsv_ust"][0])
                    cv2.setTrackbarPos("isin S alt", PENCERE, i["hsv_alt"][1])
                else:
                    print("Secili alanda yeterli renkli piksel yok.")
        if tus == ord("h") and secim["kutu"]:
            sx, sy, sw, sh = secim["kutu"]
            if sw > 10 and sh > 5:
                yuk, gen = kare.bgr.shape[:2]
                cfg["hedef_bari"]["bolge"] = {
                    "sol": round(sx / gen, 4), "ust": round(sy / yuk, 4),
                    "sag": round((sx + sw) / gen, 4), "alt": round((sy + sh) / yuk, 4)}
                cfg["hedef_bari"]["kullan"] = True
                print("Can bari bolgesi ayarlandi ->", cfg["hedef_bari"]["bolge"])
                print("  (s ile kaydetmeyi unutmayin)")
            else:
                print("Once can barinin etrafina fareyle kutu cizin.")

        if tus == ord("s"):
            # ekranda gordugumuz degerler bu cozunurluge gore olcekliydi;
            # config'e referans cozunurluk degerleriyle yaz
            ayar.kaydet(ayar.olcegi_geri_al(cfg))
            print("config.json kaydedildi (referans cozunurluge cevrildi).")

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
