import cv2
import easyocr

# ==== Ayarlar ====
# iPhone'u EpocCam / iVCam / Camo gibi bir uygulamayla sanal webcam olarak
# bağladıysanız burada 0 yerine başka bir index gerekebilir (1, 2, ...).
# Doğru index'i bulmak için CAMERA_INDEX değerini değiştirip deneyin.
CAMERA_INDEX = 0
PADDING = 200  # QR kodun etrafında OCR için bırakılacak boşluk (piksel)

# EasyOCR modelini bir kez yükle
reader = easyocr.Reader(['en'])

# QR kod dedektörü
detector = cv2.QRCodeDetector()

cap = cv2.VideoCapture(CAMERA_INDEX)
if not cap.isOpened():
    raise RuntimeError(f"Kamera açılamadı (index={CAMERA_INDEX}). Farklı bir CAMERA_INDEX deneyin.")

print("Çıkmak için 'q' tuşuna basın.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Kameradan görüntü alınamadı.")
        break

    display_frame = frame.copy()

    data, bbox, _ = detector.detectAndDecode(frame)

    if bbox is not None and data:
        pts = bbox[0].astype(int)
        cv2.polylines(display_frame, [pts], True, (0, 255, 0), 2)

        h, w = frame.shape[:2]
        min_x, min_y = pts[:, 0].min(), pts[:, 1].min()
        max_x, max_y = pts[:, 0].max(), pts[:, 1].max()

        x1, y1 = max(int(min_x), 0), max(int(min_y), 0)
        x2, y2 = min(int(max_x) + PADDING, w), min(int(max_y) + PADDING, h)

        crop_img = frame[y1:y2, x1:x2]

        if crop_img.size > 0:
            rgb_crop = cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)
            results = reader.readtext(rgb_crop)

            for ocr_bbox, text, conf in results:
                top_left = tuple(map(int, ocr_bbox[0]))
                bottom_right = tuple(map(int, ocr_bbox[2]))
                cv2.rectangle(crop_img, top_left, bottom_right, (0, 0, 255), 2)
                cv2.putText(crop_img, text, (top_left[0], max(top_left[1] - 5, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            display_frame[y1:y2, x1:x2] = crop_img

    cv2.imshow("QR + OCR (canli kamera)", display_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
