"""All database read/write operations."""

from datetime import datetime
from typing import Optional
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from models.database import async_session_factory
from models.orm_models import SensorReading, Incident
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.crud")


async def insert_reading(
    timestamp: str,
    temp_internal: float,
    temp_external: float,
    humidity: float,
    risk_score: float,
    status: str,
    vvm_damage: float,
    exposure_minutes: int,
    is_anomaly: bool,
    potency_percent: float,
    eta_to_critical: Optional[int] = None,
) -> SensorReading:
    """Insert a new sensor reading into the database.

    Args:
        All sensor reading fields.

    Returns:
        The created SensorReading ORM object.

    Raises:
        Exception: If database write fails.
    """
    try:
        async with async_session_factory() as session:
            reading = SensorReading(
                timestamp=datetime.fromisoformat(timestamp),
                temp_internal=temp_internal,
                temp_external=temp_external,
                humidity=humidity,
                risk_score=risk_score,
                status=status,
                vvm_damage=vvm_damage,
                exposure_minutes=exposure_minutes,
                is_anomaly=is_anomaly,
                potency_percent=potency_percent,
                eta_to_critical=eta_to_critical,
            )
            session.add(reading)
            await session.commit()
            await session.refresh(reading)
            logger.debug(f"Inserted reading id={reading.id}, status={status}, risk={risk_score}")
            return reading
    except Exception as e:
        logger.critical(f"Database write failed: {e}")
        raise


async def get_readings(limit: int = 60) -> list[dict]:
    """Get the last N sensor readings ordered by timestamp descending.

    Args:
        limit: Maximum number of readings to return.

    Returns:
        List of reading dictionaries.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(SensorReading)
                .order_by(desc(SensorReading.timestamp))
                .limit(limit)
            )
            readings = result.scalars().all()
            return [r.to_dict() for r in reversed(readings)]
    except Exception as e:
        logger.error(f"Failed to fetch readings: {e}")
        return []


async def get_latest_reading() -> Optional[dict]:
    """Get the single most recent sensor reading.

    Returns:
        Reading dictionary or None.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(SensorReading)
                .order_by(desc(SensorReading.timestamp))
                .limit(1)
            )
            reading = result.scalar_one_or_none()
            return reading.to_dict() if reading else None
    except Exception as e:
        logger.error(f"Failed to fetch latest reading: {e}")
        return None


async def get_temperature_stats() -> dict:
    """Get temperature statistics across all readings.

    Returns:
        Dictionary with min, max, mean temperatures.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(
                    func.min(SensorReading.temp_internal).label("min_temp"),
                    func.max(SensorReading.temp_internal).label("max_temp"),
                    func.avg(SensorReading.temp_internal).label("avg_temp"),
                    func.count(SensorReading.id).label("total_readings"),
                )
            )
            row = result.one()
            return {
                "min_temp": round(row.min_temp, 2) if row.min_temp else 0.0,
                "max_temp": round(row.max_temp, 2) if row.max_temp else 0.0,
                "avg_temp": round(row.avg_temp, 2) if row.avg_temp else 0.0,
                "total_readings": row.total_readings,
            }
    except Exception as e:
        logger.error(f"Failed to fetch temperature stats: {e}")
        return {"min_temp": 0.0, "max_temp": 0.0, "avg_temp": 0.0, "total_readings": 0}


async def insert_incident(
    status_from: Optional[str],
    status_to: Optional[str],
    report_text: Optional[str] = None,
    pdf_path: Optional[str] = None,
) -> Incident:
    """Insert a new incident record.

    Args:
        status_from: Previous status.
        status_to: New status.
        report_text: Claude-generated report text.
        pdf_path: Path to generated PDF.

    Returns:
        The created Incident ORM object.
    """
    try:
        async with async_session_factory() as session:
            incident = Incident(
                triggered_at=datetime.utcnow(),
                status_from=status_from,
                status_to=status_to,
                report_text=report_text,
                pdf_path=pdf_path,
            )
            session.add(incident)
            await session.commit()
            await session.refresh(incident)
            logger.info(f"Incident recorded: {status_from} → {status_to}, id={incident.id}")
            return incident
    except Exception as e:
        logger.critical(f"Failed to insert incident: {e}")
        raise


async def update_incident(incident_id: int, report_text: str = None, pdf_path: str = None) -> None:
    """Update an existing incident with report text or PDF path.

    Args:
        incident_id: ID of the incident to update.
        report_text: Generated report text.
        pdf_path: Path to generated PDF.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Incident).where(Incident.id == incident_id)
            )
            incident = result.scalar_one_or_none()
            if incident:
                if report_text is not None:
                    incident.report_text = report_text
                if pdf_path is not None:
                    incident.pdf_path = pdf_path
                await session.commit()
                logger.debug(f"Updated incident id={incident_id}")
    except Exception as e:
        logger.error(f"Failed to update incident {incident_id}: {e}")


async def get_incidents() -> list[dict]:
    """Get all incident records ordered by triggered_at descending.

    Returns:
        List of incident dictionaries.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Incident).order_by(desc(Incident.triggered_at))
            )
            incidents = result.scalars().all()
            return [i.to_dict() for i in incidents]
    except Exception as e:
        logger.error(f"Failed to fetch incidents: {e}")
        return []


async def get_latest_incident() -> Optional[dict]:
    """Get the most recent incident.

    Returns:
        Incident dictionary or None.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Incident).order_by(desc(Incident.triggered_at)).limit(1)
            )
            incident = result.scalar_one_or_none()
            return incident.to_dict() if incident else None
    except Exception as e:
        logger.error(f"Failed to fetch latest incident: {e}")
        return None


async def get_incident_by_id(incident_id: int) -> Optional[dict]:
    """Get an incident by its ID.

    Args:
        incident_id: The incident ID.

    Returns:
        Incident dictionary or None.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Incident).where(Incident.id == incident_id)
            )
            incident = result.scalar_one_or_none()
            return incident.to_dict() if incident else None
    except Exception as e:
        logger.error(f"Failed to fetch incident {incident_id}: {e}")
        return None


async def get_recent_readings_for_report(limit: int = 20) -> list[dict]:
    """Get recent readings for report generation.

    Args:
        limit: Number of recent readings.

    Returns:
        List of reading dictionaries.
    """
    return await get_readings(limit=limit)
