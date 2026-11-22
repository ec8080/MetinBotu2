# -*- coding: utf-8 -*-
"""
Windows girdi katmani: insansi fare hareketi + tus basma (SendInput).
pyautogui yerine dogrudan SendInput kullaniliyor; oyun istemcileri bunu
daha guvenilir aliyor.
"""

import ctypes
import math
import random
import threading
import time

try:
    import win32gui
    import win32process
    import win32con
    import win32api
except ImportError:  # Windows disinda sadece import edilebilsin diye
    win32gui = win32process = win32con = win32api = None

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


def dpi_farkinda_ol():
    """Windows olcekleme (%125, %150) acikken pencere koordinatlari ile ekran
    goruntusu piksellerinin ayni olmasi icin. Program basinda bir kez cagrilir."""
    if user32 is None:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


dpi_farkinda_ol()

# Birden fazla client ayni anda calisirken gercek imleci ayni anda iki bot
# oynatmasin diye tek kilit.
IMLEC_KILIDI = threading.Lock()

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

SCAN = {
    "e": 0x12, "q": 0x10, "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20,
    "f": 0x21, "r": 0x13, "space": 0x39, "esc": 0x01,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    "up": 0xC8, "down": 0xD0, "left": 0xCB, "right": 0xCD,
    "tab": 0x0F, "enter": 0x1C, "shift": 0x2A, "ctrl": 0x1D, "alt": 0x38,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
    "m": 0x32, "n": 0x31, "i": 0x17, "t": 0x14, "y": 0x15, "u": 0x16,
    "o": 0x18, "p": 0x19, "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F, "f6": 0x40,
    "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44
}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


def _gonder(inp):
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _mutlak_tasi(x, y):
    ew = user32.GetSystemMetrics(0)
    eh = user32.GetSystemMetrics(1)
    mx = int(x * 65535 / max(1, ew - 1))
    my = int(y * 65535 / max(1, eh - 1))
    inp = _INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(
        mx, my, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None)))
    _gonder(inp)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def fare_konumu():
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = P()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def _bezier(p0, p1, p2, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def insansi_tasi(hedef_x, hedef_y, sure=None):
    """Egrisel yol, degisken hiz."""
    bx, by = fare_konumu()
    mesafe = math.hypot(hedef_x - bx, hedef_y - by)
    if sure is None:
        sure = min(0.55, max(0.10, mesafe / 1800.0 + random.uniform(0.04, 0.12)))
    sapma = max(12, mesafe * random.uniform(0.06, 0.16))
    orta = ((bx + hedef_x) / 2 + random.uniform(-sapma, sapma),
            (by + hedef_y) / 2 + random.uniform(-sapma, sapma))
    adim = max(8, int(sure * 110))
    basla = time.time()
    for i in range(1, adim + 1):
        t = i / float(adim)
        t = t * t * (3 - 2 * t)           # yavasla-hizlan-yavasla
        x, y = _bezier((bx, by), orta, (hedef_x, hedef_y), t)
        _mutlak_tasi(int(round(x)), int(round(y)))
        hedef_zaman = basla + sure * (i / float(adim))
        uyku = hedef_zaman - time.time()
        if uyku > 0:
            time.sleep(uyku)
    _mutlak_tasi(int(hedef_x), int(hedef_y))


def sol_tikla(basili=None):
    if basili is None:
        basili = random.uniform(0.055, 0.11)
    _gonder(_INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None))))
    time.sleep(basili)
    _gonder(_INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None))))


def sag_tikla(x, y, insansi=True):
    """ON PLAN: verilen noktaya SAG tikla."""
    if insansi:
        insansi_tasi(x, y)
    else:
        _mutlak_tasi(x, y)
    time.sleep(random.uniform(0.03, 0.08))
    inp = _INPUT()
    inp.type = 0
    inp.u.mi = _MOUSEINPUT(0, 0, 0, MOUSEEVENTF_RIGHTDOWN, 0, None)
    _gonder(inp)
    time.sleep(random.uniform(0.04, 0.09))
    inp2 = _INPUT()
    inp2.type = 0
    inp2.u.mi = _MOUSEINPUT(0, 0, 0, MOUSEEVENTF_RIGHTUP, 0, None)
    _gonder(inp2)
    return True


def tikla(x, y, insansi=True):
    if insansi:
        insansi_tasi(x, y)
        time.sleep(random.uniform(0.03, 0.09))
    else:
        _mutlak_tasi(x, y)
        time.sleep(0.02)
    sol_tikla()


def tekerlek(tik, x=None, y=None, adim_bekleme=(0.05, 0.12)):
    """ON PLAN: gercek fare tekerlegi. tik<0 = asagi, tik>0 = yukari.
    x,y verilirse once oraya insansi sekilde gidilir."""
    if x is not None and y is not None:
        insansi_tasi(int(x), int(y))
        time.sleep(random.uniform(0.05, 0.12))
    yon = 1 if tik > 0 else -1
    for _ in range(abs(int(tik))):
        inp = _INPUT()
        inp.type = 0
        inp.u.mi = _MOUSEINPUT(0, 0, ctypes.c_ulong((yon * WHEEL_DELTA) & 0xFFFFFFFF),
                               MOUSEEVENTF_WHEEL, 0, None)
        _gonder(inp)
        time.sleep(random.uniform(*adim_bekleme))
    return True


def tus_bas(tus, sure=0.05):
    """Tusa bas-birak (on plan, SendInput)."""
    kod = SCAN.get(tus.lower())
    if kod is None:
        return False
    _gonder(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(0, kod, KEYEVENTF_SCANCODE, 0, None))))
    time.sleep(sure)
    _gonder(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(
        0, kod, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, None))))
    return True


def _tus_indir(kod):
    _gonder(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(0, kod, KEYEVENTF_SCANCODE, 0, None))))


def _tus_kaldir(kod):
    _gonder(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(
        0, kod, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, None))))


def tus_kombin(tuslar, sure=0.05):
    """ON PLAN: birden fazla tusu AYNI ANDA basili tut, sonra ters sirada birak.
    Orn. tus_kombin(["space", "a"], 2.0) -> space+A 2 sn basili."""
    kodlar = [SCAN.get(t.lower()) for t in tuslar]
    kodlar = [k for k in kodlar if k is not None]
    if not kodlar:
        return False
    for k in kodlar:
        _tus_indir(k)
        time.sleep(0.02)
    time.sleep(sure)
    for k in reversed(kodlar):
        _tus_kaldir(k)
        time.sleep(0.02)
    return True


# ---------------- pencere ----------------

def tum_pencereler():
    """Gorunur, makul boyuttaki tum pencereler: (hwnd, pid, baslik, rect)."""
    if win32gui is None:
        return []
    liste = []

    def geri(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        baslik = win32gui.GetWindowText(hwnd)
        if not baslik.strip():
            return
        sol, ust, sag, alt = win32gui.GetWindowRect(hwnd)
        if sag - sol < 300 or alt - ust < 200:
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        liste.append((hwnd, pid, baslik, (sol, ust, sag, alt)))

    win32gui.EnumWindows(geri, None)
    return liste


def pid_pencereleri(pid):
    """Verilen PID'e ait gorunur pencereler."""
    return [k for k in tum_pencereler() if k[1] == int(pid)]


def surec_adi(pid):
    try:
        import subprocess
        cikti = subprocess.check_output(
            ["tasklist", "/FI", "PID eq %d" % int(pid), "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL, text=True, encoding="cp857", errors="ignore",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        parcalar = cikti.strip().strip('"').split('","')
        return parcalar[0] if parcalar and parcalar[0] else "?"
    except Exception:
        return "?"


def pencere_bul(baslik_icerir=None, pid=None):
    """Oyun penceresinin tutamacini bul."""
    if win32gui is None:
        return []
    bulunan = []

    def geri(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        baslik = win32gui.GetWindowText(hwnd)
        if pid is not None:
            _, p = win32process.GetWindowThreadProcessId(hwnd)
            if p != pid:
                return
        elif baslik_icerir and baslik_icerir.lower() not in baslik.lower():
            return
        elif not baslik_icerir:
            return
        sol, ust, sag, alt = win32gui.GetWindowRect(hwnd)
        if sag - sol < 200 or alt - ust < 200:
            return
        bulunan.append((hwnd, baslik, (sol, ust, sag, alt)))

    win32gui.EnumWindows(geri, None)
    return bulunan


def istemci_alani(hwnd):
    if win32gui is None:
        return (0, 0, 0, 0)
    sol, ust = win32gui.ClientToScreen(hwnd, (0, 0))
    _, _, w, h = win32gui.GetClientRect(hwnd)
    return (sol, ust, sol + w, ust + h)


def pencere_var_mi(hwnd):
    """Pencere hala acik mi? (client kapandiysa/coktuyse False)"""
    if win32gui is None:
        return True
    try:
        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False


def one_getir(hwnd):
    """Pencereyi one getir. Windows bazen baska programin odagi 'kilitlemesi'
    yuzunden reddeder; o zaman ALT tusu hilesiyle bir kez daha denenir."""
    if win32gui is None:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.15)
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        # odak kilidi: kisa bir ALT bas-birak Windows'a 'kullanici girdisi' gosterir
        VK_MENU = 0x12
        user32.keybd_event(VK_MENU, 0, 0, 0)
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        finally:
            user32.keybd_event(VK_MENU, 0, 0x0002, 0)
        time.sleep(0.15)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def odakta_mi(hwnd):
    if win32gui is None:
        return False
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


# =====================================================================
#  ARKA PLAN MODU (deneysel)
#  Oyun penceresi onde olmasa da pencereye mesaj gonderir.
#  Gercek fare/klavye kullanilmaz -> bu sirada bilgisayari kullanabilirsiniz.
#  Bazi Metin2 istemcileri bu mesajlari yok sayar: GUI'deki "Arka plan testi"
#  ile deneyin.
# =====================================================================

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_MOUSEWHEEL = 0x020A
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MK_RBUTTON = 0x0002
MK_LBUTTON = 0x0001


def yonetici_mi():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _post(hwnd, mesaj, wparam, lparam):
    try:
        win32gui.PostMessage(hwnd, mesaj, wparam, lparam)
    except Exception as hata:
        if getattr(hata, "winerror", None) == 5 or (hata.args and hata.args[0] == 5):
            raise RuntimeError(
                "Erisim engellendi: oyun YONETICI olarak calisiyor, bot degil. "
                "Baslat.bat ile acin (yonetici izni ister) ya da komut istemini "
                "'Yonetici olarak calistir' ile acip python gui.py yazin.")
        raise


def _lparam(x, y):
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def arka_tikla(hwnd, istemci_x, istemci_y, imleci_tasi=True):
    """Pencereye istemci koordinatinda sol tik mesaji gonder.

    Metin2 istemcileri tiklanan nesneyi mesajdaki koordinattan degil GERCEK
    imlecin yerinden bulur. imleci_tasi=True: imlec bir anlik hedefe goturulur,
    mesaj gonderilir, imlec eski yerine geri konur (~0.1 sn). Bu sirada fare
    girisi kisa sure kilitlenir ki kullanicinin hareketi tiklamayi kaydirmasin."""
    if win32gui is None:
        return False
    lp = _lparam(istemci_x, istemci_y)
    if not imleci_tasi:
        _post(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(random.uniform(0.03, 0.07))
        _post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(random.uniform(0.05, 0.10))
        _post(hwnd, WM_LBUTTONUP, 0, lp)
        return True

    with IMLEC_KILIDI:
        return _imlecli_tikla(hwnd, istemci_x, istemci_y, lp)


def _imlecli_tikla(hwnd, istemci_x, istemci_y, lp):
    sx, sy = win32gui.ClientToScreen(hwnd, (int(istemci_x), int(istemci_y)))
    eski = fare_konumu()
    kilitli = False
    try:
        kilitli = bool(user32.BlockInput(True))      # yonetici gerekir
    except Exception:
        pass
    try:
        user32.SetCursorPos(int(sx), int(sy))
        time.sleep(0.02)
        _post(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.03)
        _post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(0.05)
        _post(hwnd, WM_LBUTTONUP, 0, lp)
        time.sleep(0.04)       # oyun mesaji isleyene kadar imlec yerinde kalsin
    finally:
        user32.SetCursorPos(int(eski[0]), int(eski[1]))
        if kilitli:
            user32.BlockInput(False)
    return True


def _araliktan(deger, varsayilan):
    try:
        a, b = float(deger[0]), float(deger[1])
        return random.uniform(min(a, b), max(a, b))
    except Exception:
        return random.uniform(*varsayilan)


def yavas_tikla(hwnd, istemci_x, istemci_y, tur="sol", arka_plan=True, ayar=None):
    """INSANSI tiklama (ek gorsel tiklama icin).

    Hizli 'imleci isinla + tikla' bazi oyun butonlarinda bosa gidiyor: oyun,
    imlec butonun ustune GELDIGINI (hover) gormeden tiklamayi aliyor.
    Burada:
      1) imlec egri bir yolla, degisken hizla hedefe goturulur,
      2) hedefin ustunde kisa bir sure beklenir, 1-2 piksel kipirdatilir
         (oyun 'fare ustunde' durumuna gecsin),
      3) tus insan gibi basili tutulup birakilir,
      4) arka plan modunda imlec yine insansi sekilde eski yerine doner.
    tur: 'sol' | 'sag' | 'cift'"""
    ayar = ayar or {}
    if win32gui is None:
        return False
    sx, sy = win32gui.ClientToScreen(hwnd, (int(istemci_x), int(istemci_y)))
    lp = _lparam(istemci_x, istemci_y)
    gercek = bool(ayar.get("gercek_tiklama", False)) or not arka_plan

    with IMLEC_KILIDI:
        eski = fare_konumu()
        kilitli = False
        if arka_plan:
            try:
                kilitli = bool(user32.BlockInput(True))     # kullanici fareyi kaydirmasin
            except Exception:
                pass
        try:
            if arka_plan and gercek:
                one_getir(hwnd)
            insansi_tasi(sx, sy)

            # hover: ustunde bekle, hafif kipirdat
            hover_bitis = time.time() + _araliktan(ayar.get("hover_bekleme"), (0.18, 0.35))
            while time.time() < hover_bitis:
                jx, jy = sx + random.choice((-1, 0, 1)), sy + random.choice((-1, 0, 1))
                _mutlak_tasi(jx, jy)
                if arka_plan:
                    _post(hwnd, WM_MOUSEMOVE, 0, _lparam(istemci_x + jx - sx, istemci_y + jy - sy))
                time.sleep(random.uniform(0.04, 0.08))
            _mutlak_tasi(sx, sy)
            if arka_plan:
                _post(hwnd, WM_MOUSEMOVE, 0, lp)
            time.sleep(random.uniform(0.03, 0.07))

            kac = 2 if tur == "cift" else 1
            for n in range(kac):
                basili = _araliktan(ayar.get("basili_tutma"), (0.07, 0.14))
                if gercek:
                    asagi, yukari = ((MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if tur == "sag"
                                     else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
                    _gonder(_INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, asagi, 0, None))))
                    time.sleep(basili)
                    _gonder(_INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, yukari, 0, None))))
                else:
                    if tur == "sag":
                        _post(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lp)
                        time.sleep(basili)
                        _post(hwnd, WM_RBUTTONUP, 0, lp)
                    else:
                        _post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
                        time.sleep(basili)
                        _post(hwnd, WM_LBUTTONUP, 0, lp)
                if n + 1 < kac:
                    time.sleep(random.uniform(0.07, 0.12))

            # oyun tiklamayi islerken imlec hedefte kalsin
            time.sleep(_araliktan(ayar.get("tik_sonrasi_bekleme"), (0.12, 0.25)))
        finally:
            if arka_plan and ayar.get("imleci_geri_getir", True) and eski:
                try:
                    insansi_tasi(eski[0], eski[1])
                except Exception:
                    _mutlak_tasi(*eski)
            if kilitli:
                user32.BlockInput(False)
    return True


def arka_tikla_sessiz(hwnd, istemci_x, istemci_y, sag=False):
    """ARKA PLAN, fare oynamadan: sadece tik mesaji (fare-hareket mesaji yok;
    oyun o mesajla gercek imleci kendine cekiyor). Oyun yine de imleci cekerse
    imlec hemen kullanicinin biraktigi yere geri konur."""
    if win32gui is None:
        return False
    lp = _lparam(int(istemci_x), int(istemci_y))
    asagi, yukari, bayrak = ((WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON) if sag
                             else (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON))
    try:
        hx, hy = win32gui.ClientToScreen(hwnd, (int(istemci_x), int(istemci_y)))
    except Exception:
        hx = hy = None
    eski = fare_konumu()
    _post(hwnd, asagi, bayrak, lp)
    time.sleep(random.uniform(0.04, 0.08))
    _post(hwnd, yukari, 0, lp)
    if hx is None:
        return True
    bitis = time.time() + 0.35
    while time.time() < bitis:
        # sadece oyun imleci TIK NOKTASINA cektiyse geri al (kullanici oynatirsa karisma)
        x, y = fare_konumu()
        if abs(x - hx) <= 3 and abs(y - hy) <= 3 and (x, y) != eski:
            user32.SetCursorPos(int(eski[0]), int(eski[1]))
        time.sleep(0.01)
    return True


def arka_sag_tikla(hwnd, istemci_x, istemci_y, imleci_tasi=True):
    """ARKA PLAN: pencereye sag tiklama mesaji gonderir. Metin2 tiklamayi
    gercek imlec yerinden alabildigi icin imlec bir anlik hedefe tasinir."""
    if win32gui is None:
        return False
    lp = _lparam(int(istemci_x), int(istemci_y))
    if not imleci_tasi:
        _post(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.02)
        _post(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lp)
        time.sleep(random.uniform(0.04, 0.09))
        _post(hwnd, WM_RBUTTONUP, 0, lp)
        return True
    sx, sy = win32gui.ClientToScreen(hwnd, (int(istemci_x), int(istemci_y)))
    with IMLEC_KILIDI:
        eski = fare_konumu()
        _mutlak_tasi(sx, sy)
        time.sleep(0.02)
        _post(hwnd, WM_MOUSEMOVE, 0, lp)
        _post(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lp)
        time.sleep(random.uniform(0.04, 0.09))
        _post(hwnd, WM_RBUTTONUP, 0, lp)
        time.sleep(0.02)
        if eski:
            _mutlak_tasi(*eski)
    return True


def arka_tekerlek(hwnd, istemci_x, istemci_y, tik, imleci_tasi=True,
                  adim_bekleme=(0.06, 0.14)):
    """ARKA PLAN: pencereye WM_MOUSEWHEEL gonderir. WM_MOUSEWHEEL EKRAN
    koordinati ister. imleci_tasi=True ise (tiklamada oldugu gibi) imlec bir
    anlik hedefe tasinir; bazi oyunlar tekerlegi gercek imlec yerinden alir."""
    if win32gui is None:
        return False
    sx, sy = win32gui.ClientToScreen(hwnd, (int(istemci_x), int(istemci_y)))
    lp = (sy << 16) | (sx & 0xFFFF)
    yon = 1 if tik > 0 else -1
    for _ in range(abs(int(tik))):
        wp = ((yon * WHEEL_DELTA) << 16) & 0xFFFFFFFF
        if imleci_tasi:
            with IMLEC_KILIDI:
                eski = fare_konumu()
                _mutlak_tasi(sx, sy)
                time.sleep(0.01)
                _post(hwnd, WM_MOUSEWHEEL, wp, lp)
                # gercek tekerlek de gonder: imlec hedefin uzerindeyken
                inp = _INPUT()
                inp.type = 0
                inp.u.mi = _MOUSEINPUT(0, 0, ctypes.c_ulong((yon * WHEEL_DELTA) & 0xFFFFFFFF),
                                       MOUSEEVENTF_WHEEL, 0, None)
                _gonder(inp)
                time.sleep(0.01)
                if eski:
                    _mutlak_tasi(*eski)
        else:
            _post(hwnd, WM_MOUSEWHEEL, wp, lp)
        time.sleep(random.uniform(*adim_bekleme))
    return True


WM_CHAR = 0x0102
TUS_YONTEMLERI = ("mesaj", "mesaj_char", "one_getir", "guclu")
WM_ACTIVATE, WM_SETFOCUS, WM_ACTIVATEAPP, WM_NCACTIVATE = 0x0006, 0x0007, 0x001C, 0x0086


def aktif_kandir(hwnd):
    """Arkadaki oyuna 'su an aktifsin / klavye sende' mesajlari (testte 2. yontem)."""
    try:
        tid = user32.GetWindowThreadProcessId(hwnd, None)
    except Exception:
        tid = 0
    _post(hwnd, WM_ACTIVATEAPP, 1, tid)
    _post(hwnd, WM_NCACTIVATE, 1, 0)
    _post(hwnd, WM_ACTIVATE, 1, 0)
    _post(hwnd, WM_SETFOCUS, 0, 0)


def _guclu_bas(hwnd, kod, vk):
    """Testte calisan yontemler: 'aktifsin' mesajlari + 3 kez kisa bas-birak
    (basili tutma yok)."""
    aktif_kandir(hwnd)
    time.sleep(0.05)
    for n in range(3):
        if n:
            time.sleep(0.09)
        _post(hwnd, WM_KEYDOWN, vk, 1 | (kod << 16))
        time.sleep(0.06)
        _post(hwnd, WM_KEYUP, vk, 1 | (kod << 16) | 0xC0000000)


def arka_tus_bas(hwnd, tus, sure=0.05, yontem="mesaj"):
    """ARKA PLAN tus basma. yontem:
      'mesaj'      : WM_KEYDOWN/WM_KEYUP (varsayilan; TAB/SPACE boyle calisiyor)
      'mesaj_char' : + WM_CHAR (bazi client'lar rakam/harfi karakter mesajindan alir)
      'one_getir'  : pencere bir anlik one getirilir, GERCEK tus basilir, onceki
                     pencere geri getirilir (en garantisi, ekran bir an titrer)"""
    if win32gui is None:
        return False
    kod = SCAN.get(tus.lower())
    if kod is None:
        return False
    if yontem == "one_getir":
        with IMLEC_KILIDI:
            eski = None
            try:
                eski = win32gui.GetForegroundWindow()
            except Exception:
                pass
            one_getir(hwnd)
            time.sleep(0.05)
            tus_bas(tus, max(sure, 0.05))
            time.sleep(0.05)
            if eski and eski != hwnd:
                try:
                    win32gui.SetForegroundWindow(eski)
                except Exception:
                    pass
        return True
    vk = user32.MapVirtualKeyW(kod, 1)       # MAPVK_VSC_TO_VK
    if yontem == "guclu":
        _guclu_bas(hwnd, kod, vk)
        return True
    _post(hwnd, WM_KEYDOWN, vk, 1 | (kod << 16))
    if yontem == "mesaj_char" and len(tus) == 1:
        _post(hwnd, WM_CHAR, ord(tus.lower()), 1 | (kod << 16))
    time.sleep(sure)
    _post(hwnd, WM_KEYUP, vk, 1 | (kod << 16) | 0xC0000000)
    return True


# ---------- ARKA PLAN pelerin yontemleri (SpaceTesti'ndeki numaralarla ayni) ----------
PELERIN_YONTEMLERI = {
    "1": "1) Mesaj - basili tut",
    "2": "2) 'Aktifsin' + basili tut",
    "3": "3) Bas-birak seri",
    "4": "4) SendMessage - basili tut",
    "5": "5) Mesaj + karakter",
    "6": "6) Klavye durumu + 'aktifsin'",
    "7": "7) Surekli one al-birak (gercek tus, fareye dokunmaz)",
    "8": "8) Tek kisa basis",
    "9": "9) Gercek klavye gibi (F1'den sonra SPACE tekrari yok)",
    "10": "10) Odak sifirla + tek basis",
    "11": "11) Gercek tus, oyunu ONE ALMADAN",
}


_PM = None


def _post_test(hwnd, mesaj, w, l):
    """SpaceTesti'nin kullandigi gonderimin AYNISI (ctypes PostMessageW, tipli).
    Dondurur: True/False (Windows kabul etti mi)."""
    global _PM
    if _PM is None:
        import ctypes.wintypes as wt
        f = ctypes.WinDLL("user32", use_last_error=True).PostMessageW
        f.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        f.restype = wt.BOOL
        _PM = f
    ok = bool(_PM(hwnd, mesaj, w, l))
    PELERIN_ISTAT["ok" if ok else "hata"] += 1
    if not ok:
        PELERIN_ISTAT["kod"] = ctypes.get_last_error()
    return ok


PELERIN_ISTAT = {"ok": 0, "hata": 0, "kod": 0}


def _lp(kod, yukari=False, tekrar=False):
    d = 1 | (kod << 16)
    if tekrar:
        d |= 0x40000000
    if yukari:
        d |= 0xC0000000
    return d


def _send(hwnd, mesaj, w, l):
    try:
        sonuc = ctypes.c_size_t()
        user32.SendMessageTimeoutW(hwnd, mesaj, w, l, 0x0002, 200, ctypes.byref(sonuc))
    except Exception:
        _post(hwnd, mesaj, w, l)


def arka_pelerin(hwnd, tus, yontem="1", sure=1.0, dur_mu=None):
    """Pelerin tusunu secilen yontemle gonder (sure: basili/seri suresi, sn).
    Ayri thread'de cagrilir; SPACE bu sirada basili kalir."""
    if win32gui is None:
        return False
    kod = SCAN.get(tus.lower())
    if kod is None:
        return False
    vk = user32.MapVirtualKeyW(kod, 1)
    t = tus.lower()
    if t.startswith("f") and t[1:].isdigit():
        vk = 0x70 + int(t[1:]) - 1            # testteki gibi: F1 = 0x70
    kod = user32.MapVirtualKeyW(vk, 0) or kod  # testteki gibi: scan = MapVirtualKey(vk, 0)
    dur = dur_mu or (lambda: False)
    bitis = time.time() + max(0.05, sure)
    yontem = str(yontem)

    if yontem == "7":
        # Bir anlik one getir -> GERCEK F1 kisa bas -> eski pencereye don.
        # Fareye dokunulmaz. Birden fazla client ayni anda one gelmesin diye
        # islemler arasi ortak kilit (Windows mutex) kullanilir.
        mutex = None
        try:
            k32 = ctypes.windll.kernel32
            mutex = k32.CreateMutexW(None, False, "MetinBotu2_OneGetir")
            if mutex:
                k32.WaitForSingleObject(mutex, 3000)
        except Exception:
            mutex = None
        try:
            with IMLEC_KILIDI:
                eski = None
                try:
                    eski = win32gui.GetForegroundWindow()
                except Exception:
                    pass
                if not one_getir(hwnd):
                    return False
                time.sleep(0.03)
                _tus_indir(kod)
                time.sleep(random.uniform(0.05, 0.09))
                _tus_kaldir(kod)
                time.sleep(0.04)
                if eski and eski != hwnd:
                    one_getir(eski)
            return True
        finally:
            if mutex:
                try:
                    k32.ReleaseMutex(mutex)
                    k32.CloseHandle(mutex)
                except Exception:
                    pass

    if yontem == "11":
        # Oyun kisayollari 'tus su an basili mi' diye okuyorsa (mesaj degil)
        # gercek tus arkadaki oyuna da gorunur. Pencere one alinmaz.
        with IMLEC_KILIDI:
            _gonder(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(vk, kod, 0, 0, None))))
            time.sleep(random.uniform(0.06, 0.1))
            _gonder(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(vk, kod, 0x0002, 0, None))))
        return True

    if yontem == "10":
        # Oyun F1'i 'hala basili' sanip yeni basisi yok sayiyor olabilir:
        # odak kaybet/kazan mesajlari oyunun kendi tus tablosunu sifirlar
        # (alt-tab yapip geri donmek gibi), sonra tek kisa basis.
        _post_test(hwnd, WM_KEYUP, vk, _lp(kod, yukari=True))
        _post_test(hwnd, 0x0008, 0, 0)          # WM_KILLFOCUS
        _post_test(hwnd, WM_ACTIVATE, 0, 0)
        time.sleep(0.03)
        aktif_kandir(hwnd)
        time.sleep(0.04)
        _post_test(hwnd, WM_KEYDOWN, vk, _lp(kod))
        time.sleep(random.uniform(0.04, 0.08))
        _post_test(hwnd, WM_KEYUP, vk, _lp(kod, yukari=True))
        return True

    if yontem in ("8", "9"):
        _post_test(hwnd, WM_KEYDOWN, vk, _lp(kod))
        time.sleep(random.uniform(0.04, 0.08))
        _post_test(hwnd, WM_KEYUP, vk, _lp(kod, yukari=True))
        return True

    if yontem == "3":
        while time.time() < bitis and not dur():
            _post_test(hwnd, WM_KEYDOWN, vk, _lp(kod))
            time.sleep(0.06)
            _post_test(hwnd, WM_KEYUP, vk, _lp(kod, yukari=True))
            time.sleep(0.09)
        return True

    gonder = _send if yontem == "4" else _post_test
    bagli = False
    durum = None
    benim = hedef = 0
    if yontem in ("2", "6"):
        aktif_kandir(hwnd)
        time.sleep(0.05)
    if yontem == "6":
        try:
            benim = ctypes.windll.kernel32.GetCurrentThreadId()
            hedef = user32.GetWindowThreadProcessId(hwnd, None)
            bagli = bool(user32.AttachThreadInput(benim, hedef, True))
            durum = (ctypes.c_ubyte * 256)()
            if bagli:
                user32.GetKeyboardState(durum)
                durum[vk] = 0x80
                user32.SetKeyboardState(durum)
        except Exception:
            bagli = False
    try:
        gonder(hwnd, WM_KEYDOWN, vk, _lp(kod))
        son_kandir = time.time()
        while time.time() < bitis and not dur():
            time.sleep(0.05)
            if yontem == "2" and time.time() - son_kandir > 0.5:
                aktif_kandir(hwnd)
                son_kandir = time.time()
            if yontem == "5":
                ch = user32.MapVirtualKeyW(vk, 2) & 0xFFFF
                if ch:
                    _post_test(hwnd, WM_CHAR, ch, _lp(kod, tekrar=True))
            if yontem == "6" and bagli:
                durum[vk] = 0x80
                user32.SetKeyboardState(durum)
            gonder(hwnd, WM_KEYDOWN, vk, _lp(kod, tekrar=True))
    finally:
        gonder(hwnd, WM_KEYUP, vk, _lp(kod, yukari=True))
        if bagli:
            try:
                durum[vk] = 0
                user32.SetKeyboardState(durum)
                user32.AttachThreadInput(benim, hedef, False)
            except Exception:
                pass
    return True


def arka_tus_kombin(hwnd, tuslar, sure=0.05, guclu=False):
    """ARKA PLAN: birden fazla tusu ayni anda basili tut (WM_KEYDOWN/KEYUP)."""
    if win32gui is None:
        return False
    if guclu:
        aktif_kandir(hwnd)
        time.sleep(0.05)
        sure = max(sure, 0.3)
    kodlar = [SCAN.get(t.lower()) for t in tuslar]
    kodlar = [k for k in kodlar if k is not None]
    if not kodlar:
        return False
    vkler = [user32.MapVirtualKeyW(k, 1) for k in kodlar]
    for k, vk in zip(kodlar, vkler):
        _post(hwnd, WM_KEYDOWN, vk, 1 | (k << 16))
        time.sleep(0.02)
    time.sleep(sure)
    for k, vk in zip(reversed(kodlar), reversed(vkler)):
        _post(hwnd, WM_KEYUP, vk, 1 | (k << 16) | 0xC0000000)
        time.sleep(0.02)
    return True


class Girdi:
    """Botun kullandigi tek girdi arayuzu. mod: 'on_plan' | 'arka_plan'.
    Koordinatlar her zaman pencerenin ISTEMCI alanina gore verilir."""

    def __init__(self, hwnd, mod="on_plan", insansi=True, arka_imlec=True, tus_yontemi="mesaj"):
        self.hwnd = hwnd
        self.mod = mod
        self.insansi = insansi
        self.arka_imlec = arka_imlec
        self.tus_yontemi = tus_yontemi if tus_yontemi in TUS_YONTEMLERI else "mesaj"

    @property
    def arka_plan(self):
        return self.mod == "arka_plan"

    def tikla(self, istemci_x, istemci_y):
        if self.arka_plan:
            return arka_tikla(self.hwnd, istemci_x, istemci_y, self.arka_imlec)
        sx, sy = win32gui.ClientToScreen(self.hwnd, (int(istemci_x), int(istemci_y)))
        with IMLEC_KILIDI:
            tikla(sx, sy, insansi=self.insansi)
        return True

    def tus_bas(self, tus, sure=0.05):
        if self.arka_plan:
            return arka_tus_bas(self.hwnd, tus, sure, self.tus_yontemi)
        return tus_bas(tus, sure)

    def sag_tikla(self, istemci_x, istemci_y):
        if self.arka_plan:
            return arka_sag_tikla(self.hwnd, istemci_x, istemci_y, self.arka_imlec)
        sx, sy = win32gui.ClientToScreen(self.hwnd, (int(istemci_x), int(istemci_y)))
        with IMLEC_KILIDI:
            sag_tikla(sx, sy, insansi=self.insansi)
        return True

    def tus_kombin(self, tuslar, sure=0.05):
        """Birden fazla tusu ayni anda basili tut. Orn. ["space", "a"]"""
        if self.arka_plan:
            return arka_tus_kombin(self.hwnd, tuslar, sure, guclu=self.tus_yontemi == "guclu")
        return tus_kombin(tuslar, sure)

    def tus_indir(self, tus, tekrar=False):
        """Tusu basili konuma getir (birakilmaz). Basili tutmak icin ~0.1 sn'de bir
        tekrar=True ile yeniden cagrilir (klavyenin kendi tekrar ozelligi gibi)."""
        kod = SCAN.get(tus.lower())
        if kod is None:
            return False
        if self.arka_plan:
            vk = user32.MapVirtualKeyW(kod, 1)
            _post(self.hwnd, WM_KEYDOWN, vk, 1 | (kod << 16) | (0x40000000 if tekrar else 0))
        else:
            _tus_indir(kod)
        return True

    def tus_kaldir(self, tus):
        kod = SCAN.get(tus.lower())
        if kod is None:
            return False
        if self.arka_plan:
            vk = user32.MapVirtualKeyW(kod, 1)
            _post(self.hwnd, WM_KEYUP, vk, 1 | (kod << 16) | 0xC0000000)
        else:
            _tus_kaldir(kod)
        return True

    def guclu_tikla(self, istemci_x, istemci_y, basili=0.2):
        """Yedek yontem: imlec hedefe gider, GERCEK tik uzun basili tutulur ve ayni
        anda pencereye tik MESAJI da gonderilir (biri tutmazsa digeri tutsun)."""
        if win32gui is None:
            return False
        sx, sy = win32gui.ClientToScreen(self.hwnd, (int(istemci_x), int(istemci_y)))
        lp = _lparam(istemci_x, istemci_y)
        with IMLEC_KILIDI:
            insansi_tasi(sx, sy)
            for dx in (2, -2, 0):                      # hover'i tazele
                _mutlak_tasi(sx + dx, sy)
                time.sleep(0.04)
            _post(self.hwnd, WM_MOUSEMOVE, 0, lp)
            time.sleep(0.08)
            _gonder(_INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None))))
            time.sleep(basili)
            _gonder(_INPUT(0, _INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None))))
            time.sleep(0.15)
            _post(self.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
            time.sleep(0.08)
            _post(self.hwnd, WM_LBUTTONUP, 0, lp)
        return True

    def yavas_tikla(self, istemci_x, istemci_y, tur="sol", ayar=None):
        """Insansi hareket + hover + yavas tik (ek gorsel tiklama)."""
        return yavas_tikla(self.hwnd, istemci_x, istemci_y, tur, self.arka_plan, ayar)

    def tekerlek(self, istemci_x, istemci_y, tik):
        """tik<0 = asagi kaydir, tik>0 = yukari."""
        if self.arka_plan:
            return arka_tekerlek(self.hwnd, istemci_x, istemci_y, tik, self.arka_imlec)
        sx, sy = win32gui.ClientToScreen(self.hwnd, (int(istemci_x), int(istemci_y)))
        with IMLEC_KILIDI:
            tekerlek(tik, sx, sy)
        return True


def pencereyi_goster(hwnd):
    """Hangi client oldugunu anlamak icin: one getir ve gorev cubugunda yakip sondur."""
    one_getir(hwnd)

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p),
                    ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                    ("dwTimeout", ctypes.c_uint)]
    try:
        f = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x3 | 0xC, 4, 0)
        user32.FlashWindowEx(ctypes.byref(f))
    except Exception:
        pass
