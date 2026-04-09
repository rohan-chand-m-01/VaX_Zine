"""Trigger engine — detects status changes and fires output actions."""

import asyncio
from typing import Optional
from models.schemas import ProcessedReading
from services.sms_service import send_sms_alert
from services.report_service import generate_incident_report
from services.pdf_service import generate_vaccine_passport
from database.crud import (
    insert_incident, update_incident,
    get_recent_readings_for_report, get_temperature_stats
)
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.trigger_engine")


class TriggerEngine:
    """Monitors status changes and fires SMS, report, and PDF generation.

    Compares the current reading's status to the previous one. If a status
    escalation occurs (SAFE→WARNING, WARNING→CRITICAL, SAFE→CRITICAL),
    all output actions are fired in parallel.
    """

    def __init__(self):
        """Initialize with no previous status."""
        self._previous_status: Optional[str] = None
        self._latest_report: Optional[str] = None
        self._latest_pdf_path: Optional[str] = None

    async def evaluate(self, reading: ProcessedReading) -> None:
        """Evaluate a processed reading for status changes.

        Args:
            reading: The fully processed reading to evaluate.
        """
        current_status = reading.status
        previous_status = self._previous_status

        # Detect status change (escalation)
        status_changed = False
        if previous_status is not None and previous_status != current_status:
            # Any status change triggers actions
            status_changed = True
            logger.warning(
                f"STATUS CHANGE DETECTED: {previous_status} → {current_status} | "
                f"Risk: {reading.risk_score}, Temp: {reading.temp_internal}°C"
            )

        self._previous_status = current_status

        if not status_changed:
            return

        # Fire all output actions in parallel
        logger.info("Firing trigger actions...")

        try:
            # Create incident record first
            incident = await insert_incident(
                status_from=previous_status,
                status_to=current_status,
            )

            # Fire SMS, report, and PDF in parallel
            sms_task = asyncio.create_task(
                self._fire_sms(reading)
            )
            report_task = asyncio.create_task(
                self._fire_report(reading, previous_status, current_status, incident.id)
            )

            # Wait for SMS and report concurrently
            sms_result = await sms_task
            report_text = await report_task

            # Generate PDF with report text
            pdf_task = asyncio.create_task(
                self._fire_pdf(reading, incident.id, report_text)
            )
            pdf_path = await pdf_task

            # Store latest PDF path for dashboard access
            self._latest_pdf_path = pdf_path

            # Update incident with report and PDF path
            await update_incident(
                incident_id=incident.id,
                report_text=report_text,
                pdf_path=pdf_path,
            )

            # Broadcast trigger event to dashboard via WebSocket
            try:
                from api.websocket_manager import ws_manager
                await ws_manager.broadcast({
                    "_trigger_event": True,
                    "type": "status_change",
                    "from": previous_status,
                    "to": current_status,
                    "incident_id": incident.id,
                    "sms_sent": sms_result,
                    "pdf_generated": pdf_path is not None,
                    "pdf_path": pdf_path,
                })
            except Exception:
                pass  # WebSocket broadcast is best-effort

            logger.info(
                f"All trigger actions completed for incident {incident.id} | "
                f"SMS={'✅' if sms_result else '❌'} | "
                f"PDF={'✅ ' + (pdf_path or '') if pdf_path else '❌'}"
            )

        except Exception as e:
            logger.error(f"Trigger engine error: {e}")

    async def _fire_sms(self, reading: ProcessedReading) -> bool:
        """Fire SMS alert.

        Args:
            reading: Current processed reading.

        Returns:
            True if SMS was sent successfully.
        """
        try:
            result = await send_sms_alert(
                status=reading.status,
                risk_score=reading.risk_score,
                temp_internal=reading.temp_internal,
                eta_to_critical=reading.eta_to_critical,
                potency_percent=reading.potency_percent,
            )
            return result
        except Exception as e:
            logger.error(f"SMS trigger failed: {e}")
            return False

    async def _fire_report(
        self, reading: ProcessedReading,
        status_from: str, status_to: str,
        incident_id: int,
    ) -> str:
        """Generate incident report via Claude API.

        Args:
            reading: Current processed reading.
            status_from: Previous status.
            status_to: New status.
            incident_id: Associated incident ID.

        Returns:
            Generated report text.
        """
        try:
            recent_readings = await get_recent_readings_for_report(limit=20)
            report_text = await generate_incident_report(
                readings=recent_readings,
                current_status=reading.status,
                risk_score=reading.risk_score,
                vvm_damage=reading.vvm_damage,
                potency_percent=reading.potency_percent,
                exposure_minutes=reading.exposure_minutes,
                status_from=status_from,
                status_to=status_to,
            )
            self._latest_report = report_text
            return report_text
        except Exception as e:
            logger.error(f"Report generation trigger failed: {e}")
            fallback = "Report generation failed. Please review sensor data manually."
            self._latest_report = fallback
            return fallback

    async def _fire_pdf(
        self, reading: ProcessedReading,
        incident_id: int, report_text: str,
    ) -> str | None:
        """Generate vaccine passport PDF.

        Args:
            reading: Current processed reading.
            incident_id: Associated incident ID.
            report_text: Generated report text to include in PDF.

        Returns:
            Path to generated PDF, or None on failure.
        """
        try:
            recent_readings = await get_recent_readings_for_report(limit=20)
            temp_stats = await get_temperature_stats()
            pdf_path = await generate_vaccine_passport(
                incident_id=incident_id,
                readings=recent_readings,
                vvm_damage=reading.vvm_damage,
                potency_percent=reading.potency_percent,
                report_text=report_text,
                temp_stats=temp_stats,
            )
            return pdf_path
        except Exception as e:
            logger.error(f"PDF generation trigger failed: {e}")
            return None

    @property
    def latest_report(self) -> Optional[str]:
        """Get the most recently generated report text."""
        return self._latest_report

    @property
    def previous_status(self) -> Optional[str]:
        """Get the previous status."""
        return self._previous_status

    @property
    def latest_pdf_path(self) -> Optional[str]:
        """Get the most recently generated PDF path."""
        return self._latest_pdf_path


# Global singleton instance
trigger_engine = TriggerEngine()
