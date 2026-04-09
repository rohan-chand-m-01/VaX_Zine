"""Rolling baseline temperature learner."""

from collections import deque
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.baseline")


class BaselineLearner:
    """Maintains a rolling window of temperature readings to compute baseline statistics.

    The baseline mean and standard deviation are used by the risk engine and
    anomaly detector to identify deviations from normal operating conditions.
    """

    def __init__(self, window_size: int = None):
        """Initialize the baseline learner.

        Args:
            window_size: Number of readings to maintain in the rolling window.
                         Defaults to BASELINE_WINDOW from settings.
        """
        self.window_size = window_size or settings.BASELINE_WINDOW
        self._readings: deque = deque(maxlen=self.window_size)
        self._mean: float = 5.0  # Initial assumption: optimal temp
        self._std: float = 1.0   # Initial assumption: reasonable variance

    def update(self, temp_internal: float) -> None:
        """Add a new temperature reading and recompute statistics.

        Args:
            temp_internal: The internal temperature reading in Celsius.
        """
        self._readings.append(temp_internal)

        if len(self._readings) >= 2:
            self._mean = sum(self._readings) / len(self._readings)
            variance = sum((x - self._mean) ** 2 for x in self._readings) / len(self._readings)
            self._std = max(variance ** 0.5, 0.1)  # Prevent zero std
        elif len(self._readings) == 1:
            self._mean = self._readings[0]
            self._std = 1.0

        logger.debug(
            f"Baseline updated: mean={self._mean:.2f}°C, "
            f"std={self._std:.2f}°C, window={len(self._readings)}/{self.window_size}"
        )

    @property
    def mean(self) -> float:
        """Current rolling mean temperature."""
        return self._mean

    @property
    def std(self) -> float:
        """Current rolling standard deviation."""
        return self._std

    @property
    def deviation(self) -> float:
        """How far the latest reading is from the mean in std units."""
        if not self._readings:
            return 0.0
        latest = self._readings[-1]
        return abs(latest - self._mean) / self._std

    @property
    def window_fill(self) -> int:
        """Number of readings currently in the window."""
        return len(self._readings)


# Global singleton instance
baseline_learner = BaselineLearner()
