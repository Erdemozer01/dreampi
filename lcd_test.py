# lcd_test.py

import time
from RPLCD.i2c import CharLCD
import smbus

# Lütfen bu ayarların LCD'niz için doğru olduğunu kontrol edin
LCD_I2C_ADDRESS = 0x27
LCD_PORT_EXPANDER = 'PCF8574'
I2C_PORT = 1
LCD_COLS = 16
LCD_ROWS = 2

print(">>> LCD Ekran Testi Başlatılıyor...")

# Önce I2C adresini kontrol edelim
try:
    bus = smbus.SMBus(I2C_PORT)
    bus.read_byte(LCD_I2C_ADDRESS)
    print(f">>> Adres {hex(LCD_I2C_ADDRESS)} üzerinde bir I2C cihazı bulundu. Teste devam ediliyor...")
except Exception as e:
    print(f"\n!!! HATA: Adres {hex(LCD_I2C_ADDRESS)} üzerinde cihaz bulunamadı veya I2C hatası!")
    print("!!! Lütfen 'sudo i2cdetect -y 1' komutu ile adresi doğrulayın.")
    print(f"!!! Sistem Hatası: {e}")
    exit()  # Testi sonlandır

# Cihaz bulunduysa, LCD'yi başlatmayı dene
lcd = None
try:
    lcd = CharLCD(i2c_expander=LCD_PORT_EXPANDER,
                  address=LCD_I2C_ADDRESS,
                  port=I2C_PORT,
                  cols=LCD_COLS,
                  rows=LCD_ROWS,
                  auto_linebreaks=False)

    print(">>> LCD başarıyla başlatıldı!")
    lcd.clear()

    lcd.write_string('LCD Testi')
    lcd.cursor_pos = (1, 0)  # Alt satıra geç
    lcd.write_string('Basarili!')

    print(">>> Ekrana 'LCD Testi Basarili!' yazıldı. 5 saniye bekleniyor...")
    time.sleep(5)
    print(">>> Test tamamlandı.")

except Exception as e:
    print(f"\n!!! HATA: LCD başlatılırken veya yazılırken sorun oluştu: {e}")

finally:
    if lcd:
        print(">>> LCD temizleniyor.")
        lcd.clear()