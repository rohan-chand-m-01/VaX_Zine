"""CSV replay simulator for demo/hackathon mode."""

import csv
import asyncio
from datetime import datetime
from models.schemas import SensorDataInput
from processing.pipeline import process_reading
from database.crud import insert_reading
from api.websocket_manager import ws_manager
from triggers.trigger_engine import trigger_engine
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.simulator")


async def run_simulator() -> None:
    """Run the CSV replay simulator as an async background task.

    Reads sensor data from the CSV file, processes each row through the
    full pipeline, and broadcasts results to WebSocket clients.
    Loops back to the start when the CSV ends.
    """
    csv_path = settings.SIMULATION_CSV_PATH
    interval = settings.SIMULATION_INTERVAL_SECONDS

    logger.info(
        f"Starting CSV simulator: path={csv_path}, "
        f"interval={interval}s"
    )

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"Simulator cycle {cycle}: reading {csv_path}")

        try:
            rows = _read_csv(csv_path)
            if not rows:
                logger.error(f"No data found in {csv_path}")
                await asyncio.sleep(5)
                continue

            logger.info(f"Loaded {len(rows)} rows from CSV")

            for i, row in enumerate(rows):
                try:
                    # Parse CSV row
                    sensor_data = SensorDataInput(
                        temp_internal=float(row["temp_internal"]),
                        temp_external=float(row["temp_external"]),
                        humidity=float(row["humidity"]),
                        timestamp=datetime.utcnow().isoformat(),
                    )

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

                    # Evaluate triggers
                    await trigger_engine.evaluate(processed)

                    # Broadcast to WebSocket clients
                    await ws_manager.broadcast(processed.model_dump())

                    logger.debug(
                        f"Sim row {i + 1}/{len(rows)}: "
                        f"temp={processed.temp_internal:.1f}°C, "
                        f"status={processed.status}, "
                        f"risk={processed.risk_score:.1f}"
                    )

                    # Wait before next reading
                    await asyncio.sleep(interval)

                except ValueError as e:
                    logger.warning(f"Invalid CSV row {i + 1}, skipping: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing CSV row {i + 1}: {e}")
                    continue

            logger.info(f"Simulator cycle {cycle} complete. Looping back to start...")

        except FileNotFoundError:
            logger.error(f"CSV file not found: {csv_path}")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Simulator error: {e}")
            await asyncio.sleep(5)


def _read_csv(csv_path: str) -> list[dict]:
    """Read the simulation CSV file.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of dictionaries with sensor data.
    """
    rows = []
    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception as e:
        logger.error(f"Failed to read CSV {csv_path}: {e}")
    return rows
