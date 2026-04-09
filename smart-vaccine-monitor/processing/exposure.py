"""Time-at-risk exposure tracker."""

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.exposure")


class ExposureTracker:
    """Tracks cumulative time that temperature has been outside the safe range.

    Each reading that falls outside [SAFE_TEMP_MIN, SAFE_TEMP_MAX] increments
    the exposure counter. In simulation mode, each reading represents
    SIMULATION_INTERVAL_SECONDS of elapsed time.
    """

    def __init__(self):
        """Initialize the exposure tracker with zero exposure."""
        self._exposure_minutes: int = 0
        self._consecutive_out_of_range: int = 0

    def update(self, temp_internal: float) -> int:
        """Check if the temperature is out of safe range and update exposure.

        Args:
            temp_internal: Internal temperature reading in Celsius.

        Returns:
            Current cumulative exposure in minutes.
        """
        if temp_internal > settings.SAFE_TEMP_MAX or temp_internal < settings.SAFE_TEMP_MIN:
            # Each reading represents approximately 1 minute of exposure
            # In sim mode, readings come every SIMULATION_INTERVAL_SECONDS
            increment = max(1, settings.SIMULATION_INTERVAL_SECONDS // 60) if settings.SIMULATION_MODE else 1
            increment = max(increment, 1)  # At least 1 minute per out-of-range reading
            self._exposure_minutes += increment
            self._consecutive_out_of_range += 1
            logger.debug(
                f"Exposure incremented: {self._exposure_minutes} min total, "
                f"{self._consecutive_out_of_range} consecutive out-of-range readings"
            )
        else:
            self._consecutive_out_of_range = 0

        return self._exposure_minutes

    @property
    def exposure_minutes(self) -> int:
        """Current cumulative exposure in minutes."""
        return self._exposure_minutes

    @property
    def consecutive_out_of_range(self) -> int:
        """Number of consecutive out-of-range readings."""
        return self._consecutive_out_of_range

    def reset(self) -> None:
        """Reset the exposure tracker. Use with caution — only for testing."""
        self._exposure_minutes = 0
        self._consecutive_out_of_range = 0
        logger.info("Exposure tracker reset")


# Global singleton instance
exposure_tracker = ExposureTracker()
