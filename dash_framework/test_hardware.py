# test_hardware.py - Donanım Bileşenlerini Test Et
# Raspberry Pi üzerinde çalıştırın: python test_hardware.py

import sys
import time
import logging

# Logging ayarla
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

print("="*60)
print("DREAM PI DONANIM TEST SCRİPTİ")
print("="*60)
print()

# Config ve hardware manager import
try:
    from config import CameraConfig, MotorConfig, SensorConfig
    from hardware_manager import hardware_manager, CAMERA_AVAILABLE, GPIO_AVAILABLE
    print("✓ Modüller başarıyla import edildi")
except ImportError as e:
    print(f"✗ Modül import hatası: {e}")
    print("Lütfen tüm dosyaların doğru konumda olduğundan emin olun.")
    sys.exit(1)

print()
print("-"*60)
print("DONANIM KULLANILIRLIK KONTROLÜ")
print("-"*60)

print(f"Kamera Kütüphanesi (picamera2): {'✓ Mevcut' if CAMERA_AVAILABLE else '✗ Bulunamadı'}")
print(f"GPIO Kütüphanesi (gpiozero): {'✓ Mevcut' if GPIO_AVAILABLE else '✗ Bulunamadı'}")
print()

if not CAMERA_AVAILABLE and not GPIO_AVAILABLE:
    print("⚠️  UYARI: Hiçbir donanım kütüphanesi bulunamadı!")
    print("Bu normal bir bilgisayarda çalıştırıyorsanız normaldir.")
    print("Raspberry Pi'de çalıştırıyorsanız kütüphaneleri yükleyin:")
    print("  pip install picamera2 gpiozero")
    print()

# Test menüsü
def show_menu():
    print("-"*60)
    print("TEST MENÜSÜ")
    print("-"*60)
    print("1. Tüm Donanımı Başlat")
    print("2. Kamera Test")
    print("3. Motor Test")
    print("4. Sensör Test")
    print("5. Tam Sistem Testi (Otomatik)")
    print("0. Çıkış")
    print("-"*60)

def test_camera():
    """Kamera testini çalıştır"""
    print("\n[KAMERA TESTİ]")
    print("Kamera başlatılıyor...")

    success = hardware_manager.initialize_camera()
    if not success:
        print("✗ Kamera başlatılamadı")
        return False

    print("✓ Kamera başlatıldı")
    print("3 fotoğraf çekiliyor...")

    for i in range(3):
        time.sleep(1)
        frame = hardware_manager.capture_frame()
        if frame is not None:
            print(f"  ✓ Fotoğraf {i+1}: {frame.shape}")
        else:
            print(f"  ✗ Fotoğraf {i+1}: Başarısız")

    print("✓ Kamera testi tamamlandı")
    return True

def test_motor():
    """Motor testini çalıştır"""
    print("\n[MOTOR TESTİ]")
    print("Motor başlatılıyor...")

    success = hardware_manager.initialize_motor()
    if not success:
        print("✗ Motor başlatılamadı")
        return False

    print("✓ Motor başlatıldı")
    print("Motor hareketleri test ediliyor...")

    test_angles = [0, 45, 90, 45, 0, -45, -90, -45, 0]

    for angle in test_angles:
        print(f"  → {angle}° pozisyonuna gidiliyor...")
        hardware_manager.move_to_angle(angle)
        current = hardware_manager.get_motor_angle()
        print(f"    Mevcut pozisyon: {current:.1f}°")
        time.sleep(1)

    print("✓ Motor testi tamamlandı")
    return True

def test_sensor():
    """Sensör testini çalıştır"""
    print("\n[SENSÖR TESTİ]")
    print("Sensör başlatılıyor...")

    success = hardware_manager.initialize_sensor()
    if not success:
        print("✗ Sensör başlatılamadı")
        return False

    print("✓ Sensör başlatıldı")
    print("10 mesafe okuması yapılıyor...")

    readings = []
    for i in range(10):
        time.sleep(0.5)
        distance = hardware_manager.read_distance()
        readings.append(distance)

        if distance is not None:
            print(f"  Okuma {i+1}: {distance:.1f} cm")
        else:
            print(f"  Okuma {i+1}: Hata")

    # İstatistikler
    valid_readings = [r for r in readings if r is not None]
    if valid_readings:
        avg = sum(valid_readings) / len(valid_readings)
        print(f"\nOrtalama mesafe: {avg:.1f} cm")
        print(f"Başarılı okuma: {len(valid_readings)}/10")

    print("✓ Sensör testi tamamlandı")
    return True

def full_system_test():
    """Tam sistem testini otomatik çalıştır"""
    print("\n" + "="*60)
    print("TAM SİSTEM TESTİ BAŞLADI")
    print("="*60)

    results = {
        'camera': False,
        'motor': False,
        'sensor': False
    }

    # Tüm donanımı başlat
    print("\n1. Tüm donanım başlatılıyor...")
    init_results = hardware_manager.initialize_all()
    print(f"Sonuçlar: {init_results}")

    # Kamera testi
    if init_results['camera']:
        print("\n2. Kamera testi...")
        results['camera'] = test_camera()

    # Motor testi
    if init_results['motor']:
        print("\n3. Motor testi...")
        results['motor'] = test_motor()

    # Sensör testi
    if init_results['sensor']:
        print("\n4. Sensör testi...")
        results['sensor'] = test_sensor()

    # Entegre test (Motor + Sensör)
    if results['motor'] and results['sensor']:
        print("\n5. Entegre test (Motor + Sensör)...")
        print("Motor ile tarama simülasyonu yapılıyor...")

        scan_points = []
        for angle in range(-90, 91, 30):
            hardware_manager.move_to_angle(angle)
            time.sleep(0.5)
            distance = hardware_manager.read_distance()

            if distance:
                scan_points.append({'angle': angle, 'distance': distance})
                print(f"  Açı: {angle}°, Mesafe: {distance:.1f} cm")

        print(f"✓ {len(scan_points)} tarama noktası toplandı")

    # Sonuçlar
    print("\n" + "="*60)
    print("TEST SONUÇLARI")
    print("="*60)
    print(f"Kamera: {'✓ BAŞARILI' if results['camera'] else '✗ BAŞARISIZ'}")
    print(f"Motor: {'✓ BAŞARILI' if results['motor'] else '✗ BAŞARISIZ'}")
    print(f"Sensör: {'✓ BAŞARILI' if results['sensor'] else '✗ BAŞARISIZ'}")

    total = sum(results.values())
    print(f"\nToplam: {total}/3 test başarılı")
    print("="*60)

# Ana program
def main():
    try:
        while True:
            show_menu()
            choice = input("\nSeçiminiz (0-5): ").strip()

            if choice == '0':
                print("\nÇıkış yapılıyor...")
                break

            elif choice == '1':
                print("\nTüm donanım başlatılıyor...")
                results = hardware_manager.initialize_all()
                print(f"Sonuçlar: {results}")

            elif choice == '2':
                test_camera()

            elif choice == '3':
                test_motor()

            elif choice == '4':
                test_sensor()

            elif choice == '5':
                full_system_test()

            else:
                print("✗ Geçersiz seçim!")

            input("\nDevam etmek için Enter'a basın...")

    except KeyboardInterrupt:
        print("\n\nTest kesildi (Ctrl+C)")

    finally:
        print("\nTemizlik yapılıyor...")
        hardware_manager.cleanup_all()
        print("✓ Temizlik tamamlandı")
        print("Görüşmek üzere!")

if __name__ == '__main__':
    main()