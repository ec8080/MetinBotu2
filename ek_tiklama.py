# -*- coding: utf-8 -*-
"""
Ek gorsel tiklama
-----------------
Metin kesmeden BAGIMSIZ: 'tiklanacaklar' klasorune koydugun resimler
(bir buton, bir pencere, bir simge...) oyun ekraninda gorundugu anda tiklanir.
Tas bulma isi yine isim (OCR) yontemiyle yapilir; bu modul ona karismaz.

Dosya adina gore tiklama turu:
    Tamam.png          -> sol tik
    Esya_sag.png       -> sag tik
    Kutu_cift.png      -> cift tik
    Buton_2x.png ...   -> (diger her sey sol tik)

tiklanacaklar/olcek.json: resim hangi pencere yuksekliginde kesildi
(farkli boyuttaki client'larda resim otomatik olceklenir).

Netlik icin (her resim icin otomatik):
  * MASKE: resmin 'yapisi' (cerceve cizgileri, yazi/rakam) ayrilir; yari saydam
    kutularda icinden gorunen zemin puani dusurmez.
  * MERKEZ DOGRULAMA: resmin ortasinda yazi/rakam varsa (orn. '4'), bulunan yerde
    o da ayrica kontrol edilir -> bos kutu ya da baska rakam tiklanmaz.
  * KONUM OGRENME: resim ilk bulundugu yer kaydedilir (konumlar.json); sonra once
    orada aranir. Orada esik biraz esnektir (bolge_toleransi). Bulunamazsa tum
    pencerede aranir.
"""

import json
import logging
import os
import random
import time

import cv2
import numpy as np

from sablon import UZANTILAR, olcek_kayitlari, resim_oku
from yol import BURASI


VARSAYILAN_KLASOR = {"ek_tiklama": "tiklanacaklar", "olum_kontrol": "olum"}


def klasor_yolu(cfg, bolum="ek_tiklama"):
    ad = cfg.get(bolum, {}).get("klasor", VARSAYILAN_KLASOR.get(bolum, bolum))
    yol = ad if os.path.isabs(ad) else os.path.join(BURASI, ad)
    if not os.path.isdir(yol):
        os.makedirs(yol, exist_ok=True)
    return yol


class _Gorsel:
    def __init__(self, dosya, bgr, k):
        self.dosya = dosya
        ad = os.path.splitext(dosya)[0]
        import re
        kucuk = re.sub(r"\s*\(\d+\)$", "", ad.lower())     # "Esya_sag (2)" -> "esya_sag"
        self.tur = "sag" if kucuk.endswith("_sag") else "cift" if kucuk.endswith("_cift") else "sol"
        self.ad = ad
        if abs(k - 1.0) > 0.02:
            ara = cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR
            bgr = cv2.resize(bgr, (max(4, int(round(bgr.shape[1] * k))),
                                   max(4, int(round(bgr.shape[0] * k)))), interpolation=ara)
        self.bgr = bgr
        self.son_tik = 0.0
        self.tik_sayisi = 0
        self.son_ham = 0.0           # son aramadaki gercek benzerlik
        self.son_bolgede = False     # ogrenilen konumda mi bulundu
        self._yapi_hazirla()

    def _yapi_hazirla(self):
        """Yapi maskesi (cerceve + yazi) ve merkezdeki yazi/rakam bolgesi."""
        g = cv2.cvtColor(self.bgr, cv2.COLOR_BGR2GRAY).astype(np.int16)
        yapi = (np.abs(g - int(np.median(g))) > 25).astype(np.uint8)
        yapi = cv2.dilate(yapi, np.ones((3, 3), np.uint8)) > 0
        oran = float(yapi.mean())
        self.maske = yapi if 0.03 <= oran <= 0.9 else None
        self.merkez = None
        th, tw = g.shape
        x0, y0, x1, y1 = int(tw * 0.2), int(th * 0.2), int(tw * 0.8), int(th * 0.8)
        if self.maske is not None and x1 - x0 >= 4 and y1 - y0 >= 4:
            if self.maske[y0:y1, x0:x1].mean() > 0.02:
                self.merkez = (x0, y0, x1, y1)


class EkTiklayici:
    def __init__(self, cfg, bolum="ek_tiklama"):
        self.cfg = cfg
        self.bolum = bolum             # 'ek_tiklama' | 'olum_kontrol'
        self.gorseller = []
        self._imza = None
        self._son_kontrol_klasor = 0.0
        self._son_tarama = 0.0
        self._konumlar = {}
        self.yukle()

    @property
    def e(self):
        return self.cfg.get(self.bolum, {})

    @property
    def aktif(self):
        return bool(self.e.get("aktif", False)) and bool(self.gorseller)

    def _klasor_imzasi(self, klasor):
        try:
            return tuple(sorted((a, os.path.getmtime(os.path.join(klasor, a)))
                                for a in os.listdir(klasor)
                                if a.lower().endswith(UZANTILAR + (".json",))
                                and a != "konumlar.json"))
        except OSError:
            return None

    def yukle(self):
        klasor = klasor_yolu(self.cfg, self.bolum)
        olcekler = olcek_kayitlari(klasor)
        istemci = self.cfg.get("_istemci")
        simdiki_y = istemci[1] if istemci else None
        eski = {g.dosya: g for g in self.gorseller}
        yeni = []
        for dosya in sorted(os.listdir(klasor)):
            if not dosya.lower().endswith(UZANTILAR):
                continue
            bgr = resim_oku(os.path.join(klasor, dosya))
            if bgr is None or bgr.size == 0:
                logging.warning("Ek tiklama resmi okunamadi: %s", dosya)
                continue
            k = 1.0
            if olcekler.get(dosya) and simdiki_y:
                k = max(0.4, min(2.5, float(simdiki_y) / float(olcekler[dosya])))
            g = _Gorsel(dosya, bgr, k)
            if dosya in eski:                   # bekleme sureleri kaybolmasin
                g.son_tik, g.tik_sayisi = eski[dosya].son_tik, eski[dosya].tik_sayisi
            yeni.append(g)
        self.gorseller = yeni
        self._imza = self._klasor_imzasi(klasor)
        try:
            with open(os.path.join(klasor, "konumlar.json"), "r", encoding="utf-8") as f:
                self._konumlar = json.load(f)
        except Exception:
            self._konumlar = {}
        if yeni:
            logging.info("Ek tiklama: %d resim (%s)", len(yeni),
                         ", ".join("%s[%s]" % (g.ad, g.tur) for g in yeni[:5]) +
                         (" ..." if len(yeni) > 5 else ""))
        return len(yeni)

    def _klasor_degisti_mi(self):
        simdi = time.time()
        if simdi - self._son_kontrol_klasor < 2.0:
            return
        self._son_kontrol_klasor = simdi
        if self._klasor_imzasi(klasor_yolu(self.cfg, self.bolum)) != self._imza:
            self.yukle()

    # ---------- eslestirme ----------
    @staticmethod
    def _maskeli(parca, sablon, maske):
        """Sadece maskeli piksellerde normalize korelasyon (-1..1)."""
        if maske is None or parca.shape != sablon.shape:
            return -1.0
        a = parca[maske].astype(np.float32).ravel()
        b = sablon[maske].astype(np.float32).ravel()
        if a.size < 8:
            return -1.0
        a -= a.mean()
        b -= b.mean()
        payda = float(np.sqrt((a * a).sum() * (b * b).sum()))
        return float((a * b).sum() / payda) if payda > 1e-6 else 0.0

    def _adaylar(self, img, g, taban, adet=5):
        """Duz eslestirmeyle en iyi birkac aday (x, y, duz_puan)."""
        th, tw = g.bgr.shape[:2]
        if img.shape[0] < th or img.shape[1] < tw:
            return []
        r = cv2.matchTemplate(img, g.bgr, cv2.TM_CCOEFF_NORMED)
        np.nan_to_num(r, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        cikti = []
        for _ in range(adet):
            _, en, _, (x, y) = cv2.minMaxLoc(r)
            if en < taban:
                break
            cikti.append((x, y, float(en)))
            r[max(0, y - th // 2):y + th // 2 + 1, max(0, x - tw // 2):x + tw // 2 + 1] = -1
        return cikti

    def _puanla(self, img, g, x, y, duz):
        """Aday yeri: duz + maskeli puanin iyisi; merkez (orn. '4') tutmazsa 0."""
        th, tw = g.bgr.shape[:2]
        parca = img[y:y + th, x:x + tw]
        puan = max(duz, self._maskeli(parca, g.bgr, g.maske))
        if g.merkez is not None:
            x0, y0, x1, y1 = g.merkez
            m = g.maske[y0:y1, x0:x1]
            merkez = self._maskeli(parca[y0:y1, x0:x1], g.bgr[y0:y1, x0:x1], m)
            if merkez < float(self.e.get("merkez_esik", 0.55)):
                return 0.0
        return puan

    def _bolgede_ara(self, img, g, ofs, taban):
        en = (0.0, 0, 0)
        for x, y, duz in self._adaylar(img, g, taban):
            p = self._puanla(img, g, x, y, duz)
            if p > en[0]:
                en = (p, x + ofs[0], y + ofs[1])
        return en

    def _konum_kaydet(self, g, x, y, W, H):
        eski = self._konumlar.get(g.dosya)
        if eski and abs(eski[0] - x) <= 4 and abs(eski[1] - y) <= 4 and eski[2:] == [W, H]:
            return
        self._konumlar[g.dosya] = [int(x), int(y), int(W), int(H)]
        logging.info("Ek tiklama: '%s' konumu %s (%d,%d)", g.ad,
                     "ogrenildi" if not eski else "guncellendi", x, y)
        try:
            yol = os.path.join(klasor_yolu(self.cfg, self.bolum), "konumlar.json")
            with open(yol, "w", encoding="utf-8") as f:
                json.dump(self._konumlar, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def ara(self, kare, gorsel):
        """Dondurur: (puan, x, y) en iyi eslesme, kare koordinatinda sol-ust.
        Ogrenilmis konumda bulunursa puana bolge_toleransi eklenir (esnek esik)."""
        g = gorsel
        img = kare.bgr
        th, tw = g.bgr.shape[:2]
        H, W = img.shape[:2]
        gorsel.son_ham, gorsel.son_bolgede = 0.0, False
        if th > H or tw > W:
            return 0.0, 0, 0
        esik = float(self.e.get("esik", 0.85))
        tolerans = float(self.e.get("bolge_toleransi", 0.1)) if self.e.get("konum_ogren", self.bolum == "ek_tiklama") else 0.0
        taban = max(0.2, esik - tolerans - 0.3)

        # 1) ogrenilen konumun cevresi
        k = self._konumlar.get(g.dosya) if self.e.get("konum_ogren", self.bolum == "ek_tiklama") else None
        if k:
            sx, sy = W / float(k[2] or W), H / float(k[3] or H)
            pay = int(self.e.get("bolge_payi", 40))
            bx0, by0 = max(0, int(k[0] * sx) - pay), max(0, int(k[1] * sy) - pay)
            bx1, by1 = min(W, int(k[0] * sx) + tw + pay), min(H, int(k[1] * sy) + th + pay)
            p, x, y = self._bolgede_ara(img[by0:by1, bx0:bx1], g, (bx0, by0), taban)
            if p >= esik - tolerans:
                g.son_ham, g.son_bolgede = p, True
                if p >= esik:
                    self._konum_kaydet(g, x, y, W, H)
                return min(1.0, p + tolerans), x, y

        # 2) tum pencere
        p, x, y = self._bolgede_ara(img, g, (0, 0), taban)
        g.son_ham = p
        if p >= esik and self.e.get("konum_ogren", self.bolum == "ek_tiklama"):
            self._konum_kaydet(g, x, y, W, H)
        return p, x, y

    def bul(self, kare, esik=None):
        """Sadece arar, TIKLAMAZ. Dondurur: (gorsel, puan, merkez_x, merkez_y) ya da None."""
        self._klasor_degisti_mi()
        esik = float(self.e.get("esik", 0.85) if esik is None else esik)
        en_iyi = None
        for g in self.gorseller:
            puan, x, y = self.ara(kare, g)
            if puan >= esik and (en_iyi is None or puan > en_iyi[1]):
                th, tw = g.bgr.shape[:2]
                en_iyi = (g, puan, x + tw // 2, y + th // 2)
        return en_iyi

    def kontrol(self, kare, girdi, kare_al=None, durdu_mu=None):
        """Her dongude cagrilir. Bir resim bulup tikladiysa True.
        tiklama_oncesi_bekleme > 0 ise resim goruldukten sonra o kadar beklenir,
        resim hala ekrandaysa (yeni yerine) tiklanir."""
        if not self.e.get("aktif", False):
            return False
        self._klasor_degisti_mi()
        if not self.gorseller:
            return False
        simdi = time.time()
        if simdi - self._son_tarama < float(self.e.get("kontrol_araligi", 0.5)):
            return False
        self._son_tarama = simdi
        esik = float(self.e.get("esik", 0.85))
        bekleme = float(self.e.get("ayni_resim_bekleme", 3.0))
        for g in self.gorseller:
            if simdi - g.son_tik < bekleme:
                continue
            puan, x, y = self.ara(kare, g)
            if puan < esik:
                continue
            gecikme = float(self.e.get("tiklama_oncesi_bekleme", 2.0))
            if gecikme > 0:
                logging.info("Ek tiklama: '%s' goruldu (puan %.2f, gercek %.2f%s, konum %d,%d) "
                             "-> %.1f sn sonra tiklanacak", g.ad, puan, g.son_ham,
                             ", ogrenilen yerde" if g.son_bolgede else "", x, y, gecikme)
                bitis = time.time() + gecikme
                while time.time() < bitis:
                    if durdu_mu is not None and durdu_mu():
                        return True
                    time.sleep(min(0.1, max(0.0, bitis - time.time())))
                if kare_al is not None:
                    yeni = kare_al()
                    if yeni is not None:
                        puan, x, y = self.ara(yeni, g)
                        if puan < esik:
                            logging.info("Ek tiklama: '%s' beklerken kayboldu -> tiklanmadi", g.ad)
                            g.son_tik = time.time()
                            return True
            th, tw = g.bgr.shape[:2]
            cx = x + tw // 2 + random.randint(-max(1, tw // 8), max(1, tw // 8))
            cy = y + th // 2 + random.randint(-max(1, th // 8), max(1, th // 8))
            tutmayan = getattr(g, "tutmayan", 0)
            if tutmayan:                                # onceki tik tutmadi: SPACE'i birak
                birak = getattr(girdi, "zorla_birak", None)
                if birak:
                    birak()
                    time.sleep(0.12)
            if tutmayan % 3 == 2 and g.tur == "sol" and hasattr(girdi, "guclu_tikla"):
                girdi.guclu_tikla(cx, cy)
            elif tutmayan % 3 == 1 and g.tur == "sol":
                girdi.tikla(cx, cy)
            elif self.e.get("insansi", True) and hasattr(girdi, "yavas_tikla"):
                girdi.yavas_tikla(cx, cy, g.tur, self.e)
            elif g.tur == "sag":
                girdi.sag_tikla(cx, cy)
            else:
                girdi.tikla(cx, cy)
                if g.tur == "cift":
                    time.sleep(random.uniform(0.06, 0.11))
                    girdi.tikla(cx, cy)
            g.son_tik = time.time()
            g.tik_sayisi += 1
            logging.info("Ek tiklama -> '%s' (%s tik, puan %.2f, konum %d,%d, toplam %d)",
                         g.ad, g.tur, puan, cx, cy, g.tik_sayisi)
            time.sleep(float(self.e.get("tiklama_sonrasi_bekleme", 0.3)))
            # DOGRULA: resim hala ayni yerdeyse tiklama tutmamistir -> hemen tekrar denenecek
            if kare_al is not None:
                time.sleep(0.4)
                yeni = kare_al()
                if yeni is not None:
                    p2, x2, y2 = self.ara(yeni, g)
                    if p2 >= esik and abs(x2 - x) <= 6 and abs(y2 - y) <= 6:
                        g.tutmayan = tutmayan + 1
                        g.son_tik = 0.0
                        self._son_tarama = 0.0
                        logging.warning("Ek tiklama: '%s' TUTMADI (hala %d,%d'de) -> %d. kez, "
                                        "baska yontemle tekrar", g.ad, x2, y2, g.tutmayan)
                    else:
                        if tutmayan:
                            logging.info("Ek tiklama: '%s' %d. denemede tuttu", g.ad, tutmayan + 1)
                        g.tutmayan = 0
            return True
        return False
