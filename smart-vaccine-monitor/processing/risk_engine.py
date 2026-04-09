"""Risk engine — combines multiple signals into a composite risk score."""

from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.risk_engine")

OPTIMAL_TEMP = 5.0  # Optimal storage temperature in Celsius


def compute_risk_score(
    temp_internal: float,
    baseline_mean: float,
    baseline_std: float,
    exposure_minutes: int,
    vvm_damage: float,
    is_anomaly: bool,
) -> tuple[float, str]:
    """Compute a composite risk score from multiple signal sources.

    The risk score ranges from 0 (perfectly safe) to 100 (critical danger).
    Four signals contribute to the total:
      - Temperature deviation from optimal (0–40 points)
      - Cumulative exposure time outside safe range (0–30 points)
      - VVM damage accumulation (0–20 points)
      - Anomaly detection flag (0–10 points)

    Args:
        temp_internal: Current internal temperature reading.
        baseline_mean: Rolling baseline mean temperature.
        baseline_std: Rolling baseline standard deviation.
        exposure_minutes: Cumulative minutes outside safe range.
        vvm_damage: Cumulative VVM damage score.
        is_anomaly: Whether the current reading is flagged as anomalous.

    Returns:
        Tuple of (risk_score, status_string).
        Status is one of "SAFE", "WARNING", or "CRITICAL".
    """
    # Temperature deviation signal (0-40 points)
    deviation = abs(temp_internal - OPTIMAL_TEMP)
    temp_score = min(40.0, deviation * 10.0)

    # Exposure signal (0-30 points)
    exposure_score = min(30.0, exposure_minutes * 0.5)

    # VVM damage signal (0-20 points)
    vvm_score = min(20.0, vvm_damage * 20.0)

    # Anomaly signal (0-10 points)
    anomaly_score = 10.0 if is_anomaly else 0.0

    # Composite risk score
    risk_score = temp_score + exposure_score + vvm_score + anomaly_score
    risk_score = min(100.0, max(0.0, risk_score))  # Clamp to [0, 100]

    # Determine status
    if risk_score < 30:
        status = "SAFE"
    elif risk_score < 70:
        status = "WARNING"
    else:
        status = "CRITICAL"

    logger.debug(
        f"Risk computed: score={risk_score:.1f} ({status}) | "
        f"temp_score={temp_score:.1f}, exposure_score={exposure_score:.1f}, "
        f"vvm_score={vvm_score:.1f}, anomaly_score={anomaly_score:.1f}"
    )

    return round(risk_score, 2), status
