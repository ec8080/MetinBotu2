# -*- coding: utf-8 -*-
"""
At Ustu Cekme Vurma
-------------------
Metin kesmeden AYRI bir calisma sekli. Karakter atin ustunde yerinde durur:
  * SPACE surekli basili tutulur (vurus),
  * kullanicinin sectigi tustaki pelerin belli araliklarla basilir (yaratik cekme),
  * istenirse olum kontrolu: 'olum' klasorundeki resim ekranda gorulurse
    vurus durur; ya o resme (orn. 'Burada yeniden basla') insansi tiklanip
    devam edilir ya da bu client durdurulur,
  * istenirse ek gorsel tiklama ('tiklanacaklar' klasoru) burada da calisir.

Tek client: pencere onde, gercek klavye.
Coklu client (SiraliCekmeVurma): client'lar SIRAYLA one getirilir. Oyun, pencere
degisirken SPACE'in birakildigini gormedigi icin arkada kalan client'lar vurmaya
devam eder. Her client'ta kisa bir sure kalinip SPACE yeniden basilir ve pelerin
basilir, sonra SPACE basiliyken siradakine gecilir.
"""

import logging
import random
import threading
import time

import girdi
from ek_tiklama import EkTiklayici
from vision import Goz

CALISIYOR = "CEKME-VURMA"
OLDU = "OLDU"
DURDU = "DURDU"


class _BirakanGirdi:
    """Ek tiklama tiklamadan once SPACE'i birakir (tik dogru gitsin)."""

    def __init__(self, sahip):
        self.sahip = sahip

    def zorla_birak(self):
        """Tiklama tutmadiysa: tekrar denemeden once SPACE'i birak."""
        self.sahip._space_birak()

    def __getattr__(self, ad):
        hedef = getattr(self.sahip.girdi, ad)
        if ad in ("tikla", "sag_tikla", "yavas_tikla") and \
                self.sahip.a.get("tiklarken_space_birak", False):
            def sarili(*a, **k):
                self.sahip._space_birak()
                return hedef(*a, **k)
            return sarili
        return hedef


class CekmeVurma:
    def __init__(self, cfg, hwnd, baslik):
        self.cfg = cfg
        self.hwnd = hwnd
        self.baslik = baslik
        g = cfg.get("girdi", {})
        # Oyun arka plandayken SPACE'i basili tutmayi kabul etmiyor -> bu mod
        # varsayilan olarak ON PLANDA calisir (gercek klavye, pencere onde).
        mod = "on_plan" if cfg.get("cekme_vurma", {}).get("on_plan", True) else "arka_plan"
        self.girdi = girdi.Girdi(hwnd, mod,
                                 cfg["guvenlik"].get("insansi_fare", True), g.get("arka_imlec", True),
                                 cfg.get("cekme_vurma", {}).get("arka_tus_yontemi", "guclu"))
        self.goz = None
        self.wgc = None
        self.olum = None
        self.ek = None

        self.calisiyor = True
        self.duraklat = False
        self.durum = CALISIYOR
        self.space_basili = False
        self._son_space = 0.0
        self._sonraki_pelerin = 0.0
        self._son_kontrol = 0.0
        self._son_bos_uyari = 0.0

        self.sirali = False            # SiraliCekmeVurma icindeyse goruntu hep WGC'den
        self.olu_bekliyor = False      # oldu, 'Burada yeniden basla' icin sure doluyor
        self._pel_thread = None        # arka planda pelerin gonderen thread
        self._pel_islem = None         # arka planda pelerin gonderen ayri islem (bot icinde)
        self._pel_tus = None           # arka planda basili tutulan pelerin tusu
        self._pel_bitis = 0.0
        self._pel_son = 0.0
        self.diril_zamani = 0.0
        self.basla_zamani = None
        self.pelerin_sayisi = 0
        self.olum_sayisi = 0
        self.son_olum = None

    # ---------- ayarlar ----------
    @property
    def a(self):
        return self.cfg.get("cekme_vurma", {})

    def _pelerin_tusu(self):
        return str(self.a.get("pelerin_tusu", "4")).strip().lower()

    # ---------- GUI'den ----------
    def durdur(self):
        self.calisiyor = False

    def duraklat_degistir(self):
        self.duraklat = not self.duraklat
        logging.info("DURAKLATILDI" if self.duraklat else "DEVAM")
        if self.duraklat:
            self._space_birak()
        return self.duraklat

    def ozet(self):
        return {
            "durum": DURDU if not self.calisiyor else
            ("DURAKLATILDI" if self.duraklat else self.durum),
            "pelerin": self.pelerin_sayisi,
            "olum": self.olum_sayisi,
            "sure": (time.time() - self.basla_zamani) if self.basla_zamani else 0,
        }

    # ---------- tuslar ----------
    def _space_tut(self):
        """SPACE basili kalsin: klavyenin tekrar ozelligi gibi ~0.1 sn'de bir."""
        simdi = time.time()
        if simdi - self._son_space < float(self.a.get("space_tekrar", 0.1)):
            return
        if (self.space_basili and self.girdi.arka_plan
                and str(self.a.get("pelerin_yontemi")) == "9"):
            return                             # gercek klavye gibi: tekrar yok, basili kalir
        ara = getattr(self, "_pi_space", None)
        if self._pel_islem is not None and ara is not None and ara.is_set():
            self._son_space = simdi            # F1 icin kisa SPACE araligi: bekle
            return
        self.girdi.tus_indir("space", tekrar=self.space_basili)
        if not self.space_basili:
            logging.info("SPACE basili tutuluyor (vurus)")
        self.space_basili = True
        self._son_space = simdi

    def _space_birak(self):
        self._pelerin_birak()
        if self.space_basili:
            try:
                self.girdi.tus_kaldir("space")
            except Exception:
                logging.exception("SPACE birakilamadi")
            self.space_basili = False

    def _pelerin_birak(self):
        if self._pel_tus:
            try:
                self.girdi.tus_kaldir(self._pel_tus)
            except Exception:
                logging.exception("Pelerin tusu birakilamadi")
            self._pel_tus = None

    def _pelerin_tut(self):
        """ARKA PLAN: pelerin tusu basili tutuluyorsa tekrar mesajlarini gonder,
        sure dolunca birak. SPACE ayni anda basili kalir (testte 1. yontem)."""
        if not self._pel_tus:
            return
        simdi = time.time()
        if simdi >= self._pel_bitis:
            self._pelerin_birak()
            return
        if simdi - self._pel_son >= 0.05:
            self.girdi.tus_indir(self._pel_tus, tekrar=True)
            self._pel_son = simdi

    # ---------- ARKA PLAN pelerin: bot icinde ayri islem ----------
    def _islem_ayar(self):
        tus = self._pelerin_tusu()
        yontem = str(self.a.get("pelerin_yontemi", "8"))
        aralik = max(0.5, float(self.a.get("pelerin_araligi", 5.0)))
        sure = float(self.a.get("pelerin_basili_sure", 1.0))
        return tus, yontem, aralik, sure

    def _sag_tik(self, simdi):
        """Ayarli konuma belli araliklarla sag tik. SPACE ve pelerin devam eder."""
        if not self.a.get("sag_tik_aktif"):
            return
        x, y = self.a.get("sag_tik_x"), self.a.get("sag_tik_y")
        if x is None or y is None:
            return
        if simdi < getattr(self, "_sonraki_sag", 0.0):
            return
        aralik = max(0.3, float(self.a.get("sag_tik_araligi", 5.0)))
        try:
            self.girdi.sag_tikla(int(x), int(y))
            self.sag_tik_sayisi = getattr(self, "sag_tik_sayisi", 0) + 1
            if self.sag_tik_sayisi <= 3:
                logging.info("Sag tik: x=%d, y=%d (%s)", x, y, self.hwnd)
        except Exception:
            logging.exception("Sag tik yapilamadi")
        self._sonraki_sag = simdi + aralik + random.uniform(-aralik * 0.05, aralik * 0.05)

    def _islem_baslat(self):
        import multiprocessing as mp
        import pelerin_islem
        tus, yontem, aralik, sure = self._islem_ayar()
        if tus not in girdi.SCAN:
            logging.error("Pelerin tusu '%s' taninmadi", tus)
            return
        self._pi_dur = mp.Event()
        self._pi_bekle = mp.Event()
        self._pi_aralik = mp.Value("d", aralik)
        self._pi_sure = mp.Value("d", sure)
        self._pi_sayac = mp.Value("i", 0)
        self._pi_space = mp.Event() if self.a.get("pelerinde_space_kisa_birak", True) else None
        self._pi_anahtar = (tus, yontem)
        self._pel_islem = mp.Process(
            target=pelerin_islem.calis,
            args=(int(self.hwnd), tus, yontem, self._pi_aralik, self._pi_sure,
                  self._pi_dur, self._pi_bekle, self._pi_sayac, self._pi_space),
            daemon=True)
        self._pel_islem.start()
        logging.info("Pelerin (arka plan) ayri islemde: %s, yontem %s, %.1f sn'de bir",
                     tus.upper(), girdi.PELERIN_YONTEMLERI.get(yontem, yontem), aralik)

    def _islem_durdur(self):
        if self._pel_islem is None:
            return
        try:
            self._pi_dur.set()
            self._pel_islem.join(2.0)
            if self._pel_islem.is_alive():
                self._pel_islem.terminate()
        except Exception:
            logging.exception("Pelerin islemi durdurulamadi")
        self._pi_taban = getattr(self, "_pi_taban", 0) + self._pi_sayac.value
        self.pelerin_sayisi = self._pi_taban
        self._pel_islem = None

    def _islem_guncelle(self):
        """Her donguda: ayar degistiyse uygula, duraklat/olumde beklet, sayaci al."""
        if self._pel_islem is None:
            return
        tus, yontem, aralik, sure = self._islem_ayar()
        if (tus, yontem) != self._pi_anahtar or not self._pel_islem.is_alive():
            self._islem_durdur()
            self._islem_baslat()
            return
        self._pi_aralik.value = aralik
        self._pi_sure.value = sure
        if self.duraklat or self.olu_bekliyor:
            self._pi_bekle.set()
        else:
            self._pi_bekle.clear()
        self.pelerin_sayisi = getattr(self, "_pi_taban", 0) + self._pi_sayac.value

    def _pelerin_fareyle(self, simdi):
        """ARKA PLAN: pelerin F1 yerine kisayol/envanter kutusuna tiklanarak kullanilir
        (oyun arkadayken klavye kisayolunu almiyor, tiklamayi aliyor)."""
        if simdi < self._sonraki_pelerin:
            return
        x, y = self.a.get("pelerin_tik_x"), self.a.get("pelerin_tik_y")
        aralik = max(0.5, float(self.a.get("pelerin_araligi", 5.0)))
        if x is None or y is None:
            if simdi - self._son_bos_uyari > 10:
                logging.error("Pelerin kutusunun konumu secilmedi ('Konum sec' ile secin)")
                self._son_bos_uyari = simdi
            self._sonraki_pelerin = simdi + 2
            return
        sag = self.a.get("pelerin_tik_tur", "sol") == "sag"
        imlec = bool(self.a.get("pelerin_tik_imlec", False))   # False: fare hic oynamaz
        try:
            if not imlec:
                girdi.arka_tikla_sessiz(self.hwnd, int(x), int(y), sag)
            elif sag:
                girdi.arka_sag_tikla(self.hwnd, int(x), int(y), True)
            else:
                girdi.arka_tikla(self.hwnd, int(x), int(y), True)
            self.pelerin_sayisi += 1
            if self.pelerin_sayisi <= 3:
                logging.info("Pelerin fareyle: %s tik x=%d, y=%d (%s)", "sag" if sag else "sol",
                             x, y, "imlec gidip gelir" if imlec else "fare oynamaz")
        except Exception:
            logging.exception("Pelerin kutusuna tiklanamadi")
        oynama = min(max(0.0, float(self.a.get("pelerin_oynama", 0.6))), aralik * 0.1)
        self._sonraki_pelerin = simdi + aralik + random.uniform(-oynama, oynama)

    def _pelerin(self, simdi):
        if self.girdi.arka_plan and self.a.get("pelerin_tik_aktif"):
            if self._pel_islem is not None:
                self._islem_durdur()
            self._pelerin_fareyle(simdi)
            return
        if self._pel_islem is not None:
            return
        if simdi < self._sonraki_pelerin:
            return
        tus = self._pelerin_tusu()
        if tus not in girdi.SCAN:
            if self.pelerin_sayisi == 0 and simdi - self._son_bos_uyari > 10:
                logging.error("Pelerin tusu '%s' taninmadi (1-9, 0, F1-F10, harf olmali)", tus)
                self._son_bos_uyari = simdi
            self._sonraki_pelerin = simdi + 5
            return
        aralik = max(0.5, float(self.a.get("pelerin_araligi", 5.0)))
        if self.girdi.arka_plan:
            # ARKA PLAN: secilen yontem (SpaceTesti numaralari) ayri thread'de calisir,
            # SPACE ayni anda basili kalir.
            if self._pel_thread is not None and self._pel_thread.is_alive():
                return                            # onceki basis hala suruyor
            yontem = str(self.a.get("pelerin_yontemi", "1"))
            sure = float(self.a.get("pelerin_basili_sure", 1.0))
            sure = max(0.2, min(sure, aralik - 0.1))
            def gonder(tus=tus, yontem=yontem, sure=sure, n=self.pelerin_sayisi + 1):
                try:
                    once = dict(girdi.PELERIN_ISTAT)
                    girdi.arka_pelerin(self.hwnd, tus, yontem, sure,
                                       lambda: not self.calisiyor or self.duraklat)
                    if n <= 3:
                        sonra = girdi.PELERIN_ISTAT
                        logging.info("Pelerin #%d gonderildi: kabul %d, RED %d%s", n,
                                     sonra["ok"] - once["ok"], sonra["hata"] - once["hata"],
                                     " (hata kodu %d)" % sonra["kod"] if sonra["hata"] > once["hata"] else "")
                except Exception:
                    logging.exception("Pelerin gonderilirken HATA")
            self._pel_thread = threading.Thread(target=gonder, daemon=True)
            self._pel_thread.start()
            basis = "yontem %s, %.1f sn" % (girdi.PELERIN_YONTEMLERI.get(yontem, yontem), sure)
        else:
            self.girdi.tus_bas(tus, random.uniform(0.04, 0.08))
            basis = "on plan"
        self.pelerin_sayisi += 1
        if self.pelerin_sayisi == 1 or basis != getattr(self, "_son_basis", None):
            logging.info("Pelerin gonderiliyor (%s, %s)", tus.upper(), basis)
            self._son_basis = basis
        # girilen sureye sadik kal: en fazla %10 oynama
        oynama = min(max(0.0, float(self.a.get("pelerin_oynama", 0.6))), aralik * 0.1)
        self._sonraki_pelerin = simdi + aralik + random.uniform(-oynama, oynama)
        logging.debug("Pelerin (%s) #%d", tus, self.pelerin_sayisi)

    # ---------- goruntu ----------
    def _yakalayici_kur(self):
        if not (self.girdi.arka_plan or self.sirali):
            return
        try:
            from vision import wgc_al
            self.wgc = wgc_al(self.hwnd)
            logging.info("Arka plan goruntusu: Windows Graphics Capture")
        except Exception as hata:
            self.wgc = None
            logging.info("Arka plan goruntusu: PrintWindow (%s)", hata)

    def _kare_al(self):
        if self.girdi.arka_plan or self.sirali:
            if self.wgc is not None:
                kare = self.wgc.kare()
                if kare is None or kare.bgr.size == 0:
                    if time.time() - self._son_bos_uyari > 5:
                        logging.warning("Arka plan goruntusu gelmiyor (oyun simge durumunda mi?)")
                        self._son_bos_uyari = time.time()
                    return None
                return kare
            kare = self.goz.yakala_pencere(self.hwnd)
            return None if self.goz.kare_bos_mu(kare) else kare
        return self.goz.yakala(girdi.istemci_alani(self.hwnd))

    # ---------- olum ----------
    # Olum sirasi (oyunun istedigi):
    #   oldu -> SPACE birak -> 10 sn bekle -> 'Burada yeniden basla' tikla
    #   -> 0.5 sn -> ctrl+g (ata bin) -> 2.5 sn -> SPACE'e devam
    def _olum_basladi(self, kare):
        """Olum ekrani gorulduyse: SPACE birakilir, dirilme zamani kurulur. True/False."""
        o = self.cfg.get("olum_kontrol", {})
        if self.olu_bekliyor:
            return True
        if not o.get("aktif", False) or self.olum is None or not self.olum.gorseller:
            return False
        bulunan = self.olum.bul(kare)
        if bulunan is None:
            return False
        g, puan, _, _ = bulunan
        self._space_birak()
        self.olum_sayisi += 1
        self.son_olum = time.time()
        self.durum = OLDU
        if o.get("davranis", "tikla") == "durdur":
            logging.warning("OLUM algilandi (toplam %d) - ayar 'durdur': bu client durduruluyor",
                            self.olum_sayisi)
            self.calisiyor = False
            return True
        bekle = float(o.get("tiklama_oncesi_bekleme", 10.0))
        self.olu_bekliyor = True
        self.diril_zamani = time.time() + bekle
        logging.warning("OLUM algilandi (puan %.2f, toplam %d) -> %.1f sn sonra 'Burada yeniden "
                        "basla'", puan, self.olum_sayisi, bekle)
        return True

    def _dirilt(self):
        """Sure dolunca: butona tikla, bekle, ctrl+g, bekle. Pencere ONDE olmali."""
        o = self.cfg.get("olum_kontrol", {})
        kare = self._kare_al()
        bulunan = self.olum.bul(kare) if kare is not None else None
        if bulunan is None:
            logging.info("'Burada yeniden basla' artik gorunmuyor (zaten dirilmis olabilir)")
            self.olu_bekliyor = False
            self.durum = CALISIYOR
            return True
        # tikla ve DOGRULA: buton hala ekrandaysa tiklama tutmamistir -> BASKA YONTEMLE tekrar
        yontemler = ["yavas", "klasik", "guclu"]
        ilk = getattr(self, "_olum_yontemi", None)      # daha once tutan yontem once denenir
        if ilk in yontemler:
            yontemler.remove(ilk)
            yontemler.insert(0, ilk)
        self.girdi.tus_kaldir("space")                  # her ihtimale karsi SPACE birakilsin
        self.space_basili = False
        kapandi = False
        for deneme, yontem in enumerate(yontemler, 1):
            if not self.calisiyor:
                return False
            g, puan, cx, cy = bulunan
            cx += random.randint(-12, 12)
            cy += random.randint(-2, 2)
            if yontem == "klasik":
                self.girdi.tikla(cx, cy)
            elif yontem == "guclu":
                self.girdi.guclu_tikla(cx, cy)
            else:
                self.girdi.yavas_tikla(cx, cy, g.tur, self.cfg.get("ek_tiklama", {}))
            logging.info("'%s' tiklandi (%d. deneme, yontem %s, konum %d,%d)", g.ad, deneme,
                         yontem, cx, cy)
            # ekranin kapanmasini 2 sn'ye kadar bekle
            bitis = time.time() + max(2.0, float(o.get("dirilme_sonrasi_bekleme", 0.5)))
            while self.calisiyor and time.time() < bitis:
                time.sleep(0.2)
                kare = self._kare_al()
                bulunan = self.olum.bul(kare) if kare is not None else None
                if bulunan is None:
                    break
            if bulunan is None:
                kapandi = True
                self._olum_yontemi = yontem
                logging.info("Olum ekrani kapandi (tutan yontem: %s)", yontem)
                break
            logging.warning("Olum ekrani hala acik (%s yontemi tutmadi) -> baska yontem", yontem)
        if not kapandi:
            logging.warning("'Burada yeniden basla' 3 yontemle de kapanmadi; 3 sn sonra yeniden "
                            "denenecek")
            self.diril_zamani = time.time() + 3.0
            return False
        self._bekle(float(o.get("dirilme_sonrasi_bekleme", 0.5)))
        self._dirilince_tuslar(o)
        self.olu_bekliyor = False
        self.son_dirilme = time.time()
        self._sonraki_pelerin = 0.0           # hemen pelerin bas
        self.durum = CALISIYOR
        return True

    def _olum_kontrol(self, kare):
        """Tek client: olumu gor, sureyi bekle, dirilt (hepsi burada)."""
        if not self._olum_basladi(kare):
            return False
        if not self.calisiyor:
            return True
        while self.calisiyor and self.olu_bekliyor:
            while self.calisiyor and time.time() < self.diril_zamani:
                time.sleep(0.05)
            if self.calisiyor:
                self._dirilt()
        return True

    def _dirilince_tuslar(self, o):
        """Olunce karakter attan iner: orn. 'ctrl+g' ile ata bin, sonra vurusa don."""
        for tus in o.get("dirilince_basilacak_tuslar", []) or []:
            if not self.calisiyor:
                return
            parcalar = [p.strip().lower() for p in str(tus).split("+") if p.strip()]
            if not parcalar or any(p not in girdi.SCAN for p in parcalar):
                logging.warning("Dirilince basilacak tus taninmadi: %r", tus)
                continue
            if len(parcalar) > 1:
                self.girdi.tus_kombin(parcalar, random.uniform(0.08, 0.14))
            else:
                self.girdi.tus_bas(parcalar[0], random.uniform(0.05, 0.09))
            logging.info("Dirilince: %s basildi", "+".join(p.upper() for p in parcalar))
            self._bekle(float(o.get("tus_sonrasi_bekleme", 2.5)))

    def _bekle(self, sn):
        bitis = time.time() + max(0.0, sn)
        while self.calisiyor and time.time() < bitis:
            time.sleep(0.05)

    # ---------- ana dongu ----------
    def calistir(self):
        self.goz = Goz(self.cfg)
        self.olum = EkTiklayici(self.cfg, "olum_kontrol")
        self.ek = EkTiklayici(self.cfg, "ek_tiklama")
        logging.info("At ustu cekme vurma: pencere=%s  mod=%s  pelerin tusu=%s  aralik=%.1f sn",
                     self.baslik, "ARKA PLAN" if self.girdi.arka_plan else "on plan",
                     self._pelerin_tusu().upper(), float(self.a.get("pelerin_araligi", 5.0)))
        oc = self.cfg.get("olum_kontrol", {})
        logging.info("Olum kontrolu: %s", ("ACIK (%d resim, %s)" % (
            len(self.olum.gorseller),
            "resme tikla ve devam" if oc.get("davranis", "tikla") != "durdur" else "client'i durdur"))
            if oc.get("aktif") else "KAPALI")
        if oc.get("aktif") and not self.olum.gorseller:
            logging.warning("Olum kontrolu acik ama 'olum' klasorunde resim yok.")
        if not self.girdi.arka_plan:
            girdi.one_getir(self.hwnd)
        self._yakalayici_kur()
        self.basla_zamani = time.time()
        bekci = _BirakanGirdi(self)
        if (self.girdi.arka_plan and self.a.get("pelerin_ayri_islem", True)
                and not self.a.get("pelerin_tik_aktif")):
            try:
                self._islem_baslat()
            except Exception:
                logging.exception("Pelerin islemi baslatilamadi, eski yonteme donuluyor")
                self._pel_islem = None

        try:
            while self.calisiyor:
                if not girdi.pencere_var_mi(self.hwnd):
                    logging.warning("Oyun penceresi KAPANDI (client kapandi/coktu) -> durduruldu")
                    self.space_basili = False
                    break
                self._islem_guncelle()
                if self.duraklat:
                    self._space_birak()
                    time.sleep(0.2)
                    continue
                if (not self.girdi.arka_plan and self.cfg["guvenlik"].get(
                        "pencere_odakta_degilse_bekle", True) and not girdi.odakta_mi(self.hwnd)):
                    self._space_birak()
                    time.sleep(0.3)
                    continue

                simdi = time.time()
                # goruntu kontrolleri (olum + ek tiklama)
                if simdi - self._son_kontrol >= float(self.a.get("kontrol_araligi", 0.5)):
                    self._son_kontrol = simdi
                    kare = self._kare_al()
                    if kare is not None:
                        if self._olum_kontrol(kare):
                            continue
                        if self.cfg.get("ek_tiklama", {}).get("aktif") and self.ek.kontrol(
                                kare, bekci, kare_al=self._kare_al,
                                durdu_mu=lambda: (not self.calisiyor) or self.duraklat):
                            continue

                self._space_tut()
                self._pelerin_tut()
                self._pelerin(time.time())
                self._sag_tik(time.time())
                time.sleep(0.03)
        except Exception:
            logging.exception("At ustu cekme vurma hatayla durdu")
        finally:
            self._islem_durdur()
            self._space_birak()
            if self.wgc is not None:
                try:
                    from vision import wgc_birak
                    wgc_birak(self.hwnd)
                except Exception:
                    pass
            self.calisiyor = False
            logging.info("At ustu cekme vurma durdu. Pelerin: %d  Olum: %d",
                         self.pelerin_sayisi, self.olum_sayisi)


# ======================================================================
#  COKLU CLIENT: sirayla one getir
# ======================================================================
class _Gorunum:
    """GUI icin her client'in kendi satiri; isler ortak denetleyiciye gider."""

    def __init__(self, denetleyici, istemci):
        self._d = denetleyici
        self._c = istemci

    def __getattr__(self, ad):
        return getattr(self._c, ad)

    @property
    def duraklat(self):
        return self._d.duraklat

    def duraklat_degistir(self):
        return self._d.duraklat_degistir()

    def durdur(self):
        self._d.cikar(self._c)

    def ozet(self):
        o = self._c.ozet()
        if self._c.calisiyor and self._d.calisiyor:
            if self._d.duraklat:
                o["durum"] = "DURAKLATILDI"
            elif self._c.durum == OLDU:
                o["durum"] = OLDU
            else:
                o["durum"] = "ONDE (sirada)" if self._d.simdiki is self._c else "ARKADA vuruyor"
        return o


class SiraliCekmeVurma:
    """Birden fazla client: sirayla one getir, SPACE basili birakarak gec."""

    def __init__(self, istemciler):
        self.istemciler = list(istemciler)
        for c in self.istemciler:
            c.sirali = True
        self.calisiyor = True
        self.duraklat = False
        self.simdiki = None
        self._birakilacak = []        # durdurulan client'lar: SPACE'i birakilacak
        self._oncelik = None          # arkada olum/gorsel goruldu -> hemen one alinacak
        self._son_uyari = {}

    @property
    def a(self):
        return self.istemciler[0].a if self.istemciler else {}

    # ---------- GUI ----------
    def gorunumler(self):
        return [(c.hwnd, _Gorunum(self, c)) for c in self.istemciler]

    def durdur(self):
        self.calisiyor = False

    def cikar(self, c):
        if c.calisiyor:
            c.calisiyor = False
            self._birakilacak.append(c)
            logging.info("PID %s siradan cikarildi", getattr(c, "pid", "?"))
        if not any(i.calisiyor for i in self.istemciler):
            self.calisiyor = False

    def duraklat_degistir(self):
        self.duraklat = not self.duraklat
        logging.info("DURAKLATILDI (tum client'larda SPACE birakiliyor)" if self.duraklat
                     else "DEVAM")
        return self.duraklat

    # ---------- yardimci ----------
    def _bekle(self, sn):
        bitis = time.time() + max(0.0, sn)
        while self.calisiyor and not self.duraklat and time.time() < bitis:
            time.sleep(0.03)

    def _one_al(self, c):
        girdi.one_getir(c.hwnd)
        bitis = time.time() + 1.5
        while time.time() < bitis:
            if girdi.odakta_mi(c.hwnd):
                time.sleep(float(self.a.get("sirali_gecis_bekleme", 0.25)))
                return True
            time.sleep(0.05)
        return False

    def _space_birak_hepsi(self, sebep):
        """Her client'i one getirip SPACE'i birak (oyun ancak ondeyken duyar)."""
        for c in self.istemciler:
            if c.space_basili:
                if self._one_al(c):
                    c._space_birak()
                c.space_basili = False
        logging.info("Tum client'larda SPACE birakildi (%s)", sebep)

    def _ilgi_gerekiyor(self, c):
        """Bu client'in ekraninda olum ya da tiklanacak gorsel var mi? (TIKLAMAZ)
        Arka plandaki client'lar da WGC ile bakilabildigi icin hepsi surekli taranir."""
        if c.olu_bekliyor:                       # olum ekrani: sadece sure dolunca
            return "diril" if time.time() >= c.diril_zamani else None
        try:
            kare = c._kare_al()
        except Exception:
            return None
        if kare is None:
            return None
        o = c.cfg.get("olum_kontrol", {})
        if o.get("aktif") and c.olum is not None and c.olum.gorseller:
            if c.olum.bul(kare) is not None:
                return "olum"
        e = c.cfg.get("ek_tiklama", {})
        if e.get("aktif") and c.ek is not None and c.ek.gorseller:
            esik = float(e.get("esik", 0.85))
            b = c.ek.bul(kare, esik=max(0.3, esik - 0.2))      # esige yakinlari da gor
            if b is not None:
                if b[1] >= esik:
                    if time.time() - b[0].son_tik >= float(e.get("ayni_resim_bekleme", 3.0)):
                        return "gorsel"
                elif time.time() - self._son_uyari.get(("yakin", id(c)), 0) > 5:
                    self._son_uyari[("yakin", id(c))] = time.time()
                    logging.info("PID %s: '%s' ESIGIN ALTINDA (puan %.2f < esik %.2f) -> "
                                 "tiklanmiyor", getattr(c, "pid", "?"), b[0].ad, b[1], esik)
        return None

    def _acil_bul(self):
        """Tum client'lari tara; ilk ilgi gerekeni dondur: (client, sebep) ya da (None, None)."""
        for c in self.istemciler:
            if not c.calisiyor:
                continue
            sebep = self._ilgi_gerekiyor(c)
            if sebep:
                return c, sebep
        return None, None

    def _space_tazele(self, c):
        c.girdi.tus_kaldir("space")
        time.sleep(0.04)
        c.girdi.tus_indir("space")
        c.space_basili = True

    def _ondekini_isle(self, c, bekci):
        """Ondeki client'ta olum/gorsel: hallet, sonra SPACE'e yeniden bas."""
        kare = c._kare_al()
        if kare is None:
            return
        if c._olum_basladi(kare):                # SPACE birakildi, sure isliyor
            return
        if c.cfg.get("ek_tiklama", {}).get("aktif"):
            c.ek._son_tarama = 0.0          # aralik beklemesine takilmasin
            if c.ek.kontrol(kare, bekci, kare_al=c._kare_al,
                            durdu_mu=lambda: (not self.calisiyor) or self.duraklat):
                if not c.space_basili:      # tiklarken birakildiysa geri bas
                    self._space_tazele(c)
            else:
                logging.info("PID %s: gorsel gorulmustu ama tiklama yapilmadi (tekrar bakilacak)",
                             getattr(c, "pid", "?"))

    def _sira(self, c):
        """Bir client'in sirasi: one al, olum/ek kontrol, SPACE'i tazele, pelerin."""
        if c.olu_bekliyor and time.time() < c.diril_zamani:
            return                                # olu: sure dolana kadar sirasi atlanir
        if not girdi.pencere_var_mi(c.hwnd):
            logging.warning("PID %s penceresi KAPANDI (client kapandi/coktu) -> siradan "
                            "cikarildi, diger client'lar devam ediyor", getattr(c, "pid", "?"))
            c.calisiyor = False
            c.space_basili = False
            c.durum = "KAPANDI"
            if not any(i.calisiyor for i in self.istemciler):
                self.calisiyor = False
            return
        if not self._one_al(c):
            c._odak_hata = getattr(c, "_odak_hata", 0) + 1
            if c._odak_hata in (1, 5) or c._odak_hata % 30 == 0:
                logging.warning("PID %s one getirilemedi, sirasi atlandi (%d. kez)",
                                getattr(c, "pid", "?"), c._odak_hata)
            return
        c._odak_hata = 0
        self.simdiki = c
        bekci = _BirakanGirdi(c)
        if c.olu_bekliyor:                        # sure doldu: dirilt, sonra normal sira
            if not c._dirilt() or not c.calisiyor:
                return
        kare = c._kare_al()
        if kare is not None:
            if c._olum_basladi(kare):
                return                            # yeni oldu: SPACE birakildi, sure basladi
            elif c.cfg.get("ek_tiklama", {}).get("aktif"):
                c.ek._son_tarama = 0.0      # sira basinda her zaman bak
                c.ek.kontrol(kare, bekci, kare_al=c._kare_al,
                             durdu_mu=lambda: (not self.calisiyor) or self.duraklat)
        # bu client'ta SPACE'e TAZE bas: onceki pencerede basili kalan tus bu pencerede
        # 'yeni basildi' sayilmayabilir -> once birak (sadece ondeki bu client duyar), sonra bas
        c.girdi.tus_kaldir("space")
        time.sleep(0.04)
        c.girdi.tus_indir("space")
        c.space_basili = True

        sure = max(0.5, float(self.a.get("sirali_tur_suresi", 2.0)))
        adet = max(0, int(self.a.get("sirali_tur_pelerin", 3)))
        tus = c._pelerin_tusu()
        aralik = sure / adet if adet else sure
        bitis = time.time() + sure
        sonraki_pelerin = time.time()
        sonraki_space = time.time() + 0.1
        tarama = max(0.2, float(self.a.get("kontrol_araligi", 0.5)))
        sonraki_tarama = time.time() + tarama
        basilan = 0
        while self.calisiyor and c.calisiyor and not self.duraklat and time.time() < bitis:
            simdi = time.time()
            # TUM client'larda olum / tiklanacak gorsel surekli aranir
            if simdi >= sonraki_tarama:
                sonraki_tarama = simdi + tarama
                acil, sebep = self._acil_bul()
                if acil is c:
                    logging.info("PID %s (onde): %s", getattr(c, "pid", "?"),
                                 "OLDU" if sebep == "olum" else "gorsel gorundu")
                    self._ondekini_isle(c, bekci)
                    if c.olu_bekliyor or not c.calisiyor:
                        break                     # olu client'ta SPACE basmaya devam etme
                    continue
                if acil is not None:
                    if time.time() - self._son_uyari.get(id(acil), 0) > 3:
                        logging.info("PID %s arkada %s -> sira beklenmeden one aliniyor",
                                     getattr(acil, "pid", "?"),
                                     {"olum": "OLDU", "diril": "dirilme suresi doldu"}.get(
                                         sebep, "gorsel gorundu"))
                        self._son_uyari[id(acil)] = time.time()
                    self._oncelik = acil
                    break
            if adet and basilan < adet and simdi >= sonraki_pelerin and tus in girdi.SCAN:
                c.girdi.tus_bas(tus, random.uniform(0.04, 0.08))
                c.pelerin_sayisi += 1
                basilan += 1
                sonraki_pelerin = simdi + aralik
            if simdi >= sonraki_space:
                c.girdi.tus_indir("space", tekrar=True)
                sonraki_space = simdi + 0.1
            time.sleep(0.02)
        # SPACE BASILI birakilarak siradakine gecilir

    # ---------- ana dongu ----------
    def calistir(self):
        for c in self.istemciler:
            c.goz = Goz(c.cfg)
            c.olum = EkTiklayici(c.cfg, "olum_kontrol")
            c.ek = EkTiklayici(c.cfg, "ek_tiklama")
            c._yakalayici_kur()
            c.basla_zamani = time.time()
        logging.info("SIRALI CEKME VURMA: %d client, her birinde %.1f sn, %d pelerin (%s tusu)",
                     len(self.istemciler), float(self.a.get("sirali_tur_suresi", 2.0)),
                     int(self.a.get("sirali_tur_pelerin", 3)),
                     self.istemciler[0]._pelerin_tusu().upper())
        try:
            while self.calisiyor:
                while self._birakilacak:
                    c = self._birakilacak.pop()
                    if c.space_basili and self._one_al(c):
                        c._space_birak()
                if self.duraklat:
                    if any(c.space_basili for c in self.istemciler):
                        self._space_birak_hepsi("duraklatildi")
                    self.simdiki = None
                    time.sleep(0.2)
                    continue
                aktif = [c for c in self.istemciler if c.calisiyor]
                if not aktif:
                    break
                for c in aktif:
                    if not self.calisiyor or self.duraklat:
                        break
                    if c.calisiyor:
                        self._sira(c)
                    # arkada olen / gorsel cikan client varsa sirayi beklemeden onu isle
                    sinir = 0
                    while (self._oncelik is not None and self.calisiyor and not self.duraklat
                           and sinir < len(self.istemciler)):
                        o, self._oncelik = self._oncelik, None
                        sinir += 1
                        if o.calisiyor:
                            self._sira(o)
        except Exception:
            logging.exception("Sirali cekme vurma hatayla durdu")
        finally:
            self.simdiki = None
            try:
                self._space_birak_hepsi("durduruldu")
            except Exception:
                logging.exception("SPACE birakilirken hata")
            for c in self.istemciler:
                c.calisiyor = False
                if c.wgc is not None:
                    try:
                        from vision import wgc_birak
                        wgc_birak(c.hwnd)
                    except Exception:
                        pass
            self.calisiyor = False
            logging.info("Sirali cekme vurma durdu. " + "  ".join(
                "PID %s: pelerin %d, olum %d" % (getattr(c, "pid", "?"), c.pelerin_sayisi,
                                                  c.olum_sayisi) for c in self.istemciler))
