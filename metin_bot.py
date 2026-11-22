# -*- coding: utf-8 -*-
"""
Metin Tasi Farm Botu
--------------------
Ekrandaki "Lv 100 Korsan Metini" gibi isim yazilarini okur, tasa tiklar ve
ekranin ustundeki HEDEF CAN BARINI izleyerek tasin kirilmasini bekler.
Tas kirilinca (bar kaybolur / can sifira iner) siradaki tasa gecer.

Calistirma:
    python gui.py                    -> PENCERELI ARAYUZ (onerilen)
    python metin_bot.py              -> konsol, acilista PID sorar
    python metin_bot.py --pid 20028  -> konsol, sormaz
Durdurma: F5      Duraklat/devam: F6
"""

import logging
import os
import random
import sys
import time
from collections import Counter

import cv2

import ayar
import girdi
from vision import Goz, HedefBari, Etiket

from yol import BURASI

# durumlar
ARIYOR = "ARIYOR"      # tiklanacak tas ariyor
TIKLADI = "TIKLADI"    # tikladi, can barinin cikmasini bekliyor
KESIYOR = "KESIYOR"    # bar goruldu, tas kirilana kadar bekliyor
DURDU = "DURDU"


class _Seri:
    """Tek bir can olcusunun (mutlak ya da yuzde) gurultuye dayanikli takibi."""

    def __init__(self):
        self.min = None
        self.son = []
        self.gecmis = []

    def ekle(self, deger, tam, esik=None):
        esik = max(tam * 1e-6, 1e-9) if esik is None else float(esik)
        self.gecmis = (self.gecmis + [deger])[-8:]
        if self.min is None:
            self.min = deger
            self.son = [deger]
            return False
        self.son = (self.son + [deger])[-3:]
        alt = [v for v in self.son if v < self.min - esik]
        if len(alt) >= 2:
            self.min = max(alt)
            self.son = []
            return True
        # asagi yanlis okunup min takilirsa: son 3 okuma birbirine yakin ve
        # hepsi min'in ustundeyse min'i onlara cek
        if len(self.son) == 3 and min(self.son) > self.min + esik \
                and max(self.son) - min(self.son) <= tam * 0.01:
            self.min = min(self.son)
        return False


class Tas:
    """Ekranda takip edilen bir isim etiketi (tas olsun olmasin).
    Arayuz yazilari da takip edilir ki her taramada tekrar OCR edilmesin."""
    _sayac = 0

    def __init__(self, etiket):
        Tas._sayac += 1
        self.id = Tas._sayac
        self.etiket = etiket
        self.merkez = etiket.merkez
        self.son_gorulme = time.time()
        self.son_tiklama = 0.0
        self.engelli_kadar = 0.0      # bu ana kadar secilmesin
        self.takilma_sayisi = 0
        self.yazi = ""
        self.sinif = None             # 'hedef' | 'belirsiz' | 'degil' | None (okunmadi)
        self.ocr_zamani = 0.0
        self.sablon = False           # resimle (sablonla) bulundu

    def guncelle(self, etiket):
        self.etiket = etiket
        self.merkez = etiket.merkez
        self.son_gorulme = time.time()
        etiket.yazi = self.yazi


class MetinBotu:
    def __init__(self, cfg, hwnd, baslik=""):
        self.cfg = cfg
        self.z = cfg["zamanlayici"]
        self.hwnd = hwnd
        self.baslik = baslik
        g = cfg.get("girdi", {})
        self.mod = g.get("mod", "on_plan")
        self.girdi = girdi.Girdi(hwnd, self.mod, cfg["guvenlik"].get("insansi_fare", True),
                                 g.get("arka_imlec", True), g.get("arka_tus_yontemi", "mesaj"))
        self.goz = None
        self.bar = None
        self.sablon = None             # SablonBulucu (resimle bulma)
        self.ek = None                 # EkTiklayici (taslardan bagimsiz resim tiklama)
        self.olcek = float(cfg.get("_olcek", 1.0))

        self.taslar = []
        self.durum = ARIYOR
        self.durum_zamani = time.time()
        self.hedef_tas = None
        self.son_imza = None
        self.son_can_degisimi = time.time()
        self.tik_oncesi_imza = None
        self.terk_imza = None
        self.bar_yok_sayac = 0
        self.olu_nokta = None          # (merkez, zaman) - az once kirilan tas
        self.son_aday_gorulme = time.time()
        self.son_tarama = 0.0
        self.hemen_tara = True
        self.kare_boyutu = (1, 1)

        # istatistik
        self.kirilan = 0
        self.takilma = 0
        self.basla_zamani = None
        self.kirilma_zamani = None     # son kirilma ani (gecis olcumu icin)
        self.gecis_tiklama = []        # kirildi -> yeni tasa tiklandi (sn)
        self.gecis_vurus = []          # kirildi -> yeni tasin cani dusmeye basladi (sn)
        self.son_bar = None

        self.duraklat = False
        self.calisiyor = True
        self.boss = None
        self.boss_istegi = False
        self.bar_yoksay_kadar = 0.0    # boss turundan sonra ekranda kalan bar       # GUI'den "simdi boss turu yap"
        self._son_gunluk = 0.0
        self._son_bos_uyari = 0.0
        self._sonraki_pelerin = 0.0
        self.pelerin_sayisi = 0
        self._pelerin_uyari = 0.0
        self._son_can_gunlugu = 0.0
        self._hasar_sifirla()

    # ---------------- disaridan kontrol (GUI) ----------------

    def durdur(self):
        self.calisiyor = False

    def duraklat_degistir(self):
        self.duraklat = not self.duraklat
        logging.info("DURAKLATILDI" if self.duraklat else "DEVAM")
        return self.duraklat

    def ozet(self):
        def ort(liste):
            return sum(liste[-20:]) / len(liste[-20:]) if liste else None
        return {
            "durum": DURDU if not self.calisiyor else ("DURAKLATILDI" if self.duraklat else self.durum),
            "kirilan": self.kirilan,
            "takilma": self.takilma,
            "sure": 0 if self.basla_zamani is None else time.time() - self.basla_zamani,
            "gecis_tiklama_son": self.gecis_tiklama[-1] if self.gecis_tiklama else None,
            "gecis_tiklama_ort": ort(self.gecis_tiklama),
            "gecis_vurus_son": self.gecis_vurus[-1] if self.gecis_vurus else None,
            "gecis_vurus_ort": ort(self.gecis_vurus),
            "tas_sayisi": sum(1 for t in self.taslar if t.sinif == "hedef"),
            "can": None if self.son_bar is None or self.son_bar.yuzde is None
            else self.son_bar.yuzde,
        }

    # ---------------- yardimcilar ----------------

    def _bekle(self, deger):
        """Sayi ya da [a, b] araligi kadar bekle."""
        if isinstance(deger, (list, tuple)):
            time.sleep(random.uniform(deger[0], deger[1]))
        else:
            time.sleep(float(deger))

    def _durum(self, yeni):
        if yeni != self.durum:
            logging.debug("Durum: %s -> %s", self.durum, yeni)
        self.durum = yeni
        self.durum_zamani = time.time()

    @property
    def durumda_gecen(self):
        return time.time() - self.durum_zamani

    def _kamera_aktif(self):
        return bool(self.cfg.get("kamera", {}).get("aktif", False))

    def _kamera_cevir(self):
        tus = self.cfg.get("kamera", {}).get("cevirme_tusu", "e")
        sure = self.z.get("kamera_cevirme_basili_tutma", [0.35, 0.6])
        basili = random.uniform(sure[0], sure[1]) if isinstance(sure, (list, tuple)) else float(sure)
        logging.info("Kamera ceviriliyor (%s)", tus.upper())
        self.girdi.tus_bas(tus, sure=basili)
        self.hemen_tara = True

    # ---------------- takip + tarama ----------------

    def tespit_yontemi(self):
        """'ocr' | 'sablon' | 'ikisi'. Sablon yoksa her zaman OCR."""
        y = self.cfg.get("tespit", {}).get("yontem", "ikisi")
        if y not in ("ocr", "sablon", "ikisi"):
            y = "ikisi"
        if y != "ocr" and (self.sablon is None or not self.sablon.hazir):
            return "ocr"
        return y

    def sablon_kur(self):
        """Resimle bulma modulunu (yeniden) hazirla. GUI'den de cagrilir."""
        try:
            from sablon import SablonBulucu
            self.sablon = SablonBulucu(self.cfg, self.goz, getattr(self.goz, "_havuz", None))
        except Exception:
            logging.exception("Sablon modulu yuklenemedi")
            self.sablon = None
        istenen = self.cfg.get("tespit", {}).get("yontem", "ikisi")
        if istenen != "ocr" and (self.sablon is None or not self.sablon.hazir):
            logging.warning("Tespit '%s' secili ama 'sablonlar' klasorunde resim yok -> OCR "
                            "kullaniliyor. Arayuzde 'Ekrandan sablon kes' ile ekleyin.", istenen)
        logging.info("Tespit yontemi: %s", {"ocr": "OCR (yazi okuma)", "sablon": "RESIM (sablon)",
                                             "ikisi": "RESIM + OCR"}[self.tespit_yontemi()])

    def ek_kur(self):
        """Ek gorsel tiklama (tiklanacaklar klasoru). GUI'den de cagrilir."""
        try:
            from ek_tiklama import EkTiklayici
            self.ek = EkTiklayici(self.cfg)
        except Exception:
            logging.exception("Ek tiklama modulu yuklenemedi")
            self.ek = None
            return
        if self.cfg.get("ek_tiklama", {}).get("aktif", False):
            logging.info("Ek gorsel tiklama: ACIK (%d resim)", len(self.ek.gorseller))

    def _etiketleri_topla(self, kare):
        """Sablon bulgulari (kesin hedef, OCR gerekmez) + OCR icin yazi bloklari."""
        yontem = self.tespit_yontemi()
        sablonlu = []
        if yontem in ("sablon", "ikisi"):
            for b in self.sablon.bul(kare, self.goz.arama_bolgesi(kare)):
                e = Etiket((b.x, b.y, b.w, b.h), yazi=b.ad)
                e.sablon = True
                e.puan = b.puan
                sablonlu.append(e)
        bloklar = []
        if yontem in ("ocr", "ikisi"):
            for e in self.goz.etiketleri_bul(kare):
                # sablonun zaten buldugu yaziyi tekrar OCR etme
                if any(abs(e.merkez[0] - s.merkez[0]) < (e.w + s.w) * 0.35 and
                       abs(e.merkez[1] - s.merkez[1]) < (e.h + s.h) * 0.6 for s in sablonlu):
                    continue
                e.sablon = False
                bloklar.append(e)
        return sablonlu + bloklar

    def _tara(self, kare):
        """Etiketleri bul, takip edilenlerle eslestir, SADECE yeni/eskimis
        olanlari (paralel) OCR et. Sablonla bulunanlar OCR'siz hedef sayilir."""
        simdi = time.time()
        etiketler = self._etiketleri_topla(kare)

        # olu tasin son kareler kalan yazisini yok say
        if self.olu_nokta and simdi - self.olu_nokta[1] < 1.0:
            (ox, oy), _ = self.olu_nokta
            yaricap = 45 * self.olcek
            etiketler = [e for e in etiketler
                         if (e.merkez[0] - ox) ** 2 + (e.merkez[1] - oy) ** 2 > yaricap ** 2]

        # en yakin ciftler once eslessin
        esik = 70 * max(0.5, self.olcek)
        ciftler = []
        for i, e in enumerate(etiketler):
            for j, t in enumerate(self.taslar):
                dx = t.merkez[0] - e.merkez[0]
                dy = t.merkez[1] - e.merkez[1]
                m = (dx * dx + dy * dy) ** 0.5
                if m < esik:
                    ciftler.append((m, i, j))
        ciftler.sort()
        etiket_tas = [None] * len(etiketler)
        kullanilan = set()
        for _, i, j in ciftler:
            if etiket_tas[i] is None and j not in kullanilan:
                etiket_tas[i] = self.taslar[j]
                kullanilan.add(j)

        yeni_liste = []
        for i, e in enumerate(etiketler):
            t = etiket_tas[i]
            if t is None:
                t = Tas(e)
            else:
                t.guncelle(e)
            if getattr(e, "sablon", False):
                t.sablon = True
                t.sinif = "hedef"
                t.yazi = e.yazi
                t.ocr_zamani = simdi
            else:
                t.sablon = False
            etiket_tas[i] = t
            yeni_liste.append(t)

        # kimleri OCR edelim: yeni, belirsiz (sik), bilinen (seyrek)
        o = self.cfg["ocr"]
        tekrar = float(o.get("tekrar_okuma_suresi", 4.0))
        belirsiz_tekrar = float(o.get("belirsiz_tekrar_suresi", 0.8))
        okunacak = []
        for t in yeni_liste:
            if t.sablon:
                continue
            yas = simdi - t.ocr_zamani
            if t.sinif is None or (t.sinif == "belirsiz" and yas > belirsiz_tekrar) or yas > tekrar:
                okunacak.append(t)
        if okunacak:
            self.goz.toplu_oku(kare, [t.etiket for t in okunacak], onbellek_suresi=0)
            for t in okunacak:
                t.yazi = t.etiket.yazi
                yeni = self.goz.sinif(t.yazi)
                # bir kez 'hedef' okunduysa tek bir kotu okuma ile dusurme
                if not (t.sinif == "hedef" and yeni == "belirsiz"):
                    t.sinif = yeni
                t.ocr_zamani = simdi

        # gorunmeyenleri kisa bir sure hatirla (tiklama/engel bilgisi kaybolmasin)
        tolerans = self.z.get("hedef_kaybolma_toleransi", 1.5)
        eski = [t for t in self.taslar
                if t not in yeni_liste and simdi - t.son_gorulme < tolerans]
        self.taslar = yeni_liste + eski
        self.son_tarama = simdi
        self.hemen_tara = False
        self._tarama_gunlugu()

    def _tas_hedef_mi(self, t):
        if t.sinif == "hedef":
            return True
        o = self.cfg["ocr"]
        if t.sinif == "belirsiz":
            return (not o.get("zorunlu", True)) or o.get("mod") == "oncelik"
        if t.sinif == "benzer":
            # adi tam okunamayan metin: sadece oncelik modunda denenir, can bari dogrular
            return o.get("mod") == "oncelik"
        return False

    def _uygun_taslar(self):
        simdi = time.time()
        uygun = []
        for tas in self.taslar:
            if simdi - tas.son_gorulme > 0.01 + max(0.0, simdi - self.son_tarama):
                continue                      # bu taramada gorulmedi
            if not self._tas_hedef_mi(tas):
                continue
            if simdi < tas.engelli_kadar:
                continue
            if simdi - tas.son_tiklama < self.z["ayni_tasa_tekrar_tiklama_bekleme"]:
                continue
            if tas.etiket.h < self.cfg["secim"].get("min_etiket_yuksekligi", 0):
                continue
            uygun.append(tas)
        return uygun

    def _aday_sec(self, en_yakini_zorla=False):
        """Tiklanacak tasi sec.
        Metin2'de isim yazisi uzaklikla kuculur: BUYUK etiket = YAKIN tas."""
        uygun = self._uygun_taslar()
        if not uygun:
            return None

        h, w = self.kare_boyutu
        mx, my = w / 2.0, h / 2.0
        kosegen = (w * w + h * h) ** 0.5 or 1.0

        yontem = "en_yakin" if en_yakini_zorla else self.cfg["secim"].get("yontem", "karisik")
        agirlik = float(self.cfg["secim"].get("boyut_agirligi", 0.65))

        def guven(t):          # resimle / OCR ile kesin bulunan tas once
            if t.sablon:
                return 1.05
            return {"hedef": 1.0, "belirsiz": 0.5, "benzer": 0.3}.get(t.sinif, 0.3)

        def boyut_puani(t):
            return t.etiket.h * 100.0 + t.etiket.w

        def merkez_puani(t):
            dx, dy = t.merkez[0] - mx, t.merkez[1] - my
            return (dx * dx + dy * dy) ** 0.5 / kosegen      # 0 = ortada

        if yontem == "en_yakin":
            return max(uygun, key=lambda t: boyut_puani(t) * guven(t))
        if yontem == "ekran_ortasi":
            return max(uygun, key=lambda t: (1.0 - merkez_puani(t)) * guven(t))

        en_buyuk = max(boyut_puani(t) for t in uygun) or 1.0
        return max(uygun, key=lambda t: guven(t) * (
            agirlik * (boyut_puani(t) / en_buyuk) + (1 - agirlik) * (1.0 - merkez_puani(t))))

    def _engel_sec(self):
        """Yolu kapatan tas genelde karakterin DIBINDEKI tastir. Karakter ekranin
        ortasinda durur -> tas gövdesi ekran ortasina en yakin olani sec."""
        uygun = self._uygun_taslar()
        if not uygun:
            return None
        h, w = self.kare_boyutu
        kx = w / 2.0
        ky = h * float(self.cfg.get("kurtulma", {}).get("karakter_y_orani", 0.5))
        ofset = self.cfg["tiklama"]["hedef_ofset_y"]

        def mesafe(t):
            gx = t.etiket.x + t.etiket.w / 2.0
            gy = t.etiket.y + t.etiket.h + ofset
            return ((gx - kx) ** 2 + (gy - ky) ** 2) ** 0.5
        return min(uygun, key=mesafe)

    def _tikla(self, tas, bar):
        e = tas.etiket
        yanilma = max(3, e.w // 6)
        hx = e.x + e.w // 2 + random.randint(-yanilma, yanilma)
        hy = e.y + e.h + self.cfg["tiklama"]["hedef_ofset_y"] + random.randint(-8, 8)
        h, w = self.kare_boyutu
        hx = max(0, min(w - 1, hx))
        hy = max(0, min(h - 1, hy))
        self.tik_oncesi_imza = bar.imza if bar.var else None
        self.girdi.tikla(hx, hy)
        tas.son_tiklama = time.time()
        self.hedef_tas = tas
        if self.kirilma_zamani is not None and not self.gecis_tiklama_kaydedildi:
            gecen = time.time() - self.kirilma_zamani
            self.gecis_tiklama.append(gecen)
            self.gecis_tiklama_kaydedildi = True
        logging.info("Tikla -> #%d %r", tas.id, tas.yazi or "<okunamadi>")
        self._bekle(self.z["tiklama_sonrasi_bekleme"])
        self._durum(TIKLADI)

    gecis_tiklama_kaydedildi = True

    def _terk_et(self, bar, sebep):
        """Mevcut tasi birak (takildi / zaman asimi) ve baska tasa gec."""
        self.takilma += 1
        logging.warning("%s -> tas birakiliyor", sebep)
        self.terk_imza = bar.imza if bar is not None else None

        if self.hedef_tas is not None:
            self.hedef_tas.takilma_sayisi += 1
            bekle = self.z.get("takilan_tas_bekleme", 30.0)
            self.hedef_tas.engelli_kadar = time.time() + bekle
            logging.info("Tas #%d %.0f sn boyunca atlanacak", self.hedef_tas.id, bekle)

        k = self.cfg.get("kurtulma", {})
        ekstra = k.get("tus")
        if ekstra:
            self.girdi.tus_bas(ekstra)
            self._bekle([0.15, 0.3])

        if self._kamera_aktif() and k.get("kamera_cevir", True):
            self._kamera_cevir()
            self._bekle(self.z.get("kurtulma_sonrasi_bekleme", [0.3, 0.5]))

        self.hedef_tas = None
        self.son_imza = None
        if k.get("engeli_hedefle", True):
            engel = self._engel_sec()
            if engel is not None:
                logging.info("Yolu kapatan (karaktere en yakin) tasa geciliyor -> #%d %r",
                             engel.id, engel.yazi)
                self._tikla(engel, bar)
                return
        self._durum(ARIYOR)

    def _hasar_sifirla(self):
        self._seriler = {"can": _Seri(), "yuzde": _Seri(), "dolgu": _Seri()}
        self._tam = None
        self._tam_adaylar = []
        self._kayma_onay = 0

    def _min_tam_can(self):
        return float(self.cfg.get("hedef_bari", {}).get("min_tam_can", 1e6))

    def _okuma_makul_mu(self, bar):
        """OCR buyuk sayilarda rakam kacirabiliyor: '398.255.857 / 400.000.000.000'
        yerine '255.857' okuyor. Metin taslarinin TAM cani milyarlarca oldugundan
        kucuk 'tam' degerleri cop sayilir ve hic kullanilmaz."""
        if bar.can is None or not bar.tam:
            return False
        if bar.tam < self._min_tam_can():
            return False
        return 0 <= bar.can <= bar.tam

    def _tam_kabul(self, bar):
        """Tasin TAM cani icin referans belirler. Ilk okumaya korukorune guvenmek
        yerine ayni degerin 2 kez gorulmesi beklenir; sonra bu degerle
        uyusmayan okumalar yok sayilir (OCR gurultusu seriyi bozmasin)."""
        if not self._okuma_makul_mu(bar):
            return False
        if self._tam is None:
            self._tam_adaylar = (self._tam_adaylar + [bar.tam])[-10:]
            deger, sayi = Counter(self._tam_adaylar).most_common(1)[0]
            if sayi >= 2:
                self._tam = deger
                logging.info("Tasin tam cani: %s",
                             "{:,}".format(int(deger)).replace(",", "."))
            return False        # referans netlesene kadar okuma kullanilmaz
        return abs(bar.tam - self._tam) <= self._tam * 1e-6

    @property
    def _min_deger(self):
        return self._seriler["can"].min

    def _hedef_disaridan_degisti_mi(self, bar):
        """Kesilen tasin cani bir anda YUKSELDIYSE ya da tam cani degistiyse ekrandaki
        bar artik baska bir tasin bari: hedef bot disinda degisti (orn. baska
        pencerede yapilan tiklamayi oyun kendi tiklamasi sandi)."""
        if not self._okuma_makul_mu(bar):
            return False            # OCR copu -> "hedef degisti" sanma
        if self._tam is None:
            self._tam_kabul(bar)
            return False
        farkli_tur = abs(bar.tam - self._tam) > self._tam * 0.001
        yukseldi = self._min_deger is not None and bar.can > self._min_deger + bar.tam * 0.01
        if farkli_tur or yukseldi:
            self._kayma_onay += 1
        else:
            self._kayma_onay = 0
        return self._kayma_onay >= 2

    def _hedefe_geri_don(self, bar):
        simdi = time.time()
        self.hedef_degisimi = getattr(self, "hedef_degisimi", 0) + 1
        t = self.hedef_tas
        gorunur = t is not None and t in self.taslar and simdi - t.son_gorulme < 2.0
        if gorunur:
            logging.warning("Hedef disaridan degisti -> kendi tasina geri donuyor (#%d)", t.id)
            t.son_tiklama = 0.0
            t.engelli_kadar = 0.0
            self._tikla(t, bar)
        else:
            logging.warning("Hedef disaridan degisti, eski tas gorunmuyor -> yeni tas araniyor")
            self.hedef_tas = None
            self.hemen_tara = True
            self._durum(ARIYOR)

    def _hasar_var_mi(self, bar):
        """Tas gercekten hasar aliyor mu?
        OCR buyuk sayilari arada yanlis okur. Mutlak can ve yuzde AYRI ayri izlenir
        (karisirsa 758 milyar ile %74 kiyaslanip hasar hic gorulmuyordu).
        Son 3 okumadan 2'si onceki en dusuk degerin altindaysa hasar sayilir."""
        hasar = False
        if self._tam_kabul(bar):
            hasar |= self._seriler["can"].ekle(bar.can, bar.tam)
        if bar.yuzde is not None and not bar.yuzde_dolgu:
            hasar |= self._seriler["yuzde"].ekle(bar.yuzde, 100.0)
        hb = self.cfg.get("hedef_bari", {})
        if bar.yuzde is not None and bar.yuzde_dolgu and hb.get("dolgu_hasar_sayilsin", True):
            # OCR rakamlari okuyamadi: barin renkli dolgusu azaliyorsa da hasar var.
            # (Yoksa tas kesiliyorken 'can degismedi' sanilip birakiliyordu.)
            hasar |= self._seriler["dolgu"].ekle(bar.yuzde, 100.0,
                                                 esik=float(hb.get("dolgu_hasar_esigi", 2.0)))
        return hasar

    def _hasar_ozeti(self):
        c, y = self._seriler["can"], self._seriler["yuzde"]
        can = ", ".join("{:,}".format(int(v)).replace(",", ".") for v in c.gecmis[-4:]) or "okunamadi"
        yuzde = ", ".join("%.1f" % v for v in y.gecmis[-4:]) or "okunamadi"
        return "son can okumalari: [%s]  yuzde: [%s]" % (can, yuzde)

    def _okunakli_baska_isim(self, bar):
        """Bar net okunuyor ve aranan tas degil mi? (bulanik okumayi yanlis hedef sayma)
        Barin ilk satiri can sayilari oldugu icin tum yazi kullanilir."""
        harfler = "".join(k for k in (bar.ham or bar.isim) if not k.isdigit())
        return self.goz.sinif(harfler) in ("degil", "benzer")

    # ---------------- durum makinesi ----------------

    def _adim(self, kare):
        bar = self.bar.oku(kare)
        self.son_bar = bar
        simdi = time.time()

        # --- KESIYOR: bar izleniyor ---
        if self.durum == KESIYOR:
            canli = bar.var and (bar.yuzde is None or bar.yuzde > 0)
            if canli:
                self.bar_yok_sayac = 0
                self.son_imza = bar.imza
                if self._hedef_disaridan_degisti_mi(bar):
                    self._hedefe_geri_don(bar)
                    return
                if self._hasar_var_mi(bar):
                    self.son_can_degisimi = simdi
                    if simdi - self._son_can_gunlugu > 2.0 and bar.yuzde is not None:
                        logging.info("Can: %%%.1f", bar.yuzde)
                        self._son_can_gunlugu = simdi
                    if self.kirilma_zamani is not None:
                        self.gecis_vurus.append(simdi - self.kirilma_zamani)
                        logging.info("Gecis: kirildi -> yeni tasa vurus %.1f sn",
                                     self.gecis_vurus[-1])
                        self.kirilma_zamani = None

                if simdi - self.son_can_degisimi > self.z.get("can_degismeme_suresi", 10.0):
                    logging.info("Okunan: %s", self._hasar_ozeti())
                    self._terk_et(bar, "Can %.0f sn'dir degismedi (yol kapali?)"
                                  % self.z.get("can_degismeme_suresi", 10.0))
                    return
                if self.durumda_gecen > self.z["tas_kesme_zaman_asimi"]:
                    self._terk_et(bar, "Zaman asimi (%.0f sn)" % self.z["tas_kesme_zaman_asimi"])
                return

            # bar yok: tek karelik OCR hatasini kirilma sanma
            self.bar_yok_sayac += 1
            can_sifir = bar.var and bar.yuzde is not None and bar.yuzde <= 0
            if not can_sifir and self.bar_yok_sayac < int(self.z.get("kirilma_onay_kare", 2)):
                return

            self.kirilan += 1
            logging.info("TAS KIRILDI (toplam %d)", self.kirilan)
            if self.hedef_tas is not None:
                self.olu_nokta = (self.hedef_tas.merkez, simdi)
                if self.hedef_tas in self.taslar:
                    self.taslar.remove(self.hedef_tas)
            self.kirilma_zamani = simdi
            self.gecis_tiklama_kaydedildi = False
            self.hedef_tas = None
            self.son_imza = None
            self.terk_imza = None
            self.bar_yok_sayac = 0
            self.hemen_tara = True
            self._bekle(self.z["tas_kirildi_sonrasi_bekleme"])
            self._durum(ARIYOR)
            self._hizli_gecis(bar)
            return

        # --- TIKLADI: barin cikmasi / yeni hedefe gecmesi bekleniyor ---
        if self.durum == TIKLADI:
            if bar.var:
                if (self.cfg["hedef_bari"]["yuzde_okuma"] == "ocr" and bar.isim
                        and not bar.metin_mi and self._okunakli_baska_isim(bar)):
                    logging.info("Hedef aranan tas degil (%r) -> baska tas",
                                 " ".join((bar.ham or "").split())[:50])
                    if self.hedef_tas is not None:
                        self.hedef_tas.engelli_kadar = simdi + self.z.get("yanlis_hedef_bekleme", 20.0)
                    self._durum(ARIYOR)
                    return
                ayni = (self.tik_oncesi_imza is not None and bar.imza == self.tik_oncesi_imza)
                if ayni and self.durumda_gecen < self.z.get("hedef_degisim_bekleme", 1.2):
                    return            # ekrandaki hala eski tasin bari
                logging.info("Hedef alindi%s", "" if bar.yuzde is None
                             else "  can %%%.1f" % bar.yuzde)
                self.son_imza = bar.imza
                self.son_can_degisimi = simdi
                self.terk_imza = None
                self.bar_yok_sayac = 0
                self._hasar_sifirla()
                self._durum(KESIYOR)
                return
            if self.durumda_gecen > self.z["hedef_bari_cikma_suresi"]:
                logging.info("Can bari cikmadi -> baska tas")
                self._durum(ARIYOR)
            return

        # --- ARIYOR ---
        if (bar.var and bar.metin_mi and (bar.yuzde is None or bar.yuzde > 0)
                and bar.imza != self.terk_imza
                and simdi >= self.bar_yoksay_kadar):
            logging.info("Ekranda kesilen bir tas var -> izleniyor")
            self.son_imza = bar.imza
            self.son_can_degisimi = simdi
            self._hasar_sifirla()
            self._durum(KESIYOR)
            return

        aday = self._aday_sec()
        if aday is not None:
            self.son_aday_gorulme = simdi
            self._tikla(aday, bar)
            return

        if self._kamera_aktif() and simdi - self.son_aday_gorulme > self.z.get("kamera_cevirme_esigi", 6.0):
            self._kamera_cevir()
            self.son_aday_gorulme = simdi

    def _pelerin_bas(self):
        """Metin kesme sirasinda pelerin (acik/kapali, GUI'den)."""
        p = self.cfg.get("metin_pelerin", {})
        if not p.get("aktif", False):
            return
        simdi = time.time()
        if simdi < self._sonraki_pelerin:
            return
        tus = str(p.get("tus", "4")).strip().lower()
        if tus not in girdi.SCAN:
            if simdi - self._pelerin_uyari > 30:
                logging.error("Pelerin tusu '%s' taninmadi (1-9, 0, F1-F10 ya da harf)", tus)
                self._pelerin_uyari = simdi
            self._sonraki_pelerin = simdi + 5
            return
        self.girdi.tus_bas(tus, random.uniform(0.04, 0.08))
        self.pelerin_sayisi += 1
        if self.pelerin_sayisi == 1:
            logging.info("Pelerin acik: %s tusu, %.1f sn'de bir", tus.upper(), float(p.get("aralik", 5.0)))
        self._sonraki_pelerin = simdi + max(0.5, float(p.get("aralik", 5.0))) + random.uniform(-0.6, 0.6)

    def _hizli_gecis(self, bar):
        """Tas kirilir kirilmaz taze bir kare alip siradaki tasa hemen tikla.
        Eskiden bir sonraki dongu turunu (yakalama + tarama + bar okuma) bekliyordu."""
        if not self.cfg.get("secim", {}).get("hizli_gecis", True):
            return
        try:
            kare = self._kare_al()
            if kare is None:
                return
            self.kare_boyutu = kare.bgr.shape[:2]
            self._tara(kare)
            aday = self._aday_sec()
            if aday is not None:
                self.son_aday_gorulme = time.time()
                self._tikla(aday, bar)
        except Exception:
            logging.exception("Hizli gecis hatasi (normal akisa donuluyor)")
            self._durum(ARIYOR)

    # ---------------- ana dongu ----------------

    def hazirlik(self):
        self.goz = Goz(self.cfg)
        self.bar = HedefBari(self.goz)
        logging.info("Hedef pencere: %s  mod=%s  olcek=%.2f",
                     self.baslik, "ARKA PLAN" if self.girdi.arka_plan else "on plan", self.olcek)
        if self.goz.ocr_hazir:
            logging.info("OCR hazir (Tesseract calisiyor).")
        else:
            logging.error("TESSERACT CALISMIYOR: %s", self.goz.son_ocr_hatasi)
            logging.error("Cozum: Tesseract kurun / config.json > ocr.tesseract_yolu")
        logging.info("Kamera cevirme (E): %s", "ACIK" if self._kamera_aktif() else "KAPALI")
        self.sablon_kur()
        self.ek_kur()

    def _arka_yakalayici_kur(self):
        """arka plan goruntu yontemi: 'wgc' (onerilen) ya da 'printwindow'"""
        yontem = self.cfg.get("girdi", {}).get("yakalama", "otomatik")
        self.wgc = None
        if yontem in ("otomatik", "wgc"):
            try:
                from vision import wgc_al
                self.wgc = wgc_al(self.hwnd)
                logging.info("Arka plan goruntusu: Windows Graphics Capture")
                return
            except ImportError:
                logging.warning("windows-capture kurulu degil -> PrintWindow deneniyor "
                                "(siyah gelirse: pip install windows-capture)")
            except Exception as hata:
                logging.warning("Windows Graphics Capture baslatilamadi: %s", hata)
        logging.info("Arka plan goruntusu: PrintWindow")

    def _kare_al(self):
        if self.girdi.arka_plan:
            if getattr(self, "wgc", None) is not None:
                kare = self.wgc.kare()
                if kare is None or kare.bgr.size == 0:
                    if time.time() - self._son_bos_uyari > 5:
                        logging.warning("Arka plan goruntusu gelmiyor (oyun simge durumunda mi?) %s",
                                        self.wgc.hata or "")
                        self._son_bos_uyari = time.time()
                    return None
                return kare
            kare = self.goz.yakala_pencere(self.hwnd)
            if self.goz.kare_bos_mu(kare):
                if time.time() - self._son_bos_uyari > 5:
                    logging.warning("Arka plan goruntusu SIYAH geliyor -> bu oyun "
                                    "PrintWindow desteklemiyor, on plan modunu kullanin")
                    self._son_bos_uyari = time.time()
                return None
            return kare
        return self.goz.yakala(girdi.istemci_alani(self.hwnd))

    def calistir(self):
        self.hazirlik()
        g = self.cfg["guvenlik"]
        if not self.girdi.arka_plan:
            girdi.one_getir(self.hwnd)
        kaydet = self.cfg["gunluk"].get("kare_kaydet")
        klasor = os.path.join(BURASI, self.cfg["gunluk"].get("kare_klasoru", "debug"))
        if kaydet and not os.path.isdir(klasor):
            os.makedirs(klasor)
        if self.girdi.arka_plan:
            self._arka_yakalayici_kur()
        self._boss_kur()
        self.basla_zamani = time.time()
        logging.info("Bot calisiyor.")

        while self.calisiyor:
            try:
                if self.duraklat:
                    time.sleep(0.3)
                    continue
                if (not self.girdi.arka_plan and g["pencere_odakta_degilse_bekle"]
                        and not girdi.odakta_mi(self.hwnd)):
                    time.sleep(0.4)
                    continue

                if self.boss is not None and (self.boss_istegi
                                              or self.boss.zamani_geldi_mi()):
                    self.boss_istegi = False
                    self._boss_turu()
                    continue

                kare = self._kare_al()
                if kare is None:
                    time.sleep(1.0)
                    continue
                self.kare_boyutu = kare.bgr.shape[:2]

                self._pelerin_bas()

                # taslardan bagimsiz: eklenen resim ekrandaysa once ona tikla
                if self.ek is not None and self.ek.kontrol(
                        kare, self.girdi, kare_al=self._kare_al,
                        durdu_mu=lambda: (not self.calisiyor) or self.duraklat):
                    self.hemen_tara = True
                    continue

                aralik = self.z.get("kesme_sirasinda_tarama_araligi", 1.0)
                if (self.hemen_tara or self.durum == ARIYOR
                        or time.time() - self.son_tarama > aralik):
                    self._tara(kare)

                self._adim(kare)

                if kaydet:
                    self._kareyi_kaydet(kare, klasor)

                time.sleep(self.z["dongu_araligi"])

            except KeyboardInterrupt:
                break
            except Exception:
                logging.exception("Dongu hatasi, 1 sn sonra devam")
                time.sleep(1.0)

        self.calisiyor = False
        if getattr(self, "wgc", None) is not None:
            from vision import wgc_birak
            wgc_birak(self.hwnd)
            self.wgc = None
        logging.info("Bot durdu. Kirilan tas: %d  Takilma: %d", self.kirilan, self.takilma)

    def _tarama_gunlugu(self):
        simdi = time.time()
        if simdi - self._son_gunluk < 3.0:
            return
        self._son_gunluk = simdi
        if not self.taslar:
            logging.info("Etiket bulunamadi (arama_bolgesi / parlaklik esigi?)")
            return
        hedef = [t for t in self.taslar if self._tas_hedef_mi(t)]
        logging.debug("Etiket: %d  Hedef: %d (resimle %d, %.0f ms) -> %s", len(self.taslar),
                      len(hedef), sum(1 for t in hedef if t.sablon),
                      1000 * (self.sablon.son_sure if self.sablon else 0),
                      ", ".join("%r" % t.yazi for t in hedef[:5]))

    # ---------------- boss turu ----------------

    def _boss_kur(self):
        """Boss cagirma modulu (config > boss > aktif ise)."""
        b = self.cfg.get("boss", {})
        if not b.get("aktif"):
            self.boss = None
            return
        try:
            from boss import BossCagirici
        except Exception as hata:
            logging.warning("Boss modulu yuklenemedi: %s", hata)
            self.boss = None
            return
        self.boss = BossCagirici(self.cfg, self.goz, self.girdi, self.hwnd,
                                 kare_al=self._kare_al, gunluk=logging.info)
        if not self.boss.hazir_mi():
            logging.warning("Boss turu KAPALI: logo sablonu ya da boss listesi eksik")
            self.boss = None
            return
        logging.info("Boss turu ACIK: her %s dk, %d boss (%s)",
                     b.get("periyot_dakika", 120), len(self.boss.liste()),
                     ", ".join(self.boss.liste()[:3]) +
                     (" ..." if len(self.boss.liste()) > 3 else ""))

    def boss_turu_iste(self):
        """GUI: siradaki dongude boss turu yap."""
        self.boss_istegi = True

    def _boss_turu(self):
        logging.info("--- Boss zamani: metin kesme duraklatildi ---")
        self.hedef_tas = None
        self.taslar = []
        self._durum(ARIYOR)
        try:
            self.boss.tur(durdur_kontrol=lambda: (not self.calisiyor) or self.duraklat)
        except Exception:
            logging.exception("Boss turu hatasi")
        finally:
            self.boss.son_tur = time.time()
            self.hedef_tas = None
            self.taslar = []
            self.olu_nokta = None
            self.son_imza = None
            self.tik_oncesi_imza = None
            self.terk_imza = None
            self.bar_yok_sayac = 0
            self.son_can_degisimi = time.time()
            self.son_aday_gorulme = time.time()
            self._hasar_sifirla()
            self._durum(ARIYOR)
            self.hemen_tara = True
            # Boss'a vururken SPACE yakindaki metne de deger; ekranda o metnin
            # can bari asili kalir. Bot onu "kendi kestigim tas" sanmasin diye
            # kisa bir sure yok sayilir, kendi tasini kendi secer.
            self.bar_yoksay_kadar = time.time() + float(
                self.cfg.get("boss", {}).get("tur_sonrasi_bar_yoksay", 4.0))
            logging.info("--- Metin farmina donuldu (sonraki boss turu ~%.0f dk sonra) ---",
                         self.boss.kalan_sure() / 60.0)

    def _kareyi_kaydet(self, kare, klasor):
        gorsel = kare.bgr.copy()
        x1, y1, x2, y2 = self.goz.arama_bolgesi(kare)
        cv2.rectangle(gorsel, (x1, y1), (x2, y2), (80, 80, 80), 1)
        bx1, by1, bx2, by2 = self.bar.bolge(kare)
        cv2.rectangle(gorsel, (bx1, by1), (bx2, by2), (255, 0, 255), 1)
        for tas in self.taslar:
            e = tas.etiket
            renk = (255, 0, 255) if tas.sablon else (0, 255, 0) if tas.sinif == "hedef" \
                else (0, 200, 255) if tas.sinif == "belirsiz" else (120, 120, 120)
            cv2.rectangle(gorsel, (e.x, e.y), (e.x + e.w, e.y + e.h), renk, 1)
        cv2.putText(gorsel, "%s  kirilan=%d" % (self.durum, self.kirilan),
                    (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imwrite(os.path.join(klasor, "kare_%d.png" % int(time.time() * 10)), gorsel)


def _kisayollari_kur(bot, cfg):
    try:
        import keyboard
    except ImportError:
        logging.warning("keyboard modulu yok; F12/F11 devre disi (Ctrl+C ile durdurun)")
        return
    g = cfg["guvenlik"]
    keyboard.add_hotkey(g["durdurma_tusu"], bot.durdur)
    keyboard.add_hotkey(g["duraklat_tusu"], bot.duraklat_degistir)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    pid, sor = None, True
    if "--pid" in sys.argv:
        pid = int(sys.argv[sys.argv.index("--pid") + 1])
        sor = False
    if "--sorma" in sys.argv:
        sor = False

    if pid:
        ham = ayar.yukle()
        ham.setdefault("pencere", {})["pid"] = pid
        ayar.kaydet(ham)

    cfg, hwnd, baslik = ayar.hazirla(sor=sor)
    logging.getLogger().setLevel(
        getattr(logging, cfg["gunluk"]["seviye"].upper(), logging.INFO))
    bot = MetinBotu(cfg, hwnd, baslik)
    _kisayollari_kur(bot, cfg)
    bot.calistir()


if __name__ == "__main__":
    main()
