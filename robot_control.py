# robot_control_reliable.py
# This version uses standard libraries (tty, termios) instead of the 'keyboard' library
# to make it more reliable when running with sudo.

import sys
import tty
import termios
import serial
import time
import select

# --- Pico Connection Setup ---
PICO_PORT = '/dev/ttyACM0'
BAUD_RATE = 115200
pico_serial = None

try:
    pico_serial = serial.Serial(PICO_PORT, BAUD_RATE, timeout=1)
    print(f"Successfully connected to Pico on port {PICO_PORT}.")
    time.sleep(2)
except serial.SerialException as e:
    print(f"ERROR: Could not connect to Pico. {e}")
    exit()


def send_command(command):
    """Encodes and sends a single character command to the Pico."""
    if pico_serial and pico_serial.is_open:
        pico_serial.write(command.encode('utf-8'))


# --- Keyboard Reading Function ---
def get_key():
    """Reads a single keystroke from the terminal without waiting for Enter."""
    # Check if there's input waiting
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        return sys.stdin.read(1)
    return None


def get_arrow_key():
    """
    Detects arrow key presses, which are multi-byte sequences.
    e.g., Up Arrow is '\x1b', '[', 'A'
    """
    # Check for the initial escape character
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        first_char = sys.stdin.read(1)
        if first_char == '\x1b':  # Escape character
            # Read the next two characters for the arrow key sequence
            sequence = sys.stdin.read(2)
            key_map = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}
            return key_map.get(sequence)
    return None


# --- Main Program ---
print("\n--- Robot Control Panel (Reliable Version) ---")
print("   Use arrow keys to move.")
print("   Use SPACEBAR to stop.")
print("   Press 'q' to quit.")
print("----------------------------------------------\n")

# Save original terminal settings
old_settings = termios.tcgetattr(sys.stdin)

try:
    # Put terminal in cbreak mode - reads keys instantly
    tty.setcbreak(sys.stdin.fileno())

    last_sent_command = None
    while True:
        key = get_arrow_key()
        if not key:
            # If it wasn't an arrow key, check for regular keys
            key = get_key()

        current_command = None
        if key == 'up':
            current_command = 'F\n'
        elif key == 'down':
            current_command = 'B\n'
        elif key == 'left':
            current_command = 'L\n'
        elif key == 'right':
            current_command = 'R\n'
        elif key == ' ':  # Spacebar
            current_command = 'S\n'
        elif key == 'q':
            print("'q' pressed, exiting.")
            break

        # If no key is pressed, we don't send anything,
        # the robot continues with its last command from Pico.
        # To make it stop when no key is pressed, uncomment the line below.
        # else:
        #     current_command = 'S\n'

        if current_command and current_command != last_sent_command:
            send_command(current_command)
            last_sent_command = current_command

        # A short sleep to prevent high CPU usage
        time.sleep(0.02)

finally:
    # Always restore original terminal settings
    print("Restoring terminal settings and sending STOP command.")
    send_command('S\n')
    if pico_serial and pico_serial.is_open:
        pico_serial.close()
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)