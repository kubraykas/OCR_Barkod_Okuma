# OCR_Barkod_Okuma

Webcam üzerinden **QR kod ve barkod okuyan**, aynı zamanda kodun üzerinde/etrafında basılı **seri numarası gibi metinleri EasyOCR ile okuyan**, her taramayı **kalıcı olarak kaydeden** (CSV + Excel) bir Python/Tkinter masaüstü uygulaması.

Ana uygulama: **[`QR_Tracking_App.py`](QR_Tracking_App.py)**

---

## İçindekiler

- [Özellikler](#özellikler)
- [Ekran Yapısı](#ekran-yapısı)
- [Proje Dosyaları](#proje-dosyaları)
- [Kurulum](#kurulum)
- [Kullanım](#kullanım)
- [Nasıl Çalışıyor](#nasıl-çalışıyor)
- [Kayıt Formatı (CSV / Excel)](#kayıt-formatı-csv--excel)
- [Bilinen Sınırlamalar](#bilinen-sınırlamalar)
- [Sorun Giderme](#sorun-giderme)
- [Bağımlılıklar](#bağımlılıklar)
- [Lisans](#lisans)

---

## Özellikler

- **QR kod okuma** — `pyzbar` (zbar motoru) ile, OpenCV'nin kendi `QRCodeDetector`'ı yedek olarak kullanılıyor.
- **1D Barkod okuma** — EAN-13, EAN-8, UPC-A/UPC-E, Code128, Code39, Codabar, ITF gibi `pyzbar`'ın desteklediği tüm barkod tipleri (sadece QR değil).
- **Küçük/uzak kodlar için otomatik büyütme denemesi** — kod ilk seferde bulunamazsa kare birkaç farklı oranda (1.5x, 2x, 3x) büyütülüp tekrar denenir.
- **OCR ile seri numarası okuma** — her kod okunduğunda etrafındaki bölge (dört yöne de pay bırakılarak kırpılır) EasyOCR'a gönderilir; İngilizce ve Türkçe (ç, ş, ğ, ı, ö, ü dahil) karakterleri okuyabilir.
- **Kim / hangi ürün** takibi — her taramaya opsiyonel kullanıcı ve ürün adı etiketlenebilir.
- **Otomatik kamera seçimi** — sistemde birden fazla kamera/sanal kamera varsa (dahili laptop kamerası, harici USB webcam, IR kamera vb.), sadece "açılabilen" değil **gerçekten görüntü veren** (siyah/boş çıkmayan) ilk kamerayı otomatik seçer.
- **Canlı "Son Okunan" paneli** — video görüntüsüyle aynı anda, en son okunan kodun tipini/içeriğini/OCR metnini büyük ve belirgin şekilde gösterir.
- **Kalıcı kayıt** — her okuma hem bellekte tutulur hem `scans_log.csv` dosyasına anlık olarak yazılır.
- **Excel'e aktarma** — tek tuşla tüm kayıtları `.xlsx` dosyası olarak istediğin konuma indirebilirsin.
- **Canlı metrikler** — toplam okuma sayısı, dakika başına okuma, en aktif kullanıcı/ürün gibi basit istatistikler.
- **Tekrar okuma koruması (cooldown)** — aynı kod kamera önünde dururken art arda tekrar tekrar kaydedilmez (varsayılan 3 saniye).

## Ekran Yapısı

Pencere yukarıdan aşağıya şu şekilde düzenlenmiştir:

1. **Üst kontrol çubuğu** — kamera seçimi, "Kameraları Tara", "Bu Kameraya Bağlan", "Durdur/Başlat"
2. **Kullanıcı / Ürün alanı** — taramayı kime/hangi ürüne ait olarak etiketlemek için (opsiyonel)
3. **Video alanı** — canlı kamera görüntüsü, tam genişlikte, tespit edilen kodun etrafında yeşil çerçeve ve tip+içerik etiketiyle
4. **"Son Okunan" paneli** — video ile aynı anda, en son okunan kodu büyük yazıyla gösterir
5. **Metrikler kutusu + "Excel'e Aktar" butonu**
6. **Okuma Kayıtları tablosu** — tüm geçmiş taramalar (sıra, saat, dakika, kullanıcı, ürün, kod tipi, kod içeriği, OCR metni)

## Proje Dosyaları

| Dosya | Açıklama |
|---|---|
| **`QR_Tracking_App.py`** | **Ana/güncel uygulama.** Canlı kamera + QR/barkod okuma + OCR + CSV/Excel kaydı + kullanıcı arayüzü. |
| `OCR_Kamera_App.py` | Daha basit bir Tkinter uygulaması — sadece QR okur (barkod desteği yok), OCR sonucu ekranda gösterir ama kalıcı kayıt yapmaz. |
| `EasyOCR_Camera.py` | En ilkel canlı kamera denemesi — Tkinter yerine ham bir OpenCV penceresi (`cv2.imshow`) kullanır, sadece QR okur. |
| `EasyOCR.py` | Tek bir statik resim (`test.png`) üzerinde QR bulup çevresini EasyOCR ile okuyan basit demo script. |
| `PaddlePaddleOCR.py` | `EasyOCR.py` ile aynı işi PaddleOCR kütüphanesiyle yapmayı deneyen alternatif demo (bkz. [Bilinen Sınırlamalar](#bilinen-sınırlamalar)). |
| `list_cameras.py` | Sistemde bulunan kameraları listeleyen küçük yardımcı script. |
| `scans_log.csv` | Uygulamanın otomatik olarak yazdığı kayıt dosyası (uygulama ilk çalıştığında otomatik oluşur). |

## Kurulum

```bash
pip install -r requirements.txt
```

Gerekli temel kütüphaneler: `opencv-python`, `easyocr`, `pyzbar`, `numpy`, `Pillow`, `openpyxl` (Excel için).

> **Not:** `easyocr` kurulumu beraberinde `torch` (PyTorch) getirir; ilk kurulum biraz zaman alabilir. İlk çalıştırmada EasyOCR, İngilizce ve Türkçe dil modellerini (~birkaç yüz MB) internetten bir kere indirir, sonraki çalıştırmalarda diskten okur.

## Kullanım

```bash
python QR_Tracking_App.py
```

1. Uygulama açıldığında otomatik olarak kameraları tarar ve gerçek görüntü veren ilk kamerayı seçip bağlanır.
2. Yanlış kameraya bağlandıysa üstteki kamera kutusundan doğru index'i seçip **"Bu Kameraya Bağlan"** butonuna bas.
3. İstersen **Kullanıcı** ve **Ürün** alanlarını doldur — her taramaya bu bilgiler etiketlenir.
4. Bir QR kod veya barkodu kameraya göster; tespit edildiğinde etrafına yeşil çerçeve çizilir, "Son Okunan" panelinde ve tablodaki listede görünür.
5. Kayıtları Excel olarak indirmek için **"Excel'e Aktar"** butonuna bas.

### İpucu: Net okuma için

- Kod ile kamera arasında yeterli mesafe bırak (çoğu webcam'in sabit/otomatik odağı çok yakın mesafede net görüntü veremez).
- Kodu kameraya mümkün olduğunca dik ve düz tut, açılı tutma.
- Işığın kod üzerine doğrudan yansıyıp parlamasına izin verme.
- Kamera ve kod elde tutuluyorsa mümkünse ikisini de sabit bir yüzeye koy — el titremesi bulanıklığa yol açar.

## Nasıl Çalışıyor

**Kod okuma (`decode_codes`):**
1. Önce `pyzbar` ile orijinal karede QR/barkod aranır (hem QR hem 1D barkod tiplerini destekler).
2. Bulunamazsa OpenCV'nin `QRCodeDetector`'ı (sadece QR) denenir.
3. O da bulamazsa kare sırasıyla 1.5x, 2x, 3x büyütülüp tekrar denenir (küçük/uzak kodlar için).

**OCR (`_run_ocr_and_store`):**
1. Kodun etrafı (`OCR_PADDING` kadar dört yöne de pay bırakılarak) kırpılır.
2. Kırpılan bölge 2x büyütülür.
3. EasyOCR'ın metin tespit hassasiyeti (varsayılandan daha düşük eşik değerleriyle) artırılarak `readtext()` çağrılır — bu, düşük kontrastlı/soluk metinlerin de yakalanma ihtimalini artırır.
4. Arka planda ayrı bir thread'de çalışır, böylece kamera görüntüsü kilitlenmez.

**Mimari:** Kamera okuma + görüntü çizimi ana (UI) thread'inde, OCR ise ayrı bir arka plan thread'inde çalışır; ikisi paylaşılan veriler üzerinden `Lock` ile güvenli şekilde haberleşir.

## Kayıt Formatı (CSV / Excel)

Her satırda şu sütunlar bulunur:

| Sütun | Açıklama |
|---|---|
| Sıra | Kayıt numarası |
| Saat | Taramanın yapıldığı saat |
| Dakika | Uygulama açıldığından itibaren kaçıncı dakika |
| Kullanıcı | Taramayı yapan kişi (belirtilmediyse `(belirtilmedi)`) |
| Ürün | Taranan ürün adı (belirtilmediyse `(belirtilmedi)`) |
| Kod Tipi | `QRCODE`, `EAN13`, `CODE128` vb. |
| Kod İçeriği | Kodun çözülmüş verisi |
| OCR Metni | Kodun etrafından okunan serbest metin (seri no vb.) |

`scans_log.csv` dosyasının şeması (sütunları) değişirse, eski dosya otomatik olarak `scans_log_backup_<tarih>.csv` adıyla yedeklenir ve yeni şemayla temiz bir dosya açılır — veri kaybı yaşanmaz.

## Bilinen Sınırlamalar

- **Sabit odaklı webcam'ler** yakın mesafede (birkaç cm) net görüntü veremez; bu durumda hem QR/barkod okuma hem OCR başarısız olur. Bu bir yazılım kısıtı değil, donanımın fiziksel odak aralığı meselesidir — kamerayı odağın net olduğu mesafede tutmak gerekir.
- **`PaddlePaddleOCR.py`** şu haliyle çalışmaz: dosyanın adı (`PaddlePaddleOCR.py`) `paddleocr` paketiyle çakışıyor (satır 1'deki `from PaddlePaddleOCR import ...` kendi kendini import etmeye çalışıyor) ve `fonts/simfang.ttf` yolu projede yok. Kullanmak için dosyanın import satırının `from paddleocr import PaddleOCR, draw_ocr` olarak düzeltilmesi ve bir font dosyası eklenmesi gerekir.
- Düşük ışıkta veya çok bulanık karelerde EasyOCR bazen kısmi/yanlış metin okuyabilir (ör. uzun bir seri numarasının son birkaç hanesini kaçırmak gibi) — bu, kaynak görüntüdeki piksel detayının yetersizliğinden kaynaklanır, OCR ayarlarıyla tamamen çözülemez.

## Sorun Giderme

**"Kamera açılamadı" hatası:** `MAX_CAMERA_INDEX` içindeki index'lerden hiçbiri kameranıza denk gelmiyor olabilir; "Kameraları Tara" butonuyla mevcut index'leri görüp deneyin.

**Uygulama yanlış kameraya bağlanıyor:** Bazı sistemlerde IR kamera veya boşta duran bir sanal kamera (OBS/Camo vb.) da "kamera" olarak algılanabilir. Uygulama bunları siyah/düz renk çıktısına bakarak elemeye çalışır, ama emin olmak için kamera kutusundan index'leri tek tek deneyip doğru olanı seçebilirsiniz.

**EasyOCR modeli hiç bitmeyecekmiş gibi yavaş indiriyor:** Nadiren, EasyOCR'ın kendi indirme mekanizması ağ hızından bağımsız olarak çok yavaş kalabiliyor. Bu durumda model dosyasını (`https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/latin_g2.zip` gibi) tarayıcı/`curl` ile elle indirip `~/.EasyOCR/model/` klasörüne (zip içindeki `.pth` dosyasını çıkararak) yerleştirmek, EasyOCR'ın indirmeyi atlayıp dosyayı doğrudan kullanmasını sağlar.

**`cv2` bulunamıyor / ModuleNotFoundError:** `pip install -r requirements.txt` çalıştırılmamış olabilir, ya da `opencv-python` ile `opencv-python-headless` aynı anda kurulup birbirinin dosyalarının üzerine yazmış olabilir — bu durumda `pip uninstall opencv-python opencv-python-headless` ile ikisini de kaldırıp sadece birini (`pip install opencv-python`) yeniden kurmak sorunu çözer.

## Bağımlılıklar

```
easyocr
matplotlib
numpy
opencv-python
openpyxl
Pillow
pyzbar
```

Tam sürüm bilgisi için [`requirements.txt`](requirements.txt) dosyasına bakın.

## Lisans

Bu proje **Apache License 2.0** ile lisanslanmıştır. Detaylar için [`LICENSE`](LICENSE) dosyasına bakın. Orijinal statik demo scriptleri (`EasyOCR.py`, `PaddlePaddleOCR.py`) Alejandro Olivo'nun QR+OCR demo reposundan (2023) türetilmiştir; canlı kamera, barkod desteği, OCR entegrasyonu, kayıt (CSV/Excel) ve arayüz geliştirmeleri bu depoda eklenmiştir.
