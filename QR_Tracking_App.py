"""QR Kod ve Barkod Takip Platformu.

Webcam'den akan görüntüde hem QR kodlarını hem de 1D barkodları (EAN13,
EAN8, UPC-A/E, Code128, Code39, Codabar, ITF vb. - pyzbar/zbar'ın
desteklediği tüm tipler) okur, her okumayı "kim / hangi ürün / kaçıncı
dakika / kod tipi" bilgisiyle birlikte kaydeder ve canlı metrikler gösterir.
Her kod okunduğunda etrafındaki bölge (OCR_PADDING kadar pay ile) EasyOCR'a
gönderilir; kodun üzerinde/yanında basılı seri numarası gibi metinler okunur
ve aynı kayda (`ocr_metni`) eklenir. Yani her satırda hem kodun tipi+içeriği
hem de o kodun çevresinden okunan OCR metni birlikte tutulur.

Şu an için kayıtlar bellekte tutulur ve `scans_log.csv` dosyasına da yazılır
(gerçek bir veritabanı bağlanana kadar geçici depolama). Veritabanına geçişte
tek yapılması gereken `DataStore.add()` içindeki CSV yazma satırının yerine
bir DB insert çağrısı koymaktır.
"""

import csv
import os
import threading
import time
import tkinter as tk
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

import cv2
import numpy as np
from PIL import Image, ImageTk

CAMERA_INDEX = 1  # başlangıçta bağlanılacak kamera; ekrandaki "Kamera" alanından her an değiştirilebilir
BLANK_FRAME_STD_THRESHOLD = 5.0  # bu değerin altındaki std sapma "siyah/duz renk, gercek goruntu degil" sayilir
MAX_CAMERA_INDEX = 10  # "Kameraları Tara" ile denenecek maksimum index
MAX_DISPLAY_W = 1200  # video artik ustte tam genislikte oldugu icin daha buyuk gosterilebiliyor
MAX_DISPLAY_H = 720
SCAN_COOLDOWN_SECONDS = 3.0  # aynı QR kamerada dururken tekrar tekrar kaydetmesin
OCR_PADDING = 200  # QR'ın etrafındaki yazıyı da yakalamak için bırakılan pay (piksel)
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scans_log.csv")

try:
    from pyzbar.pyzbar import decode as zbar_decode
    QR_BACKEND = "pyzbar"
except Exception:
    zbar_decode = None
    QR_BACKEND = "opencv"

_cv_detector = cv2.QRCodeDetector()


def _decode_with_pyzbar(gray):
    """pyzbar (zbar motoru) QR dışında EAN13/EAN8/UPC/Code128/Code39/Codabar/ITF
    gibi çoğu 1D barkodu da okuyabilir; burada tipe göre filtreleme yapmıyoruz."""
    found = []
    for obj in zbar_decode(gray):
        text = obj.data.decode("utf-8", errors="replace")
        pts = [(p.x, p.y) for p in obj.polygon] if obj.polygon else None
        found.append((text, obj.type, pts))
    return found


def _decode_with_opencv(frame):
    # cv2.QRCodeDetector sadece QR okuyabilir, barkod desteklemez
    data, bbox, _ = _cv_detector.detectAndDecode(frame)
    if data:
        pts = [tuple(p) for p in bbox[0].astype(int)] if bbox is not None else None
        return [(data, "QRCODE", pts)]
    return []


UPSCALE_RETRY_FACTORS = (1.5, 2.0, 3.0)  # tek sabit oran bazen tam da isabet etmiyor, birkacini deniyoruz


def decode_codes(frame, try_upscale=True):
    """Karedeki tüm QR kodlarını VE barkodları (metin, kod_tipi, poligon_noktalari)
    listesi olarak döner.

    Önce pyzbar (hem QR hem barkod okur), sonra OpenCV'nin QR-only dedektörünü
    dener; ikisi de bulamazsa (ve try_upscale=True ise) kareyi birkaç farklı
    oranda büyütüp tekrar dener (küçük/uzaktaki kodlarda modül genişliği
    yetersiz kalabiliyor - hangi oranın işe yarayacağı görüntüye göre
    değiştiği için birden fazla deniyoruz). Büyütme pahalı bir işlem olduğu
    için (özellikle yüksek çözünürlüklü kamerada) her karede değil, çağıran
    tarafından (ör. birkaç karede bir) tetiklenmesi bekleniyor.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    results = _decode_with_pyzbar(gray) if zbar_decode is not None else []
    if not results:
        results = _decode_with_opencv(frame)
    if not results and try_upscale:
        for factor in UPSCALE_RETRY_FACTORS:
            big_gray = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
            if zbar_decode is not None:
                results = [
                    (text, kod_tipi, _rescale_pts(pts, factor))
                    for text, kod_tipi, pts in _decode_with_pyzbar(big_gray)
                ]
            if not results:
                big_frame = cv2.cvtColor(big_gray, cv2.COLOR_GRAY2BGR)
                results = [
                    (text, kod_tipi, _rescale_pts(pts, factor))
                    for text, kod_tipi, pts in _decode_with_opencv(big_frame)
                ]
            if results:
                break
    return results


def _rescale_pts(pts, factor):
    """Büyütülmüş (upscale) görüntü üzerinde bulunan poligon noktalarını orijinal
    kare koordinatlarına geri çevirir - bu sayede büyütme denemesiyle bulunan
    kodlar için de ekranda çerçeve çizilebiliyor (önceden bu durumda pts atılıp
    None dönüyordu, yani kod okunuyordu ama ekranda hiçbir görsel işaret
    çıkmıyordu)."""
    if pts is None:
        return None
    return [(x / factor, y / factor) for x, y in pts]


@dataclass
class ScanRecord:
    sira: int
    saat: str
    dakika: int
    kullanici: str
    urun: str
    kod_tipi: str
    kod_icerik: str
    ocr_metni: str = ""


CSV_HEADER = ["Sira", "Saat", "Dakika", "Kullanici", "Urun", "Kod_Tipi", "Kod_Icerik", "OCR_Metni"]


class DataStore:
    """Taramaları bellekte tutar ve CSV'ye ekler (ileride DB ile değiştirilecek katman)."""

    def __init__(self, csv_path):
        self.records = []
        self.csv_path = csv_path
        self._lock = threading.Lock()
        self._ensure_csv_header()

    def _ensure_csv_header(self):
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(CSV_HEADER)
            return

        # Dosya var ama eski şemadan kalmış olabilir (ör. Kod_Tipi/OCR_Metni sütunu
        # yok) -- veri kaybetmeden eski dosyayı yedekleyip yeni şemayla devam et.
        with open(self.csv_path, "r", newline="", encoding="utf-8-sig") as f:
            first_line = f.readline().strip()
        current_header = ",".join(CSV_HEADER)
        if first_line != current_header:
            backup_path = self.csv_path.replace(
                ".csv", f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            os.replace(self.csv_path, backup_path)
            with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(CSV_HEADER)

    def add(self, kullanici, urun, kod_icerik, dakika, kod_tipi="QRCODE", ocr_metni=""):
        with self._lock:
            record = ScanRecord(
                sira=len(self.records) + 1,
                saat=datetime.now().strftime("%H:%M:%S"),
                dakika=dakika,
                kullanici=kullanici or "(belirtilmedi)",
                urun=urun or "(belirtilmedi)",
                kod_tipi=kod_tipi,
                kod_icerik=kod_icerik,
                ocr_metni=ocr_metni,
            )
            self.records.append(record)
            # TODO: veritabanı entegrasyonu burada yapılacak (şimdilik CSV'ye yazılıyor)
            with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(list(asdict(record).values()))
            return record

    def total_count(self):
        return len(self.records)

    def count_in_minute(self, dakika):
        return sum(1 for r in self.records if r.dakika == dakika)

    def top_users(self, n=3):
        return Counter(r.kullanici for r in self.records).most_common(n)

    def top_products(self, n=3):
        return Counter(r.urun for r in self.records).most_common(n)


class QrTrackingApp:
    def __init__(self, root):
        self.root = root
        root.title(f"QR Kod Takip Platformu ({QR_BACKEND} motoru)")

        self.store = DataStore(CSV_PATH)

        self.cap = None
        self.running = False
        self.start_time = None
        self.last_seen = {}  # qr_text -> son kaydedilme zamani (cooldown icin)
        self.frame_count = 0
        self.active_loop_id = 0  # kamera degistirildiginde eski dongu iptal edilsin diye

        self.reader = None  # EasyOCR reader, ilk kullanimda yuklenir (ensure_reader)
        self._reader_lock = threading.Lock()  # ayni anda birden fazla OCR cagrisi calismasin diye
        self.live_cameras = []  # scan_cameras() tarafindan doldurulur: gercek goruntu veren index'ler

        self._build_ui()
        # kullanici pencereyi actiginda once kameralari tara, sonra uygun olana baglan
        self.root.after(300, self.auto_connect_camera)

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text="Kamera:").pack(side=tk.LEFT)
        self.camera_var = tk.StringVar(value=str(CAMERA_INDEX))
        self.camera_combo = ttk.Combobox(top, textvariable=self.camera_var, width=6,
                                         values=[str(i) for i in range(MAX_CAMERA_INDEX)])
        self.camera_combo.pack(side=tk.LEFT, padx=4)

        ttk.Button(top, text="Kameraları Tara", command=self.scan_cameras).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Bu Kameraya Bağlan", command=self.switch_camera).pack(side=tk.LEFT, padx=4)

        self.start_button = ttk.Button(top, text="Durdur", command=self.toggle_camera)
        self.start_button.pack(side=tk.LEFT, padx=4)

        self.status_label = ttk.Label(top, text="Hazırlanıyor...")
        self.status_label.pack(side=tk.LEFT, padx=10)

        meta = ttk.Frame(self.root)
        meta.pack(fill=tk.X, padx=8, pady=(0, 8))

        ttk.Label(meta, text="Kullanıcı (Kim):").pack(side=tk.LEFT)
        self.kullanici_var = tk.StringVar()
        self.kullanici_combo = ttk.Combobox(meta, textvariable=self.kullanici_var, width=18)
        self.kullanici_combo.pack(side=tk.LEFT, padx=4)

        ttk.Label(meta, text="Ürün:").pack(side=tk.LEFT, padx=(16, 0))
        self.urun_var = tk.StringVar()
        self.urun_combo = ttk.Combobox(meta, textvariable=self.urun_var, width=18)
        self.urun_combo.pack(side=tk.LEFT, padx=4)

        # Video ustte, tam genislikte, buyuk gorunecek sekilde (once bu, cunku
        # kamerayi doğrultup QR/barkodu izlemek asil is - tablo/istatistikler
        # altta daha az yer kaplayarak devam ediyor)
        video_box = ttk.Frame(self.root)
        video_box.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.video_label = ttk.Label(video_box, anchor=tk.CENTER)
        self.video_label.pack(fill=tk.X)

        # Video ile AYNI ANDA veri gorebilmek icin: tabloya bakmaya gerek
        # kalmadan en son okunan kodu buyuk/belirgin gosteren canli panel
        last_read_box = ttk.LabelFrame(self.root, text="Son Okunan")
        last_read_box.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.last_read_label = ttk.Label(
            last_read_box, text="(henüz kod okunmadı)",
            justify=tk.LEFT, font=("Consolas", 12, "bold"), foreground="#0a6"
        )
        self.last_read_label.pack(anchor=tk.W, padx=8, pady=6)

        bottom = ttk.Frame(self.root)
        bottom.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        stats_box = ttk.LabelFrame(bottom, text="Metrikler")
        stats_box.pack(fill=tk.X, pady=(0, 8))
        self.stats_label = ttk.Label(stats_box, justify=tk.LEFT, font=("Consolas", 10))
        self.stats_label.pack(side=tk.LEFT, anchor=tk.W, padx=8, pady=8)
        ttk.Button(stats_box, text="Excel'e Aktar", command=self.export_to_excel).pack(
            side=tk.RIGHT, padx=8, pady=8
        )

        log_box = ttk.LabelFrame(bottom, text="Okuma Kayıtları")
        log_box.pack(fill=tk.BOTH, expand=True)

        columns = ("sira", "saat", "dakika", "kullanici", "urun", "tip", "kod", "ocr")
        self.tree = ttk.Treeview(log_box, columns=columns, show="headings", height=8)
        headings = {"sira": "#", "saat": "Saat", "dakika": "Dakika", "kullanici": "Kullanıcı",
                    "urun": "Ürün", "tip": "Tip", "kod": "Kod İçeriği", "ocr": "OCR Metni (Seri No vb.)"}
        widths = {"sira": 40, "saat": 70, "dakika": 55, "kullanici": 100, "urun": 110,
                  "tip": 70, "kod": 220, "ocr": 260}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W)
        vsb = ttk.Scrollbar(log_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(bottom, text=f"Kayıtlar ayrıca şuraya yazılıyor: {CSV_PATH}",
                  foreground="#555").pack(anchor=tk.W, pady=(6, 0))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(1000, self.refresh_stats)

    # ---------- Kamera ----------
    @staticmethod
    def _frame_looks_live(frame):
        """Kare tamamen siyah/düz renkse (kapalı kamera, boşta duran sanal kamera
        vb.) standart sapma çok düşük çıkar; gerçek bir görüntüde dokuya/ışığa
        bağlı olarak belirgin şekilde daha yüksektir."""
        if frame is None:
            return False
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(gray.std()) >= BLANK_FRAME_STD_THRESHOLD

    def scan_cameras(self):
        self.status_label.config(text="Kameralar taranıyor...")
        self.root.update_idletasks()
        found = []
        self.live_cameras = []  # gercekten anlamli goruntu veren (siyah/placeholder olmayan) index'ler
        for i in range(MAX_CAMERA_INDEX):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    found.append(str(i))
                    if self._frame_looks_live(frame):
                        self.live_cameras.append(str(i))
            cap.release()
        self.camera_combo["values"] = found
        if found:
            self.status_label.config(
                text=f"{len(found)} kamera bulundu: {', '.join(found)} "
                     f"(gerçek görüntü veren: {', '.join(self.live_cameras) or 'yok'})"
            )
        else:
            self.status_label.config(text="Kamera bulunamadı.")

    def ensure_reader(self):
        """EasyOCR modelini tembel (lazy) yükler; sadece ilk çağrıda gerçekten yükler.

        Türkçe karakterli (ç, ş, ğ, ı, ö, ü) etiket/seri no metinlerini de doğru
        okuyabilmek için İngilizce ile birlikte Türkçe dil modeli de yükleniyor
        (ilk yüklemede ek bir model dosyası daha indirilip biraz daha sürebilir).
        """
        if self.reader is None:
            import easyocr
            self.status_label.config(
                text="EasyOCR modeli yükleniyor (en+tr, ilk seferde uzun sürebilir)..."
            )
            self.root.update_idletasks()
            self.reader = easyocr.Reader(['en', 'tr'])

    def switch_camera(self):
        value = self.camera_var.get().strip()
        if not value.isdigit():
            messagebox.showwarning("Geçersiz kamera", "Kamera index'i sayı olmalı.")
            return
        self.open_camera(int(value))

    def toggle_camera(self):
        if self.running:
            self.stop_camera()
        else:
            value = self.camera_var.get().strip()
            self.open_camera(int(value) if value.isdigit() else CAMERA_INDEX)

    def open_camera(self, index):
        """Verilen index'teki kameraya bağlanır; çalışan sistemi ve metrikleri sıfırlamaz."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

        new_cap = cv2.VideoCapture(index)
        if not new_cap.isOpened():
            messagebox.showerror("Hata", f"Kamera açılamadı (index={index}).")
            self.running = False
            self.start_button.config(text="Başlat")
            self.status_label.config(text=f"Kamera {index} açılamadı.")
            return

        # Varsayılan çözünürlük genelde 640x480 gibi düşük oluyor; QR/barkod
        # karede küçük kalırsa modüller yeterince piksel içermeyip decode
        # edilemiyor. Kameradan daha yüksek çözünürlük istiyoruz (destekliyorsa
        # uygular, desteklemiyorsa kendi maksimumuna düşer, hata vermez).
        new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        actual_w = int(new_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(new_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[Kamera {index}] istenen 1920x1080, alinan çözünürlük: {actual_w}x{actual_h}")

        self.cap = new_cap
        self.camera_var.set(str(index))
        self.last_seen.clear()
        self.frame_count = 0
        if self.start_time is None:
            self.start_time = time.time()

        try:
            self.ensure_reader()
        except Exception as exc:
            self.reader = None
            messagebox.showwarning(
                "EasyOCR",
                f"EasyOCR modeli yüklenemedi, sadece QR içeriği kaydedilecek.\n{exc}",
            )

        self.running = True
        self.active_loop_id += 1
        self.start_button.config(text="Durdur")
        self.status_label.config(text=f"Kamera {index} bağlandı, QR kodları bekleniyor...")
        self.update_frame(self.active_loop_id)

    def start_camera(self):
        value = self.camera_var.get().strip()
        self.open_camera(int(value) if value.isdigit() else CAMERA_INDEX)

    def auto_connect_camera(self):
        """Açılışta çalışır: sabit bir index denemek yerine önce kameraları tarar,
        sonra bulunanlardan varsayılanı seçip bağlanır.

        "Kamera olarak açılıyor" ile "gerçekten anlamlı görüntü veriyor" farklı
        şeyler: sistemde IR kamera, kapalı/karartılmış kamera ya da boşta duran
        bir sanal kamera (OBS/Camo vb. - başlangıç logosu gösteren) de "açıldı"
        sayılabiliyor ama hepsi siyah/düz kare döndürüyor. Bu yüzden en yüksek
        index yerine, scan_cameras()'ın tespit ettiği "gerçek görüntü veren"
        (live_cameras) ilk kamerayı tercih ediyoruz; hiçbiri yoksa (hepsi
        siyah/placeholder ise) bulunan ilk index'e bağlanıp durumu bildiriyoruz.
        Yanlışsa üstteki kamera kutusundan value değiştirip 'Bu Kameraya
        Bağlan' ile istediğin kameraya geçebilirsin.
        """
        self.scan_cameras()
        found = list(self.camera_combo["values"])
        if not found:
            self.status_label.config(
                text="Kamera bulunamadı. Webcam bağlıysa 'Kameraları Tara'ya tekrar basıp deneyin."
            )
            return

        if self.live_cameras:
            chosen = self.live_cameras[0]
        else:
            chosen = found[0]
            messagebox.showwarning(
                "Kamera",
                f"Bulunan kameraların hiçbiri gerçek görüntü vermiyor (hepsi siyah/boş çıktı).\n"
                f"Yine de index {chosen}'e bağlanılıyor; üstteki kamera kutusundan diğer "
                f"index'leri deneyip 'Bu Kameraya Bağlan' ile doğru kamerayı seçebilirsin.",
            )

        self.camera_var.set(chosen)
        self.open_camera(int(chosen))

    def stop_camera(self):
        self.running = False
        self.active_loop_id += 1
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.start_button.config(text="Başlat")
        self.video_label.config(image="")
        self.status_label.config(text="Durduruldu.")

    # ---------- Ana döngü ----------
    def current_minute(self):
        if self.start_time is None:
            return 0
        return int((time.time() - self.start_time) // 60) + 1

    def update_frame(self, loop_id):
        if loop_id != self.active_loop_id or not self.running or self.cap is None:
            return

        ret, frame = self.cap.read()
        if not ret:
            self.status_label.config(text="Kameradan görüntü alınamadı.")
            self.root.after(200, self.update_frame, loop_id)
            return

        self.frame_count += 1
        display_frame = frame.copy()
        found_texts = []
        # Pahali "buyutup tekrar dene" adimini her karede degil, birkac karede
        # bir calistiriyoruz (yuksek cozunurluklu kamerada her karede yapilirsa
        # CPU'yu bogup canli goruntuyu yavaslatir)
        try_upscale = (self.frame_count % 5 == 0)
        for text, kod_tipi, pts in decode_codes(frame, try_upscale=try_upscale):
            found_texts.append(f"[{kod_tipi}] {text}")
            crop = None
            if pts:
                poly = np.array([[int(x), int(y)] for x, y in pts], dtype=np.int32)
                cv2.polylines(display_frame, [poly], True, (0, 255, 0), 2)
                x0, y0 = poly[0]
                cv2.putText(display_frame, f"{kod_tipi}: {text[:30]}", (x0, max(y0 - 8, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                # Kodun etrafına pay bırakarak kırp: üzerindeki/yanındaki seri numarası
                # gibi metinler bu bölgede olur ve EasyOCR'a bu kırpılmış görüntü gider
                crop = self._crop_for_ocr(frame, pts)
            self.register_scan(text, kod_tipi, crop)

        if self.frame_count % 10 == 0:  # her karede güncellemeyip titremeyi önle
            if found_texts:
                self.status_label.config(text=f"QR bulundu: {found_texts[0][:40]}")
            else:
                self.status_label.config(text=f"Taranıyor... ({self.frame_count}. kare, henüz QR yok)")

        self.show_on_video_label(display_frame)
        self.root.after(30, self.update_frame, loop_id)

    @staticmethod
    def _crop_for_ocr(frame, pts):
        """QR poligonunun etrafını OCR_PADDING kadar HER YÖNDE genişleterek kırpar.

        Seri numarası/etiket yazısı QR'ın altında, üstünde, solunda ya da
        sağında olabilir - bu yüzden pay sadece sağ/alt kenara değil, dört
        kenara da simetrik ekleniyor.
        """
        h, w = frame.shape[:2]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, y1 = max(int(min(xs)) - OCR_PADDING, 0), max(int(min(ys)) - OCR_PADDING, 0)
        x2, y2 = min(int(max(xs)) + OCR_PADDING, w), min(int(max(ys)) + OCR_PADDING, h)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2].copy()

    def register_scan(self, kod_text, kod_tipi, crop=None):
        # Ayni metin farkli tiplerde teorik olarak cakisabilir diye anahtar tip+metin
        key = f"{kod_tipi}:{kod_text}"
        now = time.time()
        last = self.last_seen.get(key)
        if last is not None and (now - last) < SCAN_COOLDOWN_SECONDS:
            return
        self.last_seen[key] = now

        kullanici = self.kullanici_var.get().strip()
        urun = self.urun_var.get().strip()

        if crop is not None and crop.size > 0 and self.reader is not None:
            # OCR yavaş olabileceğinden arka planda çalıştırıp UI'ı kilitlemiyoruz
            threading.Thread(
                target=self._run_ocr_and_store,
                args=(kod_text, kod_tipi, kullanici, urun, crop),
                daemon=True,
            ).start()
        else:
            record = self.store.add(kullanici, urun, kod_text, self.current_minute(), kod_tipi=kod_tipi)
            self._append_row(record)

        self._remember_choice(self.kullanici_combo, kullanici)
        self._remember_choice(self.urun_combo, urun)

    def _run_ocr_and_store(self, kod_text, kod_tipi, kullanici, urun, crop):
        """Arka plan thread'inde çalışır: kırpılmış bölgeyi EasyOCR ile okuyup kaydeder.

        EasyOCR'ın önce metni "bulan" (CRAFT) aşaması, varsayılan eşik
        değerleriyle düşük kontrastlı/küçük/bulanık metni hiç algılamayabiliyor
        - yani okuma (CRNN) aşamasına sıra bile gelmiyor. Bunu iyileştirmek için:
        1) Kırpılan bölgeyi 2x büyütüyoruz (CRAFT'a daha fazla piksel/detay verir)
        2) readtext()'in tespit hassasiyetini artıran parametrelerini
           varsayılandan daha duyarlı ayarlıyoruz (text_threshold, low_text,
           link_threshold düşürülüyor; mag_ratio ve contrast ayarları
           yükseltiliyor). Bu, yanlış pozitif riskini biraz artırır ama bizim
           senaryomuzda (hiç okuyamamak) daha büyük sorun.
        """
        ocr_metni = ""
        try:
            big_crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            rgb_crop = cv2.cvtColor(big_crop, cv2.COLOR_BGR2RGB)
            with self._reader_lock:  # ayni anda tek bir EasyOCR cagrisi calissin
                results = self.reader.readtext(
                    rgb_crop,
                    text_threshold=0.4,      # varsayilan 0.7 - dusuk kontrastli metni de kabul et
                    low_text=0.3,            # varsayilan 0.4 - soluk/bulanik metin bolgelerini de yakala
                    link_threshold=0.3,      # varsayilan 0.4 - yakin karakterleri kelimeye daha kolay birlestir
                    mag_ratio=2.0,           # varsayilan 1.0 - tespit oncesi ic buyutme orani
                    contrast_ths=0.1,
                    adjust_contrast=0.7,     # dusuk kontrastli bolgeleri ikinci bir gecist e iyilestirir
                )
            ocr_metni = " ".join(text for _, text, _ in results).strip()
        except Exception:
            ocr_metni = ""

        record = self.store.add(kullanici, urun, kod_text, self.current_minute(),
                                 kod_tipi=kod_tipi, ocr_metni=ocr_metni)
        self.root.after(0, self._append_row, record)

    @staticmethod
    def _remember_choice(combo, value):
        if not value:
            return
        values = list(combo["values"])
        if value not in values:
            combo["values"] = values + [value]

    def _append_row(self, record):
        self.tree.insert("", 0, values=(record.sira, record.saat, record.dakika,
                                         record.kullanici, record.urun, record.kod_tipi,
                                         record.kod_icerik, record.ocr_metni))
        ocr_kismi = f"  |  OCR: {record.ocr_metni}" if record.ocr_metni else ""
        self.last_read_label.config(
            text=f"[{record.kod_tipi}] {record.kod_icerik}{ocr_kismi}   (saat {record.saat})"
        )

    def show_on_video_label(self, frame):
        h, w = frame.shape[:2]
        scale = min(MAX_DISPLAY_W / w, MAX_DISPLAY_H / h, 1.0)
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        imgtk = ImageTk.PhotoImage(image=img)
        self.video_label.imgtk = imgtk
        self.video_label.config(image=imgtk)

    # ---------- Metrikler ----------
    def refresh_stats(self):
        if self.start_time is None:
            elapsed_txt = "00:00"
            minute = 0
        else:
            elapsed = int(time.time() - self.start_time)
            elapsed_txt = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
            minute = self.current_minute()

        top_users = self.store.top_users()
        top_products = self.store.top_products()
        users_txt = ", ".join(f"{u} ({c})" for u, c in top_users) or "-"
        products_txt = ", ".join(f"{p} ({c})" for p, c in top_products) or "-"

        lines = [
            f"Motor              : {QR_BACKEND}",
            f"Geçen süre         : {elapsed_txt}",
            f"Şu anki dakika     : {minute}",
            f"Toplam okuma       : {self.store.total_count()}",
            f"Bu dakikaki okuma  : {self.store.count_in_minute(minute)}",
            f"En aktif kullanıcı : {users_txt}",
            f"En çok okunan ürün : {products_txt}",
        ]
        self.stats_label.config(text="\n".join(lines))
        self.root.after(1000, self.refresh_stats)

    def export_to_excel(self):
        """Su ana kadarki tum kayitlari (self.store.records) bir .xlsx dosyasina
        yazar. CSV zaten yaziliyor ama kullanici acikca Excel formatinda,
        kendi sectigi konuma indirilebilir bir dosya istedi."""
        if not self.store.records:
            messagebox.showinfo("Excel'e Aktar", "Henüz kaydedilmiş bir okuma yok.")
            return

        default_name = f"tarama_kayitlari_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path = filedialog.asksaveasfilename(
            title="Excel dosyasını kaydet",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel dosyası", "*.xlsx"), ("Tüm dosyalar", "*.*")],
        )
        if not file_path:
            return

        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Tarama Kayıtları"

            headers = ["Sıra", "Saat", "Dakika", "Kullanıcı", "Ürün", "Kod Tipi", "Kod İçeriği", "OCR Metni"]
            ws.append(headers)
            for cell in ws[1]:
                cell.font = openpyxl.styles.Font(bold=True)

            for r in self.store.records:
                ws.append([r.sira, r.saat, r.dakika, r.kullanici, r.urun,
                           r.kod_tipi, r.kod_icerik, r.ocr_metni])

            # sutun genisliklerini icerige gore kabaca ayarla
            for col_cells in ws.columns:
                length = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells)
                ws.column_dimensions[col_cells[0].column_letter].width = min(length + 2, 60)

            wb.save(file_path)
        except Exception as exc:
            messagebox.showerror("Excel'e Aktar", f"Dosya kaydedilemedi:\n{exc}")
            return

        messagebox.showinfo("Excel'e Aktar", f"{len(self.store.records)} kayıt kaydedildi:\n{file_path}")

    def on_close(self):
        self.stop_camera()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = QrTrackingApp(root)
    root.mainloop()
