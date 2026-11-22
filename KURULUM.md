# Metin Taşı Botu

Ekrandaki **isim yazısını okuyarak** metin taşlarını bulur, tıklar, taş kırılınca
sıradakine geçer. Şablon/resim eşleştirme yok — kamera açısı ve ışık değişse de
yazı sabit kaldığı için en sağlam yöntem bu.

## YENİ: Çoklu client, hedef taş adı, paylaşılabilir .exe

### Hedef taş adı
Arayüzün en üstündeki kutuya taşın adını yaz: `Ahmet Metini`. Birden fazla için virgül:
`Ahmet Metini, Korsan Metini`. `Lv.100 (2.Seviye)` kısmı yazılmaz. Boş = tüm metin taşları.
Bot ismin **ayırt edici** kelimesine bakar (Ahmet): "Mehmet Metini"ne tıklamaz.
Can barındaki isim de aynı şekilde kontrol edilir.

### Birden fazla client
Listede tüm "Carina2" pencereleri görünür. Ctrl/Shift ile seç → **Secilileri baslat**.
Her satırda o client'ın durumu, kırılan taşı, canı görünür. Günlükte her satırın başında
`[PID 25156]` yazar. Birden fazla client için **Arka plan** modu gerekir.
"Hangisi? (goster)" seçili client'ı öne getirip görev çubuğunda yakıp söndürür.

### Arkadaşlara paylaşmak (konsolsuz .exe, kurulum gerektirmez)
Kendi bilgisayarında **bir kez** `derle.bat`'a çift tıkla. Yaptıkları:
1. PyInstaller ve gerekli paketleri kurar
2. Botu `dist\MetinBotu\MetinBotu.exe` olarak derler (konsol penceresi yok, yönetici olarak açılır)
3. Bilgisayarındaki Tesseract'ı (eng + tur dil dosyalarıyla) pakete kopyalar
4. Senin ayarlarını (can barı bölgesi, eşikler, zamanlayıcılar) paketin varsayılanı yapar
5. `MetinBotu_paylas.zip` oluşturur → arkadaşlarına bunu gönder

Arkadaşların zip'i çıkarıp `MetinBotu.exe`'yi açar. Python / Tesseract kurmaları gerekmez.
Kullanım için paketteki `OKUBENI.txt`.

## YENİ: Pencereli arayüz (GUI)

`Baslat.bat`'a çift tıkla (ya da `python gui.py`).

* **Oyun penceresi** listeden seçilir (PID sormaz). Oyun pencereleri en üstte.
* **Başlat / Duraklat (F11) / Durdur (F12)**. Bot ayrı iş parçacığında çalışır, arayüz donmaz.
* **Çalışma modu**
  * *Ön plan*: gerçek fare. Oyun penceresi önde olmalı.
  * *Arka plan (deneysel)*: oyuna doğrudan mesaj gönderir, ekranını pencereden okur.
    Oyun başka pencerelerin arkasında kalabilir (simge durumuna **küçültme**).
    Önce **Arka plan testi** düğmesine bas: oyun bunu kabul ediyor mu söyler.
* **E ile kamera çevirme**: varsayılan **kapalı**. Açarsan taş bulunamayınca / takılınca E'ye basar.
* **Oncelik modu**: OCR'ın okuyamadığı etiketleri de (düşük öncelikle) dener; can barı doğrular.
* **Durum** kutusunda *Kırıldı → tıklama* ve *Kırıldı → vuruş* süreleri ölçülür
  (vuruş süresine karakterin taşa yürümesi de dahil).
* **Zamanlayıcılar** sekmesi: tüm süreler; Kaydet çalışan bota da hemen uygulanır.
* Kalibrasyon ve Teşhis araçları arayüzden ayrı konsolda açılır.

### Bu sürümde düzeltilenler
* Can yüzdesi yanlış okunuyordu (`%9  37.597...` → `937`). Artık `can / tam` sayılarından hassas hesaplanıyor.
* Takılınca / zaman aşımında bot aynı taşa geri dönüp sonsuz döngüye girebiliyordu.
* Takılınca yeni taşa tıklandığında eski barı "hedef alındı" sanıyordu.
* Hız: etiketler **paralel** OCR ediliyor, zaten tanınan etiketler tekrar okunmuyor, kesme sırasında
  sıradaki taş önceden bulunuyor, kırılınca bekleme süreleri kısaltıldı.

## Güncelleme (zaten kurulu ise)

Yeni sürümü **eski klasörün üzerine** çıkar, hepsi bu. Ayarların bozulmaz:

* Zip'te `config.json` **yok** — senin dosyan olduğu yerde kalır
* Ayarlar `varsayilan.json`'dan gelir; yeni sürümde eklenen ayarlar senin
  `config.json`'una otomatik eklenir, mevcut değerlerine dokunulmaz

İlk çalıştırmada şunu görürsün:

```
config.json guncellendi, eklenen yeni ayarlar: secim, kurtulma, zamanlayici.can_degismeme_suresi
(mevcut ayarlariniz korundu)
```

Kalibrasyonu, can barı bölgesini, PID'i, Tesseract yolunu tekrar ayarlamana
gerek yok. Sıfırdan başlamak istersen `config.json`'u sil — bir sonraki
çalıştırmada varsayılanlardan yeniden oluşturulur.

## 1) Kurulum

```
pip install mss opencv-python numpy pytesseract pywin32 keyboard
```

Tesseract OCR motoru ayrıca kurulmalı (Windows):
https://github.com/UB-Mannheim/tesseract/wiki
Kurulumda **Turkish** dil paketini de işaretleyin.
Kurulum yolu farklıysa `config.json > ocr.tesseract_yolu` değerini düzeltin.

## 2) Çalıştırma

```
python metin_bot.py
```

Açılışta tüm pencereleri PID'leriyle listeler ve sorar:

```
======================================================================
  OYUN PENCERESI SECIMI
======================================================================
  Muhtemel oyun pencereleri:
    PID 20028   Metin2                             1280x720
  Tum acik pencereler:
    PID 20028   Metin2                             1280x720
    PID 9134    Chrome                             1920x1040
----------------------------------------------------------------------
  PID girin [20028]:
```

PID'i yazıp Enter'a bas — o pencere için çalışır ve seçim `config.json`'a
kaydedilir. Bir daha sormasın istersen:

```
python metin_bot.py --pid 20028
```

* **F12** durdur, **F11** duraklat/devam
* Oyun penceresi öne gelmediğinde bot bekler (yanlış yere tıklamaz)

Aynı şekilde `kalibrasyon.py` ve `teshis.py` de açılışta PID sorar — üç araç da
aynı pencereyle çalışır.

## 3) Çözünürlük

Ayarlar **1920x1080 referansına** göre yazılmıştır. Bot açılışta pencerenin
gerçek boyutunu ölçer ve piksel değerlerini kendisi ölçekler:

```
Pencere: Metin2  1280x720  olcek=0.67  (referans 1080p)
Ayarlar bu cozunurluge uyarlandi: etiket 5-17px, isin kutusu 80px, tiklama ofseti 40px
```

Etiket yüksekliği, tıklama ofseti, ışın kutusu ve OCR büyütme oranı buna göre
ayarlanır — pencereyi küçültüp büyütsen de tekrar ayar yapman gerekmez.
Kapatmak için: `config.json > otomatik_olcek = false`.

Kalibrasyonda **s** ile kaydettiğinde değerler referans çözünürlüğe geri
çevrilerek yazılır, yani ayarların bozulmaz.

## 4) Kalibrasyon (isteğe bağlı)

Tespit iyi çalışıyorsa gerek yok. İnce ayar için:

```
python kalibrasyon.py
```

* **Yeşil kutu** = hedef sayılıyor
* **Kırmızı/gri kutu** = yazı bulundu ama hedef değil (canavar, oyuncu ismi)
* `parlaklik` / `max doygunluk` çubukları etiket bulmayı ayarlar
* **s** kaydet, **q** çık

## Akış

```
ekranı tara → "…Metini" yazılarını bul → ekranın ortasına en yakınını seç
   → gövdesine insansı fare ile tıkla
   → ekranın üstündeki HEDEF CAN BARI çıktı mı?  (çıkmazsa tekrar dene)
   → bar izlenir: can %9 → %4 → %0
   → bar kaybolunca / can bitince TAŞ KIRILDI → sıradaki taşa geç
   → ekranda taş kalmazsa E ile kamerayı çevir
```

Durumlar konsolda görünür: `ARIYOR → TIKLADI → KESIYOR → ARIYOR`

## Can barı (taş kırıldı mı kontrolü)

Bot, hedefe tıklayınca ekranın üstünde çıkan can barını okur. Bu, taşın
kırıldığını anlamanın en kesin yolu — süre tahmini yapmaz.

**Bir kez bölgeyi göstermen gerekiyor:**

1. Oyunda bir metne tıkla, can barı çıksın
2. `python kalibrasyon.py`
3. Barın etrafına fareyle bir kutu çiz (isim + yüzde + sayılar içeride kalsın)
4. **h** tuşuna bas → bölge ayarlanır
5. **s** ile kaydet

Mor kutunun üstünde canlı okuma görünür:
`BAR: VAR  metin=True  can=9%  'Lv.100 (2.Seviye) Korsan Metini'`

`can=?` çıkıyorsa yüzde okunamıyor demektir; kutuyu biraz genişlet (yüzde
yazısı ya da `37.597.133.802 / 400.000.000.000` sayıları içeride olmalı — ikisinden
biri yeterli, bot ikisini de ayrıştırabiliyor).

### Bölge yanlış yerdeyse
`debug_teshis/can_bari.png` dosyasında **üstteki hedef barı** görünmeli. Taşın
havada duran ismi görünüyorsa bölge yanlış yerde. Bot bunu kendisi de fark eder:
`yuzde_zorunlu = true` olduğu için can/yüzde okumadan "bar var" demez, teşhis
aracı da uyarır.

En kolay yol — oyunda bir metne tıklayıp can barı ekrandayken:

```
python teshis.py
```

Bar okunamazsa ekranın üst bölgesini kendisi şerit şerit tarar, yüzdeyi bulduğu
yeri bulur ve kaydetmeyi teklif eder:

```
  Bar okunamadi -> otomatik aramayi deniyorum
  Ust bolge taraniyor...
    y=0.031  can=9%  'Lv.100 (2.Seviye) Korsan Metini 9% 37.597.133.802 / 4'
  BULUNDU -> can %9  bolge={'sol': 0.12, 'ust': 0.011, 'sag': 0.88, 'alt': 0.115}
  Bu bolgeyi config.json'a kaydedeyim mi? [E/h]:
```

Kapatmak istersen `hedef_bari.kullan = false` — o zaman sadece zamanlayıcıyla
çalışır.

## Yol kapanması (taşa gidemiyorsa)

Karakter taşa yürürken araya yeni bir taş spawn olup yolu kapatabiliyor. Bot
bunu **can barından** anlıyor: hedef alındı ama can hiç azalmıyorsa taşa
ulaşılamıyor demektir.

```
Can 10 sn'dir degismedi (can=%99) -> yol kapali gibi
Tas #4 30 sn boyunca atlanacak
Yolu kapatan tasa geciliyor -> #7
```

Ne yapıyor:

1. Takılan taşı `takilan_tas_bekleme` süresince listeden atlıyor
2. E ile kamerayı biraz çeviriyor
3. **En yakın taşa** geçiyor — yolu kapatan taş zaten en yakındaki olduğu için
   önce onu kırıyor, yol kendiliğinden açılıyor

Ayarlar `config.json > kurtulma`:

| Anahtar | Ne yapar |
|---|---|
| `engeli_hedefle` | Takılınca en yakın taşa geç (önerilen: açık) |
| `kamera_cevir` | Takılınca E ile açı değiştir |
| `tus` | Takılınca basılacak ek tuş (boş bırakılabilir) |

## Hangi taş seçilsin (`config.json > secim`)

Metin2'de isim yazısı uzaklıkla küçülür — **büyük etiket = yakın taş**. Bot bunu
kullanarak yakın taşı tercih ediyor, böylece hem daha az yürüyor hem de yolu
kapatan taşa takılma ihtimali düşüyor.

| `yontem` | Davranış |
|---|---|
| `karisik` | Etiket boyutu + ekranın ortasına yakınlık (varsayılan) |
| `en_yakin` | Sadece en büyük etiket (en yakın taş) |
| `ekran_ortasi` | Sadece ekranın ortasına en yakın |

`boyut_agirligi` (0–1) karışık modda boyutun ağırlığını belirler, varsayılan `0.65`.

## Zamanlayıcı (`config.json > zamanlayici`)

Tüm süreler saniye. `[a, b]` yazan yerlerde a–b arası rastgele beklenir.

| Anahtar | Ne zaman kullanılır | Varsayılan |
|---|---|---|
| `tiklama_sonrasi_bekleme` | Tıkladıktan sonraki duraklama | `[1.1, 1.8]` |
| `hedef_bari_cikma_suresi` | Can barının çıkması için verilen süre; dolarsa tekrar tıklar | `3.0` |
| `tas_kesme_zaman_asimi` | Bar takılı kalırsa bu süre sonunda vazgeçip yeni taş arar | `90.0` |
| `tas_kirildi_sonrasi_bekleme` | Taş kırıldıktan sonraki duraklama | `[0.5, 1.0]` |
| `ayni_tasa_tekrar_tiklama_bekleme` | Aynı taşa tekrar tıklamadan önce | `8.0` |
| `dongu_araligi` | İki tarama arası | `0.45` |
| `kamera_cevirme_esigi` | Bu süre hiç taş görülmezse E'ye basar | `6.0` |
| `kamera_cevirme_basili_tutma` | E tuşunu ne kadar basılı tutsun | `[0.35, 0.6]` |
| `hedef_kaybolma_toleransi` | Görünmeyen taşı listeden düşürme süresi | `1.5` |
| `can_degismeme_suresi` | Can bu süre boyunca azalmazsa "yol kapalı" sayılır | `10.0` |
| `takilan_tas_bekleme` | Takılınan taş ne kadar atlanacak | `30.0` |
| `kurtulma_sonrasi_bekleme` | Kurtulma hamlesinden sonraki duraklama | `[0.6, 1.0]` |

Sunucu ışınlanması yavaşsa `hedef_bari_cikma_suresi`'ni, taşlar çok dayanıklıysa
`tas_kesme_zaman_asimi`'nı artır.

## İnce ayarlar (`config.json`)

| Anahtar | Ne işe yarar |
|---|---|
| `tiklama.max_aktif_tas` | Aynı anda kaç taş kesilsin (1 = teker teker) |
| `hedef_bari.kullan` | Can barıyla bitiş kontrolü (önerilen: açık) |
| `isin.kullan` | `false` (varsayılan): taş kesiliyor mu kararı tıklama zamanlayıcısıyla verilir. `true`: mavi ışın rengine bakar — taşın kendi parlaması yanlış pozitif verebilir, önce kalibrasyonda **b** ile rengi örnekleyin |
| `otomatik_olcek` | Pencere boyutuna göre piksel ayarlarını uyarlar |
| `tiklama.hedef_ofset_y` | Yazının kaç piksel altına tıklansın (taşın gövdesi) |
| `tiklama.ayni_tasa_tekrar_tiklama_bekleme` | Aynı taşa tekrar tıklamadan önceki bekleme |
| `kamera.tas_bulunamazsa_saniye` | Bu süre taş görülmezse kamerayı çevir |
| `arama_bolgesi` | Arayüzü (üst bar, beceri çubuğu) taramanın dışında bırakır |
| `ocr.seviye_filtresi` | `"100"` yazarsanız sadece Lv 100 taşlara tıklar |
| `gunluk.kare_kaydet` | `true` → `debug/` klasörüne işaretli kareler yazar |

## Sorun giderme

* **Hiç taş bulunmuyor** → kalibrasyonda `parlaklik` eşiğini düşürün; taş isimleri
  arama bölgesinin dışında kalıyorsa `arama_bolgesi` sınırlarını genişletin.
* **Yanlış şeylere tıklıyor** → `ocr.anahtar_kelimeler` listesini daraltın,
  `ocr.seviye_filtresi` ekleyin.
* **Tıklıyor ama karakter vurmuyor** → `hedef_ofset_y` değerini artırın/azaltın;
  yazının altındaki gövdeye denk gelmeli.
* **Işın algılanmıyor** → kalibrasyonda **b** ile rengi yeniden örnekleyin,
  `isin.kutu_yukseklik` değerini taş boyuna göre ayarlayın.

---

## "Kalibrasyonda görüyor ama bot tıklamıyor"

Kalibrasyon penceresi **bulunan her yazıyı** kutuya alır; bot ise sadece
**hedef sayılanlara** tıklar. Arada fark varsa sebebi bulmak için:

```
python teshis.py
```

Bu araç sırayla pencereyi, Tesseract'ı ve bir taramayı kontrol eder; her etiketin
OCR çıktısını yazar, kırpıklarını `debug_teshis/` klasörüne kaydeder ve sonunda
teşhisi söyler. En sık üç sebep:

| Belirti | Sebep | Çözüm |
|---|---|---|
| OCR çıktısı hepsinde `''` | Tesseract kurulu değil / yolu yanlış | Tesseract'ı kurun, `ocr.tesseract_yolu`'nu düzeltin. Acil çözüm: `ocr.zorunlu = false` |
| OCR okuyor ama `hedef=False` | Yazı anahtar kelimeye uymuyor | Çıktıdan bir parçayı `ocr.anahtar_kelimeler`'e ekleyin |
| Hedef bulunuyor, fare kıpırdamıyor | Oyun yönetici hakkıyla çalışıyor | Python'u/konsolu **Yönetici olarak** çalıştırın |

Tıklama yolunu ayrıca test etmek için: `python teshis.py tikla`

Bot çalışırken konsol artık her 2 saniyede ne gördüğünü yazar:
`Etiket: 5  Hedef: 2  -> 'Lv 100 Isin Metini', 'Tuccar' [hedef degil] ...`

### `ocr.zorunlu = false` ne yapar?
OCR okuyamasa bile isim etiketi gördüğü yere tıklar. Hızlı çözümdür ama
canavarları da hedef sayar — Tesseract düzelene kadar geçici kullanın.
