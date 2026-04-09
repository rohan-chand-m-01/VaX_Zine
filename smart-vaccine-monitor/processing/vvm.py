"""VVM (Vaccine Vial Monitor) damage model using the Arrhenius equation.

The VVM damage score is a cumulative, irreversible measure of heat damage
to vaccine potency. It uses the Arrhenius equation to model the rate of
chemical degradation as a function of temperature and time.
"""

import math
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.vvm")

# Arrhenius equation constants
EA = 83_144.0          # Activation energy in J/mol (standard for vaccine VVM)
A = 1.0                # Pre-exponential factor
R = 8.314              # Universal gas constant in J/(mol·K)
T_REF_K = 277.15       # Reference temperature: 4°C in Kelvin
VVM_DISCARD_THRESHOLD = 1.0  # Discard vaccine when damage >= 1.0


class VVMDamageModel:
    """Accumulates vaccine vial monitor damage using the Arrhenius equation.

    The damage score is cumulative and NEVER resets — once damage is done,
    it cannot be undone. This models real-world vaccine degradation.
    """

    def __init__(self):
        """Initialize with zero accumulated damage."""
        self._cumulative_damage: float = 0.0
        self._reading_count: int = 0

    def update(self, temp_internal: float, delta_time_hours: float = 1.0 / 60.0) -> float:
        """Calculate and accumulate VVM damage for the current reading.

        Args:
            temp_internal: Internal temperature in Celsius.
            delta_time_hours: Time elapsed since last reading in hours.
                              Defaults to 1 minute (1/60 hour).

        Returns:
            Updated cumulative VVM damage score.
        """
        # Convert Celsius to Kelvin
        t_current_k = temp_internal + 273.15

        # Prevent division by zero or negative Kelvin
        if t_current_k <= 0:
            logger.warning(f"Invalid temperature {temp_internal}°C, skipping VVM update")
            return self._cumulative_damage

        try:
            # Arrhenius damage rate calculation
            exponent = -EA / R * (1.0 / t_current_k - 1.0 / T_REF_K)
            damage_rate = A * math.exp(exponent)

            # Accumulate damage (never subtract)
            damage_increment = damage_rate * delta_time_hours
            self._cumulative_damage += damage_increment
            self._reading_count += 1

            logger.debug(
                f"VVM update: temp={temp_internal:.1f}°C, "
                f"rate={damage_rate:.6f}, increment={damage_increment:.8f}, "
                f"total_damage={self._cumulative_damage:.6f}"
            )
        except (OverflowError, ValueError) as e:
            logger.warning(f"VVM calculation error at {temp_internal}°C: {e}")

        return self._cumulative_damage

    @property
    def damage(self) -> float:
        """Current cumulative VVM damage score."""
        return self._cumulative_damage

    @property
    def potency_percent(self) -> float:
        """Estimated remaining potency as a percentage.

        Returns:
            Float between 0 and 100.
        """
        return max(0.0, 100.0 - (self._cumulative_damage / VVM_DISCARD_THRESHOLD * 100.0))

    @property
    def is_discarded(self) -> bool:
        """Whether the vaccine should be discarded (damage >= threshold)."""
        return self._cumulative_damage >= VVM_DISCARD_THRESHOLD

    @property
    def reading_count(self) -> int:
        """Number of readings processed."""
        return self._reading_count


# Global singleton instance — damage persists across all readings
vvm_model = VVMDamageModel()
