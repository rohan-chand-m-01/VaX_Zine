"""AI-powered incident report generation using Anthropic Claude API."""

import anthropic
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.report_service")


async def generate_incident_report(
    readings: list[dict],
    current_status: str,
    risk_score: float,
    vvm_damage: float,
    potency_percent: float,
    exposure_minutes: int,
    status_from: str = None,
    status_to: str = None,
) -> str:
    """Generate a formal incident report using Claude API.

    Args:
        readings: List of recent reading dictionaries (last 20).
        current_status: Current system status.
        risk_score: Current risk score.
        vvm_damage: Current VVM damage score.
        potency_percent: Current potency percentage.
        exposure_minutes: Cumulative exposure minutes.
        status_from: Previous status (for status change context).
        status_to: New status (for status change context).

    Returns:
        Generated incident report text, or fallback message on failure.
    """
    if settings.ANTHROPIC_API_KEY == "your_key_here":
        logger.warning("Anthropic API key not configured — generating fallback report")
        return _generate_fallback_report(
            readings, current_status, risk_score, vvm_damage,
            potency_percent, exposure_minutes, status_from, status_to
        )

    # Format readings as a table for the prompt
    readings_table = _format_readings_table(readings)

    status_change_text = ""
    if status_from and status_to:
        status_change_text = f"\nSTATUS CHANGE: {status_from} → {status_to}\n"

    user_message = f"""Generate a formal vaccine cold-chain incident report based on the following data:

{status_change_text}
CURRENT STATUS: {current_status}
RISK SCORE: {risk_score}/100
VVM DAMAGE: {vvm_damage:.6f}
POTENCY: {potency_percent:.1f}%
CUMULATIVE EXPOSURE: {exposure_minutes} minutes outside safe range

RECENT SENSOR READINGS (last {len(readings)}):
{readings_table}

Please provide:
1. Incident Summary
2. Timeline of Events
3. Risk Assessment
4. Impact on Vaccine Potency
5. Recommended Actions
6. Compliance Status (WHO guidelines)
"""

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system="You are a WHO vaccine cold-chain compliance officer. Generate a formal, detailed incident report for a vaccine cold-chain breach event. Be precise, use technical language, and reference WHO guidelines where applicable.",
            messages=[
                {"role": "user", "content": user_message}
            ],
        )

        report_text = message.content[0].text
        logger.info("Claude incident report generated successfully")
        return report_text

    except anthropic.APIConnectionError as e:
        logger.error(f"Claude API connection error: {e}")
        return _generate_fallback_report(
            readings, current_status, risk_score, vvm_damage,
            potency_percent, exposure_minutes, status_from, status_to
        )
    except anthropic.RateLimitError as e:
        logger.error(f"Claude API rate limit: {e}")
        return _generate_fallback_report(
            readings, current_status, risk_score, vvm_damage,
            potency_percent, exposure_minutes, status_from, status_to
        )
    except anthropic.APIStatusError as e:
        logger.error(f"Claude API error: {e.status_code} — {e.message}")
        return _generate_fallback_report(
            readings, current_status, risk_score, vvm_damage,
            potency_percent, exposure_minutes, status_from, status_to
        )
    except Exception as e:
        logger.error(f"Unexpected report generation error: {e}")
        return _generate_fallback_report(
            readings, current_status, risk_score, vvm_damage,
            potency_percent, exposure_minutes, status_from, status_to
        )


def _format_readings_table(readings: list[dict]) -> str:
    """Format readings as a text table.

    Args:
        readings: List of reading dictionaries.

    Returns:
        Formatted text table string.
    """
    if not readings:
        return "No readings available."

    header = f"{'Timestamp':<22} {'Temp(°C)':>9} {'Humidity':>9} {'Risk':>6} {'Status':<10} {'VVM':>8}"
    lines = [header, "-" * len(header)]

    for r in readings[-20:]:
        ts = r.get("timestamp", "N/A")[:19]
        lines.append(
            f"{ts:<22} {r.get('temp_internal', 0):>9.1f} "
            f"{r.get('humidity', 0):>9.1f} {r.get('risk_score', 0):>6.1f} "
            f"{r.get('status', 'N/A'):<10} {r.get('vvm_damage', 0):>8.6f}"
        )

    return "\n".join(lines)


def _generate_fallback_report(
    readings: list[dict],
    current_status: str,
    risk_score: float,
    vvm_damage: float,
    potency_percent: float,
    exposure_minutes: int,
    status_from: str = None,
    status_to: str = None,
) -> str:
    """Generate a basic fallback report when Claude API is unavailable.

    Args:
        All same as generate_incident_report.

    Returns:
        Formatted fallback report text.
    """
    status_change = f"{status_from} → {status_to}" if status_from and status_to else "N/A"

    # Extract temp stats from readings
    temps = [r.get("temp_internal", 0) for r in readings if r.get("temp_internal")]
    min_temp = min(temps) if temps else 0
    max_temp = max(temps) if temps else 0
    avg_temp = sum(temps) / len(temps) if temps else 0

    report = f"""
═══════════════════════════════════════════════════════
    VACCINE COLD-CHAIN INCIDENT REPORT
    Generated: Auto-generated (AI service unavailable)
═══════════════════════════════════════════════════════

1. INCIDENT SUMMARY
─────────────────────
Status Change: {status_change}
Current Status: {current_status}
Risk Score: {risk_score}/100
Cumulative Exposure: {exposure_minutes} minutes outside safe range

2. TEMPERATURE ANALYSIS
─────────────────────
Min Temperature: {min_temp:.1f}°C
Max Temperature: {max_temp:.1f}°C
Average Temperature: {avg_temp:.1f}°C
Safe Range: 2.0°C – 8.0°C

3. VVM STATUS
─────────────────────
VVM Damage Score: {vvm_damage:.6f}
Remaining Potency: {potency_percent:.1f}%
Discard Threshold: 1.000000

4. RISK ASSESSMENT
─────────────────────
{"⚠ WARNING: Temperature excursion detected. Vaccines may be compromised." if current_status == "WARNING" else ""}
{"🚨 CRITICAL: Severe temperature breach. Immediate action required." if current_status == "CRITICAL" else ""}
{"✓ SAFE: All parameters within acceptable ranges." if current_status == "SAFE" else ""}

5. RECOMMENDED ACTIONS
─────────────────────
{"- Immediately isolate affected vaccine batches" if current_status == "CRITICAL" else "- Continue monitoring"}
{"- Initiate cold-chain recovery procedures" if current_status != "SAFE" else "- No action required"}
{"- Report to health authority within 24 hours" if current_status == "CRITICAL" else ""}
{"- Conduct VVM visual inspection" if vvm_damage > 0.3 else ""}
- Document incident for compliance records

6. COMPLIANCE STATUS
─────────────────────
WHO PQS E006 Temperature Monitoring: {"COMPLIANT" if current_status == "SAFE" else "NON-COMPLIANT"}
Readings Analyzed: {len(readings)}
═══════════════════════════════════════════════════════
"""
    return report.strip()
