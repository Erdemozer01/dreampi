# main.py - Raspberry Pi Pico W (Kas) Kodu - İYİLEŞTİRİLMİŞ
# Pi 5 (Beyin) tarafından gönderilen seri komutları alır ve donanımı kontrol eder.
# ACK+DONE protokolü ile güvenli iletişim

from machine import Pin, UART
import utime
import sys


# --- TMC2209 UART Kontrol Sınıfı ---
class TMC2209_UART:
    """TMC2209 stepper motor sürücü kontrolü"""

    def __init__(self, uart_id, baudrate=115200, tx_pin_id=None, rx_pin_id=None, rsense_ohm=0.11):
        if tx_pin_id is not None and rx_pin_id is not None:
            self.uart = UART(uart_id, baudrate=baudrate, tx=Pin(tx_pin_id), rx=Pin(rx_pin_id))
        else:
            self.uart = UART(uart_id, baudrate=baudrate)

        self.WRITE_ACCESS = 0x80
        self.READ_ACCESS = 0x00

        # Akım ölçekleme faktörü
        vfs = 0.325
        self.current_scaling_factor = (vfs / (rsense_ohm + 0.02)) * (1 / 1.4141) * 1000 / 32

    def _calculate_crc(self, datagram, datagram_length):
        """CRC8 hesaplama"""
        crc = 0
        for i in range(datagram_length):
            current_byte = datagram[i]
            for _ in range(8):
                if (crc >> 7) ^ (current_byte & 0x01):
                    crc = (crc << 1) ^ 0x07
                else:
                    crc = crc << 1
                current_byte = current_byte >> 1
        return crc & 0xFF

    def _send_datagram(self, address, value, access_type):
        """TMC2209'a datagram gönder"""
        datagram = bytearray(4 if access_type == self.READ_ACCESS else 8)
        datagram[0] = 0x05
        datagram[1] = 0x00
        datagram[2] = access_type | address

        if access_type == self.WRITE_ACCESS:
            datagram[3] = (value >> 24) & 0xFF
            datagram[4] = (value >> 16) & 0xFF
            datagram[5] = (value >> 8) & 0xFF
            datagram[6] = value & 0xFF
            datagram[7] = self._calculate_crc(datagram, 7)
        else:
            datagram[3] = self._calculate_crc(datagram, 3)

        self.uart.write(datagram)
        utime.sleep_ms(30)

    def write_register(self, address, value):
        """Register'a yaz"""
        self._send_datagram(address, value, self.WRITE_ACCESS)

    def read_register(self, address):
        """Register'dan oku"""
        while self.uart.any():
            self.uart.read()

        self._send_datagram(address, 0, self.READ_ACCESS)
        response = self.uart.read(8)

        if response and len(response) == 8:
            crc_received = response[7]
            crc_calculated = self._calculate_crc(response, 7)
            if crc_received == crc_calculated:
                return (response[3] << 24) | (response[4] << 16) | (response[5] << 8) | response[6]
        return None

    def set_gconf(self, uart_comm=True):
        """Genel konfigürasyon"""
        value = 0
        if uart_comm:
            value |= (1 << 2) | (1 << 3)
        self.write_register(0x00, value)

    def set_chopper_config(self, microsteps=16, stealth_chop=True, hybrid_threshold=100):
        """Chopper ve mikrostep ayarları"""
        mres_map = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}
        mres = mres_map.get(microsteps, 4)
        toff, hstrt, hend, tbl = 3, 4, 1, 2

        value = (mres << 24) | (tbl << 15) | (hend << 7) | (hstrt << 4) | (toff << 0)
        if not stealth_chop:
            value |= (1 << 17)

        self.write_register(0x6C, value)
        self.write_register(0x70, hybrid_threshold)

    def set_current(self, run_current_ma, hold_current_ma=None, hold_delay=10):
        """Motor akımlarını ayarla"""
        if hold_current_ma is None:
            hold_current_ma = run_current_ma

        irun = max(0, min(31, int(run_current_ma / self.current_scaling_factor - 1)))
        ihold = max(0, min(31, int(hold_current_ma / self.current_scaling_factor - 1)))
        iholddelay = max(0, min(15, hold_delay))

        value = (iholddelay << 16) | (irun << 8) | (ihold << 0)
        self.write_register(0x10, value)

    def get_status_flags(self):
        """Sürücü durum bayraklarını oku"""
        gstat_val = self.read_register(0x01)
        if gstat_val is not None:
            if gstat_val == 0:
                print("  ✓ Durum: Normal (GSTAT=0)")
            else:
                if gstat_val & 1:
                    print("  ⚠ Sürücü sıfırlandı (reset flag)")
                if gstat_val & 2:
                    print("  ❌ Sürücü hatası (aşırı sıcaklık/kısa devre)")
                if gstat_val & 4:
                    print("  ❌ Düşük voltaj hatası")
        else:
            print("  ❌ GSTAT okunamadı - Bağlantı sorunu")
        return gstat_val

    def get_version(self):
        """Sürücü versiyonunu oku"""
        ioin_val = self.read_register(0x06)
        if ioin_val is not None:
            version = (ioin_val >> 24) & 0xFF
            print(f"  ℹ Sürücü Versiyonu: 0x{version:X}")
            return version
        else:
            print("  ❌ Versiyon okunamadı")
            return None


# ============================================================================
# KONFİGÜRASYON
# ============================================================================

# --- SÜRÜŞ MOTORLARI (TMC2209 + NEMA 17) ---
LEFT_STEP_PIN = 2
LEFT_DIR_PIN = 3
LEFT_UART_TX = 4
LEFT_UART_RX = 5

RIGHT_STEP_PIN = 14
RIGHT_DIR_PIN = 15
RIGHT_UART_TX = 12
RIGHT_UART_RX = 13

ENABLE_PIN = 22  # Ortak Enable

# Motor Parametreleri
MOTOR_RUN_CURRENT_mA = 2000
MOTOR_HOLD_CURRENT_mA = 850
MICROSTEPS = 16
RSENSE_OHM = 0.1
HYBRID_MODE_SPEED_THRESHOLD = 100

# Hız Parametreleri (mikrosaniye)
DEFAULT_SPEED_DELAY_US = 500  # İleri/Geri hızı (düşük = hızlı)
DEFAULT_TURN_DELAY_US = 1000  # Dönüş hızı (düşük = hızlı)

# --- GLOBAL DEĞİŞKENLER ---
led = None
left_step = None
left_dir = None
right_step = None
right_dir = None
enable_motors_pin = None
left_driver = None
right_driver = None

# Sürekli hareket için
continuous_movement = False
movement_thread = None
current_left_dir = 1
current_right_dir = 1
current_delay = DEFAULT_SPEED_DELAY_US


# ============================================================================
# DONANIM BAŞLATMA
# ============================================================================

def setup_hardware():
    """Tüm donanımı başlat"""
    global led, left_step, left_dir, right_step, right_dir
    global enable_motors_pin, left_driver, right_driver

    print("\n" + "=" * 60)
    print("🤖 PICO (KAS) DONANIM BAŞLATILIYOR")
    print("=" * 60)

    try:
        # LED (debug için)
        try:
            led = Pin("LED", Pin.OUT)
            led.on()
            print("✓ LED hazır")
        except:
            print("⚠ LED bulunamadı (Pico W değil)")

        # Sürüş motor pinleri
        left_step = Pin(LEFT_STEP_PIN, Pin.OUT)
        left_dir = Pin(LEFT_DIR_PIN, Pin.OUT)
        right_step = Pin(RIGHT_STEP_PIN, Pin.OUT)
        right_dir = Pin(RIGHT_DIR_PIN, Pin.OUT)
        enable_motors_pin = Pin(ENABLE_PIN, Pin.OUT)
        print("✓ Motor pinleri hazır")

        # TMC2209 sürücüleri
        print("\n--- TMC2209 Sürücü Konfigürasyonu ---")
        left_driver = TMC2209_UART(
            uart_id=1,
            tx_pin_id=LEFT_UART_TX,
            rx_pin_id=LEFT_UART_RX,
            rsense_ohm=RSENSE_OHM
        )

        right_driver = TMC2209_UART(
            uart_id=0,
            tx_pin_id=RIGHT_UART_TX,
            rx_pin_id=RIGHT_UART_RX,
            rsense_ohm=RSENSE_OHM
        )

        # Sürücüleri yapılandır
        for name, driver in [("Sol", left_driver), ("Sağ", right_driver)]:
            print(f"\n{name} Sürücü:")
            driver.set_gconf(uart_comm=True)
            driver.set_current(MOTOR_RUN_CURRENT_mA, MOTOR_HOLD_CURRENT_mA)
            driver.set_chopper_config(
                microsteps=MICROSTEPS,
                stealth_chop=True,
                hybrid_threshold=HYBRID_MODE_SPEED_THRESHOLD
            )
            driver.get_version()
            driver.get_status_flags()

        # Motorları etkinleştir
        enable_motors_pin.low()  # TMC2209 EN pini LOW'da aktif
        print("\n✓ Motor sürücüleri etkinleştirildi")

        print("\n" + "=" * 60)
        print("✅ TÜM DONANIM BAŞARILI")
        print("=" * 60 + "\n")

        return True

    except Exception as e:
        print(f"\n❌ DONANIM BAŞLATMA HATASI: {e}")
        import sys
        sys.print_exception(e)
        return False


# ============================================================================
# MOTOR KONTROL FONKSİYONLARI
# ============================================================================

def drive_for_time(left_direction, right_direction, duration_ms, delay_us):
    """
    Sürüş motorlarını belirtilen yönlerde ve sürede çalıştır.

    Args:
        left_direction: 1=İleri, 0=Geri
        right_direction: 1=İleri, 0=Geri
        duration_ms: Çalışma süresi (milisaniye)
        delay_us: Adımlar arası gecikme (mikrosaniye)
    """
    left_dir.value(left_direction)
    right_dir.value(right_direction)

    end_time = utime.ticks_ms() + duration_ms

    while utime.ticks_diff(end_time, utime.ticks_ms()) > 0:
        # Her iki motora da pals gönder
        left_step.high()
        right_step.high()
        utime.sleep_us(delay_us)

        left_step.low()
        right_step.low()
        utime.sleep_us(delay_us)


def stop_drive_motors():
    """Sürüş motorlarını durdur (hold akımına geçer)"""
    # Aktif pals gönderilmediğinde motorlar otomatik durur
    pass


def disable_all_motors():
    """Tüm motorları devre dışı bırak"""
    enable_motors_pin.high()  # EN pini HIGH = Devre dışı


# ============================================================================
# KOMUT İŞLEYİCİLER
# ============================================================================

def handle_forward(duration_ms):
    """İleri git"""
    drive_for_time(1, 1, duration_ms, DEFAULT_SPEED_DELAY_US)


def handle_backward(duration_ms):
    """Geri git"""
    drive_for_time(0, 0, duration_ms, DEFAULT_SPEED_DELAY_US)


def handle_turn_left(duration_ms):
    """Sola dön (sol motor geri, sağ motor ileri)"""
    drive_for_time(0, 1, duration_ms, DEFAULT_TURN_DELAY_US)


def handle_turn_right(duration_ms):
    """Sağa dön (sol motor ileri, sağ motor geri)"""
    drive_for_time(1, 0, duration_ms, DEFAULT_TURN_DELAY_US)


def handle_stop_drive():
    """Sürüş motorlarını durdur"""
    stop_drive_motors()


def handle_stop_all():
    """Tüm motorları durdur ve devre dışı bırak"""
    stop_drive_motors()
    disable_all_motors()


def handle_slight_left(duration_ms):
    """
    Hafif sola dön (sol motor %50 hız, sağ motor %100 hız)
    Kavisli yol çizer
    """
    left_dir.value(1)  # İleri
    right_dir.value(1)  # İleri

    end_time = utime.ticks_ms() + duration_ms
    step_count = 0

    while utime.ticks_diff(end_time, utime.ticks_ms()) > 0:
        # Sağ motora her adımda pals
        right_step.high()

        # Sol motora her 2 adımda bir pals (yarı hız)
        if step_count % 2 == 0:
            left_step.high()

        utime.sleep_us(DEFAULT_SPEED_DELAY_US)

        left_step.low()
        right_step.low()
        utime.sleep_us(DEFAULT_SPEED_DELAY_US)

        step_count += 1


def handle_slight_right(duration_ms):
    """
    Hafif sağa dön (sol motor %100 hız, sağ motor %50 hız)
    Kavisli yol çizer
    """
    left_dir.value(1)  # İleri
    right_dir.value(1)  # İleri

    end_time = utime.ticks_ms() + duration_ms
    step_count = 0

    while utime.ticks_diff(end_time, utime.ticks_ms()) > 0:
        # Sol motora her adımda pals
        left_step.high()

        # Sağ motora her 2 adımda bir pals (yarı hız)
        if step_count % 2 == 0:
            right_step.high()

        utime.sleep_us(DEFAULT_SPEED_DELAY_US)

        left_step.low()
        right_step.low()
        utime.sleep_us(DEFAULT_SPEED_DELAY_US)

        step_count += 1


# ============================================================================
# ANA KOMUT DİNLEYİCİ
# ============================================================================

def process_command(command_line):
    """
    Komut satırını işle ve yanıt döndür.

    Returns:
        tuple: (success: bool, response: str)
    """
    try:
        command_line = command_line.strip()

        if not command_line:
            return False, None

        # FORWARD:1000
        if command_line.startswith("FORWARD:"):
            duration = int(command_line.split(":")[1])
            handle_forward(duration)
            return True, "DONE"

        # BACKWARD:1000
        elif command_line.startswith("BACKWARD:"):
            duration = int(command_line.split(":")[1])
            handle_backward(duration)
            return True, "DONE"

        # TURN_LEFT:500
        elif command_line.startswith("TURN_LEFT:"):
            duration = int(command_line.split(":")[1])
            handle_turn_left(duration)
            return True, "DONE"

        # TURN_RIGHT:500
        elif command_line.startswith("TURN_RIGHT:"):
            duration = int(command_line.split(":")[1])
            handle_turn_right(duration)
            return True, "DONE"

        # STOP_DRIVE
        elif command_line == "STOP_DRIVE":
            handle_stop_drive()
            return True, "DONE"

        # STOP_ALL
        elif command_line == "STOP_ALL":
            handle_stop_all()
            return True, "DONE"

        # SLIGHT_LEFT:1000 (Hafif sola dön)
        elif command_line.startswith("SLIGHT_LEFT:"):
            duration = int(command_line.split(":")[1])
            handle_slight_left(duration)
            return True, "DONE"

        # SLIGHT_RIGHT:1000 (Hafif sağa dön)
        elif command_line.startswith("SLIGHT_RIGHT:"):
            duration = int(command_line.split(":")[1])
            handle_slight_right(duration)
            return True, "DONE"

        # Bilinmeyen komut
        else:
            return False, "ERR:BilinmeyenKomut"

    except ValueError as e:
        return False, f"ERR:FormatHatasi:{e}"
    except Exception as e:
        return False, f"ERR:GenelHata:{e}"


def main_loop():
    """Ana komut dinleyici döngüsü"""

    # Donanımı başlat
    if not setup_hardware():
        print("❌ Donanım başlatılamadı, program sonlanıyor")
        return

    # Pi 5'e hazır sinyali gönder
    print("Pico (Kas) Hazir")

    if led:
        # LED yanıp sönsün (hazır durumu)
        for _ in range(3):
            led.off()
            utime.sleep_ms(100)
            led.on()
            utime.sleep_ms(100)

    print("\n🎧 Pi 5'ten komut bekleniyor...\n")

    command_count = 0

    # Sonsuz döngü: USB üzerinden komut al
    while True:
        try:
            # USB seri porttan komut oku
            command_line = sys.stdin.readline()

            if not command_line:
                utime.sleep_ms(10)
                continue

            command_line = command_line.strip()

            if not command_line:
                continue

            command_count += 1

            # LED'i kısa süre söndür (komut alındı göstergesi)
            if led:
                led.off()

            # Hemen ACK gönder
            print("ACK")

            # Komutu işle
            success, response = process_command(command_line)

            # Yanıtı gönder
            if response:
                print(response)

            # LED'i tekrar yak
            if led:
                led.on()

            # Debug: Her 10 komutta bir istatistik yazdır
            if command_count % 10 == 0:
                print(f"# {command_count} komut işlendi", file=sys.stderr)

        except KeyboardInterrupt:
            print("\n⚠️ CTRL+C - Program sonlandırılıyor...")
            handle_stop_all()
            break

        except Exception as e:
            print(f"ERR:DonguHatasi:{e}")
            import sys
            sys.print_exception(e)
            # Hata durumunda motorları durdur
            try:
                handle_stop_all()
            except:
                pass


# ============================================================================
# PROGRAM BAŞLANGICI
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🤖 RASPBERRY PI PICO - MOTOR KONTROL (KAS)")
    print("=" * 60)
    print("Versiyon: 2.0 (ACK+DONE Protokolü)")
    print("Görev: Pi 5'ten gelen komutları işle ve motorları kontrol et")
    print("=" * 60 + "\n")

    try:
        main_loop()
    except Exception as e:
        print(f"\n❌ KRİTİK HATA: {e}")
        import sys

        sys.print_exception(e)
    finally:
        print("\n👋 Program sonlandı")
        # Çıkışta motorları durdur
        try:
            if enable_motors_pin:
                enable_motors_pin.high()
        except:
            pass