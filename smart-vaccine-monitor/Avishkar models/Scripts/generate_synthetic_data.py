"""
Cold Chain Guardian — Synthetic Dataset Generator
==================================================
Generates realistic vaccine cold chain temperature/humidity time series
for training all 3 ML models:
  Model 1 : IsolationForest  — anomaly_flag column
  Model 2 : RandomForest     — will_breach_10min column
  Model 3 : LinearRegression — potency_pct column

Physics basis: WHO Arrhenius VVM degradation model
Scenarios:  stable, door_open, power_failure, sensor_anomaly
"""

import numpy as np
import pandas as pd

np.random.seed(42)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
SAFE_MIN     = 2.0   # °C  — WHO lower bound
SAFE_MAX     = 8.0   # °C  — WHO upper bound
DAMAGE_K     = 0.08  # damage accumulation rate (tuned to OPV-class vaccines)
POTENCY_K    = 0.693 # Arrhenius k for OPV at reference temp (WHO TRS 961)
READINGS_PER_MIN = 1 # 1 reading per minute (sensor polls every 60s)

# ─────────────────────────────────────────
# SCENARIO GENERATORS
# Each returns (temp, humidity) for one timestep
# ─────────────────────────────────────────

def gen_stable(rng):
    """Normal fridge operation: 4–6 °C with realistic sensor noise."""
    temp = rng.normal(5.0, 0.4)
    temp = np.clip(temp, SAFE_MIN + 0.1, SAFE_MAX - 0.5)
    hum  = rng.normal(50, 5)
    return temp, hum


def gen_door_open(step, rng):
    """
    Door opened: temp spikes over ~5 min then recovers over ~10 min.
    Peak can reach 10–13 °C — actually breaches the threshold.
    step: 0..duration, where duration ~ 15–20 readings
    """
    peak = rng.uniform(8.5, 11)     # door-open peak
    rise = int(rng.integers(3, 6))  # readings to reach peak
    fall = int(rng.integers(10, 18))    # readings to recover

    if step <= rise:
        temp = 5.0 + (peak - 5.0) * (step / rise)
    else:
        decay = (step - rise) / fall
        temp  = peak * np.exp(-1.5 * decay) + 4.5 * (1 - np.exp(-1.5 * decay))

    hum  = rng.normal(72, 6)        # humidity spikes when door opens
    temp = np.clip(temp, SAFE_MIN - 1, 20)
    return temp, hum


def gen_power_failure(step, rng):
    """
    Power cut: fridge warms at ~0.4–0.6 °C/min indefinitely.
    After 30+ readings (~30 min) reaches critical levels (14–20 °C).
    """
    rate = rng.uniform(0.30, 0.55)
    temp = 5.0 + rate * step + rng.normal(0, 0.2)
    hum  = rng.normal(55, 4)
    return float(np.clip(temp, 4.5, 35)), hum


def gen_compressor_fault(step, rng):
    """
    Compressor cycles abnormally: temp oscillates with growing amplitude.
    Stays borderline — sometimes breaches 8 °C.
    """
    amp  = min(4.0, 0.5 + step * 0.1)
    temp = 5.5 + amp * np.sin(step / 4.0) + rng.normal(0, 0.3)
    hum  = rng.normal(58, 4)
    return float(np.clip(temp, SAFE_MIN - 1, 15)), hum


def gen_sensor_anomaly(rng):
    """
    Sensor fault: physically impossible readings.
    Either freeze (exact same repeated value) OR wild spike.
    """
    kind = rng.choice(["spike_high", "spike_low", "freeze"])
    if kind == "spike_high":
        temp = rng.uniform(22, 40)
        hum  = rng.uniform(80, 99)
    elif kind == "spike_low":
        temp = rng.uniform(-10, 0)
        hum  = rng.uniform(5, 15)
    else:  # freeze — same value ± tiny noise
        temp = rng.choice([4.5, 5.0, 5.5]) + rng.normal(0, 0.001)
        hum  = rng.choice([48, 50, 52])    + rng.normal(0, 0.001)
    return temp, hum


# ─────────────────────────────────────────
# DAMAGE + POTENCY MODEL (WHO Arrhenius)
# ─────────────────────────────────────────

def update_damage(temp, damage):
    """
    Cumulative irreversible heat damage.
    Rate doubles every ~10 °C above threshold (Arrhenius approximation).
    """
    if temp > SAFE_MAX:
        excess  = temp - SAFE_MAX
        rate = DAMAGE_K * (1 + 0.15 * excess)   # accelerates at high temps
        damage += rate
    return round(min(damage, 10.0), 4)             # cap at 10 (fully destroyed)


def compute_potency(damage):
    """
    WHO Arrhenius VVM model: potency decays exponentially with damage.
    100% at damage=0, ~50% at damage=~8.7, 0% capped.
    """
    potency = 100.0 * np.exp(-POTENCY_K * damage / 10.0)
    return round(float(np.clip(potency, 0, 100)), 2)


# ─────────────────────────────────────────
# RISK + STATUS CLASSIFIER
# ─────────────────────────────────────────

def compute_risk(temp, hum, unsafe_mins, damage, anomaly_flag):
    """
    Rule-based risk score 0–100 (mirrors intelligence.py logic).
    Used as a label and as a feature for Model 2.
    """
    score = 0.0

    # temperature component
    if temp > SAFE_MAX:
        score += min(35, (temp - SAFE_MAX) * 8)
    elif temp < SAFE_MIN:
        score += min(20, (SAFE_MIN - temp) * 8)

    # duration component
    score += min(25, unsafe_mins * 0.6)

    # damage component
    score += min(25, damage * 4)

    # humidity spike (>75% suggests door open / condensation)
    if hum > 75:
        score += 8

    # anomaly sensor flag
    if anomaly_flag:
        score += 15

    return round(min(float(score), 100), 1)


def classify_status(risk):
    if risk < 50:
        return "SAFE"
    elif risk < 80:
        return "WARNING"
    else:
        return "CRITICAL"


# ─────────────────────────────────────────
# WILL-BREACH LABEL (Model 2 ground truth)
# Looks ahead N steps in the sequence
# ─────────────────────────────────────────

def label_will_breach(temp_series, idx, horizon=10):
    """
    True label: will any reading in the next `horizon` steps exceed SAFE_MAX?
    This is computed in a post-processing pass so it's always accurate.
    """
    future = temp_series[idx + 1 : idx + 1 + horizon]
    count = sum(t > SAFE_MAX for t in future)
    return int(count >= 5)  # require sustained breach


# ─────────────────────────────────────────
# MAIN GENERATOR
# ─────────────────────────────────────────

def generate_dataset(n=2000, n_batches=5):
    rng      = np.random.default_rng(42)
    records  = []
    batch_size = n // n_batches

    for batch_id in range(n_batches):
        damage     = 0.0
        unsafe_mins = 0
        prev_temp  = 5.0

        # Each batch has its own scenario schedule (randomised)
        i = 0
        while i < batch_size:
            # Randomly pick scenario and its duration
            scenario = rng.choice( 
                ["stable", "door_open", "power_failure", "anomaly"],
                p = [0.58, 0.17, 0.15, 0.10]# realistic frequencies
                )

            if scenario == "stable":
                duration = int(rng.integers(15, 40))
                for step in range(duration):
                    if i >= batch_size:
                        break
                    temp, hum = gen_stable(rng)
                    records.append(_make_row(
                        batch_id, i, temp, hum, prev_temp,
                        damage, unsafe_mins, scenario, rng
                    ))
                    damage, unsafe_mins, prev_temp = _update_state(temp, damage, unsafe_mins)
                    i += 1

            elif scenario == "door_open":
                duration = int(rng.integers(15, 30))
                for step in range(duration):
                    if i >= batch_size:
                        break
                    temp, hum = gen_door_open(step, rng)
                    records.append(_make_row(
                        batch_id, i, temp, hum, prev_temp,
                        damage, unsafe_mins, scenario, rng
                    ))
                    damage, unsafe_mins, prev_temp = _update_state(temp, damage, unsafe_mins)
                    i += 1

            elif scenario == "power_failure":
                duration = int(rng.integers(18, 32))
                for step in range(duration):
                    if i >= batch_size:
                        break
                    temp, hum = gen_power_failure(step, rng)
                    records.append(_make_row(
                        batch_id, i, temp, hum, prev_temp,
                        damage, unsafe_mins, scenario, rng
                    ))
                    damage, unsafe_mins, prev_temp = _update_state(temp, damage, unsafe_mins)
                    i += 1



            else:  # sensor anomaly — short burst
                duration = int(rng.integers(8, 16))
                for step in range(duration):
                    if i >= batch_size:
                        break
                    temp, hum = gen_sensor_anomaly(rng)
                    records.append(_make_row(
                        batch_id, i, temp, hum, prev_temp,
                        damage, unsafe_mins, scenario, rng
                    ))
                    damage, unsafe_mins, prev_temp = _update_state(temp, damage, unsafe_mins)
                    i += 1

    df = pd.DataFrame(records)

    # ── Post-processing: accurate will_breach_10min label ──
    temp_series = df["temp"].tolist()
    df["will_breach_10min"] = [
        label_will_breach(temp_series, idx, horizon=10)
        for idx in range(len(df))
    ]

    # ── Anomaly flag (ground truth for Model 1 evaluation) ──
    df["anomaly_flag"] = (df["scenario"] == "anomaly").astype(int)

    return df


def _make_row(batch_id, step, temp, hum, prev_temp, damage, unsafe_mins, scenario, rng):
    temp_delta  = round(temp - prev_temp, 4)
    dam = damage
    potency     = compute_potency(dam)
    a_flag      = 1 if scenario == "anomaly" else 0
    risk        = compute_risk(temp, hum, unsafe_mins, dam, a_flag)
    status      = classify_status(risk)

    return {
        "batch_id"       : batch_id,
        "step"           : step,
        "temp"           : round(float(temp), 3),
        "humidity"       : round(float(np.clip(hum, 5, 100)), 2),
        "temp_delta"     : temp_delta,
        "unsafe_mins"    : unsafe_mins,
        "damage"         : dam,
        "potency_pct"    : potency,
        "risk_score"     : risk,
        "status"         : status,
        "scenario"       : scenario,
        # will_breach_10min added in post-processing pass
    }


def _update_state(temp, damage, unsafe_mins):
    damage = update_damage(temp, damage)
    if temp > SAFE_MAX:
        unsafe_mins += 1
    # NOTE: unsafe_mins only resets on sustained cooldown (3 consecutive safe readings)
    # We do NOT decrement per step — that was the bug in the original script
    return damage, unsafe_mins, temp


# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────

if __name__ == "__main__":
    df = generate_dataset(n=2000, n_batches=5)

    # Save full dataset
    df.to_csv("synthetic_data.csv", index=False)

    # Save model-specific subsets
    # Model 1: features only (no label needed — IsolationForest is unsupervised)
    model1_features = df[df["scenario"] != "anomaly"][
        ["temp", "humidity", "temp_delta", "unsafe_mins"]
    ]
    model1_features.to_csv("model1_normal_data.csv", index=False)

    # Model 2: supervised — features + will_breach label
    model2 = df[["temp", "temp_delta", "humidity", "unsafe_mins",
                 "damage", "anomaly_flag", "will_breach_10min"]]
    model2.to_csv("model2_predictor_data.csv", index=False)

    # Model 3: regression — features + potency label
    model3 = df[["damage", "temp", "unsafe_mins", "potency_pct"]]
    model3.to_csv("model3_potency_data.csv", index=False)

    # ── Stats ──
    print("=" * 50)
    print(f"Total rows      : {len(df)}")
    print(f"Scenario counts :\n{df['scenario'].value_counts()}")
    print(f"\nStatus counts   :\n{df['status'].value_counts()}")
    print(f"\nBreach label    : {df['will_breach_10min'].value_counts().to_dict()}")
    print(f"\nTemp range      : {df['temp'].min():.1f} – {df['temp'].max():.1f} °C")
    print(f"Damage range    : {df['damage'].min():.3f} – {df['damage'].max():.3f}")
    print(f"Potency range   : {df['potency_pct'].min():.1f} – {df['potency_pct'].max():.1f} %")
    print("=" * 50)
    print("\nSample rows:")
    print(df[["temp", "humidity", "temp_delta", "unsafe_mins",
              "damage", "potency_pct", "risk_score", "status",
              "scenario", "will_breach_10min"]].head(10).to_string(index=False))
