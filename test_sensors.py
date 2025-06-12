import time

# --- Modern ve Stabil Kütüphaneler ---

# gpiozero'nun pin kontrolü için RPi.GPIO yerine pigpio'yu kullanmasını sağlar.
# Bu satır, kodun daha stabil çalışmasını sağlayan modern bir yaklaşımdır.
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero import Device, DistanceSensor

# LCD kontrolü için uzman ve pratik kütüphane
from RPLCD.i2c import CharLCD

# --- Cihaz Pin Fabrikasını Ayarla (Kodun En Başına Eklenmeli) ---
# Bu tek satır, tüm gpiozero cihazlarının pigpio altyapısını kullanmasını sağlar.
Device.pin_factory = PiGPIOFactory(host="192.168.229.27:8000")

# --- Donanım Ayarları ---
# Lütfen pin ve adres bilgilerini kendi bağlantınıza göre doğrulayın.
TRIG_PIN = 23
ECHO_PIN = 24
LCD_I2C_ADDR = 0x27  # Adresi `sudo i2cdetect -y 1` komutu ile kontrol edebilirsiniz.
LCD_WIDTH = 16
LCD_HEIGHT = 2

# LCD ve sensör nesnelerini 'try' bloğunun dışında tanımlayarak 'finally' içinde erişilebilir yapıyoruz.
lcd = None

print("Mesafe ölçer projesi başlatılıyor...")
print("GPIO Kontrolcüsü: pigpio")
print("LCD Kütüphanesi: RPLCD")

try:
    # --- Cihazları Başlat ---

    # 1. LCD'yi RPLCD kütüphanesi ile basitçe tanımla
    lcd = CharLCD(i2c_expander='PCF8574', address=LCD_I2C_ADDR, port=1,
                  cols=LCD_WIDTH, rows=LCD_HEIGHT, compat_mode=True)

    # 2. Ultrasonik sensörü gpiozero ile basitçe tanımla
    # queue_len, daha stabil okumalar için birkaç ölçümün ortalamasını alır.
    sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, queue_len=5)

    # Başlangıç ekranı
    lcd.clear()
    lcd.write_string("Sistem Hazir...")
    lcd.cursor_pos = (1, 0)  # İmleci ikinci satıra al
    lcd.write_string("Olcum basliyor")
    print("Sistem hazır. 2 saniye içinde ölçüm başlayacak...")
    time.sleep(2)
    lcd.clear()

    # --- Ana Döngü ---
    while True:
        # Mesafeyi santimetre cinsinden oku
        distance_cm = sensor.distance * 100

        # Okunan değeri konsola yazdır
        print(f"Mesafe: {distance_cm:.2f} cm")

        # Okunan değeri LCD ekrana yazdır
        # İlk satır
        lcd.cursor_pos = (0, 0)
        lcd.write_string(f"Mesafe:")

        # İkinci satır
        lcd.cursor_pos = (1, 0)
        mesafe_metni = f"{distance_cm:.2f} cm"
        # Metni ekran genişliğine göre sola yaslayarak eski verilerden kalan artıkları temizle
        lcd.write_string(mesafe_metni.ljust(LCD_WIDTH))

        # Yeni ölçüm için 1 saniye bekle
        time.sleep(1)

except KeyboardInterrupt:
    # Kullanıcı Ctrl+C ile programı durdurduğunda
    print("\nProgram kullanıcı tarafından sonlandırıldı.")

except Exception as e:
    # Diğer tüm hatalar için
    print(f"\nBeklenmedik bir hata oluştu: {e}")

finally:
    # Program ne şekilde biterse bitsin bu blok çalışır
    if lcd:
        lcd.clear()
        lcd.backlight_enabled = False  # LCD'nin arka ışığını kapat
        print("LCD ekran temizlendi ve kapatıldı.")

    # gpiozero kaynakları otomatik olarak temizler, ek bir komuta gerek yoktur.
    print("Test başarıyla sonlandırıldı.")