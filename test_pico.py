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

print("PICO_READY")
print("Pico (Kas) Hazir")
print("Waiting for commands...")

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
        print("DONE")

        # LED back on
        if led:
            led.on()

        # Log the command
        print(f"# Processed: {command}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\nStopping...")
        break
    except Exception as e:
        print(f"ERR:{e}")

print("Diagnostic ended")