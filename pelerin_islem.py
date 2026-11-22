# -*- coding: utf-8 -*-
"""
Pelerin gonderici (ARKA PLAN, At Ustu Cekme Vurma).

Botun ICINDE ama ayri bir islemde (multiprocessing) calisir: test programi
kendi basina calisirken F1 oyuna gidiyordu, botun ana isleminden gonderilince
gitmiyordu. Bu islem, test programinin yaptiginin aynisini yapar.
Kullanici ayri bir sey acmaz; bot baslatir ve durdurur.
"""

import random
import time


def _space(girdi, hwnd, indir):
    vk, kod = 0x20, 0x39
    if indir:
        girdi._post_test(hwnd, girdi.WM_KEYDOWN, vk, 1 | (kod << 16))
    else:
        girdi._post_test(hwnd, girdi.WM_KEYUP, vk, 1 | (kod << 16) | 0xC0000000)


def calis(hwnd, tus, yontem, aralik_deger, sure_deger, dur, bekle, sayac,
          space_ara=None):
    """dur: bitir. bekle: set iken basma (duraklat/olum). sayac: gonderilen pelerin."""
    import girdi
    sonraki = time.time()
    while not dur.is_set():
        if bekle.is_set():
            time.sleep(0.1)
            sonraki = time.time()
            continue
        simdi = time.time()
        if simdi >= sonraki:
            aralik = max(0.3, float(aralik_deger.value))
            sure = max(0.05, min(float(sure_deger.value), aralik - 0.1))
            try:
                if space_ara is not None:
                    # Arka planda SPACE basiliyken oyun F1'i almiyor:
                    # SPACE'i cok kisa birak -> F1 -> SPACE'e yeniden bas.
                    space_ara.set()
                    time.sleep(0.03)
                    _space(girdi, hwnd, False)
                    time.sleep(0.05)
                    try:
                        girdi.arka_pelerin(hwnd, tus, yontem, sure, dur.is_set)
                    finally:
                        time.sleep(0.03)
                        if not bekle.is_set() and not dur.is_set():
                            _space(girdi, hwnd, True)
                        space_ara.clear()
                else:
                    girdi.arka_pelerin(hwnd, tus, yontem, sure, dur.is_set)
                with sayac.get_lock():
                    sayac.value += 1
            except Exception:
                pass
            sonraki = simdi + aralik + random.uniform(-aralik * 0.1, aralik * 0.1)
        time.sleep(0.02)
