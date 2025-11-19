import cv2
import time
import logging
import numpy as np
import sys
import atexit

# --- Proje Modüllerini Import Et ---
try:
    # Bu betiğin, 'dash_framework' adlı ana Django uygulamanızın
    # bir üst dizininde olduğunu veya 'dash_framework' paketinin
    # Python path'inizde olduğunu varsayıyoruz.

    # Eğer 'No module named dash_framework' hatası alırsanız,
    # bu script'i projenizin ana dizinine (manage.py'nin yanına) taşıyın
    # ve import yollarını 'from dash_framework.config import ...' yerine
    # 'from config import ...' vb. olarak güncelleyin.

    from dash_framework.config import CameraConfig, AIConfig
    from dash_framework.hardware_manager import hardware_manager
    from dash_framework.ai_vision import ai_vision_manager

except ImportError:
    print("HATA: Proje modülleri (config, hardware_manager, ai_vision) bulunamadı.")
    print("Lütfen bu script'i doğru dizinde çalıştırdığınızdan veya")
    print("import yollarını (örn: 'dash_framework.') düzelttiğinizden emin olun.")
    sys.exit(1)

# --- Logger Ayarları ---
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s')
logger = logging.getLogger("AI_WEBCAM_STREAM")


# --- Ana Fonksiyonlar ---

def initialize_systems():
    """Donanım ve AI modüllerini başlatır."""
    logger.info("Donanım başlatılıyor...")

    # Sadece kamerayı başlatmak yeterli
    # (v3.20 mimarisi, Full FOV modunda başlar)
    cam_success = hardware_manager.initialize_camera()

    if not cam_success:
        logger.warning("⚠️ Kamera başlatılamadı! Simülasyon modu aktif (eğer donanım yoksa).")
        # hardware_manager zaten simülasyonu kendi içinde hallediyor.

    logger.info("AI modülleri başlatılıyor (ai_vision_manager)...")

    # AIConfig'e göre modülleri başlat
    if AIConfig.ENABLE_YOLO:
        logger.info(f"YOLO modeli yükleniyor ({AIConfig.YOLO_MODEL})...")
        ai_vision_manager.initialize_module('yolo',
                                            confidence=AIConfig.YOLO_CONFIDENCE,
                                            iou=AIConfig.YOLO_IOU)

    if AIConfig.ENABLE_FACE_DETECTION:
        logger.info("Yüz tanıma modeli (Haar) yükleniyor...")
        ai_vision_manager.initialize_module('face')

    if AIConfig.ENABLE_MOTION_DETECTION:
        logger.info("Hareket tespiti modülü yükleniyor...")
        motion_settings = AIConfig.get_motion_settings()
        ai_vision_manager.initialize_module('motion',
                                            min_area=motion_settings['min_area'],
                                            threshold=motion_settings['threshold'])

    if AIConfig.ENABLE_QR_BARCODE:
        logger.info("QR/Barkod okuyucu (Pyzbar) yükleniyor...")
        ai_vision_manager.initialize_module('qr')

    if AIConfig.ENABLE_EDGE_DETECTION:
        logger.info("Kenar tespiti (Canny) yükleniyor...")
        ai_vision_manager.initialize_module('edges')

    status = ai_vision_manager.get_status()
    logger.info(f"✓ Başlatma tamamlandı. Aktif AI modülleri: {status['enabled_modules']}")
    return cam_success


def run_ai_stream():
    """Ana AI akış döngüsü."""
    logger.info("AI Akışı başlatıldı. Çıkmak için 'q' tuşuna basın.")

    # Hangi AI modüllerinin çalışacağını seç
    # Bu listeyi değiştirerek performansı etkileyebilirsiniz
    active_modules = [
        module for module, enabled in ai_vision_manager.get_status()['enabled_modules'].items() if enabled
    ]

    if not active_modules:
        logger.warning("Hiçbir AI modülü aktif değil! Sadece kamera görüntüsü gösterilecek.")

    # Canlı akış için kamera ayarları (v3.20 mimarisi için)
    # Bu ayarlar döngü boyunca sabit kalacak
    stream_settings = {
        'resolution': CameraConfig.HD_READY_RESOLUTION,  # 1280x720
        'framerate': 30.0,
        'apply_lens_correction': False,  # Akışta hızı önceliklendir
        'ae_enable': True,
        'awb_enable': True,
        # Diğer ayarları (pozlama, parlaklık vb.) varsayılan (None) bırak
        # ki hardware_manager cache'deki varsayılanları kullansın.
    }

    prev_time = time.time()
    frame_count = 0
    display_fps = 0.0

    while True:
        try:
            # 1. Frame'i al
            # hardware_manager v3.20, ayarlar değişmediyse
            # yeniden yapılandırma yapmaz, bu yüzden bu çağrı hızlıdır.
            frame = hardware_manager.capture_frame(**stream_settings)

            if frame is None:
                logger.warning("Kare alınamadı (None). 0.1sn bekleniyor.")
                time.sleep(0.1)
                continue

            # 2. Frame'i AI ile işle
            # (ai_vision_manager, ai_vision.py dosyanızdan gelir)
            processed_frame, results = ai_vision_manager.process_frame(
                frame,
                modules=active_modules,
                draw_results=True  # Çizimleri AI modülü yapsın
            )

            # 3. Ek Bilgileri (FPS, Stats) Ekle
            current_time = time.time()
            frame_count += 1
            elapsed = current_time - prev_time
            if elapsed >= 1.0:
                display_fps = frame_count / elapsed
                frame_count = 0
                prev_time = current_time

            # İstatistikleri al
            stats = results.get('stats', {})
            detections = results.get('detections', [])

            info_text_fps = f"FPS: {display_fps:.2f}"
            info_text_stats = (
                f"Detections: {len(detections)} ("
                f"YOLO: {stats.get('yolo_objects', 0)}, "
                f"Face: {stats.get('faces', 0)}, "
                f"QR: {stats.get('qr_codes', 0)}, "
                f"Motion: {stats.get('motion_regions', 0)})"
            )

            # Bilgileri frame'e yaz
            # Okunabilirlik için siyah bir arka plan ekle
            cv2.rectangle(processed_frame, (0, 0), (750, 60), (0, 0, 0), -1)
            cv2.putText(processed_frame, info_text_fps, (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(processed_frame, info_text_stats, (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # 4. Görüntüyü göster
            cv2.imshow("AI Webcam Akisi (Cikis icin 'q')", processed_frame)

            # 5. Çıkış kontrolü
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("Çıkış tuşuna basıldı ('q').")
                break

        except Exception as e:
            logger.error(f"Ana döngü hatası: {e}", exc_info=True)
            break
        except KeyboardInterrupt:
            logger.info("Kullanıcı tarafından durduruldu (Ctrl+C).")
            break


def cleanup_systems():
    """Tüm sistemleri kapatır."""
    logger.info("Sistemler temizleniyor...")
    cv2.destroyAllWindows()
    # Bu, kamerayı, motoru ve sensörü güvenle kapatır
    hardware_manager.cleanup_all()
    logger.info("Temizlik tamamlandı. Çıkılıyor.")


# --- Ana Çalıştırma Bloğu ---
if __name__ == "__main__":

    # atexit.register, script normal sonlansa da
    # hata ile çökse de cleanup_systems'in çalışmasını garantiler.
    atexit.register(cleanup_systems)

    try:
        initialize_systems()
        run_ai_stream()

    except Exception as e:
        logger.critical(f"Beklenmeyen kritik hata: {e}", exc_info=True)
    except KeyboardInterrupt:
        logger.info("Ana program (Ctrl+C) ile sonlandırıldı.")
    finally:
        logger.info("AI Akış programı sonlanıyor.")