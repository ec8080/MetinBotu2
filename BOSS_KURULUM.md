# Boss Cagirma Modulu

## Dosyalar
- `boss.py` — cagirma mantigi (panel ac, logo bul, isim oku, kaydir, tikla, space, bekle)
- `boss_kalibrasyon.py` — panel/logo/isim ayarlarini oyundan ogrenme araci
- `boss_logo.png` — cagirma butonunun sablonu (senin attigin gorselden olusturuldu)
- `girdi.py` — fare tekerlegi eklendi (`tekerlek`, `arka_tekerlek`, `Girdi.tekerlek`)
- `config.json` / `varsayilan.json` — yeni `boss` bolumu

## 1) Boss listesini gir
`config.json` > `boss` > `liste`, panelde YAZAN adlarla, sirayla:

```json
"aktif": true,
"periyot_dakika": 120,
"liste": ["Seytan Katakombu", "Mavi Ejderha Odasi"]
```
Turkce karakter/buyuk-kucuk farketmez, bulanik eslesme var (esik: `isim.benzerlik_esigi`).

## 2) Kalibrasyon (ilk kurulumda bir kez)
Oyunda TAB ile Isinlanma Sihirbazi'ni ac, sonra:

```
python boss_kalibrasyon.py
```
Tuslar: **p** panel bolgesi · **l** cagirma logosu · **i** isim hucresi · **t** test · **k** kaydirma testi · **s** kaydet · **q** cikis

`t` ile satirlarin dogru okundugunu gor, sonra `s` ile kaydet.
Hazir `boss_logo.png` cogu durumda dogrudan calisir; once `t` ile dene, tutuyorsa kalibrasyona gerek yok.

## 3) Dene
```
python boss.py
```
Pencereyi (PID) sec, 3 sn icinde oyuna gec. Akis:
TAB -> her boss icin: (gerekirse tekerlekle asagi kaydir) -> logoya tikla -> 0.6 sn sonra
SPACE 2 sn basili -> 15 sn bekle -> sonraki boss -> hepsi bitince TAB ile kapat.

Cagirma basarili olunca oyun paneli en uste atiyor; bot her boss icin kaydirmayi
bastan yapar (`kaydirma.yukari_sifirla`).

## Ayarlar (config.json > boss)
| Ayar | Anlami |
|---|---|
| `periyot_dakika` | Kac dakikada bir boss turu (entegrasyon icin, varsayilan 120) |
| `panel_acilma_bekleme` | TAB'dan sonra beklenen sure |
| `sekme` | Panel acilinca bir sekmeye tiklanacaksa `{"x":0.5,"y":0.1}` |
| `logo.esik` | Sablon eslesme esigi. Dusuk = yandaki benzer butonlar da yakalanir (0.93 onerilir) |
| `logo.sutun_x` | Sadece bu x sutunundaki butonlar sayilir (kalibrasyonda otomatik) |
| `isim.sol_ofset` / `sag_ofset` | Isim hucresi logonun ne kadar solunda |
| `kaydirma.tik` | Bir adimda kac tekerlek tiki |
| `kaydirma.max_adim` | En fazla kac adim asagi inilir |
| `zamanlayici.space_basili_tutma` | 2.0 sn |
| `zamanlayici.bosslar_arasi_bekleme` | 15.0 sn |

## Notlar
- Panelin ust satirlarindaki (Mini Kader Carki, Ork Zindani...) **koyu** butonlar
  farkli bir gorsel; sadece altin cagirma butonu taninir. O satirlari da
  istersen kalibrasyonda `l` ile o butonu secip ikinci bir sablon cikarabiliriz.
- Arka plan modunda tekerlek hem `WM_MOUSEWHEEL` mesajiyla hem de imlec bir
  anlik panelin uzerine tasinip gercek tekerlek olayiyla gonderilir
  (Metin2 tiklamada oldugu gibi gercek imlec yerini kullanabiliyor).
  Kaydirma calismazsa kalibrasyonda **k** ile test et.
## Metin botuna entegrasyon (TAMAM)
GUI'de yeni **Boss** sekmesi:
- "Boss turu acik" + suresi yazilmayanlar icin varsayilan dakika
- Boss listesi: her satira `Boss adi | dakika`
  ```
  Mavi Ejderha Odasi | 30
  Altin Ejderha Zindani | 60
  Kabus Zindani | 120
  Meleyin Ini            <- sure yazilmazsa varsayilan kullanilir
  ```
- **Kaydet** — calisan botlara da aninda uygulanir
- **Simdi boss turu yap** — beklemeden tetikler
- **Panel testi** — oyunda TAB acikken satirlari okur, gunluge yazar
- Alt satirda sonraki boss turuna kalan sure

Her bossun KENDI bekleme suresi vardir. Bir bossun suresi dolunca bot metin
kesmeyi birakir -> TAB -> **5 sn bekler** -> SADECE suresi dolan bosslari
cagirir -> TAB ile kapatir -> metin farmina devam eder. Ayni anda birden fazla
bossun suresi dolduysa hepsi tek turda cagrilir.

Sureler `boss_durum_<PID>.json` dosyasinda tutulur: **oyun acik kaldigi surece**
botu kapatip acsan da bekleme sureleri korunur. Oyunu kapatirsan sifirlanir.
Panelde bulunamayan boss bosuna tur actirmaz: bekleme her basarisizlikta
KATLANIR (5 -> 10 -> 20 -> 40 -> en fazla 60 dk) ve ust uste 2 kez bulunamazsa
artik TEK BASINA tur baslatmaz; baska bir boss icin panel zaten acildiginda
denenir. Ayarlar: `tekrar_deneme_dakika`, `max_tekrar_deneme_dakika`,
`yalniz_deneme_limiti` (0 = kapali). Her client kendi sayacini tutar.

Ayrica: isim eslesmesi KELIME BAZLI. "Mavi/Altin/Kirmizi Ejderha ..." gibi
benzer isimler karismaz; emin olunamayan satira tiklanmaz, gunluge yazilir.
