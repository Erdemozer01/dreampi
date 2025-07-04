# FINAL RASPBERRY PI 5 CONTROL SCRIPT
# This is the definitive, stable version for controlling the robot.

import sys
import tty
import termios
import serial
import time
import select

# --- CONFIGURATION ---
# If the script fails to connect, check this port with `ls /dev/ttyACM*`
PICO_PORT = '/dev/ttyACM0'
BAUD_RATE = 115200

# --- PICO CONNECTION ---
pico_serial = None
try:
    pico_serial = serial.Serial(PICO_PORT, BAUD_RATE, timeout=1)
    print(f"Pico'ya {PICO_PORT} portundan başarıyla bağlanıldı.")
    time.sleep(2)  # Give Pico a moment to initialize
except serial.SerialException as e:
    print(f"HATA: Pico'ya bağlanılamadı. Pico'nun bağlı ve doğru portta olduğundan emin olun. {e}")
    exit()


# --- FUNCTIONS ---
def send_command(command):
    """Encodes and sends the command to the Pico."""
    if pico_serial and pico_serial.is_open:
        pico_serial.write(command.encode('utf-8'))


def get_key_press():
    """Reads a single keystroke, including arrow keys, from the terminal."""
    # Check if there is data to be read on stdin
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        char = sys.stdin.read(1)
        # Arrow keys send a 3-character escape sequence (e.g., '\x1b[A')
        if char == '\x1b':
            sequence = sys.stdin.read(2)
            key_map = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}
            return key_map.get(sequence)
        return char
    return None


# --- MAIN PROGRAM ---
print("\n--- Robot Kontrol Paneli (Nihai Versiyon) ---")
print("   Hareket için ok tuşlarını kullanın (tuşu bırakınca durur).")
print("   Anında durmak için SPACEBAR tuşuna basın.")
print("   Çıkmak için 'q' tuşuna basın.")
print("----------------------------------------------\n")

# Store original terminal settings to restore them on exit
old_settings = termios.tcgetattr(sys.stdin)

try:
    # Set terminal to cbreak mode (reads keys instantly without needing Enter)
    tty.setcbreak(sys.stdin.fileno())

    last_sent_command = None
    while True:
        key = get_key_press()

        current_command = None
        if key == 'up':
            current_command = 'F\n'  # Forward
        elif key == 'down':
            current_command = 'B\n'  # Backward
        elif key == 'left':
            current_command = 'L\n'  # Turn Left
        elif key == 'right':
            current_command = 'R\n'  # Turn Right
        elif key == ' ':  # Spacebar
            current_command = 'S\n'  # Stop
        elif key == 'q':
            print("'q' tuşuna basıldı, çıkılıyor.")
            break
        else:
            # Safety Feature: If no key is being pressed, send STOP.
            # This ensures the robot only moves while a key is active.
            if last_sent_command != 'S\n':
                current_command = 'S\n'

        # Send the command only if it has changed, to avoid flooding the serial port
        if current_command and current_command != last_sent_command:
            send_command(current_command)
            last_sent_command = current_command

        # A short delay to prevent high CPU usage
        time.sleep(0.05)

finally:
    # Always restore terminal and stop the robot on exit
    print("Terminal ayarları geri yükleniyor ve DUR komutu gönderiliyor.")
    send_command('S\n')
    if pico_serial and pico_serial.is_open:
        pico_serial.close()
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)