#!/usr/bin/env python3
"""
DIAGNOSTIC VERSION - Simplified Pico code for testing
Upload this as main.py to Pico if the full version doesn't work
"""

from machine import Pin
import sys
import time

# Immediately send ready signals
print("\n" + "=" * 60)
print("PICO DIAGNOSTIC MODE")
print("=" * 60)
sys.stdout.flush()

print("PICO_READY")
sys.stdout.flush()

print("Pico (Kas) Hazir")
sys.stdout.flush()

print("Waiting for commands...")
sys.stdout.flush()

# Blink LED to show we're alive
try:
    led = Pin("LED", Pin.OUT)
except:
    try:
        led = Pin(25, Pin.OUT)
    except:
        led = None

if led:
    for _ in range(5):
        led.on()
        time.sleep(0.1)
        led.off()
        time.sleep(0.1)
    led.on()

# Simple command loop
while True:
    try:
        line = sys.stdin.readline()

        if not line:
            time.sleep(0.01)
            continue

        command = line.strip()

        if not command:
            continue

        # LED feedback
        if led:
            led.off()

        # Always respond with ACK + DONE
        print("ACK")
        sys.stdout.flush()

        print("DONE")
        sys.stdout.flush()

        # LED back on
        if led:
            led.on()

        # Log the command
        print(f"# Processed: {command}", file=sys.stderr)
        sys.stderr.flush()

    except KeyboardInterrupt:
        print("\nStopping...")
        break
    except Exception as e:
        print(f"ERR:{e}")
        sys.stdout.flush()

print("Diagnostic ended")