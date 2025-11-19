#!/usr/bin/env python3
"""
Object Detection with YOLOv8 + Distance Estimation on Raspberry Pi 5
Running as a subprocess for the Camera Control App.
"""

import cv2
import numpy as np
import time
import sys
import os
import logging
import argparse

# --- Loglama Ayarları ---
# Konsol kirliliğini önlemek için logları sadece INFO seviyesinde tutuyoruz
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
# Ultralytics (YOLO) loglarını sustur (Model yüklenirken çıkan spam'i engeller)
logging.getLogger("ultralytics").setLevel(logging.ERROR)

# --- Importlar ---
try:
    from picamera2 import Picamera2
except ImportError:
    print("HATA: 'picamera2' bulunamadı. Lütfen kurun: sudo apt install python3-libcamera")
    sys.exit(1)

try:
    from ultralytics import YOLO
except ImportError:
    print("HATA: 'ultralytics' bulunamadı. Lütfen kurun: pip install ultralytics")
    sys.exit(1)

# --- Mesafe Ölçümü İçin Sabitler ---
# Bilinen nesne genişlikleri (cm cinsinden - Ortalama değerler)
KNOWN_WIDTHS = {
    'person': 45.0,  # Ortalama omuz genişliği
    'car': 180.0,  # Ortalama araba genişliği
    'cell phone': 7.5,
    'bottle': 7.0,
    'cup': 8.0,
    'monitor': 50.0,
    'laptop': 35.0,
    'mouse': 6.0,
    'keyboard': 45.0,
    'book': 15.0,
    'chair': 50.0,
    'cat': 15.0,  # Ortalama kedi göğüs genişliği
    'dog': 20.0,  # Ortalama köpek göğüs genişliği
}

# Kameranın odak uzaklığı (Piksel cinsinden, kalibre edilebilir)
# Formül: F = (Piksel Genişliği x Bilinen Mesafe) / Bilinen Genişlik
# Varsayılan olarak 650px (VGA/HD için yaklaşık değer)
FOCAL_LENGTH = 650.0


def calculate_distance(pixel_width, label):
    """
    Nesne etiketine ve piksel genişliğine göre cm cinsinden mesafe hesaplar.
    """
    real_width = KNOWN_WIDTHS.get(label)
    if real_width and pixel_width > 0:
        # Mesafe Formülü: D = (W x F) / P
        distance = (real_width * FOCAL_LENGTH) / pixel_width
        return distance
    return None


def main():
    # --- Argümanları Parse Et (Web Arayüzünden Gelen Veriler) ---
    parser = argparse.ArgumentParser(description="YOLOv8 Object Detection")

    # Varsayılan değerler (Config dosyası yoksa veya parametre gelmezse)
    parser.add_argument("--width", type=int, default=640, help="Kamera genişliği")
    parser.add_argument("--height", type=int, default=480, help="Kamera yüksekliği")
    parser.add_argument("--model", type=str, default="models/yolov8s.pt", help="Model dosya yolu")
    parser.add_argument("--conf", type=float, default=0.5, help="Güven eşiği (0.1 - 1.0)")

    args = parser.parse_args()

    DISPLAY_WIDTH = args.width
    DISPLAY_HEIGHT = args.height
    MODEL_PATH = args.model
    CONFIDENCE = args.conf

    print("=" * 50)
    print(f"YOLOv8 Harici Pencere Başlatılıyor")
    print(f"Çözünürlük: {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}")
    print(f"Model: {MODEL_PATH}")
    print(f"Güven Skoru: {CONFIDENCE}")
    print("=" * 50)

    # 1. Modeli Yükle
    # Yol kontrolü
    if not os.path.exists(MODEL_PATH):
        print(f"UYARI: Model dosyası '{MODEL_PATH}' bulunamadı.")
        print("Ultralytics otomatik indirme yapabilir veya yol hatalı olabilir.")
        # Model klasörünü oluştur (indirme için)
        dir_name = os.path.dirname(MODEL_PATH)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    try:
        print("Model yükleniyor (İlk çalıştırmada yavaş olabilir)...")
        model = YOLO(MODEL_PATH)
        print(f"✓ Model başarıyla yüklendi: {MODEL_PATH}")
    except Exception as e:
        print(f"KRİTİK HATA: Model yüklenemedi: {e}")
        print("Lütfen 'models' klasöründe model dosyasının olduğundan emin olun.")
        sys.exit(1)

    # 2. Kamerayı Başlat (Picamera2)
    print(f"Kamera {DISPLAY_WIDTH}x{DISPLAY_HEIGHT} modunda başlatılıyor...")
    try:
        picam2 = Picamera2()
        # Performans için XRGB8888 formatı (Pencere gösterimi için optimize)
        # Bu format, RGB888'e göre donanım hızlandırmasıyla daha uyumludur.
        config = picam2.create_preview_configuration(
            main={"size": (DISPLAY_WIDTH, DISPLAY_HEIGHT), "format": "XRGB8888"}
        )
        picam2.configure(config)
        picam2.start()
        time.sleep(2)  # Sensör ısınma süresi
        print("✓ Kamera ve Akış hazır!")
    except Exception as e:
        print(f"HATA: Kamera açılamadı (Başka bir uygulama kullanıyor olabilir): {e}")
        sys.exit(1)

    fps_start_time = time.time()
    fps_counter = 0
    fps = 0

    print("=" * 50)
    print("Pencere açıldı. Çıkmak için 'q' tuşuna basın.")
    print("=" * 50)

    try:
        while True:
            # --- Görüntü Alma ---
            try:
                # capture_array: Numpy array olarak döner (Hızlı)
                frame_rgb = picam2.capture_array()
            except Exception as e:
                print(f"Kare alma hatası: {e}")
                break

            # XRGB8888 formatı 4 kanallıdır (A, R, G, B). Alpha kanalını atıyoruz.
            # Model RGB/BGR bekler (Ultralytics otomatik dönüştürür ama kanal sayısı 3 olmalı)
            if frame_rgb.shape[2] == 4:
                frame_rgb = frame_rgb[:, :, :3]

            # --- AI Tahmini (YOLO) ---
            # verbose=False -> Konsola sürekli yazı basmaz
            # imgsz -> Modelin giriş boyutu (Performans için önemli)
            results = model.predict(
                source=frame_rgb,
                conf=CONFIDENCE,
                verbose=False,
                imgsz=(DISPLAY_HEIGHT, DISPLAY_WIDTH)
            )

            # --- Sonuçları Çizme (Temel) ---
            # plot() fonksiyonu BGR formatında hazır bir resim döndürür (OpenCV dostu)
            annotated_frame = results[0].plot()

            # --- Mesafe Bilgisi Ekleme (Custom) ---
            for r in results:
                boxes = r.boxes
                for box in boxes:
                    # Koordinatları al
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    w = x2 - x1

                    # Sınıf bilgisi
                    cls = int(box.cls[0])
                    label = model.names[cls]

                    # Mesafe hesapla
                    dist = calculate_distance(w, label)

                    if dist:
                        dist_text = f"{dist:.1f}cm"

                        # Mesafe yazısı için boyut hesapla
                        (tw, th), _ = cv2.getTextSize(dist_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)

                        # Kırmızı arka planlı kutu (YOLO etiketinin hemen altına)
                        cv2.rectangle(annotated_frame, (x1, y1), (x1 + tw, y1 + 20), (0, 0, 255), -1)

                        # Beyaz yazı
                        cv2.putText(annotated_frame, dist_text, (x1, y1 + 15),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            # --- FPS Hesaplama ---
            fps_counter += 1
            if (time.time() - fps_start_time) >= 1.0:
                fps = fps_counter / (time.time() - fps_start_time)
                fps_start_time = time.time()
                fps_counter = 0

            # --- Bilgileri Ekrana Yazma ---
            # FPS Bilgisi
            cv2.putText(annotated_frame, f"FPS: {fps:.1f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Model Adı (Sol Alt)
            model_name = os.path.basename(MODEL_PATH)
            cv2.putText(annotated_frame, f"Model: {model_name} | Conf: {CONFIDENCE}", (10, DISPLAY_HEIGHT - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

            # --- Görüntüleme ---
            cv2.imshow("Raspberry Pi 5 - YOLO AI Detection", annotated_frame)

            # --- Klavye Kontrolü ---
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("Kullanıcı tarafından çıkış yapıldı.")
                break
            elif key == ord('s'):
                filename = f"snap_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                cv2.imwrite(filename, annotated_frame)
                print(f"Ekran görüntüsü kaydedildi: {filename}")

    except KeyboardInterrupt:
        print("\nDurduruluyor...")
    except Exception as e:
        print(f"\nBeklenmeyen hata oluştu: {e}")
    finally:
        # Temizlik
        try:
            picam2.stop()
            picam2.close()
        except:
            pass
        cv2.destroyAllWindows()
        print("Sistem kapatıldı.")


if __name__ == '__main__':
    main()