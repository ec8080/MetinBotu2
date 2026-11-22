# -*- coding: utf-8 -*-
"""
Metin Botu - Pencereli arayuz (coklu client)
Calistirma:  MetinBotu.exe   ya da   Baslat.bat   ya da   python gui.py

* Her client ayri is parcaciginda calisir, arayuz donmaz.
* Arka plan modunda birden fazla client ayni anda calisabilir.
* F12 = hepsini durdur, F11 = hepsini duraklat/devam
"""

import ctypes
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import girdi          # DPI farkindaligini en basta ayarlar
import ayar
from yol import BURASI, derlenmis_mi


# ---------------------------------------------------------------- log kopru

class KuyrukHandler(logging.Handler):
    def __init__(self, kuyruk):
        super().__init__()
        self.kuyruk = kuyruk

    def emit(self, kayit):
        try:
            self.kuyruk.put_nowait(self.format(kayit))
        except Exception:
            pass


class IstemciAdiFiltresi(logging.Filter):
    def filter(self, kayit):
        ad = kayit.threadName
        kayit.istemci = "GUI" if ad == "MainThread" else ad
        return True


def _sure_yaz(sn):
    return "-" if sn is None else "%.1f" % sn


def _saat_yaz(sn):
    sn = int(sn)
    return "%02d:%02d:%02d" % (sn // 3600, sn // 60 % 60, sn % 60)


# ---------------------------------------------------------------- arka plan testi

def arka_plan_testi(hwnd):
    """PrintWindow ile ekran okunuyor mu, PostMessage tiklamasi oyuna gidiyor mu?"""
    import cv2
    from vision import Goz, HedefBari

    log = logging.getLogger()
    log.info("=== ARKA PLAN TESTI ===")
    if girdi.odakta_mi(hwnd):
        log.warning("Oyun su an ONDE. Gercek test icin oyunu baska bir pencerenin "
                    "arkasinda birakin (simge durumuna KUCULTMEYIN).")
    cfg = ayar.pencere_icin_hazirla(hwnd)
    goz = Goz(cfg)
    bar = HedefBari(goz)

    # 1) goruntu: once Windows Graphics Capture, olmazsa PrintWindow
    wgc = None
    kare = None
    try:
        from vision import wgc_al, wgc_birak
        wgc = wgc_al(hwnd)
        kare = wgc.kare(bekle=3.0)
        if kare is None:
            log.warning("1a) Windows Graphics Capture kare vermedi: %s", wgc.hata or "zaman asimi")
        elif goz.kare_bos_mu(kare):
            log.warning("1a) Windows Graphics Capture da SIYAH dondu")
            kare = None
        else:
            log.info("1a) Windows Graphics Capture CALISIYOR")
    except ImportError:
        log.warning("1a) windows-capture kurulu degil -> komut isteminde: pip install windows-capture")
    except Exception as hata:
        log.warning("1a) Windows Graphics Capture hatasi: %s", hata)

    if kare is None and wgc is not None:
        wgc_birak(hwnd)
        wgc = None
    if kare is None:
        try:
            kare = goz.yakala_pencere(hwnd)
            if goz.kare_bos_mu(kare):
                log.error("1b) PrintWindow SIYAH dondu")
                kare = None
            else:
                log.info("1b) PrintWindow calisiyor")
        except Exception as hata:
            log.error("1b) PrintWindow hatasi: %s", hata)
    if kare is None:
        if wgc:
            wgc_birak(hwnd)
        return ("BASARISIZ: oyun arka planda okunamadi.\n"
                "windows-capture kurulu degilse: pip install windows-capture\n"
                "Kuruluysa ve yine olmuyorsa on plan modunu kullanin.")
    yol = os.path.join(BURASI, "debug_arkaplan.png")
    cv2.imwrite(yol, kare.bgr)
    log.info("   Goruntu (%dx%d) -> %s", kare.bgr.shape[1], kare.bgr.shape[0], yol)

    def yeni_kare():
        return wgc.kare() if wgc is not None else goz.yakala_pencere(hwnd)

    # 2) taslar
    hedefler, tumu = goz.tara(kare, ayrinti=True)
    log.info("2) Etiket: %d  Metin tasi: %d", len(tumu), len(hedefler))
    if not hedefler:
        if wgc:
            wgc_birak(hwnd)
        return ("Goruntu okunuyor ama tas bulunamadi.\n"
                "Ekranda tas gorunurken testi tekrarlayin.")

    # 3) tiklama
    once = bar.oku(kare)
    e = max(hedefler, key=lambda t: t.h * 100 + t.w)
    x = e.x + e.w // 2
    y = e.y + e.h + cfg["tiklama"]["hedef_ofset_y"]
    log.info("3) Arka plan tiklamasi gonderiliyor -> (%d, %d) %r", x, y, e.yazi)
    girdi.arka_tikla(hwnd, x, y, cfg.get("girdi", {}).get("arka_imlec", True))
    bitis = time.time() + 3.5
    try:
        while time.time() < bitis:
            time.sleep(0.3)
            k2 = yeni_kare()
            if k2 is None:
                continue
            b = bar.oku(k2)
            if b.var and (not once.var or b.imza != once.imza):
                log.info("3) Can bari cikti/degisti -> TIKLAMA CALISIYOR (%s)", b)
                return ("BASARILI: arka plan modu bu oyunda calisiyor.\n"
                        "Kontrol sekmesinde 'Arka plan' secip baslatabilirsiniz.")
    finally:
        if wgc:
            wgc_birak(hwnd)
    log.warning("3) Tiklamadan sonra can bari cikmadi.")
    return ("GORUNTU CALISIYOR ama tiklama kabul edilmedi.\n\n" + "Goruntu okunuyor ama oyun arka plan TIKLAMASINI kabul etmedi\n"
            "(ya da tas zaten seciliydi). Bir tas seciliyken ESC ile secimi kaldirip\n"
            "tekrar deneyin. Yine olmazsa on plan modunu kullanin.")


# ---------------------------------------------------------------- arayuz

TUS_YONTEM_ADLARI = {"mesaj": "1) Mesaj (varsayilan)",
                     "mesaj_char": "2) Mesaj + karakter",
                     "one_getir": "3) Bir anlik one getir (en garanti)",
                     "guclu": "4) Guclu (aktif mesaji + 3 kez bas-birak)"}


def _tus_yontem_kodu(ad):
    for k, v in TUS_YONTEM_ADLARI.items():
        if v == ad:
            return k
    return "mesaj"


OLUM_DAVRANIS = {"tikla": "Resme tikla (yeniden basla) ve devam et",
                 "durdur": "Bu client'i durdur"}


def _olum_kodu(ad):
    for k, v in OLUM_DAVRANIS.items():
        if v == ad:
            return k
    return "tikla"


TESPIT_ADLARI = {"ikisi": "Resim + OCR (onerilen)", "sablon": "Sadece resim (en hizli)",
                 "ocr": "Sadece OCR (eski)"}


def _tespit_kodu(ad):
    for k, v in TESPIT_ADLARI.items():
        if v == ad:
            return k
    return "ikisi"


KOLONLAR = [("pid", "PID", 60), ("pencere", "Pencere", 120), ("hedef", "Hedef tas", 130),
            ("durum", "Durum", 90),
            ("kirilan", "Kirilan", 60), ("takilma", "Takilma", 60), ("can", "Can", 60),
            ("gecis", "Gecis ort (sn)", 95), ("sure", "Sure", 70)]


class Arayuz:
    def __init__(self, kok):
        self.kok = kok
        self.botlar = {}            # hwnd -> (bot, thread)
        self.son_ozet = {}          # hwnd -> son ozet (bot durduktan sonra da gorunsun)
        self.vurucular = {}         # hwnd -> (CekmeVurma, thread)  (at ustu cekme vurma)
        self.son_vurucu = {}        # hwnd -> son ozet
        self.pencereler = {}        # hwnd -> (pid, baslik, rect)
        self.kuyruk = queue.Queue()

        kok.title("Metin Botu")
        kok.geometry("760x760")
        kok.minsize(640, 600)
        kok.protocol("WM_DELETE_WINDOW", self.kapat)

        self._log_kur()
        self.ham = ayar.yukle()

        defter = ttk.Notebook(kok)
        defter.pack(fill="both", expand=True, padx=8, pady=8)
        self.kontrol = self._kaydirilabilir_sekme(defter, "Kontrol")
        self.cekme = self._kaydirilabilir_sekme(defter, "At Üstü Çekme Vurma")
        self.boss_sekme = self._kaydirilabilir_sekme(defter, "Boss")
        self.zaman = self._kaydirilabilir_sekme(defter, "Zamanlayicilar")

        self._kontrol_sekmesi()
        self._boss_sekmesi()
        self._cekme_sekmesi()
        self._zaman_sekmesi()
        self.pencereleri_yenile()
        self._kisayollar()
        if girdi.yonetici_mi():
            logging.info("Yonetici olarak calisiyor (OK)")
        else:
            logging.warning("YONETICI DEGIL: oyun yonetici olarak aciksa tiklamalar oyuna "
                            "ULASMAZ. Programi yonetici olarak acin.")
            kok.title("Metin Botu  (yonetici degil!)")
        self._guncelle()

    # ---------- kaydirma ----------
    def _kaydirilabilir_sekme(self, defter, baslik):
        """Pencere kucukken asagidakilere ulasmak icin: sekme icerigi kaydirilabilir.
        Fare tekerlegi sekmenin her yerinde calisir (gunluk/liste kutularinin
        icindeyken onlar kayar)."""
        dis = ttk.Frame(defter)
        defter.add(dis, text=baslik)
        dis.rowconfigure(0, weight=1)
        dis.columnconfigure(0, weight=1)
        tuval = tk.Canvas(dis, highlightthickness=0, borderwidth=0)
        cubuk = ttk.Scrollbar(dis, orient="vertical", command=tuval.yview)
        tuval.configure(yscrollcommand=cubuk.set)
        tuval.grid(row=0, column=0, sticky="nsew")
        cubuk.grid(row=0, column=1, sticky="ns")
        try:
            tuval.configure(background=ttk.Style().lookup("TFrame", "background") or None)
        except tk.TclError:
            pass
        ic = ttk.Frame(tuval, padding=10)
        pencere = tuval.create_window((0, 0), window=ic, anchor="nw")

        def boyut(_=None):
            tuval.configure(scrollregion=tuval.bbox("all"))
            # icerik pencereden kisaysa doldursun, uzunsa kaydirilsin
            tuval.itemconfigure(pencere, width=tuval.winfo_width(),
                                height=max(ic.winfo_reqheight(), tuval.winfo_height()))
            if ic.winfo_reqheight() <= tuval.winfo_height():
                cubuk.grid_remove()
            else:
                cubuk.grid()
        ic.bind("<Configure>", boyut)
        tuval.bind("<Configure>", boyut)

        if not hasattr(self, "_kaydirmalar"):
            self._kaydirmalar = {}
            self.kok.bind_all("<MouseWheel>", self._tekerlek, add="+")
        self._kaydirmalar[str(dis)] = (tuval, ic)
        return ic

    def _tekerlek(self, olay):
        """Tekerlek: imlecin altindaki sekmeyi kaydir (gunluk/liste kutulari haric)."""
        w = olay.widget
        try:
            if w.winfo_class() in ("Text", "Treeview", "Listbox", "TCombobox",
                                   "TSpinbox", "Spinbox"):
                return
        except Exception:
            return
        while w is not None:
            kayit = self._kaydirmalar.get(str(w))
            if kayit is not None:
                tuval, ic = kayit
                if ic.winfo_reqheight() > tuval.winfo_height():
                    tuval.yview_scroll(-1 if olay.delta > 0 else 1, "units")
                return
            w = getattr(w, "master", None)

    # ---------- log ----------
    def _log_kur(self):
        kok_log = logging.getLogger()
        kok_log.setLevel(logging.INFO)
        h = KuyrukHandler(self.kuyruk)
        h.addFilter(IstemciAdiFiltresi())
        h.setFormatter(logging.Formatter("%(asctime)s [%(istemci)s] %(message)s", "%H:%M:%S"))
        kok_log.addHandler(h)
        # gunluk dosyasi: sorun olunca sonradan bakabilmek icin (gunluk.txt, en fazla ~2x2 MB)
        try:
            from logging.handlers import RotatingFileHandler
            dosya = RotatingFileHandler(os.path.join(BURASI, "gunluk.txt"), maxBytes=2_000_000,
                                        backupCount=1, encoding="utf-8")
            dosya.addFilter(IstemciAdiFiltresi())
            dosya.setFormatter(logging.Formatter(
                "%(asctime)s [%(istemci)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
            kok_log.addHandler(dosya)
        except Exception:
            pass

    # ---------- kontrol sekmesi ----------
    def _kontrol_sekmesi(self):
        f = self.kontrol
        f.columnconfigure(0, weight=1)

        # hedef tas adi
        ad = ttk.LabelFrame(f, text="Hedef tas adi", padding=6)
        ad.grid(row=0, column=0, sticky="ew")
        ad.columnconfigure(0, weight=1)
        isimler = self.ham["ocr"].get("hedef_isimler") or []
        self.hedef_ad = tk.StringVar(value=", ".join(isimler))
        giris = ttk.Entry(ad, textvariable=self.hedef_ad)
        giris.grid(row=0, column=0, sticky="ew")
        giris.bind("<Return>", lambda e: self.isim_uygula())
        ttk.Button(ad, text="Uygula", command=self.isim_uygula).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(ad, foreground="#666",
                  text="Ornek: Ahmet Metini   |   birden fazla: Ahmet Metini, Korsan Metini   |   "
                       "bos = tum metin taslari. 'Lv.100 (2.Seviye)' kismi yazilmaz."
                  ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        pb = ttk.Frame(ad)
        pb.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(pb, text="Secili pencere(ler)e ozel ata", command=self.pid_hedef_ata
                   ).pack(side="left")
        ttk.Button(pb, text="Ozel hedefi kaldir", command=self.pid_hedef_kaldir
                   ).pack(side="left", padx=6)
        ttk.Label(pb, foreground="#666",
                  text="Ozel hedefi olmayan pencere yukaridaki GENEL hedefe gider. "
                       "Satira cift tikla = o pencerenin hedefini yaz.").pack(side="left")

        # client listesi
        lst = ttk.LabelFrame(f, text="Oyun pencereleri (Ctrl/Shift ile birden fazla secin)", padding=6)
        lst.grid(row=1, column=0, sticky="nsew", pady=6)
        lst.columnconfigure(0, weight=1)
        self.tablo = ttk.Treeview(lst, columns=[k for k, _, _ in KOLONLAR], show="headings",
                                  height=5, selectmode="extended")
        for k, baslik, gen in KOLONLAR:
            self.tablo.heading(k, text=baslik)
            self.tablo.column(k, width=gen, anchor="w" if k == "pencere" else "center")
        self.tablo.grid(row=0, column=0, sticky="ew")
        self.tablo.bind("<Double-1>", self._satir_cift_tik)
        d = ttk.Frame(lst)
        d.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(d, text="Yenile", command=self.pencereleri_yenile).pack(side="left")
        self.tumunu_goster = tk.BooleanVar(value=False)
        ttk.Checkbutton(d, text="Tum pencereler", variable=self.tumunu_goster,
                        command=self.pencereleri_yenile).pack(side="left", padx=6)
        ttk.Button(d, text="Hangisi? (goster)", command=self.goster).pack(side="left", padx=6)

        # dugmeler
        b = ttk.Frame(f)
        b.grid(row=2, column=0, sticky="ew", pady=2)
        ttk.Button(b, text="Secilileri baslat", command=self.baslat).pack(side="left")
        ttk.Button(b, text="Secilileri durdur", command=self.secilileri_durdur).pack(side="left", padx=6)
        ttk.Button(b, text="Tumunu durdur (F12)", command=self.tumunu_durdur).pack(side="left")
        self.duraklat_btn = ttk.Button(b, text="Duraklat (F11)", command=self.duraklat)
        self.duraklat_btn.pack(side="left", padx=6)

        # mod
        mod = ttk.LabelFrame(f, text="Calisma modu", padding=6)
        mod.grid(row=3, column=0, sticky="ew", pady=4)
        mod.columnconfigure(0, weight=1)
        self.mod = tk.StringVar(value=self.ham.get("girdi", {}).get("mod", "on_plan"))
        ttk.Radiobutton(mod, text="Arka plan (oyun arkada kalabilir, birden fazla client)",
                        variable=self.mod, value="arka_plan").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(mod, text="On plan (gercek fare, oyun onde olmali, tek client)",
                        variable=self.mod, value="on_plan").grid(row=1, column=0, sticky="w")
        arac = ttk.Frame(mod)
        arac.grid(row=0, column=1, rowspan=2)
        ttk.Button(arac, text="Arka plan testi", command=self.arka_test).pack(fill="x")
        ttk.Button(arac, text="Teshis", command=self.teshis).pack(fill="x", pady=2)
        ttk.Button(arac, text="Kalibrasyon", command=self.kalibrasyon).pack(fill="x")
        ty = ttk.Frame(mod)
        ty.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(ty, text="Arka planda tus basma:").pack(side="left")
        self.tus_yontemi = tk.StringVar(value=TUS_YONTEM_ADLARI.get(
            self.ham.get("girdi", {}).get("arka_tus_yontemi", "mesaj"), TUS_YONTEM_ADLARI["mesaj"]))
        tyk = ttk.Combobox(ty, textvariable=self.tus_yontemi, state="readonly", width=34,
                           values=list(TUS_YONTEM_ADLARI.values()))
        tyk.pack(side="left", padx=6)
        tyk.bind("<<ComboboxSelected>>", lambda e: self.canli_uygula())
        ttk.Button(ty, text="Tus testi", command=self.tus_testi).pack(side="left")

        # secenekler
        sec = ttk.LabelFrame(f, text="Secenekler", padding=6)
        sec.grid(row=4, column=0, sticky="ew", pady=4)
        self.kamera = tk.BooleanVar(value=self.ham.get("kamera", {}).get("aktif", False))
        self.insansi = tk.BooleanVar(value=self.ham["guvenlik"].get("insansi_fare", True))
        self.oncelik = tk.BooleanVar(value=self.ham["ocr"].get("mod") == "oncelik")
        self.kare_kaydet = tk.BooleanVar(value=self.ham["gunluk"].get("kare_kaydet", False))
        ttk.Checkbutton(sec, text="E ile kamera cevirme (tas bulunamayinca / takilinca)",
                        variable=self.kamera, command=self.canli_uygula).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(sec, text="Insansi fare hareketi (on plan)",
                        variable=self.insansi, command=self.canli_uygula).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(sec, text="Adi tam okunamayan taslari da dene (oncelik modu, can bari dogrular)",
                        variable=self.oncelik, command=self.canli_uygula).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(sec, text="Hata ayiklama karelerini kaydet (debug klasoru)",
                        variable=self.kare_kaydet).grid(row=3, column=0, sticky="w")

        # metin kesme sirasinda pelerin
        mp = self.ham.get("metin_pelerin", {})
        pel = ttk.Frame(sec)
        pel.grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.mp_aktif = tk.BooleanVar(value=bool(mp.get("aktif", False)))
        ttk.Checkbutton(pel, text="Metin keserken pelerin bas", variable=self.mp_aktif,
                        command=self.metin_pelerin_uygula).pack(side="left")
        ttk.Label(pel, text="Tus:").pack(side="left", padx=(10, 2))
        self.mp_tus = tk.StringVar(value=str(mp.get("tus", "4")).upper())
        mtus = ttk.Combobox(pel, textvariable=self.mp_tus, width=5,
                            values=[str(i) for i in range(1, 10)] + ["0"] +
                            ["F%d" % i for i in range(1, 11)])
        mtus.pack(side="left")
        ttk.Label(pel, text="Kac sn'de bir:").pack(side="left", padx=(10, 2))
        self.mp_aralik = tk.StringVar(value="%.1f" % float(mp.get("aralik", 5.0)))
        msp = ttk.Spinbox(pel, from_=0.5, to=600, increment=0.5, width=6,
                          textvariable=self.mp_aralik, command=self.metin_pelerin_uygula)
        msp.pack(side="left")
        for w in (mtus, msp):
            w.bind("<<ComboboxSelected>>", lambda e: self.metin_pelerin_uygula())
            w.bind("<FocusOut>", lambda e: self.metin_pelerin_uygula())
            w.bind("<Return>", lambda e: self.metin_pelerin_uygula())

        # tespit yontemi (resimle bulma)
        tsp = ttk.Frame(sec)
        tsp.grid(row=4, column=0, sticky="w", pady=(6, 0))
        # (row=5: pelerin)
        ttk.Label(tsp, text="Tas bulma:").pack(side="left")
        self.tespit = tk.StringVar(value=TESPIT_ADLARI.get(
            self.ham.get("tespit", {}).get("yontem", "ikisi"), TESPIT_ADLARI["ikisi"]))
        kutu = ttk.Combobox(tsp, textvariable=self.tespit, state="readonly", width=24,
                            values=list(TESPIT_ADLARI.values()))
        kutu.pack(side="left", padx=6)
        kutu.bind("<<ComboboxSelected>>", lambda e: self.canli_uygula())
        ttk.Button(tsp, text="Ekrandan sablon kes", command=self.sablon_kes).pack(side="left")
        ttk.Button(tsp, text="Sablon testi", command=self.sablon_testi).pack(side="left", padx=4)
        ttk.Button(tsp, text="Klasor", command=self.sablon_klasoru).pack(side="left")

        # ek gorsel tiklama (taslardan bagimsiz)
        ekf = ttk.LabelFrame(f, text="Ek gorsel tiklama (taslardan bagimsiz)", padding=6)
        ekf.grid(row=5, column=0, sticky="ew", pady=4)
        self.ek_aktif = tk.BooleanVar(value=bool(self.ham.get("ek_tiklama", {}).get("aktif", False)))
        ttk.Checkbutton(ekf, text="Acik: eklenen resim ekranda gorununce tikla",
                        variable=self.ek_aktif, command=self.canli_uygula).pack(side="left")
        ttk.Button(ekf, text="Ekrandan resim kes", command=lambda: self.sablon_kes(ek=True)
                   ).pack(side="left", padx=(10, 4))
        ttk.Button(ekf, text="Test", command=self.ek_testi).pack(side="left")
        ttk.Button(ekf, text="Klasor", command=self.ek_klasoru).pack(side="left", padx=4)
        ttk.Label(ekf, text="Esik:").pack(side="left", padx=(10, 2))
        self.ek_esik = tk.StringVar(value="%.2f" % float(
            self.ham.get("ek_tiklama", {}).get("esik", 0.85)))
        es = ttk.Spinbox(ekf, from_=0.30, to=0.99, increment=0.01, width=5,
                         textvariable=self.ek_esik, command=self.ek_esik_uygula)
        es.pack(side="left")
        es.bind("<Return>", lambda e: self.ek_esik_uygula())
        es.bind("<FocusOut>", lambda e: self.ek_esik_uygula())
        ttk.Label(ekf, text="Bekle (sn):").pack(side="left", padx=(10, 2))
        self.ek_bekle = tk.StringVar(value="%.1f" % float(
            self.ham.get("ek_tiklama", {}).get("tiklama_oncesi_bekleme", 2.0)))
        bk = ttk.Spinbox(ekf, from_=0.0, to=60.0, increment=0.5, width=5,
                         textvariable=self.ek_bekle, command=self.ek_esik_uygula)
        bk.pack(side="left")
        bk.bind("<Return>", lambda e: self.ek_esik_uygula())
        bk.bind("<FocusOut>", lambda e: self.ek_esik_uygula())

        # log
        log_c = ttk.LabelFrame(f, text="Gunluk", padding=4)
        log_c.grid(row=6, column=0, sticky="nsew", pady=4)
        f.rowconfigure(6, weight=1)
        self.log = tk.Text(log_c, height=10, wrap="word", font=("Consolas", 9),
                           bg="#111", fg="#ddd", insertbackground="#ddd")
        kay = ttk.Scrollbar(log_c, command=self.log.yview)
        self.log.configure(yscrollcommand=kay.set)
        self.log.pack(side="left", fill="both", expand=True)
        kay.pack(side="right", fill="y")

    # ---------- zamanlayici sekmesi ----------
    # ---------- at ustu cekme vurma sekmesi ----------
    def _cekme_sekmesi(self):
        f = self.cekme
        f.columnconfigure(0, weight=1)
        c = self.ham.get("cekme_vurma", {})
        o = self.ham.get("olum_kontrol", {})

        ttk.Label(f, wraplength=680, foreground="#444",
                  text="Metin kesmeden AYRI calisir. Karakter atin ustunde yerinde durur: SPACE "
                       "surekli basili tutulur, sectigin tustaki pelerin belli araliklarla "
                       "basilir. Bir client ya metin kesmede ya burada calisir; istedigin zaman "
                       "durdurup digerine gecebilirsin. Pencereyi 'Kontrol' sekmesindeki "
                       "listeden sec. Calisma modunu asagidaki Ayarlar'dan sec: ON PLAN = oyun "
                       "penceresi one gelir, gercek klavye (coklu client'ta sirayla one gelir). "
                       "ARKA PLAN = oyun arkada kalir, tuslar pencereye mesajla gider (her client "
                       "ayni anda; oyun bunu kabul etmezse vurmaz)."
                  ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        ay = ttk.LabelFrame(f, text="Ayarlar", padding=8)
        ay.grid(row=1, column=0, sticky="ew")
        ttk.Label(ay, text="Pelerin tusu:").grid(row=0, column=0, sticky="w")
        self.cv_tus = tk.StringVar(value=str(c.get("pelerin_tusu", "4")).upper())
        tuslar = [str(i) for i in range(1, 10)] + ["0"] + ["F%d" % i for i in range(1, 11)]
        tk_tus = ttk.Combobox(ay, textvariable=self.cv_tus, values=tuslar, width=6)
        tk_tus.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(ay, text="Kac saniyede bir:").grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.cv_aralik = tk.StringVar(value="%.1f" % float(c.get("pelerin_araligi", 5.0)))
        ttk.Spinbox(ay, from_=0.5, to=600, increment=0.5, width=6,
                    textvariable=self.cv_aralik).grid(row=0, column=3, sticky="w", padx=6)
        ttk.Label(ay, foreground="#666", text="SPACE: surekli basili (vurus)"
                  ).grid(row=0, column=4, sticky="w", padx=(16, 0))
        ttk.Label(ay, text="Calisma modu:", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        self.cv_mod = tk.StringVar(value="on_plan" if c.get("on_plan", True) else "arka_plan")
        ttk.Radiobutton(ay, text="On plan (gercek klavye)", variable=self.cv_mod, value="on_plan",
                        command=self.cekme_uygula).grid(row=3, column=1, columnspan=2,
                                                        sticky="w", pady=(8, 0))
        ttk.Radiobutton(ay, text="Arka plan (mesajla, oyun arkada)", variable=self.cv_mod,
                        value="arka_plan", command=self.cekme_uygula).grid(
            row=3, column=3, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(ay, text="Arka planda pelerin yontemi:").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.cv_yontem = tk.StringVar(value=girdi.PELERIN_YONTEMLERI.get(
            str(c.get("pelerin_yontemi", "1")), girdi.PELERIN_YONTEMLERI["1"]))
        cvy = ttk.Combobox(ay, textvariable=self.cv_yontem, state="readonly", width=34,
                           values=list(girdi.PELERIN_YONTEMLERI.values()))
        cvy.grid(row=6, column=2, columnspan=3, sticky="w", pady=(4, 0))
        cvy.bind("<<ComboboxSelected>>", lambda e: self.cekme_uygula())
        ttk.Label(ay, text="Arka planda pelerin basili (sn):").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.cv_basili = tk.StringVar(value="%.1f" % float(c.get("pelerin_basili_sure", 1.0)))
        cvb = ttk.Spinbox(ay, from_=0.2, to=5, increment=0.1, width=5, textvariable=self.cv_basili,
                          command=self.cekme_uygula)
        cvb.grid(row=4, column=2, sticky="w", pady=(4, 0))
        cvb.bind("<FocusOut>", lambda e: self.cekme_uygula())
        cvb.bind("<Return>", lambda e: self.cekme_uygula())
        ttk.Label(ay, foreground="#666",
                  text="Mod degisikligi bir sonraki 'Secilileri baslat'ta uygulanir. Arka planda "
                       "SPACE surekli basili, pelerin asagidaki yontemle bu kadar sn gonderilir. "
                       "Yontem calisirken de degistirilebilir."
                  ).grid(row=5, column=0, columnspan=5, sticky="w", pady=(2, 0))
        # --- belirli konuma sag tik (SPACE + pelerin devam ederken) ---
        st = ttk.Frame(ay)
        st.grid(row=7, column=0, columnspan=5, sticky="w", pady=(8, 0))
        self.cv_sag_aktif = tk.BooleanVar(value=bool(c.get("sag_tik_aktif", False)))
        ttk.Checkbutton(st, text="Konuma sag tikla", variable=self.cv_sag_aktif,
                        command=self.cekme_uygula).pack(side="left")
        ttk.Label(st, text="  her (sn):").pack(side="left")
        self.cv_sag_aralik = tk.StringVar(value="%.1f" % float(c.get("sag_tik_araligi", 5.0)))
        sa = ttk.Spinbox(st, from_=0.3, to=600, increment=0.5, width=6,
                         textvariable=self.cv_sag_aralik, command=self.cekme_uygula)
        sa.pack(side="left", padx=4)
        sa.bind("<FocusOut>", lambda e: self.cekme_uygula())
        sa.bind("<Return>", lambda e: self.cekme_uygula())
        self.cv_sag_xy = (c.get("sag_tik_x"), c.get("sag_tik_y"))
        self.cv_sag_etiket = ttk.Label(st, foreground="#666", text=self._sag_konum_yazi())
        ttk.Button(st, text="Konum sec", command=self._sag_konum_sec).pack(side="left", padx=(8, 4))
        self.cv_sag_etiket.pack(side="left")

        # --- arka planda pelerini fareyle kullan (F1 arkada oyuna gitmiyor) ---
        pf = ttk.Frame(ay)
        pf.grid(row=8, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.cv_pt_aktif = tk.BooleanVar(value=bool(c.get("pelerin_tik_aktif", False)))
        ttk.Checkbutton(pf, text="Arka planda pelerini FAREYLE kullan (F1 yerine kutuya tikla)",
                        variable=self.cv_pt_aktif, command=self.cekme_uygula).pack(side="left")
        self.cv_pt_tur = tk.StringVar(value="Sag tik" if c.get("pelerin_tik_tur") == "sag"
                                      else "Sol tik")
        ptt = ttk.Combobox(pf, textvariable=self.cv_pt_tur, values=["Sol tik", "Sag tik"],
                           state="readonly", width=7)
        ptt.pack(side="left", padx=6)
        ptt.bind("<<ComboboxSelected>>", lambda e: self.cekme_uygula())
        self.cv_pt_imlec = tk.BooleanVar(value=bool(c.get("pelerin_tik_imlec", False)))
        ttk.Checkbutton(pf, text="imlec gidip gelsin", variable=self.cv_pt_imlec,
                        command=self.cekme_uygula).pack(side="left", padx=(0, 4))
        self.cv_pt_xy = (c.get("pelerin_tik_x"), c.get("pelerin_tik_y"))
        self.cv_pt_etiket = ttk.Label(pf, foreground="#666", text=self._xy_yazi(self.cv_pt_xy))
        ttk.Button(pf, text="Konum sec", command=lambda: self._konum_sec(
            self.cv_pt_etiket, "cv_pt_xy", "Pelerin kutusu")).pack(side="left", padx=(4, 4))
        self.cv_pt_etiket.pack(side="left")

        ttk.Label(ay, text="Coklu client:", font=("Segoe UI", 9, "bold")).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(ay, text="her client'ta kal (sn):").grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.cv_tur = tk.StringVar(value="%.1f" % float(c.get("sirali_tur_suresi", 2.0)))
        tur = ttk.Spinbox(ay, from_=0.5, to=60, increment=0.5, width=6, textvariable=self.cv_tur,
                          command=self.cekme_uygula)
        tur.grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Label(ay, text="o surede pelerin:").grid(row=1, column=3, sticky="w", padx=(16, 0),
                                                       pady=(8, 0))
        self.cv_tur_pel = tk.StringVar(value=str(int(c.get("sirali_tur_pelerin", 3))))
        tpel = ttk.Spinbox(ay, from_=0, to=20, increment=1, width=5, textvariable=self.cv_tur_pel,
                           command=self.cekme_uygula)
        tpel.grid(row=1, column=4, sticky="w", pady=(8, 0))
        ttk.Label(ay, foreground="#666", wraplength=640,
                  text="Birden fazla pencere secersen client'lar SIRAYLA one gelir: her birinde "
                       "SPACE'e yeniden basilip pelerin basilir, sonra SPACE basiliyken "
                       "siradakine gecilir. Arkada kalanlar vurmaya devam eder. (Tek pencerede "
                       "ustteki 'Kac saniyede bir' gecerli.)"
                  ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))
        for w in (tk_tus, tur, tpel):
            w.bind("<<ComboboxSelected>>", lambda e: self.cekme_uygula())
            w.bind("<FocusOut>", lambda e: self.cekme_uygula())
            w.bind("<Return>", lambda e: self.cekme_uygula())

        ol = ttk.LabelFrame(f, text="Olum kontrolu", padding=8)
        ol.grid(row=2, column=0, sticky="ew", pady=8)
        self.olum_aktif = tk.BooleanVar(value=bool(o.get("aktif", True)))
        ttk.Checkbutton(ol, text="Acik", variable=self.olum_aktif,
                        command=self.cekme_uygula).grid(row=0, column=0, sticky="w")
        ttk.Label(ol, text="Olunce:").grid(row=0, column=1, sticky="w", padx=(12, 2))
        self.olum_davranis = tk.StringVar(
            value=OLUM_DAVRANIS.get(o.get("davranis", "tikla"), OLUM_DAVRANIS["tikla"]))
        od = ttk.Combobox(ol, textvariable=self.olum_davranis, state="readonly", width=34,
                          values=list(OLUM_DAVRANIS.values()))
        od.grid(row=0, column=2, sticky="w")
        od.bind("<<ComboboxSelected>>", lambda e: self.cekme_uygula())
        ttk.Label(ol, text="Dirilince bas:").grid(row=0, column=3, sticky="w", padx=(12, 2))
        self.olum_tuslar = tk.StringVar(value=", ".join(
            o.get("dirilince_basilacak_tuslar", ["ctrl+g"]) or []))
        ot = ttk.Entry(ol, textvariable=self.olum_tuslar, width=12)
        ot.grid(row=0, column=4, sticky="w")
        ot.bind("<FocusOut>", lambda e: self.cekme_uygula())
        ot.bind("<Return>", lambda e: self.cekme_uygula())
        sr = ttk.Frame(ol)
        sr.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.olum_sureler = {}
        for anahtar, etiket, vars_ in (
                ("tiklama_oncesi_bekleme", "Olunce bekle (sn):", 10.0),
                ("dirilme_sonrasi_bekleme", "Tikladiktan sonra ctrl+g'ye kadar:", 0.5),
                ("tus_sonrasi_bekleme", "Ata bindikten sonra SPACE'e kadar:", 2.5)):
            ttk.Label(sr, text=etiket).pack(side="left", padx=(0, 2))
            v = tk.StringVar(value="%.1f" % float(o.get(anahtar, vars_)))
            sp = ttk.Spinbox(sr, from_=0, to=120, increment=0.5, width=5, textvariable=v,
                             command=self.cekme_uygula)
            sp.pack(side="left", padx=(0, 12))
            sp.bind("<FocusOut>", lambda e: self.cekme_uygula())
            sp.bind("<Return>", lambda e: self.cekme_uygula())
            self.olum_sureler[anahtar] = v
        ob = ttk.Frame(ol)
        ob.grid(row=3, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Button(ob, text="Ekrandan olum resmi kes", command=lambda: self.sablon_kes(olum=True)
                   ).pack(side="left")
        ttk.Button(ob, text="Test", command=self.olum_testi).pack(side="left", padx=4)
        ttk.Button(ob, text="Klasor", command=self.olum_klasoru).pack(side="left")
        ttk.Label(ol, foreground="#666", wraplength=640,
                  text="Hazir resim: 'Burada yeniden basla' butonu. Olunce o butona insansi "
                       "tiklanir, karakter dirilince 'Dirilince bas' tuslari basilir (ctrl+g = "
                       "ata bin; birden fazla: virgulle), sonra vurusa devam edilir. Ek gorsel "
                       "tiklama (Kontrol sekmesi) aciksa burada da calisir."
                  ).grid(row=4, column=0, columnspan=5, sticky="w", pady=(6, 0))

        b = ttk.Frame(f)
        b.grid(row=3, column=0, sticky="w", pady=4)
        ttk.Button(b, text="Secilileri baslat", command=self.cekme_baslat).pack(side="left")
        ttk.Button(b, text="Secilileri durdur", command=self.cekme_secili_durdur
                   ).pack(side="left", padx=6)
        ttk.Button(b, text="Tumunu durdur (F12)", command=self.tumunu_durdur).pack(side="left")

        self.cekme_durum = ttk.Label(f, foreground="#225", text="")
        self.cekme_durum.grid(row=4, column=0, sticky="w", pady=(6, 0))

    def _cekme_yaz(self, cfg):
        if not hasattr(self, "cv_tus"):
            return
        c = cfg.setdefault("cekme_vurma", {})
        if hasattr(self, "cv_mod"):
            c["on_plan"] = self.cv_mod.get() != "arka_plan"
        if hasattr(self, "cv_yontem"):
            for k, v in girdi.PELERIN_YONTEMLERI.items():
                if v == self.cv_yontem.get():
                    c["pelerin_yontemi"] = k
        if hasattr(self, "cv_basili"):
            try:
                c["pelerin_basili_sure"] = max(0.2, float(self.cv_basili.get().replace(",", ".")))
            except ValueError:
                pass
        if hasattr(self, "cv_pt_aktif"):
            c["pelerin_tik_aktif"] = bool(self.cv_pt_aktif.get())
            c["pelerin_tik_tur"] = "sag" if self.cv_pt_tur.get() == "Sag tik" else "sol"
            c["pelerin_tik_imlec"] = bool(self.cv_pt_imlec.get())
            x, y = self.cv_pt_xy
            if x is not None and y is not None:
                c["pelerin_tik_x"], c["pelerin_tik_y"] = int(x), int(y)
        if hasattr(self, "cv_sag_aktif"):
            c["sag_tik_aktif"] = bool(self.cv_sag_aktif.get())
            try:
                c["sag_tik_araligi"] = max(0.3, float(self.cv_sag_aralik.get().replace(",", ".")))
            except ValueError:
                pass
            x, y = self.cv_sag_xy
            if x is not None and y is not None:
                c["sag_tik_x"], c["sag_tik_y"] = int(x), int(y)
        tus = self.cv_tus.get().strip().lower()
        if tus:
            c["pelerin_tusu"] = tus
        try:
            c["pelerin_araligi"] = max(0.5, float(self.cv_aralik.get().replace(",", ".")))
        except ValueError:
            pass
        try:
            c["sirali_tur_suresi"] = max(0.5, float(self.cv_tur.get().replace(",", ".")))
            c["sirali_tur_pelerin"] = max(0, int(float(self.cv_tur_pel.get())))
        except ValueError:
            pass
        o = cfg.setdefault("olum_kontrol", {})
        o["aktif"] = bool(self.olum_aktif.get())
        o["davranis"] = _olum_kodu(self.olum_davranis.get())
        for anahtar, v in getattr(self, "olum_sureler", {}).items():
            try:
                o[anahtar] = max(0.0, float(v.get().replace(",", ".")))
            except ValueError:
                pass
        o["dirilince_basilacak_tuslar"] = [t.strip().lower().replace(" ", "")
                                           for t in self.olum_tuslar.get().split(",") if t.strip()]

    def _sag_konum_yazi(self):
        x, y = getattr(self, "cv_sag_xy", (None, None))
        if x is None or y is None:
            return "konum secilmedi"
        return "pencere icinde x=%d, y=%d" % (x, y)

    def _xy_yazi(self, xy):
        x, y = xy
        if x is None or y is None:
            return "konum secilmedi"
        return "pencere icinde x=%d, y=%d" % (x, y)

    def _sag_konum_sec(self):
        self._konum_sec(self.cv_sag_etiket, "cv_sag_xy", "Sag tik")

    def _konum_sec(self, etiket, alan, ad, kalan=3):
        """3 sn geri sayim: fareyi oyunda istenen yere goturun, konum alinir."""
        if kalan > 0:
            etiket.config(text="Fareyi oyunda o yere goturun... %d" % kalan)
            self.kok.after(1000, lambda: self._konum_sec(etiket, alan, ad, kalan - 1))
            return
        try:
            import win32gui
            sx, sy = win32gui.GetCursorPos()
            h = win32gui.WindowFromPoint((sx, sy))
            h = ctypes.windll.user32.GetAncestor(h, 2) or h
            x, y = win32gui.ScreenToClient(h, (sx, sy))
        except Exception:
            logging.exception("%s konumu alinamadi", ad)
            etiket.config(text="konum alinamadi, tekrar deneyin")
            return
        setattr(self, alan, (int(x), int(y)))
        etiket.config(text=self._xy_yazi((x, y)))
        logging.info("%s konumu secildi: pencere icinde x=%d, y=%d", ad, x, y)
        self.cekme_uygula()

    def cekme_uygula(self):
        tus = self.cv_tus.get().strip().lower()
        if tus and tus not in girdi.SCAN:
            messagebox.showerror("Pelerin tusu", "'%s' taninmadi. 1-9, 0, F1-F10 ya da tek harf "
                                 "yazin (F11/F12 botun kisayollari)." % self.cv_tus.get())
            return
        for t in self.olum_tuslar.get().split(","):
            parca = [p.strip().lower() for p in t.split("+") if p.strip()]
            if parca and any(p not in girdi.SCAN for p in parca):
                messagebox.showerror("Dirilince bas", "'%s' taninmadi. Ornek: ctrl+g  ya da  "
                                     "ctrl+g, 4" % t.strip())
                return
        self.ham = ayar.yukle()
        self._cekme_yaz(self.ham)
        ayar.kaydet(self.ham)
        for v, _ in self.vurucular.values():
            self._cekme_yaz(v.cfg)
        logging.info("Cekme vurma ayari: pelerin %s / %.1f sn, olum kontrolu %s (%s), dirilince: %s",
                     self.ham["cekme_vurma"]["pelerin_tusu"].upper(),
                     self.ham["cekme_vurma"]["pelerin_araligi"],
                     "ACIK" if self.ham["olum_kontrol"]["aktif"] else "KAPALI",
                     self.olum_davranis.get(),
                     ", ".join(self.ham["olum_kontrol"]["dirilince_basilacak_tuslar"]) or "-")

    def cekme_baslat(self):
        self.cekme_uygula()
        secili = self.secili_hwndler()
        if not secili:
            return
        mesgul = [h for h in secili if h in self.botlar]
        if mesgul:
            messagebox.showwarning(
                "Mesgul", "Su client'larda METIN KESME calisiyor: %s\nOnce onlari durdurun."
                % ", ".join(str(self.pencereler[h][0]) for h in mesgul))
        secili = [h for h in secili if h not in self.botlar and h not in self.vurucular]
        if not secili:
            return
        on_plan = bool(self.ham.get("cekme_vurma", {}).get("on_plan", True))
        if on_plan and self.vurucular:
            messagebox.showwarning(
                "Zaten calisiyor", "At ustu cekme vurma zaten calisiyor. Client eklemek icin "
                                   "once durdurup hepsini birlikte secerek baslatin.")
            return
        if on_plan and any(b.girdi.mod == "on_plan" for b, _ in self.botlar.values()):
            messagebox.showwarning(
                "Tek client", "On planda calisan bir metin botu var; klavye/fare ikisine "
                              "birden yetmez. Once onu durdurun.")
            return
        from cekme_vurma import CekmeVurma, SiraliCekmeVurma
        logging.info("At ustu cekme vurma: %s modunda baslatiliyor (%d client)",
                     "ON PLAN" if on_plan else "ARKA PLAN", len(secili))
        if on_plan and len(secili) > 1:
            c = self.ham.get("cekme_vurma", {})
            if not messagebox.askokcancel(
                    "Coklu client", "%d client SIRAYLA one getirilecek (her birinde %.1f sn, %d "
                    "pelerin).\nBu sirada fare/klavye bota ait; durdurmak icin F12, duraklatmak "
                    "icin F11." % (len(secili), float(c.get("sirali_tur_suresi", 2.0)),
                                   int(c.get("sirali_tur_pelerin", 3)))):
                return
            istemciler = []
            for hwnd in secili:
                pid, baslik, _ = self.pencereler[hwnd]
                cfg = ayar.pencere_icin_hazirla(hwnd)
                self._secenekleri_yaz(cfg)
                self._cekme_yaz(cfg)
                v = CekmeVurma(cfg, hwnd, baslik)
                v.pid = pid
                istemciler.append(v)
            d = SiraliCekmeVurma(istemciler)
            gorunumler = d.gorunumler()
            t = threading.Thread(target=self._sirali_calis, args=(d, gorunumler),
                                 name="SIRALI", daemon=True)
            for hwnd, g in gorunumler:
                self.vurucular[hwnd] = (g, t)
            t.start()
            return
        for hwnd in secili:
            pid, baslik, _ = self.pencereler[hwnd]
            cfg = ayar.pencere_icin_hazirla(hwnd)
            self._secenekleri_yaz(cfg)
            self._cekme_yaz(cfg)
            v = CekmeVurma(cfg, hwnd, baslik)
            v.pid = pid
            t = threading.Thread(target=self._cekme_calis, args=(hwnd, v),
                                 name="PID %s" % pid, daemon=True)
            self.vurucular[hwnd] = (v, t)
            t.start()

    def _sirali_calis(self, d, gorunumler):
        try:
            d.calistir()
        except Exception:
            logging.exception("Sirali cekme vurma hatayla durdu")
        finally:
            for hwnd, g in gorunumler:
                self.son_vurucu[hwnd] = g.ozet()

            def temizle():
                for hwnd, _ in gorunumler:
                    self.vurucular.pop(hwnd, None)
            self.kok.after(0, temizle)

    def _cekme_calis(self, hwnd, v):
        try:
            v.calistir()
        except Exception:
            logging.exception("Cekme vurma hatayla durdu")
        finally:
            self.son_vurucu[hwnd] = v.ozet()
            self.kok.after(0, lambda: self.vurucular.pop(hwnd, None))

    def cekme_secili_durdur(self):
        for hwnd in self.secili_hwndler(sessiz=True):
            if hwnd in self.vurucular:
                self.vurucular[hwnd][0].durdur()

    def olum_klasoru(self):
        import ek_tiklama
        os.startfile(ek_tiklama.klasor_yolu(self.ham, "olum_kontrol"))

    def olum_testi(self):
        hwnd = self._tek_secili()
        if hwnd is None:
            return

        def is_():
            import ek_tiklama
            from sablon_kes import kare_al
            cfg = ayar.pencere_icin_hazirla(hwnd)
            self._cekme_yaz(cfg)
            ek = ek_tiklama.EkTiklayici(cfg, "olum_kontrol")
            if not ek.gorseller:
                return "olum klasorunde resim yok.\nOnce 'Ekrandan olum resmi kes' ile ekleyin."
            kare = kare_al(hwnd, cfg)
            esik = float(cfg.get("olum_kontrol", {}).get("esik", 0.9))
            satirlar = []
            for g in ek.gorseller:
                puan, x, y = ek.ara(kare, g)
                durum = "GORULDU" if puan >= esik else "yok"
                logging.info("Olum testi: %-22s puan=%.2f  %s", g.ad, puan, durum)
                satirlar.append("%s: %.2f  %s" % (g.ad, puan, durum))
            return ("Esik %.2f (tiklama YAPILMADI):\n\n" % esik) + "\n".join(satirlar) + (
                "\n\nKarakter olu degilken puan dusuk (<0.8) olmali.")

        self._arka_is("Olum testi", is_)

    # ---------- boss sekmesi ----------
    def _boss_sekmesi(self):
        f = self.boss_sekme
        f.columnconfigure(0, weight=1)
        f.rowconfigure(3, weight=1)
        b = self.ham.get("boss", {})

        ttk.Label(f, wraplength=680, foreground="#444",
                  text="Bot, bekleme suresi dolan boss oldugunda metin kesmeyi birakir, "
                       "TAB ile Isinlanma Sihirbazi'ni acar, SADECE suresi dolan bosslari "
                       "cagirir (logoya tikla -> SPACE 2 sn -> 15 sn bekle), sonra metin "
                       "farmina geri doner. Her bossun kendi suresi vardir."
                  ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        ust = ttk.Frame(f)
        ust.grid(row=1, column=0, sticky="ew")
        self.boss_aktif = tk.BooleanVar(value=bool(b.get("aktif", False)))
        ttk.Checkbutton(ust, text="Boss turu acik", variable=self.boss_aktif
                        ).pack(side="left")
        ttk.Label(ust, text="Suresi yazilmayanlar icin varsayilan:").pack(side="left", padx=(16, 4))
        self.boss_periyot = tk.StringVar(value=str(b.get("periyot_dakika", 120)))
        ttk.Entry(ust, textvariable=self.boss_periyot, width=6).pack(side="left")
        ttk.Label(ust, text="dk").pack(side="left", padx=4)

        ust2 = ttk.Frame(f)
        ust2.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.boss_genel_acik = tk.BooleanVar(
            value=float(b.get("genel_tur_dakika", 0) or 0) > 0)
        ttk.Checkbutton(ust2, text="Bunlardan bagimsiz: TUM bosslari her",
                        variable=self.boss_genel_acik).pack(side="left")
        self.boss_genel = tk.StringVar(value=str(b.get("genel_tur_dakika", 120) or 120))
        ttk.Entry(ust2, textvariable=self.boss_genel, width=6).pack(side="left", padx=4)
        ttk.Label(ust2, text="dakikada bir dene").pack(side="left")
        ttk.Label(ust2, foreground="#666",
                  text="   (sureleri dolmamis olsa bile hepsi denenir)").pack(side="left")

        liste = ttk.LabelFrame(f, text="Cagrilacak bosslar  —  her satira:  Boss adi | dakika",
                               padding=6)
        liste.grid(row=3, column=0, sticky="nsew", pady=8)
        liste.columnconfigure(0, weight=1)
        liste.rowconfigure(0, weight=1)
        kay = ttk.Scrollbar(liste)
        self.boss_metin = tk.Text(liste, height=12, wrap="none", font=("Consolas", 10),
                                  yscrollcommand=kay.set)
        kay.config(command=self.boss_metin.yview)
        self.boss_metin.grid(row=0, column=0, sticky="nsew")
        kay.grid(row=0, column=1, sticky="ns")
        self.boss_metin.insert("1.0", self._boss_metne_cevir(b))
        ttk.Label(liste, foreground="#666",
                  text="Ornek:  Mavi Ejderha Odasi | 30      "
                       "Sure yazmazsan yukaridaki varsayilan kullanilir."
                  ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        alt = ttk.Frame(f)
        alt.grid(row=4, column=0, sticky="ew")
        ttk.Button(alt, text="Kaydet", command=self.boss_kaydet).pack(side="left")
        ttk.Button(alt, text="Simdi boss turu yap", command=self.boss_simdi
                   ).pack(side="left", padx=6)
        ttk.Button(alt, text="Panel testi", command=self.boss_test).pack(side="left")
        self.boss_durum = ttk.Label(f, foreground="#666", text="")
        self.boss_durum.grid(row=5, column=0, sticky="w", pady=(8, 0))

    @staticmethod
    def _boss_metne_cevir(b):
        satirlar = []
        varsayilan = b.get("periyot_dakika", 120)
        for e in (b.get("liste") or []):
            if isinstance(e, dict):
                dk = e.get("dakika", varsayilan)
                satirlar.append("%s | %g" % (e.get("ad", ""), float(dk)))
            else:
                satirlar.append(str(e))
        return "\n".join(satirlar)

    def _boss_listesi(self):
        """Her satir: 'Boss adi | dakika'  (dakika istege bagli)."""
        try:
            varsayilan = float(self.boss_periyot.get().replace(",", "."))
        except ValueError:
            varsayilan = 120.0
        out = []
        for satir in self.boss_metin.get("1.0", "end").splitlines():
            satir = satir.strip()
            if not satir:
                continue
            dk = varsayilan
            ad = satir
            for ayirac in ("|", ";", "\t"):
                if ayirac in satir:
                    ad, _, sag = satir.partition(ayirac)
                    ad = ad.strip()
                    try:
                        dk = float(sag.strip().replace(",", ".").replace("dk", "").strip())
                    except ValueError:
                        dk = varsayilan
                    break
            if ad:
                out.append({"ad": ad, "dakika": dk})
        return out

    def _boss_yaz(self, cfg):
        b = cfg.setdefault("boss", {})
        b["aktif"] = bool(self.boss_aktif.get())
        b["liste"] = self._boss_listesi()
        try:
            b["periyot_dakika"] = float(self.boss_periyot.get().replace(",", "."))
        except ValueError:
            pass
        if self.boss_genel_acik.get():
            try:
                b["genel_tur_dakika"] = float(self.boss_genel.get().replace(",", "."))
            except ValueError:
                b["genel_tur_dakika"] = 120.0
        else:
            b["genel_tur_dakika"] = 0

    def boss_kaydet(self):
        self.ham = ayar.yukle()
        self._boss_yaz(self.ham)
        ayar.kaydet(self.ham)
        for bot, _ in self.botlar.values():
            self._boss_yaz(bot.cfg)
            if getattr(bot, "boss", None) is not None:
                bot.boss.b = bot.cfg["boss"]
                # ayar degisti -> "bulunamadi" cezalarini sifirla
                bot.boss.hata.clear()
                bot.boss.deneme.clear()
                bot.boss._durum_kaydet()
            elif bot.cfg["boss"]["aktif"]:
                bot._boss_kur()
        liste = self._boss_listesi()
        logging.info("Boss ayarlari kaydedildi (%d boss): %s", len(liste),
                     ", ".join("%s=%gdk" % (e["ad"], e["dakika"]) for e in liste[:4])
                     + (" ..." if len(liste) > 4 else ""))

    def boss_simdi(self):
        self.boss_kaydet()
        calisan = [b for b, _ in self.botlar.values()]
        if not calisan:
            messagebox.showinfo("Boss turu", "Once bir bot baslatin.")
            return
        n = 0
        for bot in calisan:
            if getattr(bot, "boss", None) is None:
                bot._boss_kur()
            if getattr(bot, "boss", None) is not None:
                bot.boss_turu_iste()
                n += 1
        logging.info("Boss turu istendi (%d bot)", n)
        if n == 0:
            messagebox.showwarning("Boss turu",
                                   "Boss modulu hazir degil (liste bos ya da boss_logo.png yok).")

    def boss_test(self):
        """Oyunda TAB acikken: panelde kac satir goruluyor, isimler ne okunuyor."""
        hwnd = self._tek_secili()
        if hwnd is None:
            return
        self.boss_kaydet()

        def is_():
            import boss as boss_modulu
            from vision import Goz
            cfg = ayar.pencere_icin_hazirla(hwnd)
            self._boss_yaz(cfg)
            gr = girdi.Girdi(hwnd, self.mod.get(),
                             cfg["guvenlik"].get("insansi_fare", True),
                             cfg.get("girdi", {}).get("arka_imlec", True))
            goz = Goz(cfg)
            wgc = None
            if gr.arka_plan:
                try:
                    from vision import wgc_al
                    wgc = wgc_al(hwnd)
                except Exception:
                    wgc = None

            def kare_al():
                if gr.arka_plan and wgc is not None:
                    return wgc.kare()
                if gr.arka_plan:
                    return goz.yakala_pencere(hwnd)
                return goz.yakala(girdi.istemci_alani(hwnd))

            bc = boss_modulu.BossCagirici(cfg, goz, gr, hwnd, kare_al=kare_al,
                                          gunluk=logging.info)
            satirlar = bc.satirlari_oku()
            for isim, kutu in satirlar:
                logging.info("  y=%4d  '%s'", kutu[1], isim)
            if wgc is not None:
                from vision import wgc_birak
                wgc_birak(hwnd)
            if not satirlar:
                return ("Panelde cagirma logosu bulunamadi.\n"
                        "Oyunda TAB ile Isinlanma Sihirbazi acik mi?\n"
                        "Acikken de bulmuyorsa boss_kalibrasyon.py ile logoyu secin.")
            return "%d satir okundu. Ayrinti Gunluk'te." % len(satirlar)

        self._arka_is("Boss panel testi", is_)

    def _zaman_sekmesi(self):
        f = self.zaman
        ttk.Label(f, text="Sureler saniye. 'a - b' yazilan yerde a ile b arasi rastgele bekler.\n"
                          "Kaydet calisan botlara da hemen uygulanir.").pack(anchor="w", pady=(0, 8))
        kanvas = tk.Canvas(f, highlightthickness=0)
        kay = ttk.Scrollbar(f, command=kanvas.yview)
        ic = ttk.Frame(kanvas)
        ic.bind("<Configure>", lambda e: kanvas.configure(scrollregion=kanvas.bbox("all")))
        kanvas.create_window((0, 0), window=ic, anchor="nw")
        kanvas.configure(yscrollcommand=kay.set)
        kanvas.pack(side="left", fill="both", expand=True)
        kay.pack(side="right", fill="y")

        self.zaman_girdileri = {}
        for n, (a, d) in enumerate(k for k in self.ham["zamanlayici"].items()
                                   if not k[0].startswith("_")):
            ttk.Label(ic, text=a).grid(row=n, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=("%s - %s" % (d[0], d[1])) if isinstance(d, list) else str(d))
            ttk.Entry(ic, textvariable=v, width=14).grid(row=n, column=1, padx=8)
            self.zaman_girdileri[a] = v
        ttk.Button(ic, text="Kaydet", command=self.zaman_kaydet).grid(
            row=len(self.zaman_girdileri), column=0, columnspan=2, pady=10, sticky="w")

    def zaman_kaydet(self):
        yeni = {}
        for a, v in self.zaman_girdileri.items():
            metin = v.get().strip().replace(",", ".")
            try:
                if "-" in metin.lstrip("-"):
                    x, y = [float(p) for p in metin.split("-", 1)]
                    yeni[a] = [min(x, y), max(x, y)]
                else:
                    deger = float(metin)
                    yeni[a] = int(deger) if a == "kirilma_onay_kare" else deger
            except ValueError:
                messagebox.showerror("Hatali deger", "%s: '%s' anlasilmadi" % (a, metin))
                return
        self.ham = ayar.yukle()
        self.ham["zamanlayici"].update(yeni)
        ayar.kaydet(self.ham)
        for bot, _ in self.botlar.values():
            bot.z.update(yeni)
        logging.info("Zamanlayicilar kaydedildi.")

    # ---------- hedef isim ----------
    def _isimler(self):
        return [p.strip() for p in self.hedef_ad.get().split(",") if p.strip()]

    def isim_uygula(self):
        isimler = self._isimler()
        self.ham = ayar.yukle()
        self.ham["ocr"]["hedef_isimler"] = isimler
        ayar.kaydet(self.ham)
        for bot, _ in self.botlar.values():
            if self._pid_hedefleri().get(str(getattr(bot, "pid", ""))):
                continue                  # bu pencerenin kendi hedefi var
            bot.cfg["ocr"]["hedef_isimler"] = list(isimler)
            for t in bot.taslar:          # yeni isme gore yeniden okunsun
                t.sinif = None
        logging.info("Genel hedef tas: %s", ", ".join(isimler) if isimler else "tum metin taslari")
        self._tablo_hedefleri()

    # ---------- PID'e ozel hedef ----------
    def _pid_hedefleri(self):
        return self.ham.setdefault("ocr", {}).setdefault("pid_hedefleri", {})

    def _hedef_listesi(self, pid):
        """Bu PID'e ozel hedef varsa o, yoksa genel hedef."""
        ozel = self._pid_hedefleri().get(str(pid))
        return list(ozel) if ozel else self._isimler()

    def _hedef_yazisi(self, pid):
        ozel = self._pid_hedefleri().get(str(pid))
        if ozel:
            return ", ".join(ozel)
        genel = self._isimler()
        return "(genel) " + (", ".join(genel) if genel else "tum metinler")

    def _pid_hedef_kaydet(self, pidler, isimler):
        self.ham = ayar.yukle()
        harita = self._pid_hedefleri()
        for pid in pidler:
            if isimler:
                harita[str(pid)] = list(isimler)
            else:
                harita.pop(str(pid), None)
        ayar.kaydet(self.ham)
        # calisan botlara hemen uygula
        for hwnd, (bot, _) in self.botlar.items():
            if getattr(bot, "pid", None) in pidler:
                bot.cfg["ocr"]["hedef_isimler"] = self._hedef_listesi(bot.pid)
                for t in bot.taslar:
                    t.sinif = None
                logging.info("PID %s hedef: %s", bot.pid, self._hedef_yazisi(bot.pid))
        self._tablo_hedefleri()

    def pid_hedef_ata(self, hwndler=None):
        hwndler = hwndler or self.secili_hwndler()
        if not hwndler:
            return
        pidler = [self.pencereler[h][0] for h in hwndler if h in self.pencereler]
        from tkinter import simpledialog
        mevcut = self._pid_hedefleri().get(str(pidler[0])) or self._isimler()
        metin = simpledialog.askstring(
            "Ozel hedef", "PID %s icin hedef tas adi\n(birden fazla: virgulle ayir):"
            % ", ".join(str(p) for p in pidler),
            initialvalue=", ".join(mevcut), parent=self.kok)
        if metin is None:
            return
        isimler = [p.strip() for p in metin.split(",") if p.strip()]
        self._pid_hedef_kaydet(pidler, isimler)
        if not isimler:
            logging.info("PID %s ozel hedef kaldirildi -> genel hedef",
                         ", ".join(str(p) for p in pidler))

    def pid_hedef_kaldir(self):
        hwndler = self.secili_hwndler()
        if not hwndler:
            return
        pidler = [self.pencereler[h][0] for h in hwndler if h in self.pencereler]
        self._pid_hedef_kaydet(pidler, [])
        logging.info("PID %s ozel hedef kaldirildi -> genel hedef", ", ".join(str(p) for p in pidler))

    def _satir_cift_tik(self, olay):
        iid = self.tablo.identify_row(olay.y)
        if iid:
            self.tablo.selection_set(iid)
            self.pid_hedef_ata([int(iid)])

    def _tablo_hedefleri(self):
        for iid in self.tablo.get_children():
            pid = self.pencereler.get(int(iid), ("?",))[0]
            self.tablo.set(iid, "hedef", self._hedef_yazisi(pid))

    # ---------- pencereler ----------
    def pencereleri_yenile(self):
        anahtar = (self.ham.get("pencere", {}).get("baslik_icerir") or "").lower()
        liste = girdi.tum_pencereler()
        if not self.tumunu_goster.get() and anahtar:
            oyun = [p for p in liste if anahtar in p[2].lower()]
            liste = oyun or liste
        secili = set(self.secili_hwndler(sessiz=True))
        self.pencereler = {hwnd: (pid, baslik, r) for hwnd, pid, baslik, r in liste}
        # calisan botlarin penceresi listeden dusmesin
        for hwnd, (bot, _) in self.botlar.items():
            if hwnd not in self.pencereler:
                self.pencereler[hwnd] = (bot.pid, bot.baslik, (0, 0, 0, 0))
        self.tablo.delete(*self.tablo.get_children())
        for hwnd, (pid, baslik, r) in self.pencereler.items():
            self.tablo.insert("", "end", iid=str(hwnd),
                              values=(pid, baslik[:30], self._hedef_yazisi(pid),
                                      "-", "", "", "", "", ""))
        for hwnd in secili:
            if str(hwnd) in self.tablo.get_children():
                self.tablo.selection_add(str(hwnd))
        if not self.tablo.selection():
            kayitli = self.ham.get("pencere", {}).get("pid")
            for hwnd, (pid, _, _) in self.pencereler.items():
                if pid == kayitli:
                    self.tablo.selection_set(str(hwnd))
                    break

    def secili_hwndler(self, sessiz=False):
        if not hasattr(self, "tablo"):
            return []
        sonuc = []
        for iid in self.tablo.selection():
            hwnd = int(iid)
            if girdi.win32gui.IsWindow(hwnd):
                sonuc.append(hwnd)
        if not sonuc and not sessiz:
            messagebox.showwarning("Pencere", "Listeden en az bir oyun penceresi secin.")
        return sonuc

    def goster(self):
        for hwnd in self.secili_hwndler()[:1]:
            girdi.pencereyi_goster(hwnd)

    # ---------- ayarlar ----------
    def _secenekleri_yaz(self, cfg):
        cfg.setdefault("girdi", {})["mod"] = self.mod.get()
        if hasattr(self, "tus_yontemi"):
            cfg["girdi"]["arka_tus_yontemi"] = _tus_yontem_kodu(self.tus_yontemi.get())
        cfg.setdefault("kamera", {})["aktif"] = bool(self.kamera.get())
        cfg["guvenlik"]["insansi_fare"] = bool(self.insansi.get())
        cfg["ocr"]["mod"] = "oncelik" if self.oncelik.get() else "kesin"
        cfg["ocr"]["hedef_isimler"] = self._isimler()
        cfg["gunluk"]["kare_kaydet"] = bool(self.kare_kaydet.get())
        cfg.setdefault("tespit", {})["yontem"] = _tespit_kodu(self.tespit.get())
        cfg.setdefault("ek_tiklama", {})["aktif"] = bool(self.ek_aktif.get())
        try:
            cfg["ek_tiklama"]["esik"] = max(0.30, min(0.99, float(self.ek_esik.get().replace(",", "."))))
            cfg["ek_tiklama"]["tiklama_oncesi_bekleme"] = max(
                0.0, min(60.0, float(self.ek_bekle.get().replace(",", "."))))
        except ValueError:
            pass
        if hasattr(self, "boss_aktif"):
            self._boss_yaz(cfg)
        self._cekme_yaz(cfg)
        self._metin_pelerin_yaz(cfg)

    def _metin_pelerin_yaz(self, cfg):
        if not hasattr(self, "mp_aktif"):
            return
        mp = cfg.setdefault("metin_pelerin", {})
        mp["aktif"] = bool(self.mp_aktif.get())
        tus = self.mp_tus.get().strip().lower()
        if tus in girdi.SCAN:
            mp["tus"] = tus
        try:
            mp["aralik"] = max(0.5, float(self.mp_aralik.get().replace(",", ".")))
        except ValueError:
            pass

    def metin_pelerin_uygula(self):
        tus = self.mp_tus.get().strip().lower()
        if tus and tus not in girdi.SCAN:
            messagebox.showerror("Pelerin tusu", "'%s' taninmadi. 1-9, 0, F1-F10 ya da tek harf "
                                 "yazin (F11/F12 botun kisayollari)." % self.mp_tus.get())
            return
        self.ham = ayar.yukle()
        self._metin_pelerin_yaz(self.ham)
        ayar.kaydet(self.ham)
        for bot, _ in self.botlar.values():
            self._metin_pelerin_yaz(bot.cfg)
        mp = self.ham["metin_pelerin"]
        logging.info("Metin keserken pelerin: %s (%s tusu, %.1f sn)",
                     "ACIK" if mp["aktif"] else "KAPALI", mp.get("tus", "4").upper(), mp["aralik"])

    def canli_uygula(self):
        for bot, _ in self.botlar.values():
            bot.cfg.setdefault("kamera", {})["aktif"] = bool(self.kamera.get())
            bot.cfg["guvenlik"]["insansi_fare"] = bool(self.insansi.get())
            bot.cfg["ocr"]["mod"] = "oncelik" if self.oncelik.get() else "kesin"
            bot.girdi.insansi = bool(self.insansi.get())
            bot.girdi.tus_yontemi = _tus_yontem_kodu(self.tus_yontemi.get())
            yeni = _tespit_kodu(self.tespit.get())
            if bot.cfg.setdefault("tespit", {}).get("yontem") != yeni:
                bot.cfg["tespit"]["yontem"] = yeni
                if bot.goz is not None:
                    bot.sablon_kur()
            bot.cfg.setdefault("ek_tiklama", {})["aktif"] = bool(self.ek_aktif.get())
            if bot.goz is not None and bot.ek is None:
                bot.ek_kur()
        self.ham = ayar.yukle()
        self.ham.setdefault("tespit", {})["yontem"] = _tespit_kodu(self.tespit.get())
        self.ham.setdefault("ek_tiklama", {})["aktif"] = bool(self.ek_aktif.get())
        self.ham.setdefault("girdi", {})["arka_tus_yontemi"] = _tus_yontem_kodu(self.tus_yontemi.get())
        ayar.kaydet(self.ham)
        # (At ustu cekme vurma kendi yontemini kullanir: cekme_vurma.arka_tus_yontemi = guclu)
        if self.botlar:
            logging.info("Ayar uygulandi: kamera=%s  oncelik=%s  tespit=%s", self.kamera.get(),
                         self.oncelik.get(), self.tespit.get())

    # ---------- baslat / durdur ----------
    def baslat(self):
        secili = [h for h in self.secili_hwndler() if h not in self.botlar]
        mesgul = [h for h in secili if h in self.vurucular]
        if mesgul:
            messagebox.showwarning(
                "Mesgul", "Su client'larda AT USTU CEKME VURMA calisiyor: %s\nOnce onlari durdurun."
                % ", ".join(str(self.pencereler[h][0]) for h in mesgul))
            secili = [h for h in secili if h not in self.vurucular]
        if not secili:
            return
        mod = self.mod.get()
        if mod == "on_plan" and (len(secili) > 1 or self.botlar or self.vurucular):
            messagebox.showwarning(
                "On plan", "On plan modunda sadece TEK client calisabilir (fare tek).\n"
                           "Birden fazla client icin 'Arka plan' modunu secin.")
            return

        self.ham = ayar.yukle()
        self.ham.setdefault("pencere", {})["pid"] = self.pencereler[secili[0]][0]
        self._secenekleri_yaz(self.ham)
        ayar.kaydet(self.ham)

        from metin_bot import MetinBotu
        for hwnd in secili:
            pid, baslik, _ = self.pencereler[hwnd]
            cfg = ayar.pencere_icin_hazirla(hwnd)
            self._secenekleri_yaz(cfg)
            cfg["ocr"]["hedef_isimler"] = self._hedef_listesi(pid)
            bot = MetinBotu(cfg, hwnd, baslik)
            bot.pid = pid
            logging.info("PID %s baslatiliyor -> hedef: %s", pid, self._hedef_yazisi(pid))
            t = threading.Thread(target=self._calis, args=(hwnd, bot),
                                 name="PID %s" % pid, daemon=True)
            self.botlar[hwnd] = (bot, t)
            t.start()

    def _calis(self, hwnd, bot):
        try:
            bot.calistir()
        except Exception:
            logging.exception("Bot hatayla durdu")
        finally:
            self.son_ozet[hwnd] = bot.ozet()
            self.kok.after(0, lambda: self.botlar.pop(hwnd, None))

    def secilileri_durdur(self):
        for hwnd in self.secili_hwndler(sessiz=True):
            if hwnd in self.botlar:
                self.botlar[hwnd][0].durdur()

    def tumunu_durdur(self):
        for bot, _ in list(self.botlar.values()) + list(self.vurucular.values()):
            bot.durdur()

    def duraklat(self):
        hepsi = list(self.botlar.values()) + list(self.vurucular.values())
        if not hepsi:
            return
        hepsi_durakli = all(b.duraklat for b, _ in hepsi)
        for bot, _ in hepsi:
            if bot.duraklat == hepsi_durakli:
                bot.duraklat_degistir()
        self.duraklat_btn.configure(text="Duraklat (F11)" if hepsi_durakli else "Devam (F11)")

    # ---------- araclar ----------
    def _tek_secili(self):
        secili = self.secili_hwndler()
        if not secili:
            return None
        if len(secili) > 1:
            messagebox.showinfo("Arac", "Bu arac icin tek bir client secin.")
            return None
        return secili[0]

    def kalibrasyon(self):
        hwnd = self._tek_secili()
        if hwnd is None:
            return
        if derlenmis_mi():
            komut = [sys.executable, "--kalibrasyon", "--hwnd", str(hwnd)]
        else:
            exe = sys.executable
            if exe.lower().endswith("pythonw.exe"):
                exe = exe[:-len("pythonw.exe")] + "python.exe"
            komut = [exe, os.path.join(BURASI, "kalibrasyon.py"), "--hwnd", str(hwnd)]
        subprocess.Popen(komut, cwd=BURASI)
        logging.info("Kalibrasyon penceresi aciliyor (s=kaydet, q=cik)")

    # ---------- sablon (resimle bulma) ----------
    def sablon_kes(self, ek=False, olum=False):
        hwnd = self._tek_secili()
        if hwnd is None:
            return
        if derlenmis_mi():
            komut = [sys.executable, "--sablon-kes", "--hwnd", str(hwnd)]
        else:
            exe = sys.executable
            if exe.lower().endswith("pythonw.exe"):
                exe = exe[:-len("pythonw.exe")] + "python.exe"
            komut = [exe, os.path.join(BURASI, "sablon_kes.py"), "--hwnd", str(hwnd)]
        if olum:
            komut.append("--olum")
        elif ek:
            komut.append("--ek")
        subprocess.Popen(komut, cwd=BURASI)
        if ek:
            logging.info("Resim kesme penceresi aciliyor: tiklanacak seyi (buton/simge) kutuya al, "
                         "ENTER ile ekle, ESC ile bitir. Ad sonuna _sag / _cift eklenebilir.")
        else:
            logging.info("Sablon kesme penceresi aciliyor: tasin ISIM YAZISINI kutuya al, "
                         "ENTER ile ekle, ESC ile bitir.")

    def ek_esik_uygula(self):
        """Esik degisince hem dosyaya hem calisan botlara hemen yazilir."""
        try:
            deger = float(self.ek_esik.get().replace(",", "."))
            bekle = float(self.ek_bekle.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Ek tiklama", "Esik 0.30-0.99, bekleme 0-60 sn arasinda bir sayi olmali.")
            return
        deger = max(0.30, min(0.99, deger))
        bekle = max(0.0, min(60.0, bekle))
        self.ek_esik.set("%.2f" % deger)
        self.ek_bekle.set("%.1f" % bekle)
        self.ham = ayar.yukle()
        ek = self.ham.setdefault("ek_tiklama", {})
        if float(ek.get("esik", -1)) == deger and float(ek.get("tiklama_oncesi_bekleme", -1)) == bekle:
            return
        ek["esik"] = deger
        ek["tiklama_oncesi_bekleme"] = bekle
        ayar.kaydet(self.ham)
        for bot, _ in self.botlar.values():
            bot.cfg.setdefault("ek_tiklama", {})["esik"] = deger
            bot.cfg["ek_tiklama"]["tiklama_oncesi_bekleme"] = bekle
        logging.info("Ek tiklama: esik %.2f, tiklamadan once %.1f sn bekleme", deger, bekle)

    def ek_klasoru(self):
        import ek_tiklama
        os.startfile(ek_tiklama.klasor_yolu(self.ham))

    def ek_testi(self):
        """Secili client'ta ek tiklama resimlerini ara, puanlari yaz (TIKLAMAZ)."""
        hwnd = self._tek_secili()
        if hwnd is None:
            return

        def is_():
            import ek_tiklama
            from sablon_kes import kare_al
            cfg = ayar.pencere_icin_hazirla(hwnd)
            self._secenekleri_yaz(cfg)
            ek = ek_tiklama.EkTiklayici(cfg)
            if not ek.gorseller:
                return "tiklanacaklar klasorunde resim yok.\nOnce 'Ekrandan resim kes' ile ekleyin."
            kare = kare_al(hwnd, cfg)
            esik = float(cfg.get("ek_tiklama", {}).get("esik", 0.85))
            satirlar = []
            for g in ek.gorseller:
                puan, x, y = ek.ara(kare, g)
                durum = "BULUNDU" if puan >= esik else "yok"
                logging.info("Ek tiklama testi: %-20s puan=%.2f  %s (%d,%d)", g.ad, puan, durum, x, y)
                satirlar.append("%s: %.2f  %s" % (g.ad, puan, durum))
            return ("Esik %.2f (tiklama YAPILMADI, sadece arandi):\n\n" % esik) + "\n".join(satirlar)

        self._arka_is("Ek tiklama testi", is_)

    def sablon_klasoru(self):
        import sablon
        os.startfile(sablon.klasor_yolu(self.ham))

    def sablon_testi(self):
        """Secili client'ta sablonlari ara, puanlari Gunluk'e yaz, debug_sablon.png kaydet."""
        hwnd = self._tek_secili()
        if hwnd is None:
            return

        def is_():
            import cv2
            import sablon
            from sablon_kes import kare_al
            from vision import Goz
            cfg = ayar.pencere_icin_hazirla(hwnd)
            self._secenekleri_yaz(cfg)
            goz = Goz(cfg)
            sb = sablon.SablonBulucu(cfg, goz)
            if not sb.hazir:
                return "sablonlar klasorunde resim yok.\nOnce 'Ekrandan sablon kes' ile ekleyin."
            kare = kare_al(hwnd, cfg)
            bolge = goz.arama_bolgesi(kare)
            esik = float(cfg["tespit"].get("esik", 0.62))
            bulunan = sb.bul(kare, bolge)
            cfg["tespit"]["esik"] = max(0.3, esik - 0.15)      # esige yakin kacanlar
            yakin = [b for b in sb.bul(kare, bolge) if b.puan < esik]
            gorsel = kare.bgr.copy()
            cv2.rectangle(gorsel, bolge[:2], bolge[2:], (90, 90, 90), 1)
            for b, renk in [(b, (255, 0, 255)) for b in bulunan] + [(b, (0, 165, 255)) for b in yakin]:
                cv2.rectangle(gorsel, (b.x, b.y), (b.x + b.w, b.y + b.h), renk, 2)
                cv2.putText(gorsel, "%.2f" % b.puan, (b.x, b.y - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, renk, 1)
            yol = os.path.join(BURASI, "debug_sablon.png")
            cv2.imwrite(yol, gorsel)
            logging.info("Sablon testi: %d bulundu (esik %.2f, %.0f ms)", len(bulunan), esik,
                         sb.son_sure * 1000)
            for b in bulunan:
                logging.info("   BULUNDU  %-20s puan=%.2f  (%d,%d)", b.ad, b.puan, b.x, b.y)
            for b in yakin:
                logging.info("   esik alti %-19s puan=%.2f  (%d,%d)", b.ad, b.puan, b.x, b.y)
            return ("%d tas bulundu (mor kutu), %d tanesi esigin hemen altinda (turuncu).\n"
                    "Resim: %s\n\nTas kaciyorsa esigi dusurun ya da o zeminde yeni sablon kesin;\n"
                    "yanlis yere kutu varsa esigi yukseltin (config.json > tespit > esik)."
                    % (len(bulunan), len(yakin), yol))

        self._arka_is("Sablon testi", is_)

    def _arka_is(self, ad, is_fonk):
        def calis():
            try:
                sonuc = is_fonk()
            except Exception as hata:
                logging.exception("%s hatasi", ad)
                sonuc = "%s hatasi: %s" % (ad, hata)
            if sonuc:
                self.kok.after(0, lambda: messagebox.showinfo(ad, sonuc))
        threading.Thread(target=calis, name=ad, daemon=True).start()

    def teshis(self):
        hwnd = self._tek_secili()
        if hwnd is None:
            return
        self.isim_uygula()
        import teshis

        def is_():
            n = teshis.rapor(hwnd, lambda m: logging.info(m))
            return None if n else "Hedef tas bulunamadi. Ayrinti Gunluk'te."
        self._arka_is("Teshis", is_)

    def arka_test(self):
        hwnd = self._tek_secili()
        if hwnd is None:
            return
        if hwnd in self.botlar:
            messagebox.showinfo("Test", "Once bu client'in botunu durdurun.")
            return
        self._arka_is("Arka plan testi", lambda: arka_plan_testi(hwnd))

    def tus_testi(self):
        """Secili client'a pelerin tusunu 3 YONTEMLE sirayla basar; oyunda hangisinde
        pelerin calisti, onu sec."""
        hwnd = self._tek_secili()
        if hwnd is None:
            return
        if hwnd in self.botlar or hwnd in self.vurucular:
            messagebox.showinfo("Tus testi", "Once bu client'ta calisan botu durdurun.")
            return
        tus = (self.mp_tus.get() if hasattr(self, "mp_tus") else "4").strip().lower()
        if tus not in girdi.SCAN:
            messagebox.showerror("Tus testi", "Pelerin tusu taninmadi: %s" % tus)
            return
        if not messagebox.askokcancel(
                "Tus testi", "Secili client'a '%s' tusu 3 farkli yontemle, aralarinda 4 sn "
                "beklenerek basilacak.\nOyun ARKADA kalsin, oyuna bak: pelerin hangi "
                "denemede calisti?\n\n1) Mesaj   2) Mesaj + karakter   3) Bir anlik one getir"
                % tus.upper()):
            return

        def is_():
            sonuc = []
            for n, yontem in enumerate(("mesaj", "mesaj_char", "one_getir"), 1):
                logging.info("Tus testi %d/3: %s -> '%s' basiliyor", n, TUS_YONTEM_ADLARI[yontem],
                             tus.upper())
                girdi.arka_tus_bas(hwnd, tus, 0.06, yontem)
                sonuc.append(TUS_YONTEM_ADLARI[yontem])
                time.sleep(4.0)
            return ("Bitti. Pelerin hangi denemede calistiysa (1, 2 ya da 3) Kontrol "
                    "sekmesinde 'Arka planda tus basma' kutusundan onu secin.\n\n" +
                    "\n".join(sonuc))

        self._arka_is("Tus testi", is_)

    # ---------- kisayollar ----------
    def _kisayollar(self):
        try:
            import keyboard
        except ImportError:
            logging.info("keyboard modulu yok -> F11/F12 kisayollari kapali")
            return
        g = self.ham["guvenlik"]
        try:
            keyboard.add_hotkey(g.get("durdurma_tusu", "f12"), lambda: self.kok.after(0, self.tumunu_durdur))
            keyboard.add_hotkey(g.get("duraklat_tusu", "f11"), lambda: self.kok.after(0, self.duraklat))
        except Exception as hata:
            logging.warning("Kisayollar kurulamadi (%s)", hata)

    # ---------- periyodik ----------
    def _guncelle(self):
        satirlar = 0
        while satirlar < 300:
            try:
                satir = self.kuyruk.get_nowait()
            except queue.Empty:
                break
            self.log.insert("end", satir + "\n")
            satirlar += 1
        if satirlar:
            fazla = int(self.log.index("end-1c").split(".")[0]) - 2000
            if fazla > 0:
                self.log.delete("1.0", "%d.0" % fazla)
            self.log.see("end")

        for iid in self.tablo.get_children():
            hwnd = int(iid)
            if hwnd in self.botlar:
                o = self.botlar[hwnd][0].ozet()
            else:
                o = self.son_ozet.get(hwnd)
            pid, baslik, _ = self.pencereler.get(hwnd, ("?", "?", None))
            if hwnd in self.vurucular or (o is None and hwnd in self.son_vurucu):
                v = (self.vurucular[hwnd][0].ozet() if hwnd in self.vurucular
                     else self.son_vurucu[hwnd])
                durum = v["durum"] if hwnd in self.vurucular else "DURDU"
                self.tablo.item(iid, values=(pid, baslik[:30], "At ustu cekme vurma", durum,
                                             "-", "-", "-",
                                             "pelerin %d / olum %d" % (v["pelerin"], v["olum"]),
                                             _saat_yaz(v["sure"])))
                continue
            if o is None:
                degerler = (pid, baslik[:30], self._hedef_yazisi(pid), "-", "", "", "", "", "")
            else:
                durum = o["durum"] if hwnd in self.botlar else "DURDU"
                degerler = (pid, baslik[:30], self._hedef_yazisi(pid), durum,
                            o["kirilan"], o["takilma"],
                            "-" if o["can"] is None else "%.1f%%" % o["can"],
                            "%s / %s" % (_sure_yaz(o["gecis_tiklama_ort"]), _sure_yaz(o["gecis_vurus_ort"])),
                            _saat_yaz(o["sure"]))
            self.tablo.item(iid, values=degerler)
        if hasattr(self, "boss_durum"):
            yakin = None
            n = 0
            for bot, _ in self.botlar.values():
                bc = getattr(bot, "boss", None)
                if bc is None:
                    continue
                n += 1
                if not hasattr(bc, "durum_ozeti"):
                    continue
                for ad, dk, kalan in bc.durum_ozeti():
                    if yakin is None or kalan < yakin[1]:
                        yakin = (ad, kalan)
            genel = None
            for bot, _ in self.botlar.values():
                bc = getattr(bot, "boss", None)
                if bc is None:
                    continue
                fonk = getattr(bc, "genel_tur_kalan", None)
                if fonk is None:
                    continue          # eski boss.py hala bellekte (programi kapatip acin)
                try:
                    g = fonk()
                except Exception:
                    continue
                if g is not None and (genel is None or g < genel):
                    genel = g
            if yakin is not None:
                metin = ("Sirada: %s  —  %s  (%d bot)"
                         % (yakin[0], "HAZIR" if yakin[1] <= 0 else _saat_yaz(yakin[1]), n))
                if genel is not None:
                    metin += "   |   Genel tur: %s" % (
                        "HAZIR" if genel <= 0 else _saat_yaz(genel))
                self.boss_durum.config(text=metin)
            elif self.botlar:
                self.boss_durum.config(text="Boss turu kapali (bu botlarda)")
            else:
                self.boss_durum.config(text="")

        if hasattr(self, "cekme_durum"):
            if self.vurucular:
                self.cekme_durum.config(text="Calisan: " + "   |   ".join(
                    "PID %s: %s, pelerin %d, olum %d" % (getattr(v, "pid", "?"), o["durum"],
                                                          o["pelerin"], o["olum"])
                    for v, o in ((v, v.ozet()) for v, _ in self.vurucular.values())))
            else:
                self.cekme_durum.config(text="Calisan yok")
        self.kok.after(400, self._guncelle)

    def kapat(self):
        self.tumunu_durdur()
        bitis = time.time() + 2.5
        for _, t in list(self.botlar.values()) + list(self.vurucular.values()):
            t.join(timeout=max(0.1, bitis - time.time()))
        self.kok.destroy()


def main():
    if "--kalibrasyon" in sys.argv:          # derlenmis .exe icinden kalibrasyon
        import kalibrasyon
        sys.exit(kalibrasyon.main())
    if "--sablon-kes" in sys.argv:           # derlenmis .exe icinden sablon kesme
        import sablon_kes
        sys.exit(sablon_kes.main())
    kok = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    Arayuz(kok)
    kok.mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()      # derlenmis .exe'de pelerin islemi icin
    main()
