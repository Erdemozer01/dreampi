from gpiozero import Motor
from time import sleep

# ==============================================================================
# --- DC MOTOR PIN TANIMLARI ---
# Pin numaraları projenize göre doğrudur, bu kısımda değişiklik yapılmadı.
# ==============================================================================
# Sol Motor Pinleri
DC_MOTOR_SOL_ILERI = 16
DC_MOTOR_SOL_GERI = 12
DC_MOTOR_SOL_HIZ = 5

# Sağ Motor Pinleri
DC_MOTOR_SAG_ILERI = 20
DC_MOTOR_SAG_GERI = 21
DC_MOTOR_SAG_HIZ = 22

# ==============================================================================
# --- Motorları Tanımlama ---
# ==============================================================================
print("Motorlar başlatılıyor...")
sol_motor = Motor(forward=DC_MOTOR_SOL_ILERI, backward=DC_MOTOR_SOL_GERI, enable=DC_MOTOR_SOL_HIZ)
sag_motor = Motor(forward=DC_MOTOR_SAG_ILERI, backward=DC_MOTOR_SAG_GERI, enable=DC_MOTOR_SAG_HIZ)
print("Motorlar hazır. 🚀")


# ==============================================================================
# --- MAKSİMUM GÜÇLÜ HAREKET FONKSİYONLARI ---
# Not: Tüm fonksiyonlardaki varsayılan 'hiz' parametresi 1.0 (yani %100)
# olarak ayarlandı.
# ==============================================================================
def ileri(hiz=1.0):
    """Araç ileri hareket eder. Maksimum güç için hız 1.0 olmalıdır."""
    print(f"İleri hareket, Hız: {hiz * 100}%")
    sol_motor.forward(speed=hiz)
    sag_motor.forward(speed=hiz)


def geri(hiz=1.0):
    """Araç geri hareket eder."""
    print(f"Geri hareket, Hız: {hiz * 100}%")
    sol_motor.backward(speed=hiz)
    sag_motor.backward(speed=hiz)


def sola_don(hiz=1.0):
    """Araç yerinde maksimum hızla sola döner."""
    print(f"Sola dönüş, Hız: {hiz * 100}%")
    sol_motor.backward(speed=hiz)
    sag_motor.forward(speed=hiz)


def saga_don(hiz=1.0):
    """Araç yerinde maksimum hızla sağa döner."""
    print(f"Sağa dönüş, Hız: {hiz * 100}%")
    sol_motor.forward(speed=hiz)
    sag_motor.backward(speed=hiz)


def dur():
    """Araç durur."""
    print("DUR 🛑")
    sol_motor.stop()
    sag_motor.stop()


# ==============================================================================
# --- Ana Test Programı (Tüm hareketler maksimum güçte) ---
# ==============================================================================
try:
    print("\nAraç maksimum güç testi başlıyor...")

    ileri(1.0)  # Tam hızda ileri
    sleep(2)

    dur()
    sleep(1)

    geri(1.0)  # Tam hızda geri
    sleep(2)

    dur()
    sleep(1)

    saga_don(1.0)  # Tam hızda sağa dönüş
    sleep(1.5)

    dur()
    sleep(1)

    sola_don(1.0)  # Tam hızda sola dönüş
    sleep(1.5)

    print("\nTest tamamlandı.")

except KeyboardInterrupt:
    print("\nProgram kullanıcı tarafından durduruldu.")

finally:
    # Program sonlanırken motorların kesinlikle durmasını sağla
    print("Güvenlik için motorlar durduruluyor.")
    dur()

