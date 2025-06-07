from gpiozero import Motor
from time import sleep

# ==============================================================================
# --- DC MOTOR PIN TANIMLARI (YENİ VE AÇIKLAYICI) ---
# ==============================================================================
# Sol Motor Pinleri
DC_MOTOR_SOL_ILERI = 4  # L298N IN1 pini (Daha önce 17 doluydu, 4 yapmıştık)
DC_MOTOR_SOL_GERI = 5  # L298N IN2 pini
DC_MOTOR_SOL_HIZ = 9  # L298N ENA pini (Hız kontrolü)

# Sağ Motor Pinleri
DC_MOTOR_SAG_ILERI = 22  # L298N IN3 pini
DC_MOTOR_SAG_GERI = 24  # L298N IN4 pini
DC_MOTOR_SAG_HIZ = 16  # L298N ENB pini (Hız kontrolü)

# ==============================================================================
# --- Motorları Yeni Değişkenleri Kullanarak Tanımla ---
# ==============================================================================
sol_motor = Motor(forward=DC_MOTOR_SOL_ILERI, backward=DC_MOTOR_SOL_GERI, enable=DC_MOTOR_SOL_HIZ)
sag_motor = Motor(forward=DC_MOTOR_SAG_ILERI, backward=DC_MOTOR_SAG_GERI, enable=DC_MOTOR_SAG_HIZ)


# ==============================================================================
# --- Hareket Fonksiyonları (Bu kısımda değişiklik yok) ---
# ==============================================================================
def ileri(hiz=1.0):
    """Araç ileri hareket eder. hiz 0.0 ile 1.0 arasında bir değerdir."""
    print(f"İleri hareket, Hız: {hiz * 100}%")
    sol_motor.forward(speed=hiz)
    sag_motor.forward(speed=hiz)


def geri(hiz=1.0):
    """Araç geri hareket eder."""
    print(f"Geri hareket, Hız: {hiz * 100}%")
    sol_motor.backward(speed=hiz)
    sag_motor.backward(speed=hiz)


def sola_don(hiz=0.7):
    """Araç yerinde sola döner."""
    print(f"Sola dönüş, Hız: {hiz * 100}%")
    sol_motor.backward(speed=hiz)
    sag_motor.forward(speed=hiz)


def saga_don(hiz=0.7):
    """Araç yerinde sağa döner."""
    print(f"Sağa dönüş, Hız: {hiz * 100}%")
    sol_motor.forward(speed=hiz)
    sag_motor.backward(speed=hiz)


def dur():
    """Araç durur."""
    print("Dur.")
    sol_motor.stop()
    sag_motor.stop()


# ==============================================================================
# --- Ana Test Programı (Bu kısımda değişiklik yok) ---
# ==============================================================================
try:
    print("Araç hareket testi başlıyor...")

    ileri(1.0)
    sleep(2)

    dur()
    sleep(1)

    geri(0.5)
    sleep(2)

    dur()
    sleep(1)

    saga_don()
    sleep(1.5)
    sola_don()
    sleep(1.5)

    print("Test tamamlandı.")

except KeyboardInterrupt:
    print("Program kullanıcı tarafından durduruldu.")

finally:
    # Program biterken motorların durduğundan emin ol
    dur()