"""Offline training script for ML models.

Run this script directly to retrain models on the simulation CSV data:
    python -m ml.trainer
"""

import os
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, GradientBoostingClassifier
import joblib
from utils.logger import setup_logger
from config.settings import settings

logger = setup_logger("vaccine_monitor.trainer")

ANOMALY_MODEL_PATH = os.path.join("ml", "models", "anomaly_model.joblib")
PREDICTION_MODEL_PATH = os.path.join("ml", "models", "prediction_model.joblib")


def train_anomaly_model(csv_path: str = None) -> None:
    """Train the anomaly detection model on CSV data.

    Args:
        csv_path: Path to the training CSV file.
    """
    csv_path = csv_path or settings.SIMULATION_CSV_PATH
    logger.info(f"Training anomaly model from {csv_path}...")

    try:
        df = pd.read_csv(csv_path)

        # Compute features
        temp_internal = df["temp_internal"].values
        temp_external = df["temp_external"].values
        humidity = df["humidity"].values

        # Compute baseline statistics for deviation
        rolling_mean = pd.Series(temp_internal).rolling(window=50, min_periods=1).mean().values
        rolling_std = pd.Series(temp_internal).rolling(window=50, min_periods=1).std().fillna(1.0).values
        rolling_std = np.maximum(rolling_std, 0.1)
        deviation = np.abs(temp_internal - rolling_mean) / rolling_std

        X = np.column_stack([temp_internal, temp_external, humidity, deviation])

        # Only train on "normal" data (first 60 rows are normal in our CSV)
        X_normal = X[:60]

        model = IsolationForest(
            contamination=0.05,
            random_state=42,
            n_estimators=100,
        )
        model.fit(X_normal)

        os.makedirs(os.path.dirname(ANOMALY_MODEL_PATH), exist_ok=True)
        joblib.dump(model, ANOMALY_MODEL_PATH)
        logger.info(f"Anomaly model saved to {ANOMALY_MODEL_PATH}")

    except Exception as e:
        logger.error(f"Anomaly model training failed: {e}")
        raise


def train_prediction_model(csv_path: str = None) -> None:
    """Train the prediction model on CSV data.

    Args:
        csv_path: Path to the training CSV file.
    """
    csv_path = csv_path or settings.SIMULATION_CSV_PATH
    logger.info(f"Training prediction model from {csv_path}...")

    try:
        df = pd.read_csv(csv_path)

        temp_internal = df["temp_internal"].values
        n = len(temp_internal)

        # Compute features
        exposure = np.zeros(n)
        vvm_damage = np.zeros(n)
        risk_score = np.zeros(n)
        trend = np.zeros(n)

        for i in range(n):
            if temp_internal[i] > 8.0 or temp_internal[i] < 2.0:
                exposure[i] = exposure[i - 1] + 1 if i > 0 else 1
            elif i > 0:
                exposure[i] = exposure[i - 1]

            # Simplified VVM damage accumulation
            vvm_damage[i] = (vvm_damage[i - 1] if i > 0 else 0) + max(0, (temp_internal[i] - 5.0)) * 0.001

            # Simplified risk
            dev = abs(temp_internal[i] - 5.0)
            risk_score[i] = min(100, dev * 10 + exposure[i] * 0.5 + vvm_damage[i] * 20)

            # Trend
            if i >= 5:
                trend[i] = (temp_internal[i] - temp_internal[i - 5]) / 5
            elif i > 0:
                trend[i] = temp_internal[i] - temp_internal[i - 1]

        X = np.column_stack([temp_internal, exposure, vvm_damage, risk_score, trend])

        # Labels: will reach critical within 10 readings
        y = np.zeros(n)
        for i in range(n):
            for j in range(i + 1, min(i + 11, n)):
                dev_j = abs(temp_internal[j] - 5.0)
                risk_j = min(100, dev_j * 10 + exposure[min(j, n - 1)] * 0.5)
                if risk_j >= 70:
                    y[i] = 1
                    break

        model = GradientBoostingClassifier(
            n_estimators=100,
            random_state=42,
            max_depth=4,
            learning_rate=0.1,
        )
        model.fit(X, y)

        os.makedirs(os.path.dirname(PREDICTION_MODEL_PATH), exist_ok=True)
        joblib.dump(model, PREDICTION_MODEL_PATH)
        logger.info(f"Prediction model saved to {PREDICTION_MODEL_PATH}")

    except Exception as e:
        logger.error(f"Prediction model training failed: {e}")
        raise


def train_all(csv_path: str = None) -> None:
    """Train all ML models.

    Args:
        csv_path: Optional path to CSV data file.
    """
    logger.info("Starting full ML training pipeline...")
    train_anomaly_model(csv_path)
    train_prediction_model(csv_path)
    logger.info("All ML models trained successfully")


if __name__ == "__main__":
    train_all()
