# robot_control_corrected_keys.py
# This version fixes the arrow key mapping issue.

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


# --- Keyboard Reading Functions ---
def get_key_press():
    """
    Detects single key presses, including arrow keys, and returns a
    simple, readable string like 'up', 'down', 'left', 'right', or ' '.
    """
    # Put terminal in cbreak mode to read keys instantly
    tty.setcbreak(sys.stdin.fileno())

    # Check if there's input waiting
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        char = sys.stdin.read(1)

        # Arrow keys send 3-character escape sequences (e.g., '\x1b[A')
        if char == '\x1b':
            sequence = sys.stdin.read(2)
            # --- THIS IS THE CORRECTED MAPPING ---
            key_map = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}
            return key_map.get(sequence)

        # For other keys like spacebar or 'q'
        return char

    return None


# --- Main Program ---
print("\n--- Robot Control Panel (Keys Corrected) ---")
print("   Use arrow keys to move.")
print("   Use SPACEBAR to stop.")
print("   Press 'q' to quit.")
print("----------------------------------------------\n")

# Save original terminal settings
old_settings = termios.tcgetattr(sys.stdin)

try:
    last_sent_command = None
    while True:
        key = get_key_press()  # Use the combined function

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

        # To make the robot stop when no key is pressed, uncomment the lines below
        # else:
        #     if last_sent_command != 'S\n': # Send STOP only once
        #          current_command = 'S\n'

        if current_command and current_command != last_sent_command:
            send_command(current_command)
            last_sent_command = current_command

        time.sleep(0.02)

finally:
    # Always restore original terminal settings and stop the robot
    print("Restoring terminal settings and sending STOP command.")
    send_command('S\n')
    if pico_serial and pico_serial.is_open:
        pico_serial.close()
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)