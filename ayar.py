# -*- coding: utf-8 -*-
"""
Ayar yukleme, cozunurluge gore otomatik olcekleme ve pencere (PID) secimi.
"""

import copy
import json
import logging
import os

import girdi

from yol import BURASI
CFG_YOLU = os.path.join(BURASI, "config.json")
VARSAYILAN_YOLU = os.path.join(BURASI, "varsayilan.json")

# Hangi ayarlar piksel cinsinden -> cozunurlukle birlikte olceklenmeli
OLCEKLENECEK = {
    "isim_etiketi": ["min_genislik", "max_genislik", "min_yukseklik",
                     "max_yukseklik", "yatay_birlestirme"],
    "isin": ["kutu_ofset_y", "kutu_yukseklik"],
    "tiklama": ["hedef_ofset_y"],
}   # hedef_bari.bolge ve arama_bolgesi oran cinsinden -> olceklenmez


def _oku(yol):
    with open(yol, "r", encoding="utf-8") as f:
        return json.load(f)


def _birlestir(varsayilan, kullanici):
    """Kullanicinin ayarlarini varsayilanlarin uzerine yaz.
    Kullanicida olmayan YENI anahtarlar varsayilandan gelir -> guncelleme
    sonrasi eski config.json calismaya devam eder, tekrar ayar gerekmez."""
    sonuc = copy.deepcopy(varsayilan)
    for a, d in kullanici.items():
        if isinstance(d, dict) and isinstance(sonuc.get(a), dict):
            sonuc[a] = _birlestir(sonuc[a], d)
        else:
            sonuc[a] = d
    return sonuc


def yukle(yol=None):
    """config.json'i varsayilanlarla birlestirerek yukle.
    config.json yoksa varsayilandan olusturulur."""
    yol = yol or CFG_YOLU
    varsayilan = _oku(VARSAYILAN_YOLU) if os.path.exists(VARSAYILAN_YOLU) else {}

    if not os.path.exists(yol):
        if not varsayilan:
            raise RuntimeError("Ne config.json ne varsayilan.json bulundu.")
        with open(yol, "w", encoding="utf-8") as f:
            json.dump(varsayilan, f, ensure_ascii=False, indent=2)
        print("config.json olusturuldu (varsayilan ayarlar).")
        return copy.deepcopy(varsayilan)

    kullanici = _oku(yol)
    if not varsayilan:
        return kullanici

    birlesik = _birlestir(varsayilan, kullanici)
    yeni = _eksik_anahtarlar(kullanici, varsayilan)
    if yeni:
        # yeni ayarlari dosyaya da yaz ki kullanici gorup duzenleyebilsin
        with open(yol, "w", encoding="utf-8") as f:
            json.dump(birlesik, f, ensure_ascii=False, indent=2)
        print("config.json guncellendi, eklenen yeni ayarlar: %s" % ", ".join(yeni))
        print("(mevcut ayarlariniz korundu)")
    return birlesik


def _eksik_anahtarlar(kullanici, varsayilan, on=""):
    eksik = []
    for a, d in varsayilan.items():
        if a.startswith("_"):
            continue
        tam = "%s%s" % (on, a)
        if a not in kullanici:
            eksik.append(tam)
        elif isinstance(d, dict) and isinstance(kullanici.get(a), dict):
            eksik += _eksik_anahtarlar(kullanici[a], d, tam + ".")
    return eksik


def kaydet(cfg, yol=None):
    with open(yol or CFG_YOLU, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def olcekle(cfg, istemci_g, istemci_y):
    """Ayarlari pencerenin gercek boyutuna gore uyarla.
    Ayarlar 1920x1080 referansina gore yazilmistir."""
    cfg = copy.deepcopy(cfg)
    if not cfg.get("otomatik_olcek", True):
        cfg["_olcek"] = 1.0
        return cfg

    ref_y = float(cfg.get("referans_yukseklik", 1080))
    k = istemci_y / ref_y
    # cok kucuk/buyuk degerlerde kontrolden cikmasin
    k = max(0.4, min(2.5, k))

    for bolum, anahtarlar in OLCEKLENECEK.items():
        for a in anahtarlar:
            if a in cfg.get(bolum, {}):
                cfg[bolum][a] = max(2, int(round(cfg[bolum][a] * k)))

    # kucuk cozunurlukte yazi daha az piksel -> OCR icin daha cok buyut
    taban = cfg["ocr"].get("buyutme", 3)
    cfg["_ham_buyutme"] = taban
    cfg["ocr"]["buyutme"] = int(max(2, min(6, round(taban / max(0.5, k)))))

    cfg["_olcek"] = k
    cfg["_istemci"] = [istemci_g, istemci_y]
    return cfg


def _yaz(m):
    print(m)


def pencere_sec(cfg, sor=True):
    """PID sorarak (veya config'ten okuyarak) oyun penceresini sec.
    Dondurur: (hwnd, baslik, pid)"""
    p = cfg.get("pencere", {})

    # 1) config'te pid varsa ve hala geçerliyse dogrudan kullan
    if p.get("pid"):
        bulunan = girdi.pid_pencereleri(p["pid"])
        if bulunan and not sor:
            hwnd, pid, baslik, _ = bulunan[0]
            return hwnd, baslik, pid

    if not sor:
        adaylar = girdi.pencere_bul(p.get("baslik_icerir"), p.get("pid"))
        if not adaylar and p.get("pid"):
            # kayitli PID eskimis (oyun yeniden acilmis) -> basliga gore ara
            adaylar = girdi.pencere_bul(p.get("baslik_icerir"), None)
        if not adaylar:
            raise RuntimeError("Pencere bulunamadi: %s" % p)
        hwnd, baslik, _ = adaylar[0]
        return hwnd, baslik, None

    # 2) kullaniciya sor
    pencereler = girdi.tum_pencereler()
    anahtar = (p.get("baslik_icerir") or "").lower()
    onerilen = [w for w in pencereler if anahtar and anahtar in w[2].lower()]

    _yaz("")
    _yaz("=" * 70)
    _yaz("  OYUN PENCERESI SECIMI")
    _yaz("=" * 70)
    if onerilen:
        _yaz("  Muhtemel oyun pencereleri:")
        for hwnd, pid, baslik, r in onerilen:
            _yaz("    PID %-7s %-34s %dx%d" % (pid, baslik[:34], r[2] - r[0], r[3] - r[1]))
    _yaz("  Tum acik pencereler:")
    for hwnd, pid, baslik, r in pencereler:
        _yaz("    PID %-7s %-34s %dx%d" % (pid, baslik[:34], r[2] - r[0], r[3] - r[1]))
    _yaz("-" * 70)

    varsayilan = None
    if onerilen:
        varsayilan = onerilen[0][1]
    elif p.get("pid"):
        varsayilan = p["pid"]

    while True:
        istem = "  PID girin%s: " % ("" if varsayilan is None else " [%s]" % varsayilan)
        try:
            cevap = input(istem).strip()
        except EOFError:
            cevap = ""
        if not cevap and varsayilan is not None:
            cevap = str(varsayilan)
        if not cevap.isdigit():
            _yaz("  Sayi girin.")
            continue
        pid = int(cevap)
        bulunan = girdi.pid_pencereleri(pid)
        if not bulunan:
            _yaz("  PID %d icin gorunur pencere yok. Tekrar deneyin." % pid)
            continue
        if len(bulunan) > 1:
            _yaz("  Bu PID'in birden fazla penceresi var:")
            for n, (h, pd, b, r) in enumerate(bulunan):
                _yaz("    [%d] %-34s %dx%d" % (n, b[:34], r[2] - r[0], r[3] - r[1]))
            try:
                secim = int(input("  Hangisi? [0]: ") or "0")
            except (ValueError, EOFError):
                secim = 0
            secim = max(0, min(secim, len(bulunan) - 1))
        else:
            secim = 0
        hwnd, pd, baslik, r = bulunan[secim]
        _yaz("  Secildi: PID %d  %s  (%dx%d)" % (pd, baslik, r[2] - r[0], r[3] - r[1]))

        # secimi config'e hatirlat
        cfg.setdefault("pencere", {})["pid"] = pd
        try:
            kaydet(cfg)
        except Exception:
            pass
        _yaz("=" * 70)
        _yaz("")
        return hwnd, baslik, pd


def hazirla(sor=True, yol=None):
    """Config yukle + pencere sec + cozunurluge gore olcekle.
    Dondurur: (cfg_olcekli, hwnd, baslik)"""
    cfg = yukle(yol)
    hwnd, baslik, pid = pencere_sec(cfg, sor=sor)
    sol, ust, sag, alt = girdi.istemci_alani(hwnd)
    cfg = olcekle(cfg, sag - sol, alt - ust)
    logging.info("Pencere: %s  %dx%d  olcek=%.2f  (referans %dp)",
                 baslik, sag - sol, alt - ust, cfg["_olcek"],
                 cfg.get("referans_yukseklik", 1080))
    if abs(cfg["_olcek"] - 1.0) > 0.02:
        logging.info("Ayarlar bu cozunurluge uyarlandi: etiket %d-%dpx, "
                     "isin kutusu %dpx, tiklama ofseti %dpx",
                     cfg["isim_etiketi"]["min_yukseklik"],
                     cfg["isim_etiketi"]["max_yukseklik"],
                     cfg["isin"]["kutu_yukseklik"],
                     cfg["tiklama"]["hedef_ofset_y"])
    return cfg, hwnd, baslik


def pencere_icin_hazirla(hwnd, yol=None):
    """GUI icin: pencere zaten secildi -> config yukle + olcekle."""
    cfg = yukle(yol)
    sol, ust, sag, alt = girdi.istemci_alani(hwnd)
    return olcekle(cfg, sag - sol, alt - ust)


def olcegi_geri_al(cfg):
    """Olceklenmis ayarlari referans cozunurluge geri cevirip kaydedilebilir
    hale getirir (kalibrasyon kaydederken kullanilir)."""
    cfg = copy.deepcopy(cfg)
    k = cfg.pop("_olcek", 1.0) or 1.0
    cfg.pop("_istemci", None)
    if "_ham_buyutme" in cfg:
        cfg["ocr"]["buyutme"] = cfg.pop("_ham_buyutme")
    if abs(k - 1.0) > 1e-6:
        for bolum, anahtarlar in OLCEKLENECEK.items():
            for a in anahtarlar:
                if a in cfg.get(bolum, {}):
                    cfg[bolum][a] = max(2, int(round(cfg[bolum][a] / k)))
    return cfg
