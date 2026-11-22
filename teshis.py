# -*- coding: utf-8 -*-
"""
Teshis araci - bot taslari / can barini dogru goruyor mu?

Arayuzden:   "Teshis" dugmesi (secili client icin, sonuc Gunluk'e yazilir)
Konsoldan:   python teshis.py          (PID sorar)
             python teshis.py tikla    (sonunda test tiklamasi da yapar)
Sonuc:       debug_teshis/ klasorune isaretli kare + her etiketin kirpigi
"""

import os
import sys
import time

import cv2

import ayar
import girdi
from vision import Goz, HedefBari
from yol import BURASI

KLASOR = os.path.join(BURASI, "debug_teshis")


def _kare_al(goz, hwnd, yaz, bekle_on_plan=True):
    """Once Windows Graphics Capture (oyun arkada olsa da calisir), olmazsa ekrandan."""
    try:
        from vision import wgc_al, wgc_birak
        wgc = wgc_al(hwnd, deneme=2)
        try:
            kare = wgc.kare(bekle=3.0)
        finally:
            wgc_birak(hwnd)
        if kare is not None and not goz.kare_bos_mu(kare):
            yaz("  Goruntu: Windows Graphics Capture")
            return kare
    except Exception:
        pass
    if bekle_on_plan:
        yaz("  Goruntu: ekrandan (oyun one getiriliyor)")
        girdi.one_getir(hwnd)
        time.sleep(0.8)
    return goz.yakala(girdi.istemci_alani(hwnd))


def rapor(hwnd, yaz=print, tikla=False):
    """Tum teshisi calistirir, satirlari yaz() ile verir. Soru sormaz."""
    if not os.path.isdir(KLASOR):
        os.makedirs(KLASOR)
    for eski in os.listdir(KLASOR):
        if eski.startswith("etiket_"):
            try:
                os.remove(os.path.join(KLASOR, eski))
            except OSError:
                pass

    yaz("=== 1) PENCERE ===")
    cfg = ayar.pencere_icin_hazirla(hwnd)
    import win32gui
    rect = girdi.istemci_alani(hwnd)
    yaz("  %s  %s  olcek=%.2f" % (win32gui.GetWindowText(hwnd), rect, cfg["_olcek"]))
    isimler = [i for i in (cfg["ocr"].get("hedef_isimler") or []) if str(i).strip()]
    yaz("  Aranan tas: %s" % (", ".join(isimler) if isimler else "tum metin taslari"))

    yaz("=== 2) OCR ===")
    goz = Goz(cfg)
    if goz.ocr_hazir:
        yaz("  OK: Tesseract calisiyor")
    else:
        yaz("  HATA: Tesseract calismiyor -> %s" % goz.son_ocr_hatasi)

    yaz("=== 3) TARAMA ===")
    kare = _kare_al(goz, hwnd, yaz)
    hedefler, tumu = goz.tara(kare, ayrinti=True)
    yaz("  Bulunan yazi: %d   Hedef tas: %d" % (len(tumu), len(hedefler)))
    gorsel = kare.bgr.copy()
    x1, y1, x2, y2 = goz.arama_bolgesi(kare)
    cv2.rectangle(gorsel, (x1, y1), (x2, y2), (90, 90, 90), 1)
    for n, e in enumerate(tumu):
        s = goz.sinif(e.yazi)
        renk = {"hedef": (0, 255, 0), "benzer": (0, 200, 255)}.get(s, (0, 0, 255))
        cv2.rectangle(gorsel, (e.x, e.y), (e.x + e.w, e.y + e.h), renk, 1)
        cv2.putText(gorsel, "#%d" % n, (e.x, max(12, e.y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, renk, 1)
        pad = 4
        kirp = kare.bgr[max(0, e.y - pad):e.y + e.h + pad, max(0, e.x - pad):e.x + e.w + pad]
        if kirp.size:
            cv2.imwrite(os.path.join(KLASOR, "etiket_%02d.png" % n),
                        cv2.resize(kirp, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
        yaz("  #%-2d %-28r -> %s" % (n, e.yazi[:28], s))

    yaz("=== 4) HEDEF CAN BARI ===")
    d = None
    hb = cfg["hedef_bari"]
    if not hb.get("kullan", True):
        yaz("  Kapali")
    else:
        bar = HedefBari(goz)
        bx1, by1, bx2, by2 = bar.bolge(kare)
        kirp = kare.bgr[by1:by2, bx1:bx2]
        if kirp.size:
            cv2.imwrite(os.path.join(KLASOR, "can_bari.png"),
                        cv2.resize(kirp, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        cv2.rectangle(gorsel, (bx1, by1), (bx2, by2), (255, 0, 255), 1)
        d = bar.oku(kare)
        yaz("  Bar var mi : %s" % d.var)
        yaz("  Aranan tas : %s" % d.metin_mi)
        yaz("  Can        : %s" % ("-" if d.yuzde is None else "%%%.1f" % d.yuzde))
        yaz("  Okunan     : %r" % " ".join((d.ham or "").split())[:90])
        if d.uyari:
            yaz("  UYARI: " + d.uyari)
        if not d.var:
            yaz("  (Bar yoksa: oyunda bir tasa tiklayip teshisi tekrarlayin)")
    cv2.imwrite(os.path.join(KLASOR, "kare.png"), gorsel)

    yaz("=== 5) SONUC ===")
    if not tumu:
        yaz("  Hic yazi bulunamadi -> kalibrasyonda parlaklik esigini dusurun.")
    elif not hedefler:
        benzer = [e for e in tumu if goz.sinif(e.yazi) == "benzer"]
        if benzer:
            yaz("  Metin tasi var ama adi aranan isimle eslesmedi: %s"
                % ", ".join(repr(e.yazi) for e in benzer[:4]))
            yaz("  -> 'Hedef tas adi' kutusundaki yaziyi kontrol edin.")
        else:
            yaz("  Yazilar okunuyor ama hicbiri metin tasi degil.")
    else:
        yaz("  Tespit tamam: %d tas bulundu." % len(hedefler))
    yaz("  Goruntuler: %s" % KLASOR)

    if tikla and hedefler:
        e = max(hedefler, key=lambda t: t.h * 100 + t.w)
        hx = e.x + e.w // 2
        hy = e.y + e.h + cfg["tiklama"]["hedef_ofset_y"]
        girdi.one_getir(hwnd)
        time.sleep(1.0)
        girdi.Girdi(hwnd, "on_plan").tikla(hx, hy)
        yaz("  Test tiklamasi yapildi -> karakter tasa gitti mi?")
    return len(hedefler)


def main():
    cfg, hwnd, baslik = ayar.hazirla(sor=True)
    rapor(hwnd, print, tikla=(len(sys.argv) > 1 and sys.argv[1] == "tikla"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
