# -*- coding: utf-8 -*-
"""
Boss paneli kalibrasyonu.

Oyunda TAB ile Isinlanma Sihirbazi'ni acin, sonra bu programi calistirin.

Tuslar:
  p : PANEL bolgesini sec (fareyle kutu ciz, ENTER)
  l : CAGIRMA LOGOSU'nu sec  -> boss_logo.png olarak kaydedilir + sutun ogrenilir
  2 : IKINCI logo gorunumu (farkli renkteki cagirma butonu) -> boss_logo2.png
  i : ISIM hucresi ofsetlerini otomatik ayarla (once 'l' yapilmis olmali)
  n : CAGIRMA NESNESI'ni sec (bossu uzerine ceken nesne; her cagirmadan
      sonra bir kez SAG tiklanir)
  t : TEST - logolari bul, isimleri OCR ile oku, ekranda goster
  k : KAYDIRMA testi - 1 adim asagi kaydir
  s : config.json'a KAYDET
  q : cikis
"""

import json
import logging
import os
import time

import cv2
import numpy as np

import ayar
import boss
import girdi
from vision import Goz
from yol import BURASI


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    girdi.dpi_farkinda_ol()
    cfg, hwnd, baslik = ayar.hazirla()
    g = cfg.get("girdi", {})
    gr = girdi.Girdi(hwnd, g.get("mod", "on_plan"),
                     cfg["guvenlik"].get("insansi_fare", True), g.get("arka_imlec", True))
    goz = Goz(cfg)

    wgc = None
    if gr.arka_plan:
        try:
            from vision import wgc_al
            wgc = wgc_al(hwnd)
        except Exception as hata:
            print("WGC yok (%s) -> PrintWindow" % hata)

    def kare_al():
        if gr.arka_plan and wgc is not None:
            return wgc.kare()
        if gr.arka_plan:
            return goz.yakala_pencere(hwnd)
        return goz.yakala(girdi.istemci_alani(hwnd))

    cfg.setdefault("boss", {})
    bc = boss.BossCagirici(cfg, goz, gr, hwnd, kare_al=kare_al, gunluk=print)

    print(__doc__)
    pencere = "Boss kalibrasyon"
    cv2.namedWindow(pencere, cv2.WINDOW_NORMAL)

    son_test = []
    while True:
        kare = kare_al()
        if kare is None:
            time.sleep(0.2)
            continue
        gorsel = kare.bgr.copy()

        p = cfg["boss"].get("panel_bolgesi")
        h, w = gorsel.shape[:2]
        if p:
            cv2.rectangle(gorsel,
                          (int(w * p["sol"]), int(h * p["ust"])),
                          (int(w * p["sag"]), int(h * p["alt"])), (0, 200, 255), 2)
        cn = cfg["boss"].get("cagirma_nesnesi", {})
        if cn.get("aktif"):
            px, py = int(w * float(cn.get("x", 0.5))), int(h * float(cn.get("y", 0.9)))
            cv2.drawMarker(gorsel, (px, py), (0, 140, 255), cv2.MARKER_TILTED_CROSS, 20, 2)
            cv2.putText(gorsel, "nesne", (px + 12, py - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 140, 255), 1)

        for isim, (x, y, tw, th) in son_test:
            cv2.rectangle(gorsel, (x, y), (x + tw, y + th), (0, 255, 0), 2)
            i = cfg["boss"].get("isim", {})
            x1 = max(0, x - int(i.get("sol_ofset", 450)))
            x2 = max(x1 + 10, x - int(i.get("sag_ofset", 250)))
            cv2.rectangle(gorsel, (x1, y), (x2, y + th), (255, 120, 0), 1)
            cv2.putText(gorsel, isim[:28] or "(okunamadi)", (x1, y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        cv2.imshow(pencere, gorsel)
        tus = cv2.waitKey(80) & 0xFF

        if tus == ord("q"):
            break

        elif tus == ord("p"):
            r = cv2.selectROI("Panel bolgesini secin (ENTER)", kare.bgr, False, False)
            cv2.destroyWindow("Panel bolgesini secin (ENTER)")
            if r[2] > 20 and r[3] > 20:
                cfg["boss"]["panel_bolgesi"] = {
                    "sol": round(r[0] / w, 4), "ust": round(r[1] / h, 4),
                    "sag": round((r[0] + r[2]) / w, 4), "alt": round((r[1] + r[3]) / h, 4)}
                print("Panel bolgesi: %s" % cfg["boss"]["panel_bolgesi"])

        elif tus == ord("l"):
            r = cv2.selectROI("Cagirma logosunu secin (ENTER)", kare.bgr, False, False)
            cv2.destroyWindow("Cagirma logosunu secin (ENTER)")
            if r[2] > 8 and r[3] > 8:
                kirp = kare.bgr[r[1]:r[1] + r[3], r[0]:r[0] + r[2]].copy()
                yol = os.path.join(BURASI, cfg["boss"].setdefault("logo", {})
                                   .get("dosya", "boss_logo.png"))
                cv2.imwrite(yol, kirp)
                pan = cfg["boss"].get("panel_bolgesi")
                ox = int(w * pan["sol"]) if pan else 0
                oy = int(h * pan["ust"]) if pan else 0
                cfg["boss"]["logo"]["sutun_x"] = int(r[0] - ox)
                cfg["boss"]["logo"]["dosya"] = os.path.basename(yol)
                bc.b = cfg["boss"]
                bc._sablon_yukle()
                print("Logo kaydedildi: %s  (%dx%d, panel ici x=%d, ekran y=%d)"
                      % (yol, r[2], r[3], r[0] - ox, r[1] - oy))

        elif tus == ord("2"):
            r = cv2.selectROI("IKINCI cagirma butonunu secin (ENTER)", kare.bgr, False, False)
            cv2.destroyWindow("IKINCI cagirma butonunu secin (ENTER)")
            if r[2] > 8 and r[3] > 8:
                kirp = kare.bgr[r[1]:r[1] + r[3], r[0]:r[0] + r[2]].copy()
                ad = "boss_logo2.png"
                cv2.imwrite(os.path.join(BURASI, ad), kirp)
                lg = cfg["boss"].setdefault("logo", {})
                dosyalar = lg.get("dosyalar") or [lg.get("dosya", "boss_logo.png")]
                if ad not in dosyalar:
                    dosyalar.append(ad)
                lg["dosyalar"] = dosyalar
                bc.b = cfg["boss"]
                bc._sablon_yukle()
                print("Ikinci logo kaydedildi: %s (%dx%d). Toplam sablon: %s"
                      % (ad, r[2], r[3], ", ".join(dosyalar)))

        elif tus == ord("i"):
            r = cv2.selectROI("Boss ISMININ yazdigi yeri secin (ENTER)", kare.bgr, False, False)
            cv2.destroyWindow("Boss ISMININ yazdigi yeri secin (ENTER)")
            if r[2] > 10:
                kutular = bc.logolari_bul(kare)
                if not kutular:
                    print("Once 'l' ile logoyu kaydedin (logo bulunamadi)")
                else:
                    # secilen isim kutusuna en yakin logo satirini bul
                    merkez_y = r[1] + r[3] / 2
                    lx, ly, lw, lh = min(kutular, key=lambda k: abs(k[1] + k[3] / 2 - merkez_y))
                    cfg["boss"].setdefault("isim", {})
                    cfg["boss"]["isim"]["sol_ofset"] = int(lx - r[0])
                    cfg["boss"]["isim"]["sag_ofset"] = int(lx - (r[0] + r[2]))
                    bc.b = cfg["boss"]
                    print("Isim ofsetleri: sol=%d sag=%d"
                          % (cfg["boss"]["isim"]["sol_ofset"],
                             cfg["boss"]["isim"]["sag_ofset"]))

        elif tus == ord("n"):
            r = cv2.selectROI("Cagirma nesnesini secin (ENTER)", kare.bgr, False, False)
            cv2.destroyWindow("Cagirma nesnesini secin (ENTER)")
            if r[2] > 4 and r[3] > 4:
                nx, ny = r[0] + r[2] / 2.0, r[1] + r[3] / 2.0
                cfg["boss"].setdefault("cagirma_nesnesi", {})
                cfg["boss"]["cagirma_nesnesi"].update(
                    {"aktif": True, "x": round(nx / w, 4), "y": round(ny / h, 4)})
                bc.b = cfg["boss"]
                print("Cagirma nesnesi: %d,%d  (oran %.4f / %.4f) - ACIK"
                      % (int(nx), int(ny), cfg["boss"]["cagirma_nesnesi"]["x"],
                         cfg["boss"]["cagirma_nesnesi"]["y"]))
                print("  (s ile kaydetmeyi unutmayin)")

        elif tus == ord("t"):
            bc.b = cfg["boss"]
            satirlar = bc.satirlari_oku(kare)
            son_test = [(s[0], s[1]) for s in satirlar]
            print("--- %d satir bulundu ---" % len(satirlar))
            for isim, kutu in satirlar:
                print("   y=%4d  '%s'" % (kutu[1], isim))
            if not satirlar:
                print("   Logo bulunamadi. 'l' ile logoyu yeniden secin ya da "
                      "config > boss.logo.esik degerini dusurun (simdi %.2f)"
                      % float(cfg["boss"].get("logo", {}).get("esik", 0.93)))

        elif tus == ord("k"):
            bc.b = cfg["boss"]
            bc._kaydir(kare, yon=-1)
            print("1 adim asagi kaydirildi (tik=%s)"
                  % cfg["boss"].get("kaydirma", {}).get("tik", 3))

        elif tus == ord("s"):
            tam = ayar.olcegi_geri_al(cfg)
            ayar.kaydet(tam)
            print("config.json kaydedildi.")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
