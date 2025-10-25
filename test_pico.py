#!/usr/bin/env python3
"""Basit Pico Bağlantı Testi"""

import serial
import time

PORT = '/dev/ttyACM0'
BAUD = 115200

print("🔍 Pico Bağlantı Testi Başlatılıyor...")
print(f"Port: {PORT}")
print(f"Baud: {BAUD}")
print("-" * 50)

try:
    # Seri port aç
    print("\n1. Port açılıyor...")
    ser = serial.Serial(PORT, BAUD, timeout=2)
    print("   ✓ Port açıldı")

    # 3 saniye bekle (Pico başlangıç mesajı için)
    print("\n2. Pico başlangıç mesajı bekleniyor (3 saniye)...")
    time.sleep(3)

    # Bekleyen mesajları oku
    print("\n3. Bekleyen mesajlar kontrol ediliyor...")
    messages_found = False

    while ser.in_waiting > 0:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"   📨 PICO: {line}")
                messages_found = True
        except Exception as e:
            print(f"   ⚠️ Okuma hatası: {e}")

    if not messages_found:
        print("   ⚠️ Hiç mesaj yok - Pico çalışmıyor olabilir")

    # Test komutu gönder
    print("\n4. Test komutu gönderiliyor: STOP_DRIVE")
    ser.reset_input_buffer()
    ser.write(b"STOP_DRIVE\n")
    time.sleep(0.5)

    # Yanıt kontrol et
    if ser.in_waiting > 0:
        response = ser.readline().decode('utf-8', errors='ignore').strip()
        print(f"   ← Yanıt: {response}")

        if response == "ACK":
            print("   ✓ ACK alındı, DONE bekleniyor...")
            time.sleep(0.5)
            if ser.in_waiting > 0:
                response2 = ser.readline().decode('utf-8', errors='ignore').strip()
                print(f"   ← Yanıt2: {response2}")
                if response2 == "DONE":
                    print("\n✅ PİCO ÇALIŞIYOR VE DOĞRU YANIT VERİYOR!")
                else:
                    print(f"\n⚠️ DONE yerine '{response2}' alındı")
        else:
            print(f"\n⚠️ ACK yerine '{response}' alındı")
    else:
        print("   ❌ Hiç yanıt gelmedi - Pico çalışmıyor!")

    ser.close()
    print("\n" + "=" * 50)

except serial.SerialException as e:
    print(f"\n❌ Seri Port Hatası: {e}")
    print("\nÇözüm:")
    print("  1. Pico USB kablosunu çıkarıp takın")
    print("  2. Pico'da main.py dosyasının olduğundan emin olun")
    print("  3. Thonny ile Pico'ya bağlanıp kodu yükleyin")

except Exception as e:
    print(f"\n❌ Hata: {e}")
    import traceback

    traceback.print_exc()

print("\n✅ Test tamamlandı")