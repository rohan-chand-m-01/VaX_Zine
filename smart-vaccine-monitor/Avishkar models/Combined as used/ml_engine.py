import joblib
import pandas as pd

# Load models
anomaly_model   = joblib.load("anomaly_model.pkl")
predictor_model = joblib.load("predictor_model.pkl")
potency_model   = joblib.load("potency_model.pkl")


# -------------------------
# MODEL 1 — Anomaly
# -------------------------
def run_anomaly(temp, humidity, temp_delta, unsafe_mins):
    try:
        features = pd.DataFrame([{
            "temp": temp,
            "humidity": humidity,
            "temp_delta": temp_delta,
            "unsafe_mins": unsafe_mins
        }])

        result = anomaly_model.predict(features)
        return 1 if result[0] == -1 else 0
    except Exception as e:
        return 0


# -------------------------
# MODEL 2 — Predictor
# -------------------------
def run_predictor(temp, temp_delta, humidity, unsafe_mins, damage, anomaly_flag):
    try:
        features = pd.DataFrame([{
            "temp": temp,
            "temp_delta": temp_delta,
            "humidity": humidity,
            "unsafe_mins": unsafe_mins,
            "damage": damage,
            "anomaly_flag": anomaly_flag
        }])

        prob = predictor_model.predict_proba(features)[0][1]
        return float(prob)
    except Exception:
        return 0.0


# -------------------------
# MODEL 3 — Potency
# -------------------------
def run_potency(damage, temp, unsafe_mins):
    try:
        features = pd.DataFrame([{
            "damage": damage,
            "temp": temp,
            "unsafe_mins": unsafe_mins
        }])

        potency = potency_model.predict(features)[0]
        return max(0, min(100, float(potency)))
    except Exception:
        return 100.0