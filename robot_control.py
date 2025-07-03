# robot_control_stable.py
# This version fixes the critical bug where tty.setcbreak was called in a loop.

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
def get_key_press():
    """
    Reads a single keystroke from the terminal.
    This function now assumes the terminal is already in cbreak mode.
    """
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        char = sys.stdin.read(1)
        if char == '\x1b':  # Arrow key escape sequence
            sequence = sys.stdin.read(2)
            key_map = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}
            return key_map.get(sequence)
        return char
    return None


# --- Main Program ---
print("\n--- Robot Control Panel (Stable Version) ---")
print("   Use arrow keys to move.")
print("   Use SPACEBAR to stop.")
print("   Press 'q' to quit.")
print("----------------------------------------------\n")

# Save original terminal settings
old_settings = termios.tcgetattr(sys.stdin)

try:
    # Set terminal to cbreak mode ONLY ONCE before the loop starts.
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

        # If no key is pressed, the robot continues its last command.
        # To make it stop when no key is pressed, uncomment the lines below.
        # else:
        #     if last_sent_command != 'S\n':
        #         current_command = 'S\n'

        if current_command and current_command != last_sent_command:
            send_command(current_command)
            last_sent_command = current_command

        time.sleep(0.02)

finally:
    # Always restore original terminal settings when the program exits.
    print("Restoring terminal settings and sending STOP command.")
    send_command('S\n')
    if pico_serial and pico_serial.is_open:
        pico_serial.close()
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)