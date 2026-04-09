import random

# -----------------------------
# SIMULATION MODE (for testing)
# -----------------------------
SIMULATE = True


# -----------------------------
# REAL SENSOR SETUP (Raspberry Pi)
# -----------------------------
if not SIMULATE:
    import board
    import adafruit_dht
    from w1thermsensor import W1ThermSensor

    dht_device = adafruit_dht.DHT22(board.D17)
    ds18b20 = W1ThermSensor()


# -----------------------------
# SENSOR READ FUNCTION
# -----------------------------
def read_sensors():
    if SIMULATE:
        # Fake data for testing
        internal_temp = round(random.uniform(4, 10), 2)
        external_temp = round(random.uniform(25, 40), 2)
        humidity = round(random.uniform(40, 80), 2)

        return internal_temp, external_temp, humidity

    else:
        try:
            internal_temp = ds18b20.get_temperature()
            external_temp = dht_device.temperature
            humidity = dht_device.humidity

            return internal_temp, external_temp, humidity

        except Exception as e:
            print("Sensor read error:", e)
            return None, None, None