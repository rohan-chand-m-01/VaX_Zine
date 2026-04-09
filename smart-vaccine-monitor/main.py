"""FastAPI application entry point for Smart Vaccine Monitoring System."""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from models.database import init_db, close_db
from api.routes import router
from api.websocket_manager import ws_manager
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.main")

# Store background tasks for cleanup
_background_tasks: list[asyncio.Task] = []
_mqtt_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager — handles startup and shutdown.

    Startup:
      1. Create DB tables
      2. Initialize ML models (happens on import)
      3. Start MQTT subscriber or CSV simulator
      4. Log system mode and config

    Shutdown:
      1. Cancel background tasks
      2. Stop MQTT subscriber
      3. Close database engine
    """
    global _mqtt_client

    logger.info("=" * 60)
    logger.info("  SMART VACCINE MONITORING SYSTEM — STARTING")
    logger.info("=" * 60)

    # Step 1: Initialize database
    await init_db()
    logger.info("Database initialized successfully")

    # Step 2: ML models are initialized on import (global singletons)
    # Just log their status
    try:
        from ml.anomaly_detector import anomaly_detector
        from ml.prediction_model import prediction_model
        logger.info("ML models loaded/trained successfully")
    except Exception as e:
        logger.error(f"ML model initialization error: {e}")

    # Step 3: Start data source
    _actual_mode = "SIMULATION"
    if settings.SIMULATION_MODE:
        logger.info("Starting in SIMULATION MODE")
        # from mqtt.simulator import run_simulator
        # task = asyncio.create_task(run_simulator())
        # _background_tasks.append(task)
        # logger.info(f"CSV simulator started: {settings.SIMULATION_CSV_PATH}")
    else:
        logger.info("Starting in LIVE MODE — connecting to MQTT broker...")
        try:
            # from mqtt.subscriber import start_mqtt_subscriber, set_event_loop
            # loop = asyncio.get_running_loop()
            # set_event_loop(loop)
            # _mqtt_client = start_mqtt_subscriber()
            _actual_mode = "LIVE"
            # logger.info(f"✅ MQTT subscriber connected to {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}")
        except Exception as e:
            logger.error(f"❌ Failed to start MQTT subscriber: {e}")
            logger.warning("⚠ Auto-falling back to SIMULATION MODE for demo reliability...")
            # from mqtt.simulator import run_simulator
            # task = asyncio.create_task(run_simulator())
            # _background_tasks.append(task)
            # logger.info(f"Fallback CSV simulator started: {settings.SIMULATION_CSV_PATH}")

    # Step 4: Log config summary
    mode = _actual_mode
    logger.info(f"System ready. Mode: {mode}. DB: {settings.DATABASE_URL}")
    logger.info(f"Dashboard available at http://localhost:8000")
    logger.info(f"Safe temp range: {settings.SAFE_TEMP_MIN}°C – {settings.SAFE_TEMP_MAX}°C")
    logger.info("=" * 60)

    yield

    # === SHUTDOWN ===
    logger.info("Shutting down Smart Vaccine Monitoring System...")

    # Cancel background tasks
    for task in _background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Stop MQTT subscriber
    if _mqtt_client is not None:
        from mqtt.subscriber import stop_mqtt_subscriber
        stop_mqtt_subscriber(_mqtt_client)

    # Close database
    await close_db()

    logger.info("System shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Smart Vaccine Monitoring System",
    description="Real-time IoT + AI vaccine cold-chain monitoring dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware (allow all origins for hackathon)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)


# Serve frontend
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main dashboard HTML page."""
    return FileResponse("frontend/index.html")


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle pings
            data = await websocket.receive_text()
            # Echo pings back as pongs
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


# Mount static files for frontend assets (CSS, JS)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

