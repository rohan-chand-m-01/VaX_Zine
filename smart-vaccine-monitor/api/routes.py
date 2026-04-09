"""REST API endpoints and WebSocket handler."""

import os
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from models.schemas import SensorDataInput, ProcessedReading, SimulateTriggerRequest
from processing.pipeline import process_reading
from database.crud import (
    get_readings, get_latest_reading, get_incidents,
    get_latest_incident, get_incident_by_id, insert_reading
)
from api.websocket_manager import ws_manager
from triggers.trigger_engine import trigger_engine
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.routes")

router = APIRouter()

# Global store for external Raspberry Pi data
latest_data = {}

@router.post("/api/push")
async def push_data(data: dict):
    """Receive data from external Raspberry Pi, save to DB and trigger alerts."""
    global latest_data
    latest_data = data

    try:
        # We wrap the pushed data into our internal ProcessedReading schema
        # to ensure it can be handled by the trigger engine and database.
        processed = ProcessedReading(
            timestamp=data.get("timestamp", datetime.utcnow().isoformat()),
            temp_internal=data.get("internal_temp", 0),
            temp_external=data.get("external_temp", 0),
            humidity=data.get("humidity", 0),
            risk_score=data.get("risk", 0),
            status=data.get("status", "SAFE"),
            vvm_damage=data.get("damage", 0),
            exposure_minutes=data.get("unsafe_mins", 0),
            is_anomaly=data.get("anomaly") == 1 or data.get("anomaly") is True,
            potency_percent=data.get("potency", 100.0),
            eta_to_critical=data.get("eta")
        )

        # 1. Save to Database
        await insert_reading(
            timestamp=processed.timestamp,
            temp_internal=processed.temp_internal,
            temp_external=processed.temp_external,
            humidity=processed.humidity,
            risk_score=processed.risk_score,
            status=processed.status,
            vvm_damage=processed.vvm_damage,
            exposure_minutes=processed.exposure_minutes,
            is_anomaly=processed.is_anomaly,
            potency_percent=processed.potency_percent,
            eta_to_critical=processed.eta_to_critical,
        )

        # 2. Evaluate Triggers (Fires SMS and Generates PDF/Report)
        await trigger_engine.evaluate(processed)

        # 3. Broadcast to UI via WebSocket
        await ws_manager.broadcast(processed.model_dump())

        logger.info(f"External data processed: status={processed.status}, risk={processed.risk_score}")

    except Exception as e:
        logger.error(f"Failed to process external data push: {e}")

    return {"status": "received"}


@router.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        JSON with status and current mode.
    """
    return {
        "status": "ok",
        "mode": "simulation" if settings.SIMULATION_MODE else "live",
        "websocket_connections": ws_manager.connection_count,
    }


@router.get("/api/readings")
async def api_get_readings(limit: int = Query(default=60, ge=1, le=500)):
    """Get the last N sensor readings.

    Args:
        limit: Maximum number of readings (default 60, max 500).

    Returns:
        JSON array of reading objects.
    """
    readings = await get_readings(limit=limit)
    return readings


@router.get("/api/readings/latest")
def get_latest():
    """Get the single most recent sensor reading from external source.

    Returns:
        JSON reading object.
    """
    return latest_data


@router.get("/api/status")
async def api_get_status():
    """Get current system status summary.

    Returns:
        JSON with risk score, status, ETA, VVM damage.
    """
    reading = await get_latest_reading()
    if reading is None:
        return {
            "risk_score": 0,
            "status": "SAFE",
            "eta_to_critical": None,
            "vvm_damage": 0,
            "potency_percent": 100.0,
            "exposure_minutes": 0,
            "temp_internal": 0,
            "timestamp": datetime.utcnow().isoformat(),
        }
    return {
        "risk_score": reading["risk_score"],
        "status": reading["status"],
        "eta_to_critical": reading["eta_to_critical"],
        "vvm_damage": reading["vvm_damage"],
        "potency_percent": reading["potency_percent"],
        "exposure_minutes": reading["exposure_minutes"],
        "temp_internal": reading["temp_internal"],
        "timestamp": reading["timestamp"],
    }


@router.get("/api/incidents")
async def api_get_incidents():
    """Get all incident records.

    Returns:
        JSON array of incident objects.
    """
    incidents = await get_incidents()
    return incidents


@router.get("/api/report/latest")
async def api_get_latest_report():
    """Get the latest Claude-generated incident report text.

    Returns:
        JSON with report text.
    """
    # First check trigger engine for in-memory report
    if trigger_engine.latest_report:
        return {"report": trigger_engine.latest_report}

    # Fall back to database
    incident = await get_latest_incident()
    if incident and incident.get("report_text"):
        return {"report": incident["report_text"]}

    return {"report": "No incident reports generated yet. The system will generate a report when a status change is detected."}


@router.get("/api/pdf/{incident_id}")
async def api_download_pdf(incident_id: int):
    """Download a vaccine passport PDF by incident ID.

    Args:
        incident_id: The incident ID.

    Returns:
        PDF file download or 404.
    """
    incident = await get_incident_by_id(incident_id)
    if incident is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Incident {incident_id} not found"}
        )

    pdf_path = incident.get("pdf_path")
    if pdf_path is None or not os.path.exists(pdf_path):
        return JSONResponse(
            status_code=404,
            content={"detail": f"PDF not available for incident {incident_id}"}
        )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"vaccine_passport_{incident_id}.pdf",
    )


@router.get("/api/pdf/latest/download")
async def api_download_latest_pdf():
    """Download the most recently generated vaccine passport PDF.

    Checks trigger engine first, then falls back to scanning
    the reports directory for the newest PDF file.

    Returns:
        PDF file download or 404.
    """
    pdf_path = trigger_engine.latest_pdf_path

    # Fallback: find newest PDF in reports directory
    if pdf_path is None or not os.path.exists(pdf_path):
        reports_dir = "reports"
        if os.path.isdir(reports_dir):
            pdf_files = [
                os.path.join(reports_dir, f)
                for f in os.listdir(reports_dir)
                if f.endswith(".pdf")
            ]
            if pdf_files:
                pdf_path = max(pdf_files, key=os.path.getmtime)

    if pdf_path is None or not os.path.exists(pdf_path):
        return JSONResponse(
            status_code=404,
            content={"detail": "No PDF reports available yet. A report is generated automatically when a status change occurs."}
        )

    filename = os.path.basename(pdf_path)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/api/pdf/latest/status")
async def api_latest_pdf_status():
    """Check if a PDF report is available for download.

    Returns:
        JSON with availability status and path info.
    """
    pdf_path = trigger_engine.latest_pdf_path

    # Fallback: find newest PDF in reports directory
    if pdf_path is None or not os.path.exists(pdf_path if pdf_path else ""):
        reports_dir = "reports"
        if os.path.isdir(reports_dir):
            pdf_files = [
                os.path.join(reports_dir, f)
                for f in os.listdir(reports_dir)
                if f.endswith(".pdf")
            ]
            if pdf_files:
                pdf_path = max(pdf_files, key=os.path.getmtime)

    available = pdf_path is not None and os.path.exists(pdf_path)
    return {
        "available": available,
        "filename": os.path.basename(pdf_path) if available else None,
    }


@router.post("/api/simulate/trigger")
async def api_simulate_trigger(request: SimulateTriggerRequest = None):
    """Manually trigger a simulated reading for demo purposes.

    Args:
        request: Optional custom sensor values.

    Returns:
        JSON with processed reading data.
    """
    if request is None:
        request = SimulateTriggerRequest()

    sensor_data = SensorDataInput(
        temp_internal=request.temp_internal,
        temp_external=request.temp_external,
        humidity=request.humidity,
        timestamp=datetime.utcnow().isoformat(),
    )

    try:
        # Process the reading
        processed = await process_reading(sensor_data)

        # Write to database
        await insert_reading(
            timestamp=processed.timestamp,
            temp_internal=processed.temp_internal,
            temp_external=processed.temp_external,
            humidity=processed.humidity,
            risk_score=processed.risk_score,
            status=processed.status,
            vvm_damage=processed.vvm_damage,
            exposure_minutes=processed.exposure_minutes,
            is_anomaly=processed.is_anomaly,
            potency_percent=processed.potency_percent,
            eta_to_critical=processed.eta_to_critical,
        )

        # Evaluate triggers
        await trigger_engine.evaluate(processed)

        # Broadcast via WebSocket
        await ws_manager.broadcast(processed.model_dump())

        logger.info(f"Manual trigger processed: status={processed.status}")
        return processed.model_dump()

    except Exception as e:
        logger.error(f"Manual trigger failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )


# ============================================================
# SEHAT SAATHI — MULTILINGUAL CHATBOT ENDPOINT
# ============================================================

@router.post("/api/chat")
async def api_chat(body: dict):
    """Multilingual offline chatbot — Sehat Saathi.

    Args:
        body: JSON with 'query' (or 'message') and optional 'language' (en/hi/kn).

    Returns:
        JSON with 'response' containing the translated chatbot reply.
    """
    query = body.get("query", body.get("message", "")).lower().strip()
    lang = body.get("language", "en")
    if lang not in ("en", "hi", "kn"):
        lang = "en"

    if not query:
        r = {
            "en": "Please type a question! Try asking about temperature, safety, or how the system works.",
            "hi": "कृपया एक प्रश्न टाइप करें! तापमान, सुरक्षा या सिस्टम के बारे में पूछें।",
            "kn": "ದಯವಿಟ್ಟು ಪ್ರಶ್ನೆ ಟೈಪ್ ಮಾಡಿ! ತಾಪಮಾನ, ಸುರಕ್ಷತೆ ಅಥವಾ ವ್ಯವಸ್ಥೆಯ ಬಗ್ಗೆ ಕೇಳಿ.",
        }
        return {"response": r[lang]}

    reading = await get_latest_reading()

    no_data = {
        "en": "⏳ No sensor data available yet. The system is still starting up.",
        "hi": "⏳ अभी तक कोई सेंसर डेटा उपलब्ध नहीं है। सिस्टम शुरू हो रहा है।",
        "kn": "⏳ ಸೆನ್ಸರ್ ಡೇಟಾ ಇನ್ನೂ ಲಭ್ಯವಿಲ್ಲ. ಸಿಸ್ಟಮ್ ಪ್ರಾರಂಭವಾಗುತ್ತಿದೆ.",
    }

    # ── SAFETY / STATUS ──
    if any(k in query for k in ["safe", "status", "okay", "ok?", "good", "fine",
                                  "surakshit", "sुरक्षित", "सुरक्षित", "ಸುರಕ್ಷಿತ"]):
        if reading is None:
            return {"response": no_data[lang]}
        status = reading["status"]
        risk = reading["risk_score"]
        temp = reading["temp_internal"]
        if status == "SAFE":
            r = {
                "en": f"✅ **SAFE** — Vaccines are in good condition.\n\n• Temperature: {temp:.1f}°C (within 2–8°C range)\n• Risk Score: {risk:.0f}/100\n• All parameters normal.",
                "hi": f"✅ **सुरक्षित** — वैक्सीन अच्छी स्थिति में हैं।\n\n• तापमान: {temp:.1f}°C (2–8°C सीमा में)\n• जोखिम स्कोर: {risk:.0f}/100\n• सभी पैरामीटर सामान्य हैं।",
                "kn": f"✅ **ಸುರಕ್ಷಿತ** — ಲಸಿಕೆಗಳು ಉತ್ತಮ ಸ್ಥಿತಿಯಲ್ಲಿವೆ.\n\n• ತಾಪಮಾನ: {temp:.1f}°C (2–8°C ವ್ಯಾಪ್ತಿಯಲ್ಲಿ)\n• ಅಪಾಯ ಸ್ಕೋರ್: {risk:.0f}/100\n• ಎಲ್ಲಾ ಅಂಶಗಳು ಸಾಮಾನ್ಯ.",
            }
        elif status == "WARNING":
            r = {
                "en": f"⚠️ **WARNING** — Temperature excursion detected!\n\n• Temperature: {temp:.1f}°C\n• Risk Score: {risk:.0f}/100\n• Action: Monitor closely.",
                "hi": f"⚠️ **चेतावनी** — तापमान विचलन पाया गया!\n\n• तापमान: {temp:.1f}°C\n• जोखिम स्कोर: {risk:.0f}/100\n• कार्रवाई: बारीकी से निगरानी करें।",
                "kn": f"⚠️ **ಎಚ್ಚರಿಕೆ** — ತಾಪಮಾನ ವಿಚಲನ ಪತ್ತೆಯಾಗಿದೆ!\n\n• ತಾಪಮಾನ: {temp:.1f}°C\n• ಅಪಾಯ ಸ್ಕೋರ್: {risk:.0f}/100\n• ಕ್ರಮ: ಹತ್ತಿರದಿಂದ ಮೇಲ್ವಿಚಾರಣೆ ಮಾಡಿ.",
            }
        else:
            r = {
                "en": f"🚨 **CRITICAL** — Immediate action required!\n\n• Temperature: {temp:.1f}°C\n• Risk Score: {risk:.0f}/100\n• Action: Isolate affected vaccine batches immediately!",
                "hi": f"🚨 **गंभीर** — तत्काल कार्रवाई आवश्यक!\n\n• तापमान: {temp:.1f}°C\n• जोखिम स्कोर: {risk:.0f}/100\n• कार्रवाई: प्रभावित वैक्सीन बैचों को तुरंत अलग करें!",
                "kn": f"🚨 **ಗಂಭೀರ** — ತಕ್ಷಣ ಕ್ರಮ ಅಗತ್ಯ!\n\n• ತಾಪಮಾನ: {temp:.1f}°C\n• ಅಪಾಯ ಸ್ಕೋರ್: {risk:.0f}/100\n• ಕ್ರಮ: ಬಾಧಿತ ಲಸಿಕೆ ಬ್ಯಾಚ್‌ಗಳನ್ನು ತಕ್ಷಣ ಪ್ರತ್ಯೇಕಿಸಿ!",
            }
        return {"response": r[lang]}

    # ── TEMPERATURE ──
    if any(k in query for k in ["temp", "degree", "hot", "cold", "warm", "cool",
                                  "तापमान", "ತಾಪಮಾನ", "tapman"]):
        if reading is None:
            return {"response": no_data[lang]}
        temp = reading["temp_internal"]
        ext = reading["temp_external"]
        in_range = 2 <= temp <= 8
        r = {
            "en": f"🌡️ **Temperature Report**\n\n• Internal (fridge): **{temp:.1f}°C** — {'✅ within safe range' if in_range else '⚠️ outside safe range (2–8°C)'}\n• External (room): {ext:.1f}°C\n• Safe range: 2.0°C – 8.0°C",
            "hi": f"🌡️ **तापमान रिपोर्ट**\n\n• आंतरिक (फ्रिज): **{temp:.1f}°C** — {'✅ सुरक्षित सीमा में' if in_range else '⚠️ सुरक्षित सीमा के बाहर (2–8°C)'}\n• बाहरी (कमरा): {ext:.1f}°C\n• सुरक्षित सीमा: 2.0°C – 8.0°C",
            "kn": f"🌡️ **ತಾಪಮಾನ ವರದಿ**\n\n• ಆಂತರಿಕ (ಫ್ರಿಜ್): **{temp:.1f}°C** — {'✅ ಸುರಕ್ಷಿತ ವ್ಯಾಪ್ತಿಯಲ್ಲಿ' if in_range else '⚠️ ಸುರಕ್ಷಿತ ವ್ಯಾಪ್ತಿ ಹೊರಗೆ (2–8°C)'}\n• ಬಾಹ್ಯ (ಕೊಠಡಿ): {ext:.1f}°C\n• ಸುರಕ್ಷಿತ ವ್ಯಾಪ್ತಿ: 2.0°C – 8.0°C",
        }
        return {"response": r[lang]}

    # ── RISK ──
    if any(k in query for k in ["risk", "score", "danger", "why high", "why is risk",
                                  "jokhim", "जोखिम", "ಅಪಾಯ", "khatra"]):
        if reading is None:
            return {"response": no_data[lang]}
        risk = reading["risk_score"]
        temp = reading["temp_internal"]
        vvm = reading["vvm_damage"]
        exposure = reading["exposure_minutes"]
        anomaly = reading["is_anomaly"]
        potency = reading["potency_percent"]

        factors = {"en": [], "hi": [], "kn": []}
        if temp > 8:
            factors["en"].append(f"• Temperature **{temp:.1f}°C** (above 8°C)")
            factors["hi"].append(f"• तापमान **{temp:.1f}°C** (8°C से ऊपर)")
            factors["kn"].append(f"• ತಾಪಮಾನ **{temp:.1f}°C** (8°C ಗಿಂತ ಹೆಚ್ಚು)")
        elif temp < 2:
            factors["en"].append(f"• Temperature **{temp:.1f}°C** (below 2°C)")
            factors["hi"].append(f"• तापमान **{temp:.1f}°C** (2°C से नीचे)")
            factors["kn"].append(f"• ತಾಪಮಾನ **{temp:.1f}°C** (2°C ಗಿಂತ ಕಡಿಮೆ)")
        if exposure > 0:
            factors["en"].append(f"• **{exposure} min** exposure outside safe range")
            factors["hi"].append(f"• सुरक्षित सीमा के बाहर **{exposure} मिनट** का एक्सपोज़र")
            factors["kn"].append(f"• ಸುರಕ್ಷಿತ ವ್ಯಾಪ್ತಿ ಹೊರಗೆ **{exposure} ನಿಮಿಷ** ಒಡ್ಡುವಿಕೆ")
        if anomaly:
            factors["en"].append("• ⚠️ ML anomaly detector flagged unusual patterns")
            factors["hi"].append("• ⚠️ ML विसंगति डिटेक्टर ने असामान्य पैटर्न पाया")
            factors["kn"].append("• ⚠️ ML ಅಸಹಜತೆ ಶೋಧಕ ಅಸಾಮಾನ್ಯ ಮಾದರಿಗಳನ್ನು ಗುರುತಿಸಿದೆ")
        if not factors["en"]:
            factors["en"].append("• All parameters within normal ranges")
            factors["hi"].append("• सभी पैरामीटर सामान्य सीमा में हैं")
            factors["kn"].append("• ಎಲ್ಲಾ ಅಂಶಗಳು ಸಾಮಾನ್ಯ ವ್ಯಾಪ್ತಿಯಲ್ಲಿವೆ")

        r = {
            "en": f"📊 **Risk Score: {risk:.0f}/100**\n\n**Contributing factors:**\n" + "\n".join(factors["en"]),
            "hi": f"📊 **जोखिम स्कोर: {risk:.0f}/100**\n\n**कारण:**\n" + "\n".join(factors["hi"]),
            "kn": f"📊 **ಅಪಾಯ ಸ್ಕೋರ್: {risk:.0f}/100**\n\n**ಕಾರಣಗಳು:**\n" + "\n".join(factors["kn"]),
        }
        return {"response": r[lang]}

    # ── ETA / CRITICAL ──
    if any(k in query for k in ["eta", "critical", "when", "how long", "time left", "failure",
                                  "कब", "कितना समय", "ಯಾವಾಗ", "गंभीर", "ಗಂಭೀರ"]):
        if reading is None:
            return {"response": no_data[lang]}
        eta = reading["eta_to_critical"]
        status = reading["status"]
        if status == "CRITICAL":
            r = {
                "en": "🚨 **Status is CRITICAL right now!**\n\nImmediate action required.",
                "hi": "🚨 **स्थिति अभी गंभीर है!**\n\nतत्काल कार्रवाई आवश्यक है।",
                "kn": "🚨 **ಸ್ಥಿತಿ ಈಗ ಗಂಭೀರವಾಗಿದೆ!**\n\nತಕ್ಷಣ ಕ್ರಮ ಅಗತ್ಯ.",
            }
        elif eta is not None:
            r = {
                "en": f"⏱️ **ETA to CRITICAL: {eta} minutes**\n\nAt the current rate, the system will reach CRITICAL in ~{eta} minutes.\n\nEstimate uses ML breach prediction + physics modeling.",
                "hi": f"⏱️ **गंभीर स्थिति तक: {eta} मिनट**\n\nवर्तमान दर से, सिस्टम ~{eta} मिनट में गंभीर हो जाएगा।\n\nयह अनुमान ML भविष्यवाणी + भौतिकी मॉडलिंग का उपयोग करता है।",
                "kn": f"⏱️ **ಗಂಭೀರ ಸ್ಥಿತಿಗೆ: {eta} ನಿಮಿಷ**\n\nಪ್ರಸ್ತುತ ದರದಲ್ಲಿ, ಸಿಸ್ಟಮ್ ~{eta} ನಿಮಿಷಗಳಲ್ಲಿ ಗಂಭೀರವಾಗುತ್ತದೆ.\n\nML ಭವಿಷ್ಯವಾಣಿ + ಭೌತಶಾಸ್ತ್ರ ಮಾಡೆಲಿಂಗ್ ಬಳಸುತ್ತದೆ.",
            }
        else:
            r = {
                "en": "✅ **No risk of CRITICAL status detected.**\n\nSystem operating normally.",
                "hi": "✅ **गंभीर स्थिति का कोई जोखिम नहीं।**\n\nसिस्टम सामान्य रूप से काम कर रहा है।",
                "kn": "✅ **ಗಂಭೀರ ಸ್ಥಿತಿಯ ಅಪಾಯ ಇಲ್ಲ.**\n\nಸಿಸ್ಟಮ್ ಸಾಮಾನ್ಯವಾಗಿ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತಿದೆ.",
            }
        return {"response": r[lang]}

    # ── POTENCY / VVM ──
    if any(k in query for k in ["potency", "vvm", "damage", "vaccine quality", "degradation",
                                  "क्षमता", "गुणवत्ता", "ಸಾಮರ್ಥ್ಯ", "ಹಾನಿ"]):
        if reading is None:
            return {"response": no_data[lang]}
        vvm = reading["vvm_damage"]
        potency = reading["potency_percent"]
        r = {
            "en": f"💉 **Vaccine Potency Report**\n\n• Potency: **{potency:.1f}%**\n• VVM Damage: {vvm:.6f}\n• Discard Threshold: 1.0\n• Verdict: **{'Safe for use' if potency > 50 else '⚠️ Compromised'}**",
            "hi": f"💉 **वैक्सीन क्षमता रिपोर्ट**\n\n• क्षमता: **{potency:.1f}%**\n• VVM क्षति: {vvm:.6f}\n• निपटान सीमा: 1.0\n• निर्णय: **{'उपयोग के लिए सुरक्षित' if potency > 50 else '⚠️ प्रभावित'}**",
            "kn": f"💉 **ಲಸಿಕೆ ಸಾಮರ್ಥ್ಯ ವರದಿ**\n\n• ಸಾಮರ್ಥ್ಯ: **{potency:.1f}%**\n• VVM ಹಾನಿ: {vvm:.6f}\n• ವಿಲೇವಾರಿ ಮಿತಿ: 1.0\n• ತೀರ್ಪು: **{'ಬಳಕೆಗೆ ಸುರಕ್ಷಿತ' if potency > 50 else '⚠️ ರಾಜಿಯಾಗಿದೆ'}**",
        }
        return {"response": r[lang]}

    # ── HUMIDITY ──
    if any(k in query for k in ["humid", "नमी", "ತೇವಾಂಶ"]):
        if reading is None:
            return {"response": no_data[lang]}
        h = reading["humidity"]
        r = {
            "en": f"💧 **Humidity: {h:.1f}%**\n\nMeasured by DHT22 sensor.",
            "hi": f"💧 **नमी: {h:.1f}%**\n\nDHT22 सेंसर द्वारा मापा गया।",
            "kn": f"💧 **ತೇವಾಂಶ: {h:.1f}%**\n\nDHT22 ಸೆನ್ಸರ್ ಮೂಲಕ ಅಳೆಯಲಾಗಿದೆ.",
        }
        return {"response": r[lang]}

    # ── ANOMALY ──
    if any(k in query for k in ["anomaly", "unusual", "outlier", "विसंगति", "ಅಸಹಜ"]):
        if reading is None:
            return {"response": no_data[lang]}
        if reading["is_anomaly"]:
            r = {
                "en": "⚠️ **Anomaly Detected!**\n\nThe Isolation Forest ML model has detected unusual patterns.\n\n• Possible sensor malfunction\n• Door may have been opened\n• Check physical environment",
                "hi": "⚠️ **विसंगति पाई गई!**\n\nIsolation Forest ML मॉडल ने असामान्य पैटर्न पाया है।\n\n• सेंसर खराबी संभव\n• दरवाज़ा खुला हो सकता है\n• भौतिक वातावरण जांचें",
                "kn": "⚠️ **ಅಸಹಜತೆ ಪತ್ತೆಯಾಗಿದೆ!**\n\nIsolation Forest ML ಮಾಡೆಲ್ ಅಸಾಮಾನ್ಯ ಮಾದರಿಗಳನ್ನು ಪತ್ತೆಹಚ್ಚಿದೆ.\n\n• ಸೆನ್ಸರ್ ದೋಷ ಸಾಧ್ಯ\n• ಬಾಗಿಲು ತೆರೆದಿರಬಹುದು\n• ಭೌತಿಕ ಪರಿಸರ ಪರಿಶೀಲಿಸಿ",
            }
        else:
            r = {
                "en": "✅ **No anomalies detected.** All sensor readings are within expected patterns.",
                "hi": "✅ **कोई विसंगति नहीं पाई गई।** सभी सेंसर रीडिंग अपेक्षित पैटर्न में हैं।",
                "kn": "✅ **ಯಾವುದೇ ಅಸಹಜತೆ ಪತ್ತೆಯಾಗಿಲ್ಲ.** ಎಲ್ಲಾ ಸೆನ್ಸರ್ ರೀಡಿಂಗ್‌ಗಳು ನಿರೀಕ್ಷಿತ ಮಾದರಿಯಲ್ಲಿವೆ.",
            }
        return {"response": r[lang]}

    # ── SYSTEM / HOW IT WORKS ──
    if any(k in query for k in ["how does", "how it work", "explain system", "architecture", "pipeline",
                                  "कैसे काम", "सिस्टम", "ವ್ಯವಸ್ಥೆ", "ಹೇಗೆ ಕೆಲಸ"]):
        r = {
            "en": "🏗️ **How the System Works**\n\n**1.** DS18B20 + DHT22 sensors read temp & humidity every 3s\n**2.** Data sent via MQTT to broker\n**3.** FastAPI backend runs 8-stage pipeline:\n→ Baseline → Anomaly ML → Exposure → VVM → Risk → Potency ML → ETA ML → Alerts\n**4.** 3 ML models: Isolation Forest, Random Forest, Linear Regression\n**5.** Real-time dashboard via WebSocket",
            "hi": "🏗️ **सिस्टम कैसे काम करता है**\n\n**1.** DS18B20 + DHT22 सेंसर हर 3 सेकंड में तापमान और नमी पढ़ते हैं\n**2.** डेटा MQTT के माध्यम से ब्रोकर को भेजा जाता है\n**3.** FastAPI बैकएंड 8-चरण पाइपलाइन चलाता है:\n→ बेसलाइन → विसंगति ML → एक्सपोज़र → VVM → जोखिम → क्षमता ML → ETA ML → अलर्ट\n**4.** 3 ML मॉडल: Isolation Forest, Random Forest, Linear Regression\n**5.** WebSocket के माध्यम से रियल-टाइम डैशबोर्ड",
            "kn": "🏗️ **ವ್ಯವಸ್ಥೆ ಹೇಗೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ**\n\n**1.** DS18B20 + DHT22 ಸೆನ್ಸರ್‌ಗಳು ಪ್ರತಿ 3 ಸೆಕೆಂಡಿಗೆ ತಾಪಮಾನ ಮತ್ತು ತೇವಾಂಶ ಓದುತ್ತವೆ\n**2.** MQTT ಮೂಲಕ ಬ್ರೋಕರ್‌ಗೆ ಡೇಟಾ ಕಳುಹಿಸಲಾಗುತ್ತದೆ\n**3.** FastAPI ಬ್ಯಾಕೆಂಡ್ 8-ಹಂತದ ಪೈಪ್‌ಲೈನ್ ನಡೆಸುತ್ತದೆ:\n→ ಆಧಾರರೇಖೆ → ಅಸಹಜತೆ ML → ಒಡ್ಡುವಿಕೆ → VVM → ಅಪಾಯ → ಸಾಮರ್ಥ್ಯ ML → ETA ML → ಎಚ್ಚರಿಕೆ\n**4.** 3 ML ಮಾಡೆಲ್‌ಗಳು: Isolation Forest, Random Forest, Linear Regression\n**5.** WebSocket ಮೂಲಕ ರಿಯಲ್-ಟೈಮ್ ಡ್ಯಾಶ್‌ಬೋರ್ಡ್",
        }
        return {"response": r[lang]}

    # ── SENSORS ──
    if any(k in query for k in ["sensor", "hardware", "raspberry", "ds18", "dht",
                                  "सेंसर", "हार्डवेयर", "ಸೆನ್ಸರ್"]):
        r = {
            "en": "🔌 **Sensors Used**\n\n• **DS18B20** — Waterproof probe inside fridge (internal temp, GPIO4)\n• **DHT22** — Room temperature + humidity sensor (GPIO17)\n\nBoth connected to Raspberry Pi, publishing via MQTT every 3 seconds.",
            "hi": "🔌 **उपयोग किए गए सेंसर**\n\n• **DS18B20** — फ्रिज के अंदर वाटरप्रूफ प्रोब (आंतरिक तापमान, GPIO4)\n• **DHT22** — कमरे का तापमान + नमी सेंसर (GPIO17)\n\nदोनों Raspberry Pi से जुड़े हैं, हर 3 सेकंड MQTT से डेटा भेजते हैं।",
            "kn": "🔌 **ಬಳಸಿದ ಸೆನ್ಸರ್‌ಗಳು**\n\n• **DS18B20** — ಫ್ರಿಜ್ ಒಳಗೆ ವಾಟರ್‌ಪ್ರೂಫ್ ಪ್ರೋಬ್ (ಆಂತರಿಕ ತಾಪಮಾನ, GPIO4)\n• **DHT22** — ಕೊಠಡಿ ತಾಪಮಾನ + ತೇವಾಂಶ ಸೆನ್ಸರ್ (GPIO17)\n\nಎರಡೂ Raspberry Pi ಗೆ ಸಂಪರ್ಕಿಸಲ್ಪಟ್ಟಿವೆ, ಪ್ರತಿ 3 ಸೆಕೆಂಡಿಗೆ MQTT ಮೂಲಕ ಡೇಟಾ ಕಳುಹಿಸುತ್ತವೆ.",
        }
        return {"response": r[lang]}

    # ── MQTT ──
    if any(k in query for k in ["mqtt", "protocol", "broker", "mosquitto"]):
        r = {
            "en": "📡 **What is MQTT?**\n\nLightweight IoT messaging protocol.\n\n• **Publisher** (Raspberry Pi) sends sensor data\n• **Broker** (Mosquitto) routes messages\n• **Subscriber** (FastAPI) receives & processes\n\nTopic: `vaccines/sensor/data`",
            "hi": "📡 **MQTT क्या है?**\n\nहल्का IoT मैसेजिंग प्रोटोकॉल।\n\n• **प्रकाशक** (Raspberry Pi) सेंसर डेटा भेजता है\n• **ब्रोकर** (Mosquitto) संदेश रूट करता है\n• **सब्सक्राइबर** (FastAPI) प्राप्त करता है और प्रोसेस करता है\n\nटॉपिक: `vaccines/sensor/data`",
            "kn": "📡 **MQTT ಎಂದರೇನು?**\n\nಹಗುರ IoT ಸಂದೇಶ ಪ್ರೋಟೋಕಾಲ್.\n\n• **ಪ್ರಕಾಶಕ** (Raspberry Pi) ಸೆನ್ಸರ್ ಡೇಟಾ ಕಳುಹಿಸುತ್ತದೆ\n• **ಬ್ರೋಕರ್** (Mosquitto) ಸಂದೇಶಗಳನ್ನು ರೂಟ್ ಮಾಡುತ್ತದೆ\n• **ಚಂದಾದಾರ** (FastAPI) ಸ್ವೀಕರಿಸುತ್ತದೆ ಮತ್ತು ಪ್ರಕ್ರಿಯೆಗೊಳಿಸುತ್ತದೆ\n\nವಿಷಯ: `vaccines/sensor/data`",
        }
        return {"response": r[lang]}

    # ── ML MODELS ──
    if any(k in query for k in ["ml", "machine learning", "ai", "model", "prediction",
                                  "मशीन लर्निंग", "ಯಂತ್ರ ಕಲಿಕೆ"]):
        r = {
            "en": "🧠 **ML Models Used**\n\n**1. Anomaly Detection** — Isolation Forest\n**2. Breach Prediction** — Random Forest\n**3. Potency Estimation** — Linear Regression\n\nAll pre-trained on synthetic cold-chain data. Fully offline, no external APIs.",
            "hi": "🧠 **ML मॉडल**\n\n**1. विसंगति पहचान** — Isolation Forest\n**2. उल्लंघन भविष्यवाणी** — Random Forest\n**3. क्षमता अनुमान** — Linear Regression\n\nसभी सिंथेटिक कोल्ड-चेन डेटा पर प्रशिक्षित। पूर्णतः ऑफलाइन।",
            "kn": "🧠 **ML ಮಾಡೆಲ್‌ಗಳು**\n\n**1. ಅಸಹಜತೆ ಪತ್ತೆ** — Isolation Forest\n**2. ಉಲ್ಲಂಘನೆ ಭವಿಷ್ಯವಾಣಿ** — Random Forest\n**3. ಸಾಮರ್ಥ್ಯ ಅಂದಾಜು** — Linear Regression\n\nಎಲ್ಲವೂ ಸಿಂಥೆಟಿಕ್ ಕೋಲ್ಡ್-ಚೈನ್ ಡೇಟಾದಲ್ಲಿ ತರಬೇತಿ ಪಡೆದಿವೆ. ಸಂಪೂರ್ಣವಾಗಿ ಆಫ್‌ಲೈನ್.",
        }
        return {"response": r[lang]}

    # ── ALERTS / SMS ──
    if any(k in query for k in ["alert", "sms", "notification", "अलर्ट", "ಎಚ್ಚರಿಕೆ"]):
        r = {
            "en": "📱 **Alert System**\n\nOn status change (SAFE → WARNING → CRITICAL):\n1. Incident recorded in database\n2. SMS alert via Fast2SMS\n3. Incident report generated\n4. PDF vaccine passport available",
            "hi": "📱 **अलर्ट सिस्टम**\n\nस्थिति बदलने पर (सुरक्षित → चेतावनी → गंभीर):\n1. डेटाबेस में घटना दर्ज\n2. Fast2SMS से SMS अलर्ट\n3. घटना रिपोर्ट तैयार\n4. PDF वैक्सीन पासपोर्ट उपलब्ध",
            "kn": "📱 **ಎಚ್ಚರಿಕೆ ವ್ಯವಸ್ಥೆ**\n\nಸ್ಥಿತಿ ಬದಲಾದಾಗ (ಸುರಕ್ಷಿತ → ಎಚ್ಚರಿಕೆ → ಗಂಭೀರ):\n1. ಡೇಟಾಬೇಸ್‌ನಲ್ಲಿ ಘಟನೆ ದಾಖಲು\n2. Fast2SMS ಮೂಲಕ SMS ಎಚ್ಚರಿಕೆ\n3. ಘಟನೆ ವರದಿ ರಚನೆ\n4. PDF ಲಸಿಕೆ ಪಾಸ್‌ಪೋರ್ಟ್ ಲಭ್ಯ",
        }
        return {"response": r[lang]}

    # ── HELP ──
    if any(k in query for k in ["help", "what can you", "commands", "मदद", "ಸಹಾಯ"]):
        r = {
            "en": "🤖 **I can help with:**\n\n📊 **Live Data:** safety status, temperature, risk, ETA, potency\n🔧 **System Info:** how it works, sensors, MQTT, ML models, VVM\n\nJust ask your question!",
            "hi": "🤖 **मैं इनमें मदद कर सकता हूँ:**\n\n📊 **लाइव डेटा:** सुरक्षा स्थिति, तापमान, जोखिम, ETA, क्षमता\n🔧 **सिस्टम जानकारी:** कैसे काम करता है, सेंसर, MQTT, ML मॉडल, VVM\n\nबस अपना सवाल पूछें!",
            "kn": "🤖 **ನಾನು ಇವುಗಳಲ್ಲಿ ಸಹಾಯ ಮಾಡಬಲ್ಲೆ:**\n\n📊 **ಲೈವ್ ಡೇಟಾ:** ಸುರಕ್ಷತೆ, ತಾಪಮಾನ, ಅಪಾಯ, ETA, ಸಾಮರ್ಥ್ಯ\n🔧 **ವ್ಯವಸ್ಥೆ ಮಾಹಿತಿ:** ಹೇಗೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ, ಸೆನ್ಸರ್, MQTT, ML ಮಾಡೆಲ್, VVM\n\nನಿಮ್ಮ ಪ್ರಶ್ನೆ ಕೇಳಿ!",
        }
        return {"response": r[lang]}

    # ── GREETING ──
    if any(k in query for k in ["hi", "hello", "hey", "namaste", "नमस्ते", "ನಮಸ್ಕಾರ"]):
        r = {
            "en": "👋 Hello! I'm **Sehat Saathi** — your Vaccine Monitor Assistant.\n\nAsk me about system data or how the system works!",
            "hi": "👋 नमस्ते! मैं **सेहत साथी** हूँ — आपका वैक्सीन मॉनिटर सहायक।\n\nसिस्टम डेटा या सिस्टम कैसे काम करता है, पूछें!",
            "kn": "👋 ನಮಸ್ಕಾರ! ನಾನು **ಸೆಹತ್ ಸಾಥಿ** — ನಿಮ್ಮ ಲಸಿಕೆ ಮಾನಿಟರ್ ಸಹಾಯಕ.\n\nಸಿಸ್ಟಮ್ ಡೇಟಾ ಅಥವಾ ಸಿಸ್ಟಮ್ ಹೇಗೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ ಎಂದು ಕೇಳಿ!",
        }
        return {"response": r[lang]}

    # ── FALLBACK ──
    r = {
        "en": "🤔 I didn't quite understand that.\n\n**Try asking about:**\n• Temperature, safety, or risk\n• ETA to critical\n• How the system works\n• Sensors, MQTT, or ML models\n\nOr type **\"help\"**!",
        "hi": "🤔 मैं समझ नहीं पाया।\n\n**इनके बारे में पूछें:**\n• तापमान, सुरक्षा, या जोखिम\n• गंभीर स्थिति तक का समय\n• सिस्टम कैसे काम करता है\n• सेंसर, MQTT, या ML मॉडल\n\nया **\"मदद\"** टाइप करें!",
        "kn": "🤔 ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ.\n\n**ಇವುಗಳ ಬಗ್ಗೆ ಕೇಳಿ:**\n• ತಾಪಮಾನ, ಸುರಕ್ಷತೆ, ಅಥವಾ ಅಪಾಯ\n• ಗಂಭೀರ ಸ್ಥಿತಿಗೆ ಸಮಯ\n• ವ್ಯವಸ್ಥೆ ಹೇಗೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ\n• ಸೆನ್ಸರ್, MQTT, ಅಥವಾ ML ಮಾಡೆಲ್\n\nಅಥವಾ **\"ಸಹಾಯ\"** ಟೈಪ್ ಮಾಡಿ!",
    }
    return {"response": r[lang]}

