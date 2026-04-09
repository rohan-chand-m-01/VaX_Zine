"""Pydantic request/response models for API validation."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class SensorDataInput(BaseModel):
    """Input schema for raw sensor data from MQTT or simulator."""

    temp_internal: float = Field(..., description="Internal temperature in Celsius")
    temp_external: float = Field(..., description="External/ambient temperature in Celsius")
    humidity: float = Field(..., description="Relative humidity percentage")
    timestamp: Optional[str] = Field(default=None, description="ISO format timestamp")

    @field_validator("temp_internal")
    @classmethod
    def validate_temp_internal(cls, v: float) -> float:
        if v < -30 or v > 60:
            raise ValueError(f"temp_internal {v} out of valid range [-30, 60]")
        return v

    @field_validator("humidity")
    @classmethod
    def validate_humidity(cls, v: float) -> float:
        if v < 0 or v > 100:
            raise ValueError(f"humidity {v} out of valid range [0, 100]")
        return v


class ProcessedReading(BaseModel):
    """Full processed reading with all computed fields."""

    timestamp: str
    temp_internal: float
    temp_external: float
    humidity: float
    risk_score: float
    status: str
    vvm_damage: float
    exposure_minutes: int
    is_anomaly: bool
    potency_percent: float
    eta_to_critical: Optional[int] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    mode: str


class StatusResponse(BaseModel):
    """Current system status response."""

    risk_score: float
    status: str
    eta_to_critical: Optional[int]
    vvm_damage: float
    potency_percent: float
    exposure_minutes: int
    temp_internal: float
    timestamp: str


class SimulateTriggerRequest(BaseModel):
    """Request body for manual status trigger."""

    temp_internal: float = Field(default=15.0, description="Simulated internal temp")
    temp_external: float = Field(default=25.0, description="Simulated external temp")
    humidity: float = Field(default=50.0, description="Simulated humidity")
