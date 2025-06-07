# YENİ DOSYA: autonomous_drive.py

from gpiozero import Motor, Servo, DistanceSensor
from time import sleep
import atexit

# ==============================================================================
# --- DONANIM PIN TANIMLARI (SİZİN KURULUMUNUZA GÖRE) ---
# ==============================================================================
# DC Motor Pinleri (L298N)
DC_MOTOR_SOL_ILERI = 4
DC_MOTOR_SOL_GERI = 5
DC_MOTOR_SOL_HIZ = 25
DC_MOTOR_SAG_ILERI = 22
DC_MOTOR_SAG_GERI = 10
DC_MOTOR_SAG_HIZ = 16

# Servo ve Sensör Pinleri
SERVO_PIN = 12
TRIG_PIN, ECHO_PIN = 23, 24

# ==============================================================================
# --- DONANIM NESNELERİNİ OLUŞTURMA ---
# ==============================================================================
print("Donanımlar başlatılıyor...")
sol_motor = Motor(forward=DC_MOTOR_SOL_ILERI, backward=DC_MOTOR_SOL_GERI, enable=DC_MOTOR_SOL_HIZ)
sag_motor = Motor(forward=DC_MOTOR_SAG_ILERI, backward=DC_MOTOR_SAG_GERI, enable=DC_MOTOR_SAG_HIZ)
servo = Servo(SERVO_PIN)
sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN)
print("Donanımlar hazır.")


# ==============================================================================
# --- HAREKET FONKSİYONLARI ---
# ==============================================================================
def ileri(hiz=0.6):
    sol_motor.forward(speed=hiz)
    sag_motor.forward(speed=hiz)


def dur():
    sol_motor.stop()
    sag_motor.stop()


def sola_don(hiz=0.5):
    sol_motor.backward(speed=hiz)
    sag_motor.forward(speed=hiz)


def saga_don(hiz=0.5):
    sol_motor.forward(speed=hiz)
    sag_motor.backward(speed=hiz)


# ==============================================================================
# --- OTONOM SÜRÜŞ FONKSİYONLARI ---
# ==============================================================================
def degree_to_servo_value(angle_deg):
    """0-180 dereceyi, gpiozero'nun -1 ile 1 aralığına çevirir."""
    clamped_angle = max(0, min(180, angle_deg))
    return (clamped_angle / 90.0) - 1.0


def cevreyi_tara():
    """Servo'yu 3 ana yöne çevirir ve mesafeleri ölçer."""
    print("Çevre taranıyor...")
    servo.value = degree_to_servo_value(90)  # Önce ortaya bak
    sleep(0.4)

    # 3 farklı yöndeki mesafeleri saklamak için bir sözlük (dictionary)
    mesafeler = {}

    # Sol tarafı ölç
    servo.value = degree_to_servo_value(150)  # Sola dön
    sleep(0.6)
    mesafeler['sol'] = sensor.distance * 100

    # Orta yönü ölç
    servo.value = degree_to_servo_value(90)  # Ortaya dön
    sleep(0.6)
    mesafeler['orta'] = sensor.distance * 100

    # Sağ tarafı ölç
    servo.value = degree_to_servo_value(30)  # Sağa dön
    sleep(0.6)
    mesafeler['sag'] = sensor.distance * 100

    # İş bittikten sonra tekrar ortaya dön
    servo.value = degree_to_servo_value(90)
    print(f"Ölçümler: Sol={mesafeler['sol']:.1f}cm, Orta={mesafeler['orta']:.1f}cm, Sağ={mesafeler['sag']:.1f}cm")
    return mesafeler


def en_iyi_yolu_bul(mesafeler):
    """En uzun mesafeyi en iyi yol olarak belirler."""
    # Eğer tüm yönler çok kapalıysa, dön
    if max(mesafeler.values()) < 20:
        print("Tüm yönler kapalı. Geri dönülüyor.")
        return 'geri_don'

    # En uzun mesafeye sahip yönü bul
    en_iyi_yon = max(mesafeler, key=mesafeler.get)
    print(f"En iyi yol bulundu: {en_iyi_yon.upper()}")
    return en_iyi_yon


def program_kapanirken():
    """Script kapandığında motorları ve servoyu durdurur."""
    print("\nProgram sonlanıyor. Motorlar durduruluyor.")
    dur()
    servo.detach()


atexit.register(program_kapanirken)

# ==============================================================================
# --- ANA SÜRÜŞ DÖNGÜSÜ ---
# ==============================================================================
try:
    while True:
        mesafe_olcumleri = cevreyi_tara()
        secilen_yol = en_iyi_yolu_bul(mesafe_olcumleri)

        if secilen_yol == 'orta':
            print(">>> YOL AÇIK: İleri gidiliyor...")
            ileri()
            sleep(1.5)  # 1.5 saniye ileri git
        elif secilen_yol == 'sol':
            print(">>> SOLA DÖNÜLÜYOR...")
            sola_don()
            sleep(0.5)  # 0.5 saniye sola dön
        elif secilen_yol == 'sag':
            print(">>> SAĞA DÖNÜLÜYOR...")
            saga_don()
            sleep(0.5)  # 0.5 saniye sağa dön
        elif secilen_yol == 'geri_don':
            print(">>> SIKIŞTI: Geri dönülüyor...")
            saga_don(hiz=0.8)  # Sıkışınca daha hızlı dön
            sleep(1.0)

        dur()  # Her hareketten sonra kısa bir an dur ve tekrar tara
        sleep(0.5)

except KeyboardInterrupt:
    pass  # program_kapanirken fonksiyonu zaten çalışacak