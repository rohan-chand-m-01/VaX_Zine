"""Prediction models — delegates to Avishkar pre-trained RandomForest & LinearRegression.

Model 2 (Predictor):  RandomForestClassifier  → breach probability
Model 3 (Potency):    LinearRegression         → potency percentage

ETA-to-critical is derived from breach probability + temperature trend.
"""

import numpy as np
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.prediction_model")


class PredictionModel:
    """Wraps Avishkar predictor (Model 2) and potency (Model 3) models.

    Predictor features: [temp, temp_delta, humidity, unsafe_mins, damage, anomaly_flag]
    Potency features:   [damage, temp, unsafe_mins]
    """

    def __init__(self):
        """Initialize by importing the shared adapter singleton."""
        from ml.avishkar_adapter import avishkar
        self._adapter = avishkar
        self._prev_breach_prob: float = 0.0
        logger.info("PredictionModel initialized (Avishkar RandomForest + LinearRegression)")

    def predict_eta(
        self,
        temp_internal: float,
        exposure_minutes: int,
        vvm_damage: float,
        risk_score: float,
        temp_trend_5min: float,
        *,
        humidity: float = 50.0,
        temp_delta: float = 0.0,
        unsafe_mins: int = 0,
        damage: float = 0.0,
        anomaly_flag: int = 0,
    ) -> int | None:
        """Predict estimated minutes until CRITICAL status is reached.

        Uses the Avishkar breach predictor (Model 2) to estimate probability
        of reaching critical, then converts to an ETA.

        Args:
            temp_internal: Current internal temperature.
            exposure_minutes: Cumulative exposure time (legacy — used for heuristic).
            vvm_damage: Current VVM damage score (legacy — for compatibility).
            risk_score: Current risk score (0-100).
            temp_trend_5min: Temperature trend over last 5 minutes.
            humidity: Relative humidity (keyword-only, from pipeline).
            temp_delta: Temperature change from previous reading (keyword-only).
            unsafe_mins: Avishkar unsafe_mins with reset logic (keyword-only).
            damage: Avishkar cumulative damage (keyword-only).
            anomaly_flag: 1 if anomaly detected, 0 otherwise (keyword-only).

        Returns:
            Estimated minutes to CRITICAL, or None if already CRITICAL
            or no risk of reaching CRITICAL.
        """
        # If already CRITICAL, return None
        if risk_score >= 70:
            return None

        try:
            # Run Avishkar breach predictor
            raw_prob = self._adapter.predict_breach_probability(
                temp=temp_internal,
                temp_delta=temp_delta,
                humidity=humidity,
                unsafe_mins=unsafe_mins,
                damage=damage,
                anomaly_flag=anomaly_flag,
            )

            # Exponential smoothing to reduce jitter
            breach_prob = 0.7 * self._prev_breach_prob + 0.3 * raw_prob
            self._prev_breach_prob = breach_prob

            if breach_prob < 0.1:
                return None  # Very unlikely to reach critical

            # Estimate ETA from breach probability + temperature trend
            # Higher probability → shorter ETA
            SAFE_MAX = 8.0
            if temp_delta > 0 and temp_internal < SAFE_MAX:
                # Physics-based ETA: how long until temp hits SAFE_MAX
                eta_physics = int((SAFE_MAX - temp_internal) / temp_delta)
                eta_physics = max(0, min(eta_physics, 60))
            else:
                eta_physics = -1

            # Probability-based ETA
            remaining_risk = 70 - risk_score
            rate = max(0.1, temp_trend_5min * 5 + breach_prob * 10)
            eta_prob = max(1, int(remaining_risk / rate))
            eta_prob = min(120, eta_prob)

            # Use the shorter of the two estimates when physics ETA is valid
            if eta_physics >= 0:
                eta_minutes = min(eta_physics, eta_prob)
            else:
                eta_minutes = eta_prob

            logger.debug(
                f"ETA prediction: breach_prob={breach_prob:.2f}, "
                f"eta_physics={eta_physics}, eta_prob={eta_prob}, "
                f"final_eta={eta_minutes} min"
            )
            return eta_minutes

        except Exception as e:
            logger.error(f"ETA prediction failed: {e}")
            return None

    def predict_potency(
        self, damage: float, temp: float, unsafe_mins: int,
    ) -> float:
        """Predict remaining vaccine potency using Avishkar Model 3.

        Args:
            damage: Avishkar cumulative damage score.
            temp: Current internal temperature.
            unsafe_mins: Avishkar unsafe_mins (with reset logic).

        Returns:
            Potency percentage (0–100).
        """
        return self._adapter.predict_potency(damage, temp, unsafe_mins)


# Global singleton instance
prediction_model = PredictionModel()

# Temperature trend buffer for computing 5-minute trend
_temp_history: list[float] = []


def get_temp_trend(temp_internal: float) -> float:
    """Compute temperature trend over the last 5 readings.

    Args:
        temp_internal: Current temperature reading.

    Returns:
        Rate of temperature change (positive = warming).
    """
    _temp_history.append(temp_internal)
    if len(_temp_history) > 5:
        _temp_history.pop(0)

    if len(_temp_history) < 2:
        return 0.0

    # Simple linear trend: difference between newest and oldest
    trend = (_temp_history[-1] - _temp_history[0]) / len(_temp_history)
    return round(trend, 4)
