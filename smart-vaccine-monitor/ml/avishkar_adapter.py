"""Avishkar Models Adapter — loads and wraps the 3 pre-trained .pkl models.

Models:
  1. anomaly_model.pkl   — IsolationForest  (temp, humidity, temp_delta, unsafe_mins)
  2. predictor_model.pkl — RandomForestClassifier (temp, temp_delta, humidity, unsafe_mins, damage, anomaly_flag)
  3. potency_model.pkl   — LinearRegression  (damage, temp, unsafe_mins)

The adapter also maintains stateful features that mirror the training-data
generation logic (temp_delta, unsafe_mins with reset, damage accumulation)
so that live sensor data produces inputs in the same distribution the models
were trained on.
"""

import os
import joblib
import pandas as pd
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.avishkar_adapter")

# ---------------------------------------------------------------------------
# Model file paths — relative to project root
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.join("Avishkar models")

ANOMALY_MODEL_PATH = os.path.join(_BASE_DIR, "anomaly_model.pkl")
PREDICTOR_MODEL_PATH = os.path.join(_BASE_DIR, "predictor_model.pkl")
POTENCY_MODEL_PATH = os.path.join(_BASE_DIR, "potency_model.pkl")

# Training-data constants (must match generate_synthetic_data.py)
SAFE_MAX = 8.0          # °C — WHO upper bound used during training
DAMAGE_K = 0.08         # damage rate constant
DAMAGE_CAP = 10.0       # max damage value


class AvishkarAdapter:
    """Loads avishkar pre-trained models and provides inference + state tracking."""

    def __init__(self):
        self.anomaly_model = None
        self.predictor_model = None
        self.potency_model = None

        # Pipeline state (mirrors logger.py / generate_synthetic_data.py)
        self._prev_temp: float | None = None
        self._unsafe_mins: int = 0
        self._safe_counter: int = 0       # consecutive safe readings for reset
        self._damage: float = 0.0

        self._load_models()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------
    def _load_models(self) -> None:
        """Load all 3 .pkl model files from the Avishkar models folder."""
        for name, path, attr in [
            ("Anomaly (IsolationForest)", ANOMALY_MODEL_PATH, "anomaly_model"),
            ("Predictor (RandomForest)", PREDICTOR_MODEL_PATH, "predictor_model"),
            ("Potency (LinearRegression)", POTENCY_MODEL_PATH, "potency_model"),
        ]:
            try:
                model = joblib.load(path)
                setattr(self, attr, model)
                logger.info(f"✅ Avishkar {name} loaded from {path}")
            except Exception as e:
                logger.error(f"❌ Failed to load Avishkar {name} from {path}: {e}")
                setattr(self, attr, None)

    # ------------------------------------------------------------------
    # State update — call ONCE per reading, BEFORE model inference
    # ------------------------------------------------------------------
    def update_state(self, temp_internal: float) -> None:
        """Update internal state features (temp_delta, unsafe_mins, damage).

        Must be called exactly once per sensor reading, before any predict calls.

        Args:
            temp_internal: Current internal temperature in Celsius.
        """
        # temp_delta
        if self._prev_temp is None:
            self._temp_delta = 0.0
        else:
            self._temp_delta = round(temp_internal - self._prev_temp, 4)
        self._prev_temp = temp_internal

        # unsafe_mins with reset after 3 consecutive safe readings
        if temp_internal > SAFE_MAX:
            self._unsafe_mins += 1
            self._safe_counter = 0
        else:
            self._safe_counter += 1
            if self._safe_counter >= 3:
                self._unsafe_mins = 0

        # damage accumulation (Avishkar formula)
        if temp_internal > SAFE_MAX:
            excess = temp_internal - SAFE_MAX
            self._damage += DAMAGE_K * (1 + 0.15 * excess)
        self._damage = min(self._damage, DAMAGE_CAP)

    # ------------------------------------------------------------------
    # Properties for external access
    # ------------------------------------------------------------------
    @property
    def temp_delta(self) -> float:
        return self._temp_delta if hasattr(self, "_temp_delta") else 0.0

    @property
    def unsafe_mins(self) -> int:
        return self._unsafe_mins

    @property
    def damage(self) -> float:
        return round(self._damage, 4)

    # ------------------------------------------------------------------
    # Model 1 — Anomaly Detection
    # ------------------------------------------------------------------
    def detect_anomaly(
        self, temp: float, humidity: float,
        temp_delta: float, unsafe_mins: int,
    ) -> bool:
        """Run IsolationForest anomaly detection.

        Args:
            temp: Internal temperature (°C).
            humidity: Relative humidity (%).
            temp_delta: Temperature change from previous reading.
            unsafe_mins: Cumulative minutes outside safe range (with reset).

        Returns:
            True if anomaly detected, False otherwise.
        """
        if self.anomaly_model is None:
            logger.warning("Anomaly model not loaded — returning False")
            return False

        try:
            features = pd.DataFrame([{
                "temp": temp,
                "humidity": humidity,
                "temp_delta": temp_delta,
                "unsafe_mins": unsafe_mins,
            }])
            result = self.anomaly_model.predict(features)
            is_anomaly = result[0] == -1
            if is_anomaly:
                logger.info(
                    f"🔴 ANOMALY DETECTED: temp={temp:.1f}°C, "
                    f"humidity={humidity:.1f}%, Δtemp={temp_delta:.2f}, "
                    f"unsafe_mins={unsafe_mins}"
                )
            return is_anomaly
        except Exception as e:
            logger.error(f"Anomaly prediction failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Model 2 — Breach Prediction
    # ------------------------------------------------------------------
    def predict_breach_probability(
        self, temp: float, temp_delta: float,
        humidity: float, unsafe_mins: int,
        damage: float, anomaly_flag: int,
    ) -> float:
        """Run RandomForest breach predictor.

        Args:
            temp: Internal temperature (°C).
            temp_delta: Temperature change from previous reading.
            humidity: Relative humidity (%).
            unsafe_mins: Cumulative minutes outside safe range (with reset).
            damage: Cumulative heat damage score.
            anomaly_flag: 1 if anomaly detected, 0 otherwise.

        Returns:
            Probability (0.0–1.0) of breaching safe range in the next 10 min.
        """
        if self.predictor_model is None:
            logger.warning("Predictor model not loaded — returning 0.0")
            return 0.0

        try:
            features = pd.DataFrame([{
                "temp": temp,
                "temp_delta": temp_delta,
                "humidity": humidity,
                "unsafe_mins": unsafe_mins,
                "damage": damage,
                "anomaly_flag": anomaly_flag,
            }])
            prob = self.predictor_model.predict_proba(features)[0][1]
            return float(prob)
        except Exception as e:
            logger.error(f"Breach prediction failed: {e}")
            return 0.0

    # ------------------------------------------------------------------
    # Model 3 — Potency Estimation
    # ------------------------------------------------------------------
    def predict_potency(
        self, damage: float, temp: float, unsafe_mins: int,
    ) -> float:
        """Run LinearRegression potency estimator.

        Args:
            damage: Cumulative heat damage score.
            temp: Internal temperature (°C).
            unsafe_mins: Cumulative minutes outside safe range (with reset).

        Returns:
            Estimated remaining potency percentage (clamped 0–100).
        """
        if self.potency_model is None:
            logger.warning("Potency model not loaded — returning 100.0")
            return 100.0

        try:
            features = pd.DataFrame([{
                "damage": damage,
                "temp": temp,
                "unsafe_mins": unsafe_mins,
            }])
            potency = self.potency_model.predict(features)[0]
            return max(0.0, min(100.0, float(potency)))
        except Exception as e:
            logger.error(f"Potency prediction failed: {e}")
            return 100.0

    # ------------------------------------------------------------------
    # Convenience: run full inference for a reading
    # ------------------------------------------------------------------
    def run_all(
        self, temp_internal: float, humidity: float,
    ) -> dict:
        """Run all 3 models after updating state.

        Call this once per sensor reading. It updates internal state,
        runs anomaly detection, breach prediction, and potency estimation.

        Args:
            temp_internal: Internal temperature (°C).
            humidity: Relative humidity (%).

        Returns:
            Dict with keys: is_anomaly, breach_prob, potency_pct,
            temp_delta, unsafe_mins, damage.
        """
        # Update state FIRST
        self.update_state(temp_internal)

        td = self.temp_delta
        um = self.unsafe_mins
        dm = self.damage

        # Model 1 — Anomaly
        is_anomaly = self.detect_anomaly(temp_internal, humidity, td, um)
        anomaly_flag = 1 if is_anomaly else 0

        # Model 2 — Breach prediction
        breach_prob = self.predict_breach_probability(
            temp_internal, td, humidity, um, dm, anomaly_flag,
        )

        # Model 3 — Potency
        potency_pct = self.predict_potency(dm, temp_internal, um)

        return {
            "is_anomaly": is_anomaly,
            "breach_prob": breach_prob,
            "potency_pct": round(potency_pct, 2),
            "temp_delta": td,
            "unsafe_mins": um,
            "damage": dm,
        }


# ---------------------------------------------------------------------------
# Global singleton — initialized on import
# ---------------------------------------------------------------------------
avishkar = AvishkarAdapter()
