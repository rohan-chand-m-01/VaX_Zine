"""Anomaly detection — delegates to Avishkar pre-trained IsolationForest model.

Features: [temp, humidity, temp_delta, unsafe_mins]
Output:   True if anomaly, False otherwise.
"""

import os
import numpy as np
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.anomaly_detector")


class AnomalyDetector:
    """Wraps the Avishkar IsolationForest model for real-time anomaly detection.

    Features used: [temp, humidity, temp_delta, unsafe_mins]
    """

    def __init__(self):
        """Initialize by importing the shared adapter singleton."""
        from ml.avishkar_adapter import avishkar
        self._adapter = avishkar
        logger.info("AnomalyDetector initialized (Avishkar IsolationForest)")

    def predict(
        self,
        temp_internal: float,
        humidity: float,
        temp_delta: float,
        unsafe_mins: int,
    ) -> bool:
        """Predict whether a reading is anomalous.

        Args:
            temp_internal: Internal temperature in Celsius.
            humidity: Relative humidity percentage.
            temp_delta: Temperature change from previous reading.
            unsafe_mins: Cumulative unsafe minutes (with reset logic).

        Returns:
            True if the reading is anomalous, False otherwise.
        """
        return self._adapter.detect_anomaly(
            temp=temp_internal,
            humidity=humidity,
            temp_delta=temp_delta,
            unsafe_mins=unsafe_mins,
        )

    def retrain(self, X: np.ndarray) -> None:
        """Retrain stub — Avishkar models are pre-trained, no retraining."""
        logger.warning("Retrain called but Avishkar models are frozen — skipping")


# Global singleton instance
anomaly_detector = AnomalyDetector()
