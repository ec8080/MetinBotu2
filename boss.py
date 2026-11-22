# -*- coding: utf-8 -*-
"""
Boss cagirma modulu (Isinlanma Sihirbazi / TAB paneli).

Akis:
  1. TAB'a basilir, isinlanma paneli acilir
  2. Panelde cagirma logolari (altin buton) sablon eslemesiyle bulunur
  3. Her logonun SOLUNDAKI isim hucresi OCR ile okunur
  4. Aranan boss gorunmuyorsa fare tekerlegiyle asagi kaydirilir ve tekrar bakilir
  5. Bulununca logoya tiklanir -> SPACE 2 sn basili tutulur -> 15 sn beklenir
  6. Cagirma basarili olunca oyun paneli EN USTE geri atar; sonraki boss icin
     kaydirma sifirdan yapilir
  7. Liste bitince TAB ile panel kapatilir

Tek basina denemek icin:  python boss.py
"""

import difflib
import json
import logging
import os
import random
import time

import cv2
import numpy as np

try:
    import pytesseract
except ImportError:
    pytesseract = None

import girdi
from yol import BURASI


# ----------------------------------------------------------------- yardimci

def _sadelestir(m):
    """Turkce karakterler ve OCR karisikliklarini normalize et."""
    m = (m or "").lower().strip()
    cevir = {"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c",
             "â": "a", "î": "i", "û": "u", "l": "i", "1": "i", "0": "o", "|": "i"}
    out = []
    for h in m:
        h = cevir.get(h, h)
        if h.isalnum() or h == " ":
            out.append(h)
    return " ".join("".join(out).split())


def _benzer(a, b):
    a, b = _sadelestir(a), _sadelestir(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _kelime_puani(okunan, hedef):
    """KELIME BAZLI eslesme. Hedefin HER kelimesi okunan yazida bulunmali.
    Boylece 'Mavi Ejderha Odasi' ile 'Altin Ejderha Zindani' karismaz:
    ortak kelime (ejderha) tek basina yetmez.
    Dondurur: (ortalama_puan, en_zayif_kelime_puani)"""
    o = _sadelestir(okunan).split()
    h = _sadelestir(hedef).split()
    if not o or not h:
        return 0.0, 0.0
    puanlar = []
    for kelime in h:
        en_iyi = 0.0
        for parca in o:
            r = difflib.SequenceMatcher(None, kelime, parca).ratio()
            if r > en_iyi:
                en_iyi = r
        puanlar.append(en_iyi)
    return sum(puanlar) / len(puanlar), min(puanlar)


def _bekle(deger):
    if isinstance(deger, (list, tuple)) and len(deger) == 2:
        time.sleep(random.uniform(float(deger[0]), float(deger[1])))
    else:
        time.sleep(float(deger))


# ----------------------------------------------------------------- ana sinif

class BossCagirici:
    def __init__(self, cfg, goz, girdi_nesnesi, hwnd, kare_al=None, gunluk=None):
        """
        cfg   : tum config (boss bolumu okunur)
        goz   : vision.Goz  (OCR ayarlari + tesseract yolu icin)
        girdi_nesnesi : girdi.Girdi  (on plan / arka plan tiklama)
        kare_al : parametresiz fonksiyon -> vision.Kare  (bot kendi yakalayicisini verir)
        """
        self.cfg = cfg
        self.b = cfg.get("boss", {})
        self.goz = goz
        self.girdi = girdi_nesnesi
        self.hwnd = hwnd
        self._kare_al_dis = kare_al
        self.log = gunluk or logging.info
        self.sablon = None
        self._sablon_yukle()
        self.son_tur = 0.0
        self.cagrilan = 0
        self.basarisiz = []
        self.pid = self._pid_bul()
        self.durum = {}          # boss adi -> son BASARILI cagirma zamani
        self.deneme = {}         # boss adi -> son DENEME zamani (bulunamayanlar icin)
        self.hata = {}           # boss adi -> ust uste kac kez bulunamadi
        self._durum_yukle()

    # ------------------------------------------------------------ hazirlik

    def _sablon_yukle(self):
        """Birden fazla cagirma butonu gorunumu olabilir (altin / koyu).
        logo.dosyalar listesi ya da tek logo.dosya."""
        lg = self.b.get("logo", {})
        adlar = lg.get("dosyalar") or [lg.get("dosya", "boss_logo.png")]
        self.sablonlar = []
        for ad in adlar:
            yol = os.path.join(BURASI, ad)
            if not os.path.exists(yol):
                self.log("UYARI: logo dosyasi yok: %s" % yol)
                continue
            img = cv2.imread(yol)
            if img is not None:
                self.sablonlar.append((ad, img))
        if self.sablonlar:
            self.log("Boss logolari yuklendi: %s"
                     % ", ".join("%s(%dx%d)" % (a, i.shape[1], i.shape[0])
                                 for a, i in self.sablonlar))
        else:
            self.log("UYARI: hic boss logosu yuklenemedi - boss_kalibrasyon.py ile olusturun")
        self.sablon = self.sablonlar[0][1] if self.sablonlar else None

    def hazir_mi(self):
        return bool(getattr(self, "sablonlar", None)) and bool(self.liste())

    def girisler(self):
        """[(ad, periyot_dakika)] - liste hem duz metin hem {"ad","dakika"} kabul eder."""
        varsayilan = float(self.b.get("periyot_dakika", 120))
        out = []
        for e in (self.b.get("liste") or []):
            if isinstance(e, dict):
                ad = str(e.get("ad", "")).strip()
                try:
                    dk = float(e.get("dakika", varsayilan))
                except (TypeError, ValueError):
                    dk = varsayilan
            else:
                ad, dk = str(e).strip(), varsayilan
            if ad:
                out.append((ad, dk))
        return out

    def liste(self):
        return [a for a, _ in self.girisler()]

    # ------------------------------------------------------- bekleme sureleri

    def _pid_bul(self):
        try:
            import win32process
            return int(win32process.GetWindowThreadProcessId(self.hwnd)[1])
        except Exception:
            return 0

    def _durum_yolu(self):
        return os.path.join(BURASI, "boss_durum_%d.json" % self.pid)

    def _son_durum_dosyasi(self):
        """Bu PID'in dosyasi yoksa, en son yazilan boss_durum_*.json'u bul.
        Oyun/bot yeniden baslatilinca PID degisiyor; bekleme sureleri
        sifirlanmasin diye son durum devralinir."""
        try:
            adaylar = []
            for ad in os.listdir(BURASI):
                if ad.startswith("boss_durum_") and ad.endswith(".json"):
                    tam = os.path.join(BURASI, ad)
                    adaylar.append((os.path.getmtime(tam), tam))
            if not adaylar:
                return None
            adaylar.sort()
            return adaylar[-1][1]
        except Exception:
            return None

    def _durum_yukle(self):
        """Bekleme sureleri korunur. Once bu PID'in dosyasi, yoksa en son
        kaydedilen durum devralinir (client yeniden acilinca sifirlanmasin)."""
        yol = self._durum_yolu()
        devralindi = False
        if not os.path.exists(yol):
            onceki = self._son_durum_dosyasi()
            if onceki:
                yol, devralindi = onceki, True
        try:
            with open(yol, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.durum = {k: float(v) for k, v in (d.get("durum") or {}).items()}
            self.deneme = {k: float(v) for k, v in (d.get("deneme") or {}).items()}
            self.hata = {k: int(v) for k, v in (d.get("hata") or {}).items()}
            if self.durum:
                self.log("Boss bekleme sureleri okundu (%d kayit)%s"
                         % (len(self.durum),
                            " - onceki oturumdan devralindi" if devralindi else ""))
            if devralindi:
                self._durum_kaydet()        # artik bu PID'in dosyasina yazilsin
        except Exception:
            self.durum, self.deneme, self.hata = {}, {}, {}

    def _durum_kaydet(self):
        try:
            with open(self._durum_yolu(), "w", encoding="utf-8") as f:
                json.dump({"durum": self.durum, "deneme": self.deneme,
                           "hata": self.hata}, f)
        except Exception as hata:
            logging.debug("boss durumu kaydedilemedi: %s", hata)

    def _tekrar_suresi(self, ad):
        """Bulunamayan boss icin bekleme: her basarisizlikta KATLANIR.
        5 -> 10 -> 20 -> 40 -> ... (max_tekrar_deneme_dakika ile sinirli)"""
        taban = float(self.b.get("tekrar_deneme_dakika", 5))
        tavan = float(self.b.get("max_tekrar_deneme_dakika", 60))
        n = max(1, int(self.hata.get(ad, 1)))
        return min(tavan, taban * (2 ** (n - 1))) * 60.0

    def _kalan(self, ad, dk):
        """Bu boss icin kac saniye kaldi (0 = vadesi geldi)."""
        simdi = time.time()
        son = self.durum.get(ad)
        kalan = 0.0 if son is None else max(0.0, (dk * 60.0) - (simdi - son))
        d = self.deneme.get(ad)
        if d is not None:
            kalan = max(kalan, max(0.0, self._tekrar_suresi(ad) - (simdi - d)))
        return kalan

    def _tetikleyebilir(self, ad):
        """Ust uste cok kez bulunamayan boss TEK BASINA tur baslatmaz;
        baska bir boss icin panel zaten acildiginda denenir."""
        limit = int(self.b.get("yalniz_deneme_limiti", 2))
        return limit <= 0 or int(self.hata.get(ad, 0)) < limit

    def genel_tur_kalan(self):
        """Tum bosslari deneme turuna kac saniye kaldi. 0 = simdi, None = kapali."""
        try:
            dk = float(self.b.get("genel_tur_dakika", 0) or 0)
        except (TypeError, ValueError):
            dk = 0.0
        if dk <= 0:
            return None
        son = self.durum.get("_genel_tur")
        if son is None:
            self.durum["_genel_tur"] = time.time()
            self._durum_kaydet()
            return dk * 60.0
        return max(0.0, dk * 60.0 - (time.time() - son))

    def genel_tur_zamani_mi(self):
        kalan = self.genel_tur_kalan()
        return kalan is not None and kalan <= 0.0

    def vadesi_gelenler(self, sadece_tetikleyici=False):
        out = []
        for ad, dk in self.girisler():
            if self._kalan(ad, dk) > 0.0:
                continue
            if sadece_tetikleyici and not self._tetikleyebilir(ad):
                continue
            out.append(ad)
        return out

    def _kare(self):
        if self._kare_al_dis is not None:
            return self._kare_al_dis()
        if self.girdi.arka_plan:
            return self.goz.yakala_pencere(self.hwnd)
        return self.goz.yakala(girdi.istemci_alani(self.hwnd))

    # ------------------------------------------------------------ gorme

    def _panel_kirp(self, kare):
        """Panel bolgesi (pencere oranlarina gore). None -> tum pencere."""
        p = self.b.get("panel_bolgesi")
        h, w = kare.bgr.shape[:2]
        if not p:
            return kare.bgr, 0, 0
        x1 = int(w * float(p.get("sol", 0.0)))
        y1 = int(h * float(p.get("ust", 0.0)))
        x2 = int(w * float(p.get("sag", 1.0)))
        y2 = int(h * float(p.get("alt", 1.0)))
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 - x1 < 40 or y2 - y1 < 40:
            return kare.bgr, 0, 0
        return kare.bgr[y1:y2, x1:x2], x1, y1

    def logolari_bul(self, kare):
        """Cagirma logolarinin kutularini dondurur: [(x, y, w, h)] istemci koord."""
        if not getattr(self, "sablonlar", None):
            return []
        lg = self.b.get("logo", {})
        esik = float(lg.get("esik", 0.93))
        kirp, ox, oy = self._panel_kirp(kare)
        if kirp.size == 0:
            return []
        adaylar = []
        tw = th = 0
        for _, sablon in self.sablonlar:
            sh, sw = sablon.shape[:2]
            if kirp.shape[0] < sh or kirp.shape[1] < sw:
                continue
            sonuc = cv2.matchTemplate(kirp, sablon, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(sonuc >= esik)
            adaylar += list(zip(xs.tolist(), ys.tolist(), sonuc[ys, xs].tolist()))
            tw, th = max(tw, sw), max(th, sh)
        if not adaylar:
            return []
        adaylar.sort(key=lambda a: -a[2])
        # sutun filtresi: kalibrasyonda kaydedildiyse sadece o x civari
        sut = lg.get("sutun_x")
        tol = int(lg.get("sutun_tolerans", 25))
        secilen = []
        for x, y, s in adaylar:
            if sut is not None and abs(x - int(sut)) > tol:
                continue
            if any(abs(x - a) < tw * 0.6 and abs(y - b) < th * 0.6 for a, b, _ in secilen):
                continue
            secilen.append((x, y, s))
        secilen.sort(key=lambda a: a[1])
        return [(x + ox, y + oy, tw, th) for x, y, _ in secilen]

    def _isim_oku(self, kare, kutu):
        """Logonun solundaki isim hucresini OCR ile oku."""
        if pytesseract is None:
            return ""
        i = self.b.get("isim", {})
        x, y, w, h = kutu
        sol_ofset = int(i.get("sol_ofset", 450))
        sag_ofset = int(i.get("sag_ofset", 250))
        dikey_pay = int(i.get("dikey_pay", 4))
        x1 = max(0, x - sol_ofset)
        x2 = max(x1 + 10, x - sag_ofset)
        y1 = max(0, y - dikey_pay)
        y2 = min(kare.bgr.shape[0], y + h + dikey_pay)
        hucre = kare.bgr[y1:y2, x1:x2]
        if hucre.size == 0:
            return ""
        k = int(i.get("buyutme", 3))
        buyuk = cv2.resize(hucre, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        gri = cv2.cvtColor(buyuk, cv2.COLOR_BGR2GRAY)
        # panelde acik yazi / koyu zemin -> ters cevirip esikle
        gri = cv2.threshold(gri, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        if np.mean(gri) < 127:
            gri = cv2.bitwise_not(gri)
        gri = cv2.copyMakeBorder(gri, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        try:
            return pytesseract.image_to_string(
                gri, lang=self.cfg["ocr"].get("dil", "tur+eng"),
                config="--psm 7 --oem 3").strip()
        except Exception as hata:
            logging.debug("boss OCR hatasi: %s", hata)
            return ""

    def satirlari_oku(self, kare=None):
        """Gorunen cagrilabilir satirlar: [(isim, kutu)]"""
        kare = kare if kare is not None else self._kare()
        if kare is None:
            return []
        out = []
        for kutu in self.logolari_bul(kare):
            out.append((self._isim_oku(kare, kutu), kutu))
        return out

    # ------------------------------------------------------------ hareket

    def _kaydirma_noktasi(self, kare):
        """Tekerlegin cevrilecegi nokta: panelin ortasi."""
        h, w = kare.bgr.shape[:2]
        p = self.b.get("panel_bolgesi")
        if p:
            x = w * (float(p.get("sol", 0)) + float(p.get("sag", 1))) / 2.0
            y = h * (float(p.get("ust", 0)) + float(p.get("alt", 1))) / 2.0
        else:
            x, y = w / 2.0, h / 2.0
        return int(x), int(y)

    def _kaydir(self, kare, yon=-1):
        k = self.b.get("kaydirma", {})
        x, y = self._kaydirma_noktasi(kare)
        self.girdi.tekerlek(x, y, yon * int(k.get("tik", 3)))
        _bekle(k.get("adim_bekleme", [0.35, 0.6]))

    def _en_uste_don(self, kare):
        k = self.b.get("kaydirma", {})
        if not k.get("yukari_sifirla", True):
            return
        x, y = self._kaydirma_noktasi(kare)
        self.girdi.tekerlek(x, y, int(k.get("tik", 3)) * int(k.get("max_adim", 8)) + 3)
        _bekle(k.get("adim_bekleme", [0.35, 0.6]))

    # ------------------------------------------------------------ cagirma

    def _eslesme(self, satirlar, isim):
        """Gorunen satirlar icinde bossu bulur. Yanlis tiklamayi onlemek icin:
        - hedefin her kelimesi satirda bulunmali (zayif_esigi)
        - en iyi ile ikinci arasinda belirgin fark olmali (ayirt_farki)"""
        i = self.b.get("isim", {})
        esik = float(i.get("benzerlik_esigi", 0.8))
        zayif_esigi = float(i.get("zayif_kelime_esigi", 0.6))
        ayirt = float(i.get("ayirt_farki", 0.1))

        puanli = []
        for okunan, kutu in satirlar:
            ort, zayif = _kelime_puani(okunan, isim)
            puanli.append((ort, zayif, okunan, kutu))
        # AYIRT EDICI kelime once: "Uyanis Su AZRAILI" ile "Uyanis Su KRALI"
        # ortalamada cok yakin, ama en zayif kelimede belirgin ayrilirlar.
        puanli.sort(key=lambda a: (-a[1], -a[0]))
        if not puanli:
            return None, 0.0

        ort, zayif, okunan, kutu = puanli[0]
        if ort < esik or zayif < zayif_esigi:
            self.log("  (en yakin satir: '%s' puan %.2f / ayirt %.2f - esik %.2f/%.2f)"
                     % (okunan, ort, zayif, esik, zayif_esigi))
            return None, ort
        if len(puanli) > 1:
            i_ort, i_zayif = puanli[1][0], puanli[1][1]
            rakip_gecerli = i_ort >= esik and i_zayif >= zayif_esigi
            if rakip_gecerli and (zayif - i_zayif) < ayirt and (ort - i_ort) < ayirt:
                self.log("  ! belirsiz: '%s' (%.2f/%.2f) ile '%s' (%.2f/%.2f) ayirt "
                         "edilemedi, tiklanmadi"
                         % (okunan, ort, zayif, puanli[1][2], i_ort, i_zayif))
                return None, ort
        return (okunan, kutu), ort

    def bossu_bul(self, isim):
        """Acik olan sekmede bossu arar (gerekirse kaydirir)."""
        k = self.b.get("kaydirma", {})
        max_adim = int(k.get("max_adim", 8))
        kare = self._kare()
        if kare is None:
            return None
        self._en_uste_don(kare)
        onceki_imza = None
        degismeyen = 0
        for adim in range(max_adim + 1):
            kare = self._kare()
            if kare is None:
                return None
            satirlar = self.satirlari_oku(kare)
            imza = tuple(_sadelestir(o) for o, _ in satirlar)
            if satirlar:
                self.log("  [adim %d] gorunen: %s"
                         % (adim, " | ".join(o or "?" for o, _ in satirlar)))
            else:
                self.log("  [adim %d] panelde cagirma logosu goruleMEDI" % adim)

            bulunan, puan = self._eslesme(satirlar, isim)
            if bulunan:
                self.log("  '%s' bulundu (okunan: '%s', puan %.2f)"
                         % (isim, bulunan[0], puan))
                return bulunan[1]

            if onceki_imza is not None and imza == onceki_imza and imza:
                degismeyen += 1
                if degismeyen >= int(self.b.get("kaydirma", {}).get("son_esigi", 1)):
                    if adim <= 1:
                        self.log("  ! KAYDIRMA CALISMIYOR: liste hic degismedi. "
                                 "config > boss > kaydirma > tik degerini artirin ya da "
                                 "boss_kalibrasyon.py'de 'k' ile test edin")
                    else:
                        self.log("  listenin sonuna gelindi (adim %d)" % adim)
                    break
            else:
                degismeyen = 0
            onceki_imza = imza

            if adim < max_adim:
                self._kaydir(kare, yon=-1)
        return None

    def cagir(self, isim):
        """Tek bir bossu cagirir. True = logoya tiklandi + space basildi."""
        z = self.b.get("zamanlayici", {})
        self.log("Boss araniyor: %s" % isim)
        kutu = self.bossu_bul(isim)
        if kutu is None:
            self.hata[isim] = int(self.hata.get(isim, 0)) + 1
            self.deneme[isim] = time.time()
            self.basarisiz.append(isim)
            not_ = ""
            if not self._tetikleyebilir(isim):
                not_ = " - bundan sonra SADECE panel zaten acikken denenecek"
            self.log("  BULUNAMADI: %s (%d. kez, %.0f dk sonra tekrar%s)"
                     % (isim, self.hata[isim], self._tekrar_suresi(isim) / 60.0, not_))
            self._durum_kaydet()
            return False
        x, y, w, h = kutu
        self._debug_kare(isim, kutu)
        self.girdi.tikla(x + w // 2, y + h // 2)
        self.log("  cagirma logosuna tiklandi (%d,%d)" % (x + w // 2, y + h // 2))
        time.sleep(float(z.get("cagirma_sonrasi_space_gecikmesi", 0.6)))
        self._cagirma_nesnesi()
        self._saldir(z)
        self.cagrilan += 1
        self.durum[isim] = time.time()
        self.deneme.pop(isim, None)
        self.hata.pop(isim, None)
        self._durum_kaydet()
        return True

    def _cagirma_nesnesi(self):
        """Bossu kendi uzerine cekmek icin kullanilan nesneye 1 kez SAG tikla.
        Nesne hizli slotta / ekranda sabit duruyor; yeri pencere orani olarak
        tutulur (boss_kalibrasyon.py'de 'n' tusu ile secilir)."""
        n = self.b.get("cagirma_nesnesi", {})
        if not n.get("aktif", False):
            return False
        kare = self._kare()
        if kare is None:
            return False
        h, w = kare.bgr.shape[:2]
        x = int(w * float(n.get("x", 0.5)))
        y = int(h * float(n.get("y", 0.9)))
        sapma = int(n.get("sapma", 3))
        if sapma > 0:
            x += random.randint(-sapma, sapma)
            y += random.randint(-sapma, sapma)
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        time.sleep(float(n.get("oncesi_bekleme", 0.3)))
        self.girdi.sag_tikla(x, y)
        self.log("  cagirma nesnesine sag tiklandi (%d,%d)" % (x, y))
        time.sleep(float(n.get("sonrasi_bekleme", 0.8)))
        return True

    def _saldir(self, z):
        """Cagirdiktan sonra saldiri. Bazi bosslarin hitboxu bozuk oldugu icin
        SPACE basili tutarken A/W/S/D'ye de basilir: karakter oldugu yerde yon
        degistirip saldirir, hangi yonden olursa olsun vurur.
        saldiri_yonleri bos ise sadece SPACE basili tutulur."""
        sure = float(z.get("space_basili_tutma", 2.0))
        yonler = self.b.get("saldiri_yonleri")
        if yonler is None:
            yonler = ["a", "w", "d", "s"]
        yonler = [y for y in yonler if str(y).strip()]
        if not yonler:
            self.girdi.tus_bas("space", sure)
            self.log("  SPACE %.1f sn basili tutuldu" % sure)
            return
        ara = float(z.get("yonler_arasi_bekleme", 0.15))
        for yon in yonler:
            self.girdi.tus_kombin(["space", str(yon).lower()], sure)
            time.sleep(ara)
        self.log("  SPACE + %s (her biri %.1f sn basili)"
                 % ("/".join(y.upper() for y in yonler), sure))

    def _debug_kare(self, isim, kutu):
        """Tiklamadan HEMEN once panelin resmini kaydet: nereye tiklandigi gorulur."""
        if not self.b.get("debug_kare", True):
            return
        try:
            kare = self._kare()
            if kare is None:
                return
            gorsel = kare.bgr.copy()
            x, y, w, h = kutu
            cv2.rectangle(gorsel, (x, y), (x + w, y + h), (0, 0, 255), 2)
            cv2.circle(gorsel, (x + w // 2, y + h // 2), 5, (0, 0, 255), -1)
            i = self.b.get("isim", {})
            x1 = max(0, x - int(i.get("sol_ofset", 450)))
            x2 = max(x1 + 10, x - int(i.get("sag_ofset", 250)))
            cv2.rectangle(gorsel, (x1, y), (x2, y + h), (255, 160, 0), 1)
            cv2.putText(gorsel, isim, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (0, 255, 255), 2)
            klasor = os.path.join(BURASI, "debug_boss")
            if not os.path.isdir(klasor):
                os.makedirs(klasor)
            ad = "".join(c if c.isalnum() else "_" for c in isim)[:40]
            yol = os.path.join(klasor, "%s_%s.png" % (time.strftime("%H%M%S"), ad))
            cv2.imwrite(yol, gorsel)
            self.log("  (kontrol goruntusu: debug_boss/%s)" % os.path.basename(yol))
        except Exception as hata:
            logging.debug("boss debug karesi kaydedilemedi: %s", hata)

    def tur(self, durdur_kontrol=None, hedefler=None):
        """Panel ac -> vadesi gelen bosslari sirayla cagir -> panel kapat.
        hedefler=None ise bekleme suresi dolmus bosslar alinir."""
        if not self.hazir_mi():
            self.log("Boss turu atlandi: logo sablonu ya da boss listesi yok")
            return False
        z = self.b.get("zamanlayici", {})
        genel = False
        if hedefler is not None:
            liste = list(hedefler)
        elif self.genel_tur_zamani_mi():
            # GENEL TUR: sureye bakmadan listedeki tum bosslari dene
            genel = True
            liste = self.liste()
            self.log("(genel tur: her %s dk'da tum bosslar deneniyor)"
                     % self.b.get("genel_tur_dakika"))
        else:
            # panel zaten acilacak: vadesi gelen HERKESI dene (zor bulunanlar dahil)
            tetikleyen = self.vadesi_gelenler(sadece_tetikleyici=True)
            liste = self.vadesi_gelenler() if tetikleyen else []
        if not liste:
            self.log("Boss turu atlandi: bekleme suresi dolan boss yok")
            self.son_tur = time.time()
            return False
        self.log("=== BOSS TURU BASLIYOR (%d boss: %s) ==="
                 % (len(liste), ", ".join(liste)))
        self.cagrilan = 0
        self.basarisiz = []

        self.girdi.tus_bas(self.b.get("panel_tusu", "tab"), 0.06)
        time.sleep(float(self.b.get("panel_acilma_bekleme", 1.5)))
        self._sekme_sec()

        for sira, isim in enumerate(liste):
            if durdur_kontrol and durdur_kontrol():
                self.log("Boss turu kullanici tarafindan durduruldu")
                break
            self.cagir(isim)
            if sira < len(liste) - 1:
                bekle = float(z.get("bosslar_arasi_bekleme", 15.0))
                self.log("  sonraki boss icin %.0f sn bekleniyor" % bekle)
                son = time.time() + bekle
                while time.time() < son:
                    if durdur_kontrol and durdur_kontrol():
                        break
                    time.sleep(0.2)

        time.sleep(float(z.get("kapatma_oncesi_bekleme", 1.0)))
        self.girdi.tus_bas(self.b.get("panel_tusu", "tab"), 0.06)
        time.sleep(float(self.b.get("panel_kapanma_bekleme", 0.8)))
        self.son_tur = time.time()
        if genel:
            self.durum["_genel_tur"] = time.time()
            self._durum_kaydet()
        self.log("=== BOSS TURU BITTI: %d cagrildi, %d bulunamadi (%s) ==="
                 % (self.cagrilan, len(self.basarisiz), ", ".join(self.basarisiz) or "-"))
        return True

    def _sekme_sec(self):
        """Panel acilinca belirli bir sekmeye tiklanmasi isteniyorsa."""
        s = self.b.get("sekme")
        if not s:
            return
        kare = self._kare()
        if kare is None:
            return
        h, w = kare.bgr.shape[:2]
        self.girdi.tikla(int(w * float(s.get("x", 0.5))), int(h * float(s.get("y", 0.1))))
        time.sleep(float(s.get("bekleme", 0.8)))

    # ------------------------------------------------------------ zamanlama

    def zamani_geldi_mi(self):
        """Herhangi bir bossun bekleme suresi doldu mu?"""
        if not self.b.get("aktif", False):
            return False
        # turlar arasi en az bu kadar beklensin (ust uste tur olmasin)
        ara = float(self.b.get("turlar_arasi_en_az_dakika", 1)) * 60.0
        if self.son_tur and (time.time() - self.son_tur) < ara:
            return False
        if self.genel_tur_zamani_mi():
            return True
        return bool(self.vadesi_gelenler(sadece_tetikleyici=True))

    def kalan_sure(self):
        """En yakin bossa (ya da genel tura) kac saniye kaldi."""
        kalanlar = [self._kalan(ad, dk) for ad, dk in self.girisler()]
        g = self.genel_tur_kalan()
        if g is not None:
            kalanlar.append(g)
        return min(kalanlar) if kalanlar else 0.0

    def durum_ozeti(self):
        """[(ad, periyot_dk, kalan_sn)] - GUI icin."""
        return [(ad, dk, self._kalan(ad, dk)) for ad, dk in self.girisler()]


# ----------------------------------------------------------------- tek basina

def main():
    import ayar
    from vision import Goz

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
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
            print("Arka plan goruntusu: Windows Graphics Capture")
        except Exception as hata:
            print("WGC yok (%s) -> PrintWindow" % hata)

    def kare_al():
        if gr.arka_plan and wgc is not None:
            return wgc.kare()
        if gr.arka_plan:
            return goz.yakala_pencere(hwnd)
        return goz.yakala(girdi.istemci_alani(hwnd))

    bc = BossCagirici(cfg, goz, gr, hwnd, kare_al=kare_al, gunluk=print)
    print("")
    print("Boss listesi:")
    for ad, dk in (bc.girisler() or []):
        print("   %-32s her %g dk  (kalan %.0f dk)" % (ad, dk, bc._kalan(ad, dk) / 60.0))
    print("Bu tur cagrilacaklar: %s" % (", ".join(bc.vadesi_gelenler()) or "(yok)"))
    print("3 saniye icinde oyuna gecin...")
    time.sleep(3)
    bc.tur()


if __name__ == "__main__":
    main()
