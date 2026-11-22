# -*- coding: utf-8 -*-
"""
Ekran okuma katmani.

Is akisi:
  1) Oyun penceresinin resmini al (mss).
  2) Arama bolgesinde "isim etiketi" gorunumundeki parlak/doygunlugu dusuk
     yazi bloklarini bul (metin taslarinin ustundeki yazi).
  3) Her blogu buyutup OCR'a ver, icinde "metin"/"metini" gecenleri hedef kabul et.
  4) Etiketin altindaki kutuda mavi isin var mi diye bak -> tas su an kesiliyor mu?
"""

import ctypes
import ctypes.wintypes
import difflib
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Tesseract her cagrida tum cekirdekleri kullanmaya calisir; biz zaten
# etiketleri paralel okudugumuz icin tek cekirdek cok daha hizli.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

import numpy as np
import cv2
import mss
import pytesseract

try:
    import win32gui
    import win32ui
except ImportError:
    win32gui = win32ui = None


_HAVUZ = None
_HAVUZ_KILIDI = threading.Lock()


def _ocr_havuzu(cfg):
    """Tum botlar (3 client) ayni OCR is havuzunu paylasir -> islemci bogulmaz."""
    global _HAVUZ
    with _HAVUZ_KILIDI:
        if _HAVUZ is None:
            n = int(cfg["ocr"].get("is_parcacigi", 0) or 0)
            if n <= 0:
                n = max(2, min(8, (os.cpu_count() or 4) - 1))
            _HAVUZ = ThreadPoolExecutor(max_workers=n, thread_name_prefix="ocr")
        return _HAVUZ


# genel kelimeler: bir ismi "hangi metin" olarak ayirt etmez
GENEL_KELIMELER = {"metin", "metini", "metni", "tas", "tasi", "lv", "seviye"}


class Kare:
    """Tek bir ekran goruntusu + pencere konumu."""

    def __init__(self, bgr, pencere_sol, pencere_ust):
        self.bgr = bgr
        self.sol = pencere_sol
        self.ust = pencere_ust

    def ekran_koordinati(self, x, y):
        return int(self.sol + x), int(self.ust + y)


class WgcYakalayici:
    """ARKA PLAN goruntusu: Windows Graphics Capture (Win10 1903+).
    PrintWindow'un SIYAH dondurdugu DirectX oyunlarini da yakalar; pencere
    baska pencerelerin arkasinda olsa bile calisir (simge durumunda calismaz).
    Gerekli:  pip install windows-capture"""

    def __init__(self, hwnd):
        from windows_capture import WindowsCapture   # yoksa ImportError
        self.hwnd = hwnd
        self.kullanan = 0
        self._kilit = threading.Lock()
        self._son = None
        self._son_zaman = 0.0
        self.hata = None
        self._kontrol = None
        baslik = win32gui.GetWindowText(hwnd) if win32gui else ""

        # Secenekler Windows surumune gore destekleniyor: Windows 10'da
        # draw_border/cursor_capture oturumu actirmayabiliyor ("Capture session
        # threw an exception"). En zengininden en sadesine dogru denenir.
        denemeler = []
        for pencere in ([{"window_hwnd": int(hwnd)}] + ([{"window_name": baslik}] if baslik else [])):
            for ekstra in ({"cursor_capture": False, "draw_border": False},
                           {"cursor_capture": False},
                           {}):
                denemeler.append(dict(pencere, **ekstra))

        son_hata = None
        for n, secenek in enumerate(denemeler):
            try:
                self._baslat(WindowsCapture(**secenek))
            except TypeError as hata:      # bu surumde olmayan secenek
                son_hata = hata
                continue
            except Exception as hata:
                son_hata = hata
                self._temizle()
                continue
            if self.kare(bekle=3.0) is not None:
                if "window_name" in secenek:
                    logging.warning("Yakalama pencere ADINA gore yapiliyor (%r). Ayni isimli "
                                    "birden fazla client varsa yanlis pencere yakalanabilir.", baslik)
                logging.debug("Windows Graphics Capture secenekleri: %s", secenek)
                return
            son_hata = self.hata or "goruntu gelmedi"
            self._temizle()
        raise RuntimeError("Windows Graphics Capture acilamadi (%s)" % (son_hata,))

    def _baslat(self, yakala):
        self.hata = None

        @yakala.event
        def on_frame_arrived(frame, kontrol):
            try:
                tampon = np.array(frame.frame_buffer, copy=True)
                with self._kilit:
                    self._son = tampon
                    self._son_zaman = time.time()
            except Exception as h:
                self.hata = str(h)

        @yakala.event
        def on_closed():
            self.hata = self.hata or "yakalama oturumu kapandi"

        self._kontrol = yakala.start_free_threaded()

    def _temizle(self):
        self.durdur()
        self._kontrol = None
        with self._kilit:
            self._son = None

    def _istemci_ofseti(self, gen, yuk):
        """WGC tum pencereyi (baslik cubugu dahil) verir -> istemci alanini kes."""
        _, _, w, h = win32gui.GetClientRect(self.hwnd)
        sx, sy = win32gui.ClientToScreen(self.hwnd, (0, 0))
        dikdortgen = ctypes.wintypes.RECT()
        try:
            # DWMWA_EXTENDED_FRAME_BOUNDS: gorunmez kenarliklar haric pencere siniri
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                self.hwnd, 9, ctypes.byref(dikdortgen), ctypes.sizeof(dikdortgen))
            ox, oy = dikdortgen.left, dikdortgen.top
        except Exception:
            ox, oy = win32gui.GetWindowRect(self.hwnd)[:2]
        x = max(0, min(gen - 1, sx - ox))
        y = max(0, min(yuk - 1, sy - oy))
        return x, y, min(w, gen - x), min(h, yuk - y)

    def kare(self, bekle=2.0):
        bitis = time.time() + bekle
        while True:
            with self._kilit:
                tampon = self._son
            if tampon is not None or time.time() > bitis:
                break
            time.sleep(0.03)
        if tampon is None:
            return None
        yuk, gen = tampon.shape[:2]
        x, y, w, h = self._istemci_ofseti(gen, yuk)
        bgr = cv2.cvtColor(tampon[y:y + h, x:x + w], cv2.COLOR_BGRA2BGR)
        sol, ust = win32gui.ClientToScreen(self.hwnd, (0, 0))
        return Kare(bgr, sol, ust)

    @property
    def taze_mi(self):
        return time.time() - self._son_zaman < 3.0

    def durdur(self):
        try:
            self._kontrol.stop()
        except Exception:
            pass


_WGC_KAYIT = {}
_WGC_KILIDI = threading.Lock()


def wgc_al(hwnd, deneme=3):
    """Bir pencere icin TEK yakalama oturumu tutulur ve paylasilir.
    (Ayni pencere icin ikinci oturum acmak 'Capture session threw an exception'
    hatasi veriyordu.) Hata olursa kisa araliklarla tekrar denenir."""
    with _WGC_KILIDI:
        kayit = _WGC_KAYIT.get(hwnd)
        if kayit is not None and kayit.hata is None:
            kayit.kullanan += 1
            return kayit
        _WGC_KAYIT.pop(hwnd, None)
        son_hata = None
        for n in range(deneme):
            try:
                y = WgcYakalayici(hwnd)
                y.kullanan = 1
                _WGC_KAYIT[hwnd] = y
                return y
            except ImportError:
                raise
            except Exception as hata:
                son_hata = hata
                logging.warning("Windows Graphics Capture denemesi %d/%d basarisiz: %r",
                                n + 1, deneme, hata)
                time.sleep(1.0)
        raise RuntimeError(son_hata)


def wgc_birak(hwnd):
    with _WGC_KILIDI:
        y = _WGC_KAYIT.get(hwnd)
        if y is None:
            return
        y.kullanan -= 1
        if y.kullanan <= 0:
            _WGC_KAYIT.pop(hwnd, None)
            y.durdur()


class Etiket:
    """Ekranda bulunan bir isim yazisi."""

    def __init__(self, kutu, yazi=""):
        self.x, self.y, self.w, self.h = kutu
        self.yazi = yazi
        self.hedef = False
        self.isin_var = False
        self.isin_orani = 0.0

    @property
    def merkez(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

    def __repr__(self):
        return "Etiket(%r @%s isin=%s %.3f)" % (
            self.yazi, self.merkez, self.isin_var, self.isin_orani
        )


class Goz:
    def __init__(self, cfg):
        self.cfg = cfg
        self._tesseract_ayarla(cfg["ocr"].get("tesseract_yolu"))
        self._sct = None           # mss, kullanan is parcaciginda olusturulur
        self._ocr_onbellek = {}   # kutu imzasi -> (zaman, yazi)
        self._havuz = _ocr_havuzu(cfg)
        self.son_ocr_hatasi = None
        self.ocr_hazir = self._ocr_dene()

    @staticmethod
    def _tesseract_ayarla(yol):
        """Once programin yanindaki Tesseract-OCR (paketlenmis .exe icin),
        sonra config'teki yol, sonra bilinen kurulum yerleri."""
        from yol import BURASI
        paket = os.path.join(BURASI, "Tesseract-OCR", "tesseract.exe")
        adaylar = [paket]
        adaylar += [yol] if yol else []
        adaylar += [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
        ]
        for a in adaylar:
            if a and os.path.exists(a):
                pytesseract.pytesseract.tesseract_cmd = a
                veri = os.path.join(os.path.dirname(a), "tessdata")
                if os.path.isdir(veri):
                    os.environ["TESSDATA_PREFIX"] = veri
                logging.debug("Tesseract: %s", a)
                return a
        return None

    def _ocr_dene(self):
        """Tesseract gercekten calisiyor mu? Calismiyorsa sebebini sakla.
        Turkce dil dosyasi yoksa Ingilizceye duser (isimler yine okunur)."""
        sinama = np.full((40, 160), 255, np.uint8)
        cv2.putText(sinama, "Metini", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
        dil = self.cfg["ocr"].get("dil", "tur+eng")
        try:
            pytesseract.image_to_string(sinama, lang=dil, config="--psm 7")
            return True
        except Exception as hata:
            self.son_ocr_hatasi = str(hata)
        if dil != "eng":
            try:
                pytesseract.image_to_string(sinama, lang="eng", config="--psm 7")
                logging.warning("Tesseract '%s' dil dosyasi yok -> 'eng' kullaniliyor", dil)
                self.cfg["ocr"]["dil"] = "eng"
                self.son_ocr_hatasi = None
                return True
            except Exception as hata:
                self.son_ocr_hatasi = str(hata)
        return False

    # ---------------- yakalama ----------------

    def yakala(self, rect):
        """ON PLAN: ekrandan kes. rect = (sol, ust, sag, alt) ekran koordinatlari.
        Kare koordinatlari pencerenin istemci alanina gore olur."""
        if self._sct is None:
            self._sct = mss.mss()
        sol, ust, sag, alt = rect
        mon = {"left": sol, "top": ust, "width": sag - sol, "height": alt - ust}
        ham = np.array(self._sct.grab(mon))
        return Kare(cv2.cvtColor(ham, cv2.COLOR_BGRA2BGR), sol, ust)

    @staticmethod
    def yakala_pencere(hwnd):
        """ARKA PLAN: pencerenin kendisinden resim iste (PrintWindow).
        Pencere baska pencerelerin arkasinda olsa da calisir, SIMGE DURUMUNDA
        (kucultulmus) ise calismaz. Bazi DirectX oyunlarinda siyah doner."""
        if win32gui is None:
            raise RuntimeError("pywin32 yok")
        _, _, w, h = win32gui.GetClientRect(hwnd)
        if w <= 0 or h <= 0:
            raise RuntimeError("Pencere simge durumunda ya da boyutu 0")
        hdc = win32gui.GetDC(hwnd)
        mfc = win32ui.CreateDCFromHandle(hdc)
        bellek = mfc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        try:
            bmp.CreateCompatibleBitmap(mfc, w, h)
            bellek.SelectObject(bmp)
            # 1 = PW_CLIENTONLY, 2 = PW_RENDERFULLCONTENT
            ctypes.windll.user32.PrintWindow(hwnd, bellek.GetSafeHdc(), 3)
            bits = bmp.GetBitmapBits(True)
            img = np.frombuffer(bits, np.uint8).reshape(h, w, 4)
            bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            bellek.DeleteDC()
            mfc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hdc)
        sol, ust = win32gui.ClientToScreen(hwnd, (0, 0))
        return Kare(bgr, sol, ust)

    @staticmethod
    def kare_bos_mu(kare):
        """PrintWindow siyah/tek renk dondurduyse True."""
        kucuk = cv2.resize(kare.bgr, (64, 48))
        return float(kucuk.std()) < 4.0

    def arama_bolgesi(self, kare):
        b = self.cfg["arama_bolgesi"]
        h, w = kare.bgr.shape[:2]
        return (int(w * b["sol"]), int(h * b["ust"]),
                int(w * b["sag"]), int(h * b["alt"]))

    # ---------------- etiket bulma ----------------

    def etiketleri_bul(self, kare):
        """Isim yazisi gorunumundeki bloklari dondur (henuz OCR yok)."""
        e = self.cfg["isim_etiketi"]
        x1, y1, x2, y2 = self.arama_bolgesi(kare)
        kirp = kare.bgr[y1:y2, x1:x2]
        if kirp.size == 0:
            return []

        hsv = cv2.cvtColor(kirp, cv2.COLOR_BGR2HSV)
        # YAZI mi ARKA PLAN mi: gokyuzu/kar da parlak ve soluktur (V~190, S~25) -
        # yazidan farki DUZ olmasi. Harflerin konturu yogun kenar uretir.
        min_kenar = float(e.get("min_kenar_yogunlugu", 20.0))
        kenar = None
        if min_kenar > 0:
            kenar = cv2.Canny(cv2.cvtColor(kirp, cv2.COLOR_BGR2GRAY), 60, 160)
        parlak = hsv[:, :, 2] >= e["parlaklik_esigi"]
        soluk = hsv[:, :, 1] <= e["max_doygunluk"]
        maske = (parlak & soluk)
        if e.get("yesil_dahil", True):
            # "Lv 100" kismi yesil yazilir -> etiketin tamami tek kutu olsun
            yesil = ((hsv[:, :, 0] >= 40) & (hsv[:, :, 0] <= 90) &
                     (hsv[:, :, 1] >= 80) & (hsv[:, :, 2] >= 170))
            maske = maske | yesil
        maske = maske.astype(np.uint8) * 255
        ham_maske = maske.copy()

        # harfleri tek bir satir blogu haline getir
        cekirdek = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(2, int(e["yatay_birlestirme"])), 2)
        )
        maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, cekirdek)
        maske = cv2.dilate(maske, cekirdek, iterations=1)

        konturlar, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        sonuc = []
        for k in konturlar:
            x, y, w, h = cv2.boundingRect(k)
            if not (e["min_genislik"] <= w <= e["max_genislik"] * 1.5):
                continue
            if h < e["min_yukseklik"] or h > e["max_yukseklik"] * 5:
                continue
            # Ust uste binmis yazilar (karakter adi + tas adi gibi) tek blok olur:
            # satirlara bol, her satiri ayri etiket say.
            for sx, sy, sw, sh in self._satirlara_bol(ham_maske, x, y, w, h, e):
                if not (e["min_genislik"] <= sw <= e["max_genislik"]):
                    continue
                if not (e["min_yukseklik"] <= sh <= e["max_yukseklik"]):
                    continue
                if sw < sh * 2.2:          # isim yazisi her zaman genis ve alcaktir
                    continue
                # doluluk birlestirilmemis maskede olculur: yazi pikselleri kutunun
                # bir kismini kaplar, kar/arayuz gibi duz parlak alanlar hepsini.
                doluluk = cv2.countNonZero(ham_maske[sy:sy + sh, sx:sx + sw]) / float(sw * sh)
                if doluluk < 0.06 or doluluk > 0.85:
                    continue
                if kenar is not None:
                    yogunluk = float(kenar[sy:sy + sh, sx:sx + sw].mean())
                    if yogunluk < min_kenar:
                        continue      # duz parlak alan (gokyuzu/kar) - yazi degil
                sonuc.append(Etiket((sx + x1, sy + y1, sw, sh)))
        return sonuc

    @staticmethod
    def _satirlara_bol(ham_maske, x, y, w, h, e):
        """Blogu bos satir araliklarindan yazi satirlarina ayir."""
        parca = ham_maske[y:y + h, x:x + w]
        satir_dolu = (parca > 0).sum(axis=1) > max(1, w * 0.01)
        kosular, bas = [], None
        for i, dolu in enumerate(list(satir_dolu) + [False]):
            if dolu and bas is None:
                bas = i
            elif not dolu and bas is not None:
                kosular.append([bas, i])
                bas = None
        if len(kosular) <= 1:
            return [(x, y, w, h)]
        # 1 piksellik bosluklari (harf ici) birlestir, cok ince parcalari at
        birlesik = [kosular[0]]
        for b0, b1 in kosular[1:]:
            if b0 - birlesik[-1][1] <= 1:
                birlesik[-1][1] = b1
            else:
                birlesik.append([b0, b1])
        min_sat = max(3, int(e["min_yukseklik"] * 0.6))
        satirlar = [(b0, b1) for b0, b1 in birlesik if b1 - b0 >= min_sat]
        if len(satirlar) <= 1:
            return [(x, y, w, h)]
        sonuc = []
        for b0, b1 in satirlar:
            ust, alt = max(0, b0 - 1), min(h, b1 + 1)
            sutun = np.where((parca[ust:alt] > 0).any(axis=0))[0]
            if sutun.size == 0:
                continue
            sonuc.append((x + int(sutun[0]), y + ust, int(sutun[-1] - sutun[0] + 1), alt - ust))
        return sonuc

    # ---------------- OCR ----------------

    def _imza(self, etiket):
        # yakin kareler arasinda ayni etiketi tekrar OCR etmemek icin kaba anahtar
        return (etiket.x // 12, etiket.y // 12, etiket.w // 12)

    def oku(self, kare, etiket, onbellek_suresi=1.5):
        imza = self._imza(etiket)
        simdi = time.time()
        kayit = self._ocr_onbellek.get(imza)
        if kayit and simdi - kayit[0] < onbellek_suresi:
            etiket.yazi = kayit[1]
            return etiket.yazi

        yazi = self._ocr_calistir(self._ocr_hazirla(kare, etiket))
        etiket.yazi = yazi
        self._ocr_onbellek[imza] = (simdi, yazi)
        return yazi

    def _ocr_hazirla(self, kare, etiket):
        """Iki farkli on-isleme dondurur:
        1) renk maskesi: sadece beyaz/yesil yazi pikselleri (kar zemininde en iyisi)
        2) Otsu esikleme (eski yontem, yedek)"""
        o = self.cfg["ocr"]
        pad = 4
        x1 = max(0, etiket.x - pad)
        y1 = max(0, etiket.y - pad)
        x2 = min(kare.bgr.shape[1], etiket.x + etiket.w + pad)
        y2 = min(kare.bgr.shape[0], etiket.y + etiket.h + pad)
        kirp = kare.bgr[y1:y2, x1:x2]
        if kirp.size == 0:
            return None
        k = int(o.get("buyutme", 3))

        buyuk = cv2.resize(kirp, None, fx=k + 1, fy=k + 1, interpolation=cv2.INTER_CUBIC)
        hsv = cv2.cvtColor(buyuk, cv2.COLOR_BGR2HSV)
        beyaz = (hsv[:, :, 2] >= 150) & (hsv[:, :, 1] <= 110)
        yesil = ((hsv[:, :, 0] >= 40) & (hsv[:, :, 0] <= 90) &
                 (hsv[:, :, 1] >= 70) & (hsv[:, :, 2] >= 140))
        maskeli = np.where(beyaz | yesil, 0, 255).astype(np.uint8)
        maskeli = cv2.copyMakeBorder(maskeli, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)

        gri = cv2.cvtColor(kirp, cv2.COLOR_BGR2GRAY)
        gri = cv2.resize(gri, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        gri = cv2.threshold(gri, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        otsu = cv2.bitwise_not(gri)   # tesseract koyu yazi/acik zemin ister
        return (maskeli, otsu)

    def _tesseract(self, gri):
        try:
            return pytesseract.image_to_string(
                gri, lang=self.cfg["ocr"].get("dil", "tur+eng"),
                config="--psm 7 --oem 3").strip()
        except Exception:
            return ""

    def _ocr_calistir(self, resimler):
        """Once maskeli resmi oku; metin tasi cikmazsa Otsu ile tekrar dene."""
        if resimler is None:
            return ""
        ilk = self._tesseract(resimler[0])
        if self.sinif(ilk) == "hedef":
            return ilk
        ikinci = self._tesseract(resimler[1])
        if self.sinif(ikinci) == "hedef":
            return ikinci
        return ilk if len(ilk.strip()) >= len(ikinci.strip()) else ikinci

    def toplu_oku(self, kare, etiketler, onbellek_suresi=1.5):
        """Birden fazla etiketi AYNI ANDA (paralel) oku.
        Tesseract'i tek tek cagirmak taramanin en yavas kismiydi."""
        simdi = time.time()
        okunacak = []
        for e in etiketler:
            kayit = self._ocr_onbellek.get(self._imza(e))
            if kayit and simdi - kayit[0] < onbellek_suresi:
                e.yazi = kayit[1]
            else:
                okunacak.append(e)
        if not okunacak:
            return
        resimler = [self._ocr_hazirla(kare, e) for e in okunacak]
        for e, yazi in zip(okunacak, self._havuz.map(self._ocr_calistir, resimler)):
            e.yazi = yazi
            self._ocr_onbellek[self._imza(e)] = (simdi, yazi)
        if len(self._ocr_onbellek) > 400:
            self._ocr_onbellek = {a: d for a, d in self._ocr_onbellek.items()
                                  if simdi - d[0] < 5.0}

    @staticmethod
    def _sadelestir(m):
        d = m
        # lower() yapmadan once tum harfleri guvenli bir sekilde donustur
        ceviriler = (
            ("ı", "i"), ("İ", "i"), ("I", "i"),
            ("ş", "s"), ("Ş", "s"),
            ("ğ", "g"), ("Ğ", "g"),
            ("ü", "u"), ("Ü", "u"),
            ("ö", "o"), ("Ö", "o"),
            ("ç", "c"), ("Ç", "c"),
            ("â", "a"), ("Â", "a")
        )
        for a, b in ceviriler:
            d = d.replace(a, b)
            
        d = d.lower()
        return "".join(k for k in d if k.isalnum() or k.isspace())

    @staticmethod
    def _benzer(a, b, esik):
        if not a or not b:
            return False
        if len(a) >= 4 and (a in b or b in a):
            return True
        # OCR'in sik karistirdigi harfler
        a = a.replace("rn", "m").replace("vv", "w").replace("0", "o").replace("1", "l")
        b = b.replace("rn", "m").replace("vv", "w").replace("0", "o").replace("1", "l")
        if a == b:
            return True
        return difflib.SequenceMatcher(None, a, b).ratio() >= esik

    def _isim_eslesmesi(self, d, isim):
        """d: sadelestirilmis OCR yazisi, isim: kullanicinin yazdigi tas adi.
        'hedef' : ismin AYIRT EDICI kelimeleri (Ahmet) okunuyor
        'benzer': sadece genel kelime (Metini) okunuyor -> baska bir metin olabilir
        None    : hic eslesme yok"""
        esik = float(self.cfg["ocr"].get("isim_benzerlik_esigi", 0.75))
        kelimeler = self._sadelestir(isim).split()
        ozel = [k for k in kelimeler if k not in GENEL_KELIMELER]
        genel = [k for k in kelimeler if k in GENEL_KELIMELER] or ["metin"]
        parcalar = d.split()
        bitisik = d.replace(" ", "")

        def var_mi(kelime, esik_):
            if kelime in bitisik:
                return True
            return any(self._benzer(kelime, p, esik_) for p in parcalar if len(p) >= 3)

        if ozel:
            if all(var_mi(k, esik) for k in ozel):
                return "hedef"
        elif all(var_mi(k, 0.72) for k in genel):
            return "hedef"
        if any(var_mi(k, 0.72) for k in genel) or var_mi("metin", 0.72):
            return "benzer"
        return None

    def sinif(self, yazi):
        """'hedef'   : aranan metin tasinin yazisi okundu
           'benzer'  : bir metin tasi ama adi aranan degil / tam okunamadi
                       (sadece hedef_isimler doluyken)
           'belirsiz': OCR bir sey okuyamadi (bos / birkac anlamsiz harf)
           'degil'   : okunakli ama baska bir yazi (oyuncu adi, arayuz)"""
        o = self.cfg["ocr"]
        d = self._sadelestir(yazi or "")
        if not d.strip():
            return "belirsiz"

        seviye = o.get("seviye_filtresi")
        seviye_ok = not seviye or str(seviye) in d

        isimler = [i for i in (o.get("hedef_isimler") or []) if str(i).strip()]
        if isimler:
            sonuc = None
            for isim in isimler:
                e = self._isim_eslesmesi(d, isim)
                if e == "hedef":
                    sonuc = "hedef"
                    break
                if e == "benzer":
                    sonuc = "benzer"
            if sonuc == "hedef":
                return "hedef" if seviye_ok else "benzer"
            if sonuc == "benzer":
                return "benzer"
        else:
            for kelime in o["anahtar_kelimeler"]:
                if self._sadelestir(kelime) in d:
                    return "hedef" if seviye_ok else "degil"

            # OCR harf karistirmis olabilir: kelime bazli bulanik eslesme
            esik = float(o.get("benzerlik_esigi", 0.72))
            for parca in d.split():
                if len(parca) < 4:
                    continue
                for kelime in o["anahtar_kelimeler"]:
                    if difflib.SequenceMatcher(None, parca, self._sadelestir(kelime)).ratio() >= esik:
                        return "hedef" if seviye_ok else "degil"

        harf = sum(1 for k in d if k.isalpha())
        rakam = sum(1 for k in d if k.isdigit())
        if harf < 5 and rakam < 4:
            return "belirsiz"
        return "degil"

    def hedef_mi(self, yazi):
        """Kesin karar. ocr.zorunlu=false ise belirsizler de hedef sayilir."""
        s = self.sinif(yazi)
        if s == "hedef":
            return True
        if s == "belirsiz":
            return not self.cfg["ocr"].get("zorunlu", True)
        return False

    # ---------------- mavi isin ----------------

    def isin_kontrol(self, kare, etiket):
        """Etiketin altindaki kutuda mavi isin var mi? -> tas su an kesiliyor."""
        i = self.cfg["isin"]
        if not i.get("kullan", False):
            etiket.isin_var, etiket.isin_orani = False, 0.0
            return False
        gw = int(etiket.w * i["kutu_genislik_carpani"])
        cx = etiket.x + etiket.w // 2
        x1 = max(0, cx - gw // 2)
        x2 = min(kare.bgr.shape[1], cx + gw // 2)
        y1 = max(0, etiket.y + etiket.h + int(i["kutu_ofset_y"]))
        y2 = min(kare.bgr.shape[0], y1 + int(i["kutu_yukseklik"]))
        kutu = kare.bgr[y1:y2, x1:x2]
        if kutu.size == 0:
            etiket.isin_var, etiket.isin_orani = False, 0.0
            return False

        hsv = cv2.cvtColor(kutu, cv2.COLOR_BGR2HSV)
        maske = cv2.inRange(hsv, np.array(i["hsv_alt"], np.uint8),
                            np.array(i["hsv_ust"], np.uint8))
        oran = cv2.countNonZero(maske) / float(maske.size)
        etiket.isin_orani = oran
        etiket.isin_var = oran >= i["min_oran"]
        return etiket.isin_var

    # ---------------- tek gecis ----------------

    def tara(self, kare, ayrinti=False):
        """Kareyi tara, hedef etiketleri (isin durumu isaretli) dondur.
        ayrinti=True ise (hedefler, tum_etiketler) dondurur."""
        hedefler, tumu = [], []
        etiketler = self.etiketleri_bul(kare)
        self.toplu_oku(kare, etiketler)
        for etiket in etiketler:
            etiket.hedef = self.hedef_mi(etiket.yazi)
            tumu.append(etiket)
            if not etiket.hedef:
                continue
            self.isin_kontrol(kare, etiket)
            hedefler.append(etiket)
        if ayrinti:
            return hedefler, tumu
        return hedefler


# =====================================================================
#  Hedef can bari (ekranin ustunde cikan "Lv.100 Korsan Metini  %9" bari)
# =====================================================================

class BarDurumu:
    def __init__(self):
        self.var = False          # ekranda hedef bari var mi
        self.isim = ""            # OCR ile okunan hedef ismi
        self.metin_mi = False     # hedef bir metin tasi mi
        self.yuzde = None         # 0-100 arasi can yuzdesi (bilinmiyorsa None)
        self.yuzde_dolgu = False  # yuzde yazidan degil bar renginden tahmin edildi
        self.can = None           # mutlak can ("37.597.133.802 / 400..." -> 37597133802)
        self.tam = None
        self.ham = ""             # bolgenin tum OCR ciktisi
        self.uyari = ""           # bolge yanlis gibiyse aciklama

    @property
    def imza(self):
        """Can degisti mi karsilastirmasi icin: mutlak can varsa o (cok hassas),
        yoksa yuzde."""
        if self.can is not None:
            return ("can", self.can)
        if self.yuzde is not None:
            return ("yuzde", round(self.yuzde, 1))
        return None

    def __repr__(self):
        return "Bar(var=%s metin=%s %%%s %r)" % (
            self.var, self.metin_mi, self.yuzde, self.isim[:30])


class HedefBari:
    """Hedeflenen metnin can barini okur.
    Iki yontem:
      yuzde_okuma = "ocr"   -> bolgedeki yaziyi okur, '%9' veya '12 / 400' ayristirir
      yuzde_okuma = "dolgu" -> barin renkli dolgu oranini olcer (OCR gerekmez)
    """

    def __init__(self, goz):
        self.goz = goz
        self.cfg = goz.cfg

    def bolge(self, kare):
        b = self.cfg["hedef_bari"]["bolge"]
        h, w = kare.bgr.shape[:2]
        return (int(w * b["sol"]), int(h * b["ust"]),
                int(w * b["sag"]), int(h * b["alt"]))

    def _dolgu_orani(self, kirp):
        hb = self.cfg["hedef_bari"]
        hsv = cv2.cvtColor(kirp, cv2.COLOR_BGR2HSV)
        maske = cv2.inRange(hsv, np.array(hb["dolgu_hsv_alt"], np.uint8),
                            np.array(hb["dolgu_hsv_ust"], np.uint8))
        # her sutunda dolgu rengi var mi -> soldan kac sutun dolu
        sutun = (maske.sum(axis=0) > 0)
        if sutun.size == 0:
            return None
        dolu = int(sutun.sum())
        return 100.0 * dolu / float(sutun.size)

    @staticmethod
    def _sayi(parca):
        rakam = re.sub(r"[^0-9]", "", parca)
        return float(rakam) if rakam else None

    @staticmethod
    def _can_ayristir(metin):
        """'37.597.133.802 / 400.000.000.000' -> (37597133802, 400000000000)"""
        for m in re.finditer(r"(\d[\d.,]*)\s*/\s*(\d[\d.,]*)", metin or ""):
            su_an = HedefBari._sayi(m.group(1))
            tam = HedefBari._sayi(m.group(2))
            if tam and su_an is not None and tam >= 1000 and su_an <= tam:
                return su_an, tam
        # OCR "/" isaretini kacirabiliyor: "400.000.000.000 400.000.000.000"
        grup = r"(\d{1,3}(?:[.,]\d{3}){2,})"
        for m in re.finditer(grup + r"\s*[/|lI\\]?\s*" + grup, metin or ""):
            su_an = HedefBari._sayi(m.group(1))
            tam = HedefBari._sayi(m.group(2))
            if tam and su_an is not None and su_an <= tam:
                return su_an, tam
        return None, None

    @staticmethod
    def _yuzde_ayristir(metin):
        """Once 'can / tam' sayilarindan hassas hesap, olmazsa '%9' yazisi.
        (ESKI HATA: bosluklar silindigi icin '%9  37.597' -> '%937' okunuyordu.)"""
        metin = metin or ""
        su_an, tam = HedefBari._can_ayristir(metin)
        if tam:
            return 100.0 * su_an / tam
        m = (re.search(r"%\s*(\d{1,3})(?![\d.,])", metin) or
             re.search(r"(?<![\d.,])(\d{1,3})\s*%", metin))
        if m:
            deger = float(m.group(1))
            if deger <= 100:
                return deger
        return None

    def oku(self, kare):
        d = BarDurumu()
        hb = self.cfg["hedef_bari"]
        if not hb.get("kullan", True):
            return d

        x1, y1, x2, y2 = self.bolge(kare)
        kirp = kare.bgr[y1:y2, x1:x2]
        if kirp.size == 0:
            return d

        yontem = hb.get("yuzde_okuma", "ocr")

        if yontem == "dolgu":
            oran = self._dolgu_orani(kirp)
            d.yuzde = oran
            d.var = oran is not None and oran > hb.get("bos_esigi_yuzde", 1.0)
            d.metin_mi = d.var      # isim okunmadigi icin varsayim
            return d

        # --- OCR yontemi ---
        gri = cv2.cvtColor(kirp, cv2.COLOR_BGR2GRAY)
        k = int(hb.get("buyutme", 2))
        gri = cv2.resize(gri, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        gri = cv2.threshold(gri, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        if gri.mean() < 127:
            gri = cv2.bitwise_not(gri)
        try:
            ham = pytesseract.image_to_string(
                gri, lang=self.cfg["ocr"].get("dil", "tur+eng"),
                config="--psm 6 --oem 3").strip()
        except Exception:
            ham = ""

        d.ham = ham
        d.isim = ham.splitlines()[0].strip() if ham else ""
        d.can, d.tam = self._can_ayristir(ham)
        d.yuzde = self._yuzde_ayristir(ham)
        d.metin_mi = self.goz.hedef_mi(d.isim) or self.goz.hedef_mi(ham)

        if d.yuzde is None and hb.get("ocr_basarisizsa_dolgu", True):
            oran = self._dolgu_orani(kirp)
            if oran is not None and oran > hb.get("bos_esigi_yuzde", 1.0):
                d.yuzde = oran
                d.yuzde_dolgu = True      # renkten tahmin: hasar olcumunde kullanilmaz

        if hb.get("yuzde_zorunlu", True):
            # SADECE can/yuzde okunduysa bar var sayilir.
            # Boylece tasin havada duran isim yazisi yanlislikla bar sanilmaz.
            d.var = d.yuzde is not None
            if bool(d.isim) and d.yuzde is None:
                d.uyari = ("Bolgede yazi okunuyor ama can/yuzde yok -> "
                           "bolge muhtemelen yanlis yerde")
        else:
            d.var = bool(d.isim) or d.yuzde is not None

        return d
