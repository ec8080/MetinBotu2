# -*- coding: utf-8 -*-
"""
Resimle (sablonla) tas bulma.

Kullanicinin kestigi isim yazisi resimleri ("Karanlik Metin" gibi) ekranda
aranir. OCR'a gore cok daha hizlidir ve harf karistirma sorunu yoktur.

Netlik icin:
  * Eslestirme RENKTE degil "yazi maskesinde" yapilir (beyaz/yesil yazi
    pikselleri). Arka plan (kar, cimen, gece) degisse de yazi ayni kalir.
  * Yazi uzaklikla kuculdugu icin birden fazla olcekte aranir.
  * Bulunan her aday ikinci kez gri resimle ve yazi yogunluguyla dogrulanir.
  * Ayni yazinin farkli olceklerdeki kopyalari tek sonuca indirilir.

Sablonlar: <bot klasoru>/sablonlar/*.png
sablonlar/olcek.json: hangi sablon hangi pencere yuksekliginde kesildi
(farkli boyuttaki client'larda sablon otomatik olceklenir).
"""

import json
import logging
import os
import threading
import time

import cv2
import numpy as np

from yol import BURASI

UZANTILAR = (".png", ".jpg", ".jpeg", ".bmp")
ESIK_IZ = 50          # top-hat degeri bunun ustu = yazi pikseli


def resim_oku(yol):
    """Turkce karakterli yollarda da calisan okuma."""
    veri = np.fromfile(yol, dtype=np.uint8)
    return cv2.imdecode(veri, cv2.IMREAD_COLOR)


def resim_yaz(yol, img):
    ok, tampon = cv2.imencode(os.path.splitext(yol)[1] or ".png", img)
    if not ok:
        raise RuntimeError("Resim kodlanamadi: %s" % yol)
    tampon.tofile(yol)


def yazi_maskesi(bgr, e):
    """Isim yazisi pikselleri (beyaz/soluk parlak + istege bagli yesil) -> 0/255."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    parlak = hsv[:, :, 2] >= int(e.get("parlaklik_esigi", 185))
    soluk = hsv[:, :, 1] <= int(e.get("max_doygunluk", 90))
    maske = parlak & soluk
    if e.get("yesil_dahil", True):
        yesil = ((hsv[:, :, 0] >= 40) & (hsv[:, :, 0] <= 90) &
                 (hsv[:, :, 1] >= 80) & (hsv[:, :, 2] >= 170))
        maske = maske | yesil
    return maske.astype(np.uint8) * 255


def yazi_ozelligi(bgr, cekirdek=7):
    """Yazi 'izi': ince parlak cizgiler (beyaz-top-hat). Duz parlak zemin (kar,
    gokyuzu) sifira iner, siyah kenarli yazi parlak kalir. Arka plan ne olursa
    olsun yazi ayni gorunur -> eslestirme zeminden etkilenmez."""
    gri = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cekirdek, cekirdek))
    th = cv2.morphologyEx(gri, cv2.MORPH_TOPHAT, k)
    # parlaklik farki zemine gore degisir; ikili yapmak bunu esitler
    return np.where(th >= ESIK_IZ, 255, 0).astype(np.uint8)


def yaziya_kirp(bgr, e, pay=2):
    """Gevsek kesilmis resmi sadece yazinin oldugu kutuya daralt.
    Kullanici etrafinda bosluk birakarak kesse de sablon temiz olur."""
    m = yazi_ozelligi(bgr) > 0
    ys, xs = np.where(m)
    if xs.size < 10:
        return bgr
    h, w = m.shape
    x1, x2 = max(0, xs.min() - pay), min(w, xs.max() + 1 + pay)
    y1, y2 = max(0, ys.min() - pay), min(h, ys.max() + 1 + pay)
    return bgr[y1:y2, x1:x2]


def olcek_kayitlari(klasor):
    yol = os.path.join(klasor, "olcek.json")
    try:
        with open(yol, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def olcek_kaydet(klasor, dosya_adi, pencere_yuksekligi):
    kayit = olcek_kayitlari(klasor)
    kayit[dosya_adi] = int(pencere_yuksekligi)
    with open(os.path.join(klasor, "olcek.json"), "w", encoding="utf-8") as f:
        json.dump(kayit, f, ensure_ascii=False, indent=2)


def klasor_yolu(cfg):
    ad = cfg.get("tespit", {}).get("sablon_klasoru", "sablonlar")
    yol = ad if os.path.isabs(ad) else os.path.join(BURASI, ad)
    if not os.path.isdir(yol):
        os.makedirs(yol, exist_ok=True)
    return yol


class _Sablon:
    def __init__(self, ad, bgr, e):
        self.ad = ad
        self.bgr = bgr
        self.gri = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        self.maske = yazi_ozelligi(bgr)
        self.doluluk = float((self.maske > 0).mean())
        self._olcekli = {}         # olcek -> (maske_f32, gri)

    def olcekli(self, k):
        k = round(k, 3)
        sonuc = self._olcekli.get(k)
        if sonuc is None:
            h, w = self.maske.shape
            yw, yh = max(4, int(round(w * k))), max(4, int(round(h * k)))
            ara = cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR
            m = cv2.resize(self.maske, (yw, yh), interpolation=ara)
            m = cv2.GaussianBlur(m, (3, 3), 0).astype(np.float32)
            g = cv2.resize(self.gri, (yw, yh), interpolation=ara)
            sonuc = (m, g)
            self._olcekli[k] = sonuc
        return sonuc


class Bulunan:
    __slots__ = ("x", "y", "w", "h", "puan", "ad")

    def __init__(self, x, y, w, h, puan, ad):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.puan = puan
        self.ad = ad


class SablonBulucu:
    def __init__(self, cfg, goz=None, havuz=None):
        self.cfg = cfg
        self.goz = goz                 # isim eslestirme icin (hedef_isimler)
        self.havuz = havuz
        self.sablonlar = []
        self._kilit = threading.Lock()
        self._imza = None
        self._son_kontrol = 0.0
        self.son_sure = 0.0
        self.yukle()

    # ---------------- yukleme ----------------

    @property
    def t(self):
        return self.cfg.get("tespit", {})

    def _klasor_imzasi(self, klasor):
        try:
            return tuple(sorted((a, os.path.getmtime(os.path.join(klasor, a)))
                                for a in os.listdir(klasor)
                                if a.lower().endswith(UZANTILAR + (".json",))))
        except OSError:
            return None

    def yukle(self):
        klasor = klasor_yolu(self.cfg)
        e = self.cfg["isim_etiketi"]
        olcekler = olcek_kayitlari(klasor)
        istemci = self.cfg.get("_istemci")
        simdiki_y = istemci[1] if istemci else None
        yeni = []
        for ad in sorted(os.listdir(klasor)):
            if not ad.lower().endswith(UZANTILAR):
                continue
            bgr = resim_oku(os.path.join(klasor, ad))
            if bgr is None or bgr.size == 0:
                logging.warning("Sablon okunamadi: %s", ad)
                continue
            bgr = yaziya_kirp(bgr, e)
            s = _Sablon(os.path.splitext(ad)[0], bgr, e)
            if s.doluluk < 0.03:
                logging.warning("Sablon '%s' icinde yazi bulunamadi (beyaz/yesil yazi olmali), "
                                "atlandi", ad)
                continue
            # kesildigi pencere boyutu biliniyorsa bu client'a uyarla
            s.taban = 1.0
            kayit_y = olcekler.get(ad)
            if kayit_y and simdiki_y:
                s.taban = max(0.4, min(2.5, float(simdiki_y) / float(kayit_y)))
            yeni.append(s)
        with self._kilit:
            self.sablonlar = yeni
            self._imza = self._klasor_imzasi(klasor)
        if yeni:
            logging.info("Sablon: %d resim yuklendi (%s)", len(yeni),
                         ", ".join(s.ad for s in yeni[:5]) + (" ..." if len(yeni) > 5 else ""))
        return len(yeni)

    def _degisti_mi(self):
        """Klasore yeni resim eklenince bot durdurulmadan yeniden yuklenir."""
        simdi = time.time()
        if simdi - self._son_kontrol < 2.0:
            return
        self._son_kontrol = simdi
        if self._klasor_imzasi(klasor_yolu(self.cfg)) != self._imza:
            self.yukle()

    @property
    def hazir(self):
        return bool(self.sablonlar)

    def _aktif_sablonlar(self):
        """Hedef tas adi yazildiysa ve dosya adlari buna uyuyorsa sadece onlar.
        (3 client'a farkli tas: 'Ahmet Metini.png', 'Mehmet Metini.png' ...)"""
        with self._kilit:
            hepsi = list(self.sablonlar)
        isimler = [i for i in (self.cfg["ocr"].get("hedef_isimler") or []) if str(i).strip()]
        if not isimler or self.goz is None:
            return hepsi
        uyan = []
        for s in hepsi:
            d = self.goz._sadelestir(s.ad)
            if any(self.goz._isim_eslesmesi(d, i) == "hedef" for i in isimler):
                uyan.append(s)
        return uyan or hepsi

    # ---------------- arama ----------------

    def _tek_olcek(self, arg):
        ekran_m, ekran_g, s, k, esik, dogrulama = arg
        sm, sg = s.olcekli(k)
        th, tw = sm.shape
        if th < 5 or tw < 12 or th > ekran_m.shape[0] or tw > ekran_m.shape[1]:
            return []
        sonuc = cv2.matchTemplate(ekran_m, sm, cv2.TM_CCOEFF_NORMED)
        np.nan_to_num(sonuc, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        # yerel tepe noktalari (ayni yazi icin yuzlerce komsu pikseli eleme)
        tepe = cv2.dilate(sonuc, cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(3, tw // 2) | 1, max(3, th // 2) | 1)))
        ys, xs = np.where((sonuc >= esik) & (sonuc >= tepe - 1e-6))
        cikti = []
        if xs.size > 200:                       # cok fazla -> en iyileri
            sira = np.argsort(-sonuc[ys, xs])[:200]
            ys, xs = ys[sira], xs[sira]
        for y, x in zip(ys.tolist(), xs.tolist()):
            puan = float(sonuc[y, x])
            # 2. dogrulama: gri tonlu resim de benziyor mu?
            if dogrulama > 0:
                parca = ekran_g[y:y + th, x:x + tw]
                g = float(cv2.matchTemplate(parca, sg, cv2.TM_CCOEFF_NORMED)[0, 0])
                if not np.isfinite(g) or g < dogrulama:
                    continue
                puan = 0.75 * puan + 0.25 * g
            # 3. dogrulama: yazi yogunlugu sablona yakin mi (duz parlak alan degil)
            dol = float((ekran_m[y:y + th, x:x + tw] > 127).mean())
            if not (0.5 * s.doluluk <= dol <= 1.8 * s.doluluk + 0.02):
                continue
            cikti.append(Bulunan(x, y, tw, th, puan, s.ad))
        return cikti

    @staticmethod
    def _cakisir(a, b):
        return (abs((a.x + a.w / 2.0) - (b.x + b.w / 2.0)) < (a.w + b.w) * 0.3 and
                abs((a.y + a.h / 2.0) - (b.y + b.h / 2.0)) < (a.h + b.h) * 0.45)

    def bul(self, kare, bolge):
        """bolge=(x1,y1,x2,y2) karede. Dondurur: [Bulunan] (kare koordinati)"""
        self._degisti_mi()
        sablonlar = self._aktif_sablonlar()
        if not sablonlar:
            return []
        bas = time.time()
        x1, y1, x2, y2 = bolge
        kirp = kare.bgr[y1:y2, x1:x2]
        if kirp.size == 0:
            return []
        e = self.cfg["isim_etiketi"]
        ekran_m = cv2.GaussianBlur(yazi_ozelligi(kirp), (3, 3), 0).astype(np.float32)
        ekran_g = cv2.cvtColor(kirp, cv2.COLOR_BGR2GRAY)

        esik = float(self.t.get("esik", 0.75))
        dogrulama = float(self.t.get("dogrulama_esigi", 0.35))
        olcekler = self.t.get("olcekler") or [0.8, 0.9, 1.0, 1.1, 1.2]
        isler = [(ekran_m, ekran_g, s, s.taban * float(k), esik, dogrulama)
                 for s in sablonlar for k in olcekler]
        if self.havuz is not None and len(isler) > 1:
            parcalar = list(self.havuz.map(self._tek_olcek, isler))
        else:
            parcalar = [self._tek_olcek(i) for i in isler]

        adaylar = sorted((b for p in parcalar for b in p), key=lambda b: -b.puan)
        secilen = []
        for b in adaylar:
            if any(self._cakisir(b, s) for s in secilen):
                continue
            secilen.append(b)
            if len(secilen) >= int(self.t.get("max_sonuc", 25)):
                break
        for b in secilen:
            b.x += x1
            b.y += y1
        self.son_sure = time.time() - bas
        return secilen
