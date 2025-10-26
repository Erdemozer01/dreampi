from machine import Pin, UART, WDT
import utime
import sys
import uselect


# --- TMC2209 UART Kontrol Sınıfı ---
class TMC2209_UART:
    """TMC2209 stepper motor sürücü kontrolü"""

    def __init__(self, uart_id, baudrate=115200, tx_pin_id=None, rx_pin_id=None, rsense_ohm=0.11):
        uart_timeout = 50
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
                    print("  ✗ Sürücü hatası (aşırı sıcaklık/kısa devre)")
                if gstat_val & 4:
                    print("  ✗ Düşük voltaj hatası")
        else:
            print("  ✗ GSTAT okunamadı - Bağlantı sorunu")
        return gstat_val

    def get_version(self):
        """Sürücü versiyonunu oku"""
        ioin_val = self.read_register(0x06)
        if ioin_val is not None:
            version = (ioin_val >> 24) & 0xFF
            print(f"  ℹ Sürücü Versiyonu: 0x{version:X}")
            return version
        else:
            print("  ✗ Versiyon okunamadı")
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

ENABLE_PIN = 22

# Motor Parametreleri
MOTOR_RUN_CURRENT_mA = 2000
MOTOR_HOLD_CURRENT_mA = 850
MICROSTEPS = 16
RSENSE_OHM = 0.1
HYBRID_MODE_SPEED_THRESHOLD = 100

# Hız Parametreleri (mikrosaniye)
DEFAULT_SPEED_DELAY_US = 500
DEFAULT_TURN_DELAY_US = 1000

# --- GLOBAL DEĞİŞKENLER ---
led = None
left_step = None
left_dir = None
right_step = None
right_dir = None
enable_motors_pin = None
left_driver = None
right_driver = None
wdt = None

# Sürekli hareket için
continuous_mode = "STOP"
continuous_step_count = 0


# ============================================================================
# DONANIM BAŞLATMA
# ============================================================================

def setup_hardware():
    """Tüm donanımı başlat"""
    global led, left_step, left_dir, right_step, right_dir
    global enable_motors_pin, left_driver, right_driver, wdt

    print("\n" + "=" * 60)
    print("🤖 PICO (KAS) DONANIM BAŞLATILIYOR")
    print("=" * 60)

    try:
        # ✅ Watchdog Timer (20 saniye - daha güvenli)
        wdt = WDT(timeout=20000)
        print("✓ Watchdog timer aktif (20s)")

        # LED (Pico W'de farklı)
        try:
            led = Pin("LED", Pin.OUT)
            led.on()
            print("✓ LED hazır (Pico W)")
        except:
            try:
                led = Pin(25, Pin.OUT)
                led.on()
                print("✓ LED hazır (Pico/Pico 2)")
            except:
                print("⚠ LED bulunamadı")
                led = None

        # Watchdog'u besle (ilk adımlar uzun sürebilir)
        if wdt:
            wdt.feed()

        # Sürüş motor pinleri
        left_step = Pin(LEFT_STEP_PIN, Pin.OUT)
        left_dir = Pin(LEFT_DIR_PIN, Pin.OUT)
        right_step = Pin(RIGHT_STEP_PIN, Pin.OUT)
        right_dir = Pin(RIGHT_DIR_PIN, Pin.OUT)
        enable_motors_pin = Pin(ENABLE_PIN, Pin.OUT)
        print("✓ Motor pinleri hazır")

        # Watchdog'u besle
        if wdt:
            wdt.feed()

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

        # Watchdog'u besle
        if wdt:
            wdt.feed()

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

            # Her sürücü sonrası watchdog besle
            if wdt:
                wdt.feed()

        # Motorları etkinleştir
        enable_motors_pin.low()
        print("\n✓ Motor sürücüleri etkinleştirildi")

        # Son watchdog besleme
        if wdt:
            wdt.feed()

        print("\n" + "=" * 60)
        print("✅ TÜM DONANIM BAŞARILI")
        print("=" * 60 + "\n")

        return True

    except Exception as e:
        print(f"\n✗ DONANIM BAŞLATMA HATASI: {e}")
        import sys
        sys.print_exception(e)
        return False


# ============================================================================
# MOTOR KONTROL FONKSİYONLARI (SÜRELİ)
# ============================================================================

def drive_for_time(left_direction, right_direction, duration_ms, delay_us):
    """Sürüş motorlarını belirtilen yönlerde ve sürede çalıştır"""
    left_dir.value(left_direction)
    right_dir.value(right_direction)

    end_time = utime.ticks_ms() + duration_ms
    step_count = 0

    while utime.ticks_diff(end_time, utime.ticks_ms()) > 0:
        left_step.high()
        right_step.high()
        utime.sleep_us(delay_us)

        left_step.low()
        right_step.low()
        utime.sleep_us(delay_us)

        # ✅ Watchdog'u daha sık besle (her 50 adımda)
        step_count += 1
        if step_count % 50 == 0 and wdt:
            wdt.feed()


def stop_drive_motors():
    """Sürüş motorlarını durdur"""
    global continuous_mode
    continuous_mode = "STOP"


def disable_all_motors():
    """Tüm motorları devre dışı bırak"""
    global continuous_mode
    continuous_mode = "STOP"
    enable_motors_pin.high()


# ============================================================================
# KOMUT İŞLEYİCİLER (SÜRELİ)
# ============================================================================

def handle_forward(duration_ms):
    """İleri git"""
    drive_for_time(1, 1, duration_ms, DEFAULT_SPEED_DELAY_US)


def handle_backward(duration_ms):
    """Geri git"""
    drive_for_time(0, 0, duration_ms, DEFAULT_SPEED_DELAY_US)


def handle_turn_left(duration_ms):
    """Sola dön"""
    drive_for_time(0, 1, duration_ms, DEFAULT_TURN_DELAY_US)


def handle_turn_right(duration_ms):
    """Sağa dön"""
    drive_for_time(1, 0, duration_ms, DEFAULT_TURN_DELAY_US)


def handle_stop_drive():
    """Sürüş motorlarını durdur"""
    stop_drive_motors()


def handle_stop_all():
    """Tüm motorları durdur"""
    stop_drive_motors()
    disable_all_motors()


def handle_slight_left(duration_ms):
    """Hafif sola dön (sol motor %50 hız, sağ motor %100 hız)"""
    left_dir.value(1)
    right_dir.value(1)

    end_time = utime.ticks_ms() + duration_ms
    step_count = 0

    while utime.ticks_diff(end_time, utime.ticks_ms()) > 0:
        right_step.high()

        if step_count % 2 == 0:
            left_step.high()

        utime.sleep_us(DEFAULT_SPEED_DELAY_US)

        left_step.low()
        right_step.low()
        utime.sleep_us(DEFAULT_SPEED_DELAY_US)

        step_count += 1

        # ✅ Watchdog'u daha sık besle
        if step_count % 50 == 0 and wdt:
            wdt.feed()


def handle_slight_right(duration_ms):
    """Hafif sağa dön (sol motor %100 hız, sağ motor %50 hız)"""
    left_dir.value(1)
    right_dir.value(1)

    end_time = utime.ticks_ms() + duration_ms
    step_count = 0

    while utime.ticks_diff(end_time, utime.ticks_ms()) > 0:
        left_step.high()

        if step_count % 2 == 0:
            right_step.high()

        utime.sleep_us(DEFAULT_SPEED_DELAY_US)

        left_step.low()
        right_step.low()
        utime.sleep_us(DEFAULT_SPEED_DELAY_US)

        step_count += 1

        # ✅ Watchdog'u daha sık besle
        if step_count % 50 == 0 and wdt:
            wdt.feed()


# ============================================================================
# KOMUT İŞLEYİCİLER (SÜREKLİ)
# ============================================================================

def handle_continuous_forward():
    global continuous_mode, continuous_step_count
    left_dir.value(1)
    right_dir.value(1)
    continuous_mode = "FORWARD"
    continuous_step_count = 0
    print("DONE")


def handle_continuous_turn_left():
    global continuous_mode, continuous_step_count
    left_dir.value(0)
    right_dir.value(1)
    continuous_mode = "TURN_LEFT"
    continuous_step_count = 0
    print("DONE")


def handle_continuous_turn_right():
    global continuous_mode, continuous_step_count
    left_dir.value(1)
    right_dir.value(0)
    continuous_mode = "TURN_RIGHT"
    continuous_step_count = 0
    print("DONE")


def handle_continuous_slight_left():
    global continuous_mode, continuous_step_count
    left_dir.value(1)
    right_dir.value(1)
    continuous_mode = "SLIGHT_LEFT"
    continuous_step_count = 0
    print("DONE")


def handle_continuous_slight_right():
    global continuous_mode, continuous_step_count
    left_dir.value(1)
    right_dir.value(1)
    continuous_mode = "SLIGHT_RIGHT"
    continuous_step_count = 0
    print("DONE")


# ============================================================================
# ANA KOMUT İŞLEYİCİ
# ============================================================================

def process_command(command_line):
    """
    ✅ FIXED: Ensures all responses are flushed
    """
    global continuous_mode
    try:
        command_line = command_line.strip()

        if not command_line:
            return False, None

        # Stop continuous movement for timed commands
        if not command_line.startswith("CONTINUOUS_") and command_line not in ["STOP_DRIVE", "STOP_ALL"]:
            continuous_mode = "STOP"

        # Process commands...
        if command_line.startswith("FORWARD:"):
            duration = int(command_line.split(":")[1])
            handle_forward(duration)
            return True, "DONE"

        elif command_line.startswith("BACKWARD:"):
            duration = int(command_line.split(":")[1])
            handle_backward(duration)
            return True, "DONE"

        elif command_line.startswith("TURN_LEFT:"):
            duration = int(command_line.split(":")[1])
            handle_turn_left(duration)
            return True, "DONE"

        elif command_line.startswith("TURN_RIGHT:"):
            duration = int(command_line.split(":")[1])
            handle_turn_right(duration)
            return True, "DONE"

        elif command_line.startswith("SLIGHT_LEFT:"):
            duration = int(command_line.split(":")[1])
            handle_slight_left(duration)
            return True, "DONE"

        elif command_line.startswith("SLIGHT_RIGHT:"):
            duration = int(command_line.split(":")[1])
            handle_slight_right(duration)
            return True, "DONE"

        elif command_line == "STOP_DRIVE":
            handle_stop_drive()
            return True, "DONE"

        elif command_line == "STOP_ALL":
            handle_stop_all()
            return True, "DONE"

        elif command_line == "CONTINUOUS_FORWARD":
            handle_continuous_forward()
            sys.stdout.flush()  # ✅ Flush after DONE
            return True, None  # DONE already sent in handler

        elif command_line == "CONTINUOUS_TURN_LEFT":
            handle_continuous_turn_left()
            sys.stdout.flush()
            return True, None

        elif command_line == "CONTINUOUS_TURN_RIGHT":
            handle_continuous_turn_right()
            sys.stdout.flush()
            return True, None

        elif command_line == "CONTINUOUS_SLIGHT_LEFT":
            handle_continuous_slight_left()
            sys.stdout.flush()
            return True, None

        elif command_line == "CONTINUOUS_SLIGHT_RIGHT":
            handle_continuous_slight_right()
            sys.stdout.flush()
            return True, None

        # ✅ ADD: Ping/pong test command
        elif command_line == "PING":
            return True, "DONE"

        else:
            return False, "ERR:UnknownCommand"

    except ValueError as e:
        return False, f"ERR:FormatError:{e}"
    except Exception as e:
        return False, f"ERR:GeneralError:{e}"

# ============================================================================
# ANA DÖNGÜ (DÜZELTİLMİŞ)
# ============================================================================

def main_loop():
    """
    ✅ FIXED: Ensures boot message is sent immediately
    """
    global continuous_mode, continuous_step_count

    # Initialize hardware
    if not setup_hardware():
        print("✗ Hardware initialization failed")
        sys.stdout.flush()  # ✅ CRITICAL
        return

    # ✅ CRITICAL FIX: Send ready signal MULTIPLE times and flush
    print("\n" + "=" * 60)
    print("🤖 PICO MOTOR CONTROL READY")
    print("=" * 60)
    print("Pico (Kas) Hazir")  # This is what Pi5 is looking for
    print("PICO_READY")  # Alternative message
    print("Status: Ready")  # Another alternative
    sys.stdout.flush()  # ✅ FORCE SEND NOW

    # ✅ Also write to stderr to be sure
    print("Pico (Kas) Hazir", file=sys.stderr)
    sys.stderr.flush()

    if led:
        # Blink LED pattern: READY
        for _ in range(5):
            led.off()
            utime.sleep_ms(100)
            led.on()
            utime.sleep_ms(100)

    # ✅ Send another ready message after LED blink
    print("Listening for commands...")
    sys.stdout.flush()

    print("\n🎧 Waiting for commands from Pi 5...\n")
    sys.stdout.flush()

    # Create poll object for stdin
    spoll = uselect.poll()
    spoll.register(sys.stdin, uselect.POLLIN)

    command_count = 0
    last_wdt_feed = utime.ticks_ms()
    last_heartbeat = utime.ticks_ms()

    # Main loop
    while True:
        try:
            # Feed watchdog every 5 seconds
            now = utime.ticks_ms()
            if utime.ticks_diff(now, last_wdt_feed) > 5000:
                if wdt:
                    wdt.feed()
                last_wdt_feed = now

            # ✅ Send periodic heartbeat every 30 seconds
            if utime.ticks_diff(now, last_heartbeat) > 30000:
                print(f"# Heartbeat: {command_count} commands, mode={continuous_mode}", file=sys.stderr)
                sys.stderr.flush()
                last_heartbeat = now

            # Check for commands (1ms timeout)
            if spoll.poll(1):
                command_line = sys.stdin.readline()

                if not command_line:
                    continue

                command_line = command_line.strip()

                if not command_line:
                    continue

                command_count += 1
                if led:
                    led.off()

                # ✅ Send ACK immediately with flush
                print("ACK")
                sys.stdout.flush()

                # Process command
                success, response = process_command(command_line)

                # ✅ Send response with flush
                if response:
                    print(response)
                    sys.stdout.flush()

                if led:
                    led.on()

            # Execute continuous movement
            if continuous_mode == "STOP":
                utime.sleep_ms(10)
                continue

            elif continuous_mode == "FORWARD":
                left_step.high()
                right_step.high()
                utime.sleep_us(DEFAULT_SPEED_DELAY_US)
                left_step.low()
                right_step.low()
                utime.sleep_us(DEFAULT_SPEED_DELAY_US)

            elif continuous_mode == "TURN_LEFT" or continuous_mode == "TURN_RIGHT":
                left_step.high()
                right_step.high()
                utime.sleep_us(DEFAULT_TURN_DELAY_US)
                left_step.low()
                right_step.low()
                utime.sleep_us(DEFAULT_TURN_DELAY_US)

            elif continuous_mode == "SLIGHT_LEFT":
                right_step.high()
                if continuous_step_count % 2 == 0:
                    left_step.high()
                utime.sleep_us(DEFAULT_SPEED_DELAY_US)
                left_step.low()
                right_step.low()
                utime.sleep_us(DEFAULT_SPEED_DELAY_US)
                continuous_step_count += 1

            elif continuous_mode == "SLIGHT_RIGHT":
                left_step.high()
                if continuous_step_count % 2 == 0:
                    right_step.high()
                utime.sleep_us(DEFAULT_SPEED_DELAY_US)
                left_step.low()
                right_step.low()
                utime.sleep_us(DEFAULT_SPEED_DELAY_US)
                continuous_step_count += 1

        except KeyboardInterrupt:
            print("\n⚠ CTRL+C - Stopping...")
            sys.stdout.flush()
            handle_stop_all()
            break

        except Exception as e:
            print(f"ERR:LoopError:{e}")
            sys.stdout.flush()
            import sys
            sys.print_exception(e)

            try:
                handle_stop_all()
                continuous_mode = "STOP"
            except:
                pass

            if wdt:
                wdt.feed()


# ============================================================================
# PROGRAM BAŞLANGIÇ
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🤖 RASPBERRY PI PICO - MOTOR KONTROL (KAS)")
    print("=" * 60)
    print("Versiyon: 2.4 (Düzeltilmiş - Watchdog Güvenli)")
    print("Görev: Pi 5'ten gelen komutları işle ve motorları kontrol et")
    print("=" * 60 + "\n")

    try:
        main_loop()
    except Exception as e:
        print(f"\n✗ KRİTİK HATA: {e}")
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