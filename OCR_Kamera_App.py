import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import cv2
from PIL import Image, ImageTk

PADDING = 200
MAX_CAMERA_INDEX = 10
MAX_DISPLAY_W = 900
MAX_DISPLAY_H = 700


class OcrCameraApp:
    def __init__(self, root):
        self.root = root
        root.title("QR + OCR Kamera Okuyucu")

        self.cap = None
        self.running = False
        self.reader = None
        self.ocr_thread = None
        self.ocr_stop_event = threading.Event()

        self.crop_lock = threading.Lock()
        self.latest_crop = None
        self.latest_crop_offset = (0, 0)

        self.results_lock = threading.Lock()
        self.latest_results = []

        self.detector = cv2.QRCodeDetector()

        top = ttk.Frame(root)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text="Kamera:").pack(side=tk.LEFT)
        self.camera_var = tk.StringVar()
        self.camera_combo = ttk.Combobox(top, textvariable=self.camera_var, state="readonly", width=10)
        self.camera_combo.pack(side=tk.LEFT, padx=4)

        ttk.Button(top, text="Kameraları Tara", command=self.scan_cameras).pack(side=tk.LEFT, padx=4)
        self.start_button = ttk.Button(top, text="Başlat", command=self.toggle_camera)
        self.start_button.pack(side=tk.LEFT, padx=4)

        ttk.Button(top, text="Resim Yükle...", command=self.load_image_file).pack(side=tk.LEFT, padx=4)

        self.status_label = ttk.Label(top, text="Hazır. Başlamadan önce 'Kameraları Tara' butonuna basın.")
        self.status_label.pack(side=tk.LEFT, padx=10)

        self.video_label = ttk.Label(root)
        self.video_label.pack(padx=8, pady=8)

        ttk.Label(root, text="Bulunan metinler:").pack(anchor=tk.W, padx=8)
        self.text_box = tk.Text(root, height=6, width=70)
        self.text_box.pack(padx=8, pady=(0, 8))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.scan_cameras()

    def scan_cameras(self):
        self.status_label.config(text="Kameralar taranıyor...")
        self.root.update_idletasks()
        found = []
        for i in range(MAX_CAMERA_INDEX):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    found.append(str(i))
            cap.release()
        self.camera_combo["values"] = found
        if found:
            self.camera_combo.current(0)
            self.status_label.config(text=f"{len(found)} kamera bulundu.")
        else:
            self.status_label.config(text="Kamera bulunamadı.")

    def ensure_reader(self):
        if self.reader is None:
            import easyocr
            self.status_label.config(text="EasyOCR modeli yükleniyor (ilk seferde uzun sürebilir)...")
            self.root.update_idletasks()
            self.reader = easyocr.Reader(['en'])
            self.status_label.config(text="Model hazır.")

    def toggle_camera(self):
        if self.running:
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self):
        if not self.camera_var.get():
            messagebox.showwarning("Kamera seçilmedi", "Önce 'Kameraları Tara' ile bir kamera seçin.")
            return

        index = int(self.camera_var.get())
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            messagebox.showerror("Hata", f"Kamera açılamadı (index={index}).")
            self.cap = None
            return

        self.ensure_reader()

        self.running = True
        self.start_button.config(text="Durdur")
        self.ocr_stop_event.clear()
        self.ocr_thread = threading.Thread(target=self.ocr_worker, daemon=True)
        self.ocr_thread.start()
        self.update_frame()

    def stop_camera(self):
        self.running = False
        self.ocr_stop_event.set()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.start_button.config(text="Başlat")
        self.video_label.config(image="")
        self.status_label.config(text="Durduruldu.")

    def update_frame(self):
        if not self.running or self.cap is None:
            return

        ret, frame = self.cap.read()
        if not ret:
            self.status_label.config(text="Kameradan görüntü alınamadı.")
            self.root.after(200, self.update_frame)
            return

        display_frame = frame.copy()
        data, bbox, _ = self.detector.detectAndDecode(frame)

        crop_box = None
        if bbox is not None and data:
            pts = bbox[0].astype(int)
            cv2.polylines(display_frame, [pts], True, (0, 255, 0), 2)

            h, w = frame.shape[:2]
            min_x, min_y = pts[:, 0].min(), pts[:, 1].min()
            max_x, max_y = pts[:, 0].max(), pts[:, 1].max()
            x1, y1 = max(int(min_x), 0), max(int(min_y), 0)
            x2, y2 = min(int(max_x) + PADDING, w), min(int(max_y) + PADDING, h)
            if x2 > x1 and y2 > y1:
                crop_box = (x1, y1, x2, y2)

        if crop_box is not None:
            x1, y1, x2, y2 = crop_box
            with self.crop_lock:
                self.latest_crop = frame[y1:y2, x1:x2].copy()
                self.latest_crop_offset = (x1, y1)

        with self.results_lock:
            results = list(self.latest_results)
            offset = self.latest_crop_offset

        ox, oy = offset
        for ocr_bbox, text, conf in results:
            top_left = (int(ocr_bbox[0][0]) + ox, int(ocr_bbox[0][1]) + oy)
            bottom_right = (int(ocr_bbox[2][0]) + ox, int(ocr_bbox[2][1]) + oy)
            cv2.rectangle(display_frame, top_left, bottom_right, (0, 0, 255), 2)
            cv2.putText(display_frame, text, (top_left[0], max(top_left[1] - 5, 0)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        self.show_on_video_label(display_frame)

        self.root.after(15, self.update_frame)

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

    def ocr_worker(self):
        # arka planda çalışır, ana pencereyi kilitlememesi için OCR'ı ayrı thread'de yapıyoruz
        while not self.ocr_stop_event.is_set():
            with self.crop_lock:
                crop = None if self.latest_crop is None else self.latest_crop.copy()

            if crop is not None and crop.size > 0:
                rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                try:
                    results = self.reader.readtext(rgb_crop)
                except Exception:
                    results = []
                with self.results_lock:
                    self.latest_results = results
                if results:
                    texts = [text for _, text, _ in results]
                    self.root.after(0, self.update_text_box, texts)

            time.sleep(0.3)

    def update_text_box(self, texts):
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert(tk.END, "\n".join(texts))

    def load_image_file(self):
        file_path = filedialog.askopenfilename(
            title="Resim seç",
            filetypes=[("Resim dosyaları", "*.jpg *.jpeg *.png *.bmp"), ("Tüm dosyalar", "*.*")],
        )
        if not file_path:
            return

        self.stop_camera()

        frame = cv2.imread(file_path)
        if frame is None:
            messagebox.showerror("Hata", "Resim okunamadı.")
            return

        self.ensure_reader()
        self.status_label.config(text="Resim işleniyor...")
        self.root.update_idletasks()
        threading.Thread(target=self.process_static_image, args=(frame,), daemon=True).start()

    def process_static_image(self, frame):
        display_frame = frame.copy()
        data, bbox, _ = self.detector.detectAndDecode(frame)

        crop = frame
        ox, oy = 0, 0
        if bbox is not None and data:
            pts = bbox[0].astype(int)
            cv2.polylines(display_frame, [pts], True, (0, 255, 0), 2)

            h, w = frame.shape[:2]
            min_x, min_y = pts[:, 0].min(), pts[:, 1].min()
            max_x, max_y = pts[:, 0].max(), pts[:, 1].max()
            x1, y1 = max(int(min_x), 0), max(int(min_y), 0)
            x2, y2 = min(int(max_x) + PADDING, w), min(int(max_y) + PADDING, h)
            if x2 > x1 and y2 > y1:
                crop = frame[y1:y2, x1:x2]
                ox, oy = x1, y1

        rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        try:
            results = self.reader.readtext(rgb_crop)
        except Exception:
            results = []

        for ocr_bbox, text, conf in results:
            top_left = (int(ocr_bbox[0][0]) + ox, int(ocr_bbox[0][1]) + oy)
            bottom_right = (int(ocr_bbox[2][0]) + ox, int(ocr_bbox[2][1]) + oy)
            cv2.rectangle(display_frame, top_left, bottom_right, (0, 0, 255), 2)
            cv2.putText(display_frame, text, (top_left[0], max(top_left[1] - 5, 0)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        texts = [text for _, text, _ in results]
        self.root.after(0, self.show_static_result, display_frame, texts)

    def show_static_result(self, display_frame, texts):
        self.show_on_video_label(display_frame)
        self.update_text_box(texts if texts else ["(metin bulunamadı)"])
        self.status_label.config(text="Resim işlendi.")

    def on_close(self):
        self.stop_camera()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = OcrCameraApp(root)
    root.mainloop()
