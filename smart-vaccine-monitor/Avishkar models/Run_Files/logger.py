import time
from datetime import datetime
import requests  # for FastAPI (optional)

from sensor_reader import read_sensors
from ml_engine import run_anomaly, run_predictor, run_potency

# -------------------------
# INITIAL STATE
# -------------------------

unsafe_mins = 0
damage = 0.0
safe_counter = 0  # for reset logic
prev_breach_prob = 0.0
prev_temp = None

SAFE_MAX = 8


# -------------------------
# DAMAGE MODEL
# -------------------------
def update_damage(temp, damage):
    if temp > SAFE_MAX:
        excess = temp - SAFE_MAX
        damage += 0.08 * (1 + 0.15 * excess)
    return min(damage, 10)


# -------------------------
# RISK ENGINE
# -------------------------
def compute_risk(temp, humidity, unsafe_mins, damage,
                 anomaly_flag, breach_prob, potency, external_temp):

    score = 0

    # Temperature
    if temp > SAFE_MAX:
        score += min(35, (temp - SAFE_MAX) * 8)
        score += 20   # 🔥 force stronger penalty

    # Duration
    score += min(20, unsafe_mins * 0.6)

    # Damage
    score += min(20, damage * 4)

    # Humidity spike
    if humidity > 75:
        score += 8

    # ML signals
    if anomaly_flag:
        score += 10

    score += breach_prob * 15

    # External stress
    if external_temp > 35:
        score += 5

    # Fridge failure detection
    if temp > SAFE_MAX and external_temp < 30:
        score += 5

    # Potency impact
    if potency < 80:
        score += 10
    if potency < 60:
        score += 15

    return min(score, 100)

# -------------------------
# MAIN LOOP
# -------------------------
while True:

    # -------------------------
    # SENSOR INPUT
    # -------------------------
    internal_temp, external_temp, humidity = read_sensors()

    if internal_temp is None:
        continue

    temp = float(internal_temp)
    external_temp = float(external_temp)
    humidity = float(humidity)
    
    # -------------------------
    # FEATURE ENGINEERING
    # -------------------------
    if prev_temp is None:
        temp_delta = 0
    else:
        temp_delta = temp - prev_temp

    # unsafe mins logic with reset
    if temp > SAFE_MAX:
        unsafe_mins += 1
        safe_counter = 0
    else:
        safe_counter += 1
        if safe_counter >= 3:
            unsafe_mins = 0

    # damage
    damage = update_damage(temp, damage)

    # -------------------------
    # ML MODELS
    # -------------------------
    anomaly_flag = run_anomaly(temp, humidity, temp_delta, unsafe_mins)

    
    raw_prob = run_predictor(
        temp, temp_delta, humidity,
        unsafe_mins, damage, anomaly_flag
    )
    breach_prob = 0.7 * prev_breach_prob + 0.3 * raw_prob
    prev_breach_prob = breach_prob


    potency_pct = run_potency(damage, temp, unsafe_mins)

    # -------------------------
    # ETA
    # -------------------------
    if temp_delta > 0 and temp < SAFE_MAX:
        eta = int((SAFE_MAX - temp) / temp_delta)
        eta = max(0, min(eta, 60))  # clamp to 0–60 mins
    else:
        eta = -1

    # -------------------------
    # RISK ENGINE
    # -------------------------
    risk = compute_risk(
        temp, humidity, unsafe_mins, damage,
        anomaly_flag, breach_prob, potency_pct, external_temp
    )

    # -------------------------
    # STATUS (FIXED)
    # -------------------------
    if temp >= 12:
        status = "CRITICAL"
        risk = 100
    elif temp > SAFE_MAX and unsafe_mins >= 2:
        status = "CRITICAL"
    elif risk < 40:
        status = "SAFE"
    elif risk < 70:
        status = "WARNING"
    else:
        status = "CRITICAL"
    # -------------------------
    # FINAL OUTPUT
    # -------------------------
    data = {
        "timestamp": datetime.now().isoformat(),

        "internal_temp": round(temp, 2),
        "external_temp": round(external_temp, 2),
        "humidity": round(humidity, 2),

        "unsafe_mins": unsafe_mins,
        "damage": round(damage, 2),

        "risk": round(risk, 1),
        "status": status,

        "anomaly": anomaly_flag,
        "breach_prob": round(breach_prob, 2),

        "potency": round(potency_pct, 1),
        "eta": eta
    }

    # -------------------------
    # PRINT (DEBUG)
    # -------------------------
    print("\n======================")
    for key, value in data.items():
        print(f"{key}: {value}")

    # -------------------------
    # SEND TO FASTAPI (OPTIONAL)
    # -------------------------
    try:
        # change URL later when FastAPI is ready
        requests.post("http://localhost:8000/update", json=data)
    except:
        pass

    # -------------------------
    # UPDATE STATE
    # -------------------------
    prev_temp = temp

    time.sleep(3)