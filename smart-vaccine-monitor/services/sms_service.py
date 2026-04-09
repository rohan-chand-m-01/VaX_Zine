"""SMS alert service — supports Twilio and Fast2SMS."""

import httpx
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.sms_service")


async def send_sms_alert(
    status: str,
    risk_score: float,
    temp_internal: float,
    eta_to_critical: int | None = None,
    potency_percent: float = 100.0,
) -> bool:
    """Send an SMS alert via configured provider (Twilio or Fast2SMS).

    Args:
        status: Current status (SAFE, WARNING, CRITICAL).
        risk_score: Current risk score (0-100).
        temp_internal: Current internal temperature.
        eta_to_critical: Minutes until CRITICAL, or None.
        potency_percent: Current vaccine potency percentage.

    Returns:
        True if SMS was sent successfully, False otherwise.
    """
    eta_message = ""
    if eta_to_critical is not None:
        eta_message = f" ETA to CRITICAL: {eta_to_critical} min."
    elif status == "CRITICAL":
        eta_message = " Status is CRITICAL NOW."

    message = (
        f"CRITICAL ALERT: Temp {temp_internal}°C, "
        f"Risk {risk_score}%, "
        f"Potency {potency_percent:.1f}%. "
        f"Immediate action required.{eta_message} "
        f"PDF incident report generated — check dashboard."
    )

    provider = settings.SMS_PROVIDER.lower()

    if provider == "twilio":
        return await _send_via_twilio(message)
    elif provider == "fast2sms":
        return await _send_via_fast2sms(message)
    else:
        logger.warning(f"Unknown SMS provider: {provider} — SMS skipped")
        logger.info(f"[SMS WOULD SEND] {message}")
        return False


async def _send_via_twilio(message: str) -> bool:
    """Send SMS via Twilio REST API.

    Args:
        message: The SMS message text.

    Returns:
        True if sent successfully.
    """
    sid = settings.TWILIO_ACCOUNT_SID
    token = settings.TWILIO_AUTH_TOKEN
    from_num = settings.TWILIO_FROM_NUMBER
    to_num = settings.TWILIO_TO_NUMBER

    # Validate credentials are real (Twilio SIDs always start with 'AC')
    if not sid or not sid.startswith("AC") or not token or token == "your_token_here":
        logger.warning("Twilio credentials not configured — SMS alert skipped (logged only)")
        logger.info(f"[SMS WOULD SEND] → {to_num} | {message}")
        return False

    logger.info(f"Sending Twilio SMS → {to_num} from {from_num}")
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{sid}/Messages.json"
    )

    payload = {
        "To": to_num,
        "From": from_num,
        "Body": message,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                data=payload,
                auth=(sid, token),
            )
            response.raise_for_status()
            result = response.json()
            msg_sid = result.get("sid", "unknown")
            logger.info(f"✅ Twilio SMS sent successfully! SID: {msg_sid} → {to_num}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Twilio API error: {e.response.status_code} — {e.response.text[:200]}")
        return False
    except httpx.RequestError as e:
        logger.error(f"Twilio request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected Twilio SMS error: {e}")
        return False


async def _send_via_fast2sms(message: str) -> bool:
    """Send SMS via Fast2SMS REST API.

    Args:
        message: The SMS message text.

    Returns:
        True if sent successfully.
    """
    if settings.FAST2SMS_API_KEY == "your_key_here":
        logger.warning("Fast2SMS API key not configured — SMS alert skipped (logged only)")
        logger.info(f"[SMS WOULD SEND] {message}")
        return False

    headers = {
        "authorization": settings.FAST2SMS_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "route": "q",
        "message": message,
        "language": "english",
        "numbers": settings.FAST2SMS_PHONE_NUMBER,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://www.fast2sms.com/dev/bulkV2",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"✅ Fast2SMS sent successfully: {result}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Fast2SMS API error: {e.response.status_code} — {e.response.text[:200]}")
        return False
    except httpx.RequestError as e:
        logger.error(f"Fast2SMS request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected Fast2SMS error: {e}")
        return False
