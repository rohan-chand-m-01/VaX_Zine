#!/usr/bin/env python3
"""
Raspberry Pi MQTT Publisher for Smart Vaccine Monitor
=====================================================
Reads DS18B20 (internal temp) + DHT22 (external temp + humidity)
and publishes to MQTT broker for the FastAPI backend to consume.

Hardware wiring:
  - DS18B20 data pin → GPIO4 (1-Wire default)
  - DHT22 data pin   → GPIO17
  - Both sensors need pull-up resistors (4.7kΩ for DS18B20, 10kΩ for DHT22)

Setup on Pi:
  sudo raspi-config → Interface Options → 1-Wire → Enable → Reboot
  pip3 install paho-mqtt adafruit-circuitpython-dht w1thermsensor

Usage:
  python3 vaccine_publisher.py
"""

import json
import time
from datetime import datetime

import paho.mqtt.client as mqtt

# ─────────────────────────────────────────────
# CONFIGURATION — CHANGE THESE FOR YOUR SETUP
# ─────────────────────────────────────────────

# If Pi is connected to laptop via USB/Ethernet/WiFi, use laptop's IP.
# If broker runs on the Pi itself, use "localhost".
BROKER_HOST = "localhost"
BROKER_PORT = 1883
MQTT_TOPIC  = "vaccines/sensor/data"
READ_INTERVAL = 3  # seconds between readings

# Set to True to test without real sensors (random fake data)
SIMULATE = False

# ─────────────────────────────────────────────
# SENSOR SETUP
# ─────────────────────────────────────────────

if not SIMULATE:
    try:
        import board
        import adafruit_dht
        from w1thermsensor import W1ThermSensor

        dht_device = adafruit_dht.DHT22(board.D17)  # GPIO17
        ds18b20 = W1ThermSensor()                     # 1-Wire (GPIO4 default)
        print("✅ Sensors initialized: DS18B20 + DHT22")
    except Exception as e:
        print(f"⚠ Sensor init failed: {e}")
        print("  Switching to SIMULATE mode...")
        SIMULATE = True
else:
    print("📡 Running in SIMULATE mode (random data)")

if SIMULATE:
    import random


# ─────────────────────────────────────────────
# SENSOR READ FUNCTION
# ─────────────────────────────────────────────

def read_sensors():
    """Read temperature and humidity from sensors.

    Returns:
        Tuple of (temp_internal, temp_external, humidity) or (None, None, None) on error.
    """
    if SIMULATE:
        return (
            round(random.uniform(3, 12), 2),   # fridge temp
            round(random.uniform(22, 38), 2),  # room temp
            round(random.uniform(40, 80), 2),  # humidity
        )

    try:
        internal_temp = ds18b20.get_temperature()
        external_temp = dht_device.temperature
        humidity = dht_device.humidity

        # DHT22 sometimes returns None (timing issue — well known)
        if external_temp is None or humidity is None:
            print("⚠ DHT22 returned None, will retry...")
            return None, None, None

        return (
            round(internal_temp, 2),
            round(external_temp, 2),
            round(humidity, 2),
        )
    except RuntimeError as e:
        # DHT22 throws RuntimeError on checksum failures — normal, just retry
        print(f"⚠ Sensor read retry: {e}")
        return None, None, None
    except Exception as e:
        print(f"❌ Sensor error: {e}")
        return None, None, None


# ─────────────────────────────────────────────
# MQTT CONNECTION
# ─────────────────────────────────────────────

client = mqtt.Client(client_id="vaccine_pi_publisher")

def on_connect(client, userdata, flags, rc):
    codes = {0: "✅ Connected", 1: "❌ Bad protocol", 2: "❌ Rejected",
             3: "❌ Server unavailable", 4: "❌ Bad credentials", 5: "❌ Not authorized"}
    print(f"{codes.get(rc, f'❌ Unknown code {rc}')} to MQTT broker at {BROKER_HOST}:{BROKER_PORT}")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"⚠ Disconnected from broker (code {rc}). Reconnecting...")

client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.reconnect_delay_set(min_delay=1, max_delay=10)

try:
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()
except Exception as e:
    print(f"❌ Cannot connect to broker at {BROKER_HOST}:{BROKER_PORT}: {e}")
    print("   Make sure Mosquitto is running and IP is correct.")
    exit(1)


# ─────────────────────────────────────────────
# MAIN PUBLISHING LOOP
# ─────────────────────────────────────────────

print(f"\n📡 Publishing sensor data to '{MQTT_TOPIC}' every {READ_INTERVAL}s")
print(f"   Broker: {BROKER_HOST}:{BROKER_PORT}")
print(f"   Mode: {'SIMULATED' if SIMULATE else 'REAL SENSORS'}")
print("   Press Ctrl+C to stop\n")

consecutive_failures = 0
MAX_FAILURES = 10
last_good_reading = None

try:
    while True:
        temp_internal, temp_external, humidity = read_sensors()

        # Handle sensor failure
        if temp_internal is None:
            consecutive_failures += 1
            if consecutive_failures >= MAX_FAILURES:
                print(f"❌ {consecutive_failures} consecutive sensor failures!")
            # Optionally publish last known good reading
            if last_good_reading and consecutive_failures <= MAX_FAILURES:
                print(f"   ↳ Republishing last known good reading")
                client.publish(MQTT_TOPIC, json.dumps(last_good_reading), qos=1)
            time.sleep(READ_INTERVAL)
            continue

        consecutive_failures = 0

        # Build payload — MUST match backend SensorDataInput exactly
        payload = {
            "temp_internal": temp_internal,
            "temp_external": temp_external,
            "humidity": humidity,
        }
        last_good_reading = payload

        # Publish
        result = client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
        icon = "✅" if result.rc == 0 else "❌"

        print(
            f"{icon} [{datetime.now().strftime('%H:%M:%S')}] "
            f"temp={temp_internal}°C  ext={temp_external}°C  "
            f"hum={humidity}% → {MQTT_TOPIC}"
        )

        time.sleep(READ_INTERVAL)

except KeyboardInterrupt:
    print("\n\n🛑 Stopped by user")
    client.loop_stop()
    client.disconnect()
    if not SIMULATE:
        try:
            dht_device.exit()
        except:
            pass
    print("Goodbye!")
