"""SQLAlchemy ORM table definitions."""

from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, Text
from models.database import Base


class SensorReading(Base):
    """ORM model for sensor readings table."""

    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    temp_internal = Column(Float, nullable=False)
    temp_external = Column(Float, nullable=False)
    humidity = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    status = Column(String(10), nullable=False)
    vvm_damage = Column(Float, nullable=False)
    exposure_minutes = Column(Integer, nullable=False)
    is_anomaly = Column(Boolean, nullable=False)
    potency_percent = Column(Float, nullable=False)
    eta_to_critical = Column(Integer, nullable=True)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "temp_internal": self.temp_internal,
            "temp_external": self.temp_external,
            "humidity": self.humidity,
            "risk_score": self.risk_score,
            "status": self.status,
            "vvm_damage": round(self.vvm_damage, 6),
            "exposure_minutes": self.exposure_minutes,
            "is_anomaly": self.is_anomaly,
            "potency_percent": round(self.potency_percent, 2),
            "eta_to_critical": self.eta_to_critical,
        }


class Incident(Base):
    """ORM model for incidents table."""

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    triggered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status_from = Column(String(10), nullable=True)
    status_to = Column(String(10), nullable=True)
    report_text = Column(Text, nullable=True)
    pdf_path = Column(String(255), nullable=True)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "status_from": self.status_from,
            "status_to": self.status_to,
            "report_text": self.report_text,
            "pdf_path": self.pdf_path,
        }
