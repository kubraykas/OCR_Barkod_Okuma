import cv2

MAX_INDEX_TO_CHECK = 10

print("Kameralar taranıyor...")
print("Her bulunan kamera için bir pencere açılacak.")
print("Pencere aktifken: 'n' = sıradaki kameraya geç, 'q' = tamamen çık.\n")

for index in range(MAX_INDEX_TO_CHECK):
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        continue

    ret, frame = cap.read()
    if not ret:
        cap.release()
        continue

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"CAMERA_INDEX = {index}  ({w}x{h})")

    quit_all = False
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        label = f"index={index}  ({w}x{h})  -  n:sonraki  q:cik"
        cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imshow("Kamera Testi", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('n'):
            break
        if key == ord('q'):
            quit_all = True
            break

    cap.release()
    cv2.destroyAllWindows()

    if quit_all:
        break

print("\nBitti. Kullanmak istediğin index'i EasyOCR_Camera.py içindeki CAMERA_INDEX değişkenine yaz.")
