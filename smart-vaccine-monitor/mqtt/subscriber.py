"""MQTT subscriber — connects to Mosquitto broker and processes messages."""

import json
import asyncio
import threading
from datetime import datetime
import paho.mqtt.client as mqtt
from models.schemas import SensorDataInput
from processing.pipeline import process_reading
from database.crud import insert_reading
from api.websocket_manager import ws_manager
from triggers.trigger_engine import trigger_engine
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.mqtt_subscriber")

# Reference to the running event loop for scheduling async tasks from MQTT thread
_event_loop: asyncio.AbstractEventLoop = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Set the asyncio event loop for scheduling coroutines from MQTT thread.

    Args:
        loop: The main asyncio event loop.
    """
    global _event_loop
    _event_loop = loop


async def _process_mqtt_message(payload: dict) -> None:
    """Process a single MQTT message through the full pipeline.

    Args:
        payload: Parsed JSON payload from MQTT message.
    """
    try:
        # Add timestamp if missing
        if "timestamp" not in payload or not payload["timestamp"]:
            payload["timestamp"] = datetime.utcnow().isoformat()

        # Validate with Pydantic
        sensor_data = SensorDataInput(**payload)

        # Process through pipeline
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

        # Evaluate triggers (status change detection)
        await trigger_engine.evaluate(processed)

        # Broadcast to WebSocket clients
        await ws_manager.broadcast(processed.model_dump())

    except ValueError as e:
        logger.warning(f"Invalid sensor data, skipping: {e}")
    except Exception as e:
        logger.error(f"Error processing MQTT message: {e}")


def _on_connect(client, userdata, flags, rc):
    """Callback when MQTT client connects to broker."""
    if rc == 0:
        logger.info(f"Connected to MQTT broker at {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}")
        client.subscribe(settings.MQTT_TOPIC, qos=1)
        logger.info(f"Subscribed to topic: {settings.MQTT_TOPIC}")
    else:
        logger.error(f"MQTT connection failed with code {rc}")


def _on_disconnect(client, userdata, rc):
    """Callback when MQTT client disconnects."""
    if rc != 0:
        logger.warning(f"MQTT unexpected disconnect (code {rc}). Attempting reconnect...")


def _on_message(client, userdata, msg):
    """Callback when MQTT message is received."""
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        logger.debug(f"MQTT message received on {msg.topic}: {payload}")

        # Schedule async processing on the main event loop
        if _event_loop is not None and _event_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                _process_mqtt_message(payload),
                _event_loop,
            )
        else:
            logger.error("Event loop not available for MQTT message processing")

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in MQTT message: {e}")
    except Exception as e:
        logger.error(f"Error handling MQTT message: {e}")


def start_mqtt_subscriber() -> mqtt.Client:
    """Start the MQTT subscriber in a background thread.

    Returns:
        The MQTT client instance.
    """
    client = mqtt.Client(client_id="vaccine_monitor_subscriber")
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message

    # Enable auto-reconnect
    client.reconnect_delay_set(min_delay=1, max_delay=5)

    try:
        client.connect(
            host=settings.MQTT_BROKER_HOST,
            port=settings.MQTT_BROKER_PORT,
            keepalive=60,
        )
        # Start network loop in background thread
        client.loop_start()
        logger.info("MQTT subscriber started in background thread")
        return client
    except Exception as e:
        logger.error(f"Failed to start MQTT subscriber: {e}")
        raise


def stop_mqtt_subscriber(client: mqtt.Client) -> None:
    """Stop the MQTT subscriber.

    Args:
        client: The MQTT client to stop.
    """
    try:
        client.loop_stop()
        client.disconnect()
        logger.info("MQTT subscriber stopped")
    except Exception as e:
        logger.error(f"Error stopping MQTT subscriber: {e}")
