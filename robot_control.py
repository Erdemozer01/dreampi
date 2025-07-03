# FINAL RASPBERRY PI 5 CONTROL SCRIPT
# This version is stable and includes an auto-stop safety feature.

import sys
import tty
import termios
import serial
import time
import select

# --- CONFIGURATION ---
PICO_PORT = '/dev/ttyACM0'  # Check this with `ls /dev/ttyACM*` if it fails
BAUD_RATE = 115200

# --- PICO CONNECTION ---
pico_serial = None
try:
    pico_serial = serial.Serial(PICO_PORT, BAUD_RATE, timeout=1)
    print(f"Successfully connected to Pico on port {PICO_PORT}.")
    time.sleep(2)  # Give Pico a moment to initialize
except serial.SerialException as e:
    print(f"ERROR: Could not connect to Pico. {e}")
    exit()


# --- FUNCTIONS ---
def send_command(command):
    """Encodes and sends a single character command to the Pico."""
    if pico_serial and pico_serial.is_open:
        pico_serial.write(command.encode('utf-8'))


def get_key_press():
    """Reads a single keystroke, including arrows, from the terminal."""
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        char = sys.stdin.read(1)
        if char == '\x1b':  # Arrow key escape sequence
            sequence = sys.stdin.read(2)
            key_map = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}
            return key_map.get(sequence)
        return char
    return None


# --- MAIN PROGRAM ---
print("\n--- Robot Control Panel (Final Version) ---")
print("   Use arrow keys to move (robot stops on release).")
print("   Use SPACEBAR to stop immediately.")
print("   Press 'q' to quit.")
print("----------------------------------------------\n")

# Store original terminal settings
old_settings = termios.tcgetattr(sys.stdin)

try:
    # Set terminal to cbreak mode (reads keys instantly)
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
            print("'q' pressed, exiting.")
            break
        else:
            # If no key is being pressed, send the STOP command.
            # This ensures the robot only moves while a key is active.
            if last_sent_command != 'S\n':
                current_command = 'S\n'

        if current_command and current_command != last_sent_command:
            send_command(current_command)
            last_sent_command = current_command

        time.sleep(0.05)  # Loop delay to prevent high CPU usage

finally:
    # Always restore terminal settings and stop the robot on exit
    print("Restoring terminal settings and sending STOP command.")
    send_command('S\n')
    if pico_serial and pico_serial.is_open:
        pico_serial.close()
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)