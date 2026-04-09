# Smart Vaccine Monitoring System

## Overview

The Smart Vaccine Monitoring System is a comprehensive, real-time IoT + AI solution designed to address one of the most critical challenges in global healthcare: maintaining the vaccine cold chain. Every year, millions of vaccine doses are wasted due to temperature excursions during storage and transport, compromising vaccine potency and public health outcomes.

This system integrates hardware sensors (or a CSV simulator for demonstration) with a processing pipeline that combines classical signal processing, machine learning anomaly detection, physics-based degradation modeling (Arrhenius equation), and AI-powered reporting to provide continuous, intelligent monitoring of vaccine storage conditions.

## Architecture

```
[Raspberry Pi / CSV Simulator]
        │
        │ JSON payload every 60s:
        │ {"temp_internal": float, "temp_external": float,
        │  "humidity": float, "timestamp": str}
        │
        ▼
┌──────────────────────────────┐
│      MQTT Subscriber         │
│   Topic: vaccines/sensor/data│
│   QoS: 1                    │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│     Pydantic Validation      │
│  Reject if:                  │
│  - temp_internal ∉ [-30, 60] │
│  - humidity ∉ [0, 100]       │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────┐
│              Processing Pipeline                      │
│                                                      │
│  1. baseline.py  → Rolling mean/std (window=50)      │
│  2. anomaly.py   → IsolationForest prediction        │
│  3. exposure.py  → Time-at-risk accumulation         │
│  4. vvm.py       → Arrhenius damage (irreversible)   │
│  5. risk.py      → Composite score (0-100) + status  │
│  6. predict.py   → ETA to CRITICAL (GradientBoost)   │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────┐
│        SQLite Database       │
│  Tables: sensor_readings,    │
│          incidents           │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│        Trigger Engine        │
│  On status change:           │
│  ├── SMS Alert (Fast2SMS)    │
│  ├── Report (Claude AI)      │
│  └── PDF Passport (ReportLab)│
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│      WebSocket Broadcast     │
│   → All dashboard clients    │
└──────────────────────────────┘
```

## Tech Stack Decisions

### FastAPI (Backend Framework)
Chosen for its native async/await support, automatic OpenAPI documentation generation, built-in WebSocket handling, and excellent performance with Uvicorn. FastAPI's Pydantic integration provides automatic request validation and serialization, reducing boilerplate significantly. Alternatives like Flask lack native async support, and Django is too heavyweight for an IoT edge application.

### paho-mqtt (MQTT Client)
The de facto standard for MQTT communication in Python. It provides reliable QoS 1 message delivery, automatic reconnection, and thread-safe operation. Essential for IoT sensor communication where message reliability matters for cold-chain compliance. Chosen over alternatives like `gmqtt` for its maturity and extensive documentation.

### SQLite + aiosqlite (Database)
SQLite provides zero-configuration, file-based storage ideal for edge deployments on Raspberry Pi. The `aiosqlite` driver enables async operation without blocking the event loop. This combination is perfect for a single-node monitoring system and provides a clear migration path to PostgreSQL via SQLAlchemy's abstraction.

### SQLAlchemy 2.0 (ORM)
The modern asyncio-native version of SQLAlchemy provides declarative ORM models, async session management, and database-agnostic queries. It abstracts the database layer so switching from SQLite to PostgreSQL/TimescaleDB requires only a connection string change.

### scikit-learn (Machine Learning)
Provides lightweight, well-tested implementations of IsolationForest (anomaly detection) and GradientBoostingClassifier (status prediction). No GPU required, making it suitable for edge deployment. Models are serialized with joblib for fast loading.

### Chart.js (Frontend Charts)
CDN-ready charting library with excellent line chart support, responsive design, and annotation plugins for safe zone visualization. No build step required, keeping the frontend simple and hackathon-friendly.

### ReportLab (PDF Generation)
Pure Python PDF generation with professional layout capabilities. No system dependencies (unlike wkhtmltopdf), making it portable across platforms. Supports complex table layouts, color styling, and custom typography needed for formal compliance documents.

### Fast2SMS (SMS Alerts)
Simple REST API for SMS delivery with no SDK installation required. Supports bulk messaging and provides delivery confirmation. The async httpx client prevents SMS sending from blocking the main processing pipeline.

### Anthropic Claude (AI Reports)
High-quality language model for generating formal, structured incident reports. Claude's instruction-following capability produces WHO-compliant report formatting with minimal prompt engineering. Fallback report generation ensures system resilience when the API is unavailable.

### WebSockets (Real-time Push)
Native FastAPI WebSocket support provides bidirectional communication for live dashboard updates. The browser's native WebSocket API requires no additional libraries, and the connection manager handles multi-client broadcasting with automatic dead connection cleanup.

## Module Breakdown

### `config/settings.py`
Centralized configuration using pydantic-settings. All environment variables are loaded from `.env` with type validation and sensible defaults. This ensures zero hardcoded secrets and environment-specific configuration without code changes.

### `models/database.py`
Async SQLAlchemy engine and session factory. Provides `init_db()` for table creation and `close_db()` for graceful shutdown. The async session factory ensures non-blocking database operations throughout the application.

### `models/orm_models.py`
Two ORM models: `SensorReading` (timestamped sensor data with all computed fields) and `Incident` (status change events with associated reports and PDF paths). Both include `to_dict()` methods for JSON serialization.

### `models/schemas.py`
Pydantic models for API validation. `SensorDataInput` validates raw sensor data with range checking. `ProcessedReading` represents the fully enriched reading after pipeline processing. Additional schemas for API responses ensure type safety across the system.

### `processing/baseline.py`
Rolling window baseline temperature learner. Maintains a deque of the last N readings (configurable via `BASELINE_WINDOW`) and computes running mean and standard deviation. These statistics feed into the anomaly detector and risk engine as reference points for "normal" operation.

### `processing/exposure.py`
Cumulative time-at-risk tracker. Each reading outside the safe temperature range [2°C, 8°C] increments the exposure counter. The exposure minutes factor into the risk score and provide compliance-relevant data about total time in breach.

### `processing/vvm.py`
Vaccine Vial Monitor damage model using the Arrhenius equation. Calculates the rate of chemical degradation as a function of temperature using activation energy (Ea = 83,144 J/mol) and the gas constant. Damage accumulates irreversibly — once incurred, it cannot be reversed, modeling real-world vaccine degradation physics.

### `processing/risk_engine.py`
Combines four independent signals into a composite 0-100 risk score: temperature deviation (0-40pts), exposure time (0-30pts), VVM damage (0-20pts), and anomaly detection (0-10pts). The score maps to three status levels: SAFE (<30), WARNING (30-69), CRITICAL (≥70).

### `processing/pipeline.py`
Orchestrates all processing stages in sequence for each incoming reading. Acts as the single entry point for data processing, ensuring consistent execution order and error handling across both MQTT and simulator data sources.

### `ml/anomaly_detector.py`
IsolationForest wrapper with auto-training capability. Uses four features (temp_internal, temp_external, humidity, baseline_deviation) to identify anomalous readings. If no saved model exists at startup, automatically trains on 100 synthetic normal-condition samples and saves via joblib.

### `ml/prediction_model.py`
GradientBoostingClassifier wrapper for predicting ETA to CRITICAL status. Uses five features including temperature trend over last 5 readings. Estimates minutes to CRITICAL based on prediction probability and current risk trajectory. Also manages a temperature history buffer for trend computation.

### `ml/trainer.py`
Offline training script that can be run independently (`python -m ml.trainer`). Trains both ML models on CSV data with computed features, enabling model refinement as more real-world data accumulates.

### `services/sms_service.py`
Async Fast2SMS integration. Constructs alert messages with status, risk score, temperature, and ETA information. Gracefully handles missing API keys (logs the would-be message), HTTP errors, and connection failures without crashing the system.

### `services/report_service.py`
Claude API integration for formal incident reports. Formats recent readings as a data table in the prompt and requests a structured report covering incident summary, timeline, risk assessment, and recommended actions. Includes a comprehensive fallback report generator for when the API is unavailable.

### `services/pdf_service.py`
ReportLab-based PDF generation for vaccine cold-chain passports. Produces professional, multi-section documents with batch information, temperature statistics, VVM status, a large verdict banner (SAFE/COMPROMISED), incident report text, and a data table of recent readings. Color-coded for immediate visual assessment.

### `triggers/trigger_engine.py`
Status change detector that monitors the transition between SAFE, WARNING, and CRITICAL states. On any change, fires SMS, report generation, and PDF creation in parallel using asyncio tasks. Creates an incident record and updates it with generated report text and PDF path.

### `api/routes.py`
RESTful API endpoints for dashboard data access, health checks, incident retrieval, PDF downloads, and manual simulation triggers. Includes query parameter validation and proper error responses.

### `api/websocket_manager.py`
Multi-client WebSocket connection manager. Maintains a list of active connections, broadcasts JSON data to all clients, and silently cleans up disconnected/dead connections during broadcast operations.

### `mqtt/subscriber.py`
paho-mqtt client that subscribes to the sensor data topic with QoS 1. Bridges the threaded MQTT callbacks to the async event loop using `asyncio.run_coroutine_threadsafe()`. Includes auto-reconnect with configurable delay.

### `mqtt/simulator.py`
CSV replay simulator for demonstration and testing. Reads sensor data rows from a CSV file, processes each through the full pipeline with configurable delay between readings, and loops back to the start when the file ends. Provides the same data flow as live MQTT operation.

### `frontend/`
Professional dark-themed medical IoT dashboard with clinical-precision aesthetics. Real-time temperature chart (Chart.js), risk score gauge (SVG), status badge with status-dependent animations, VVM damage progress bar, ETA countdown, incident report panel, and color-coded readings table. WebSocket client with exponential backoff reconnection.

## Environment Setup

### Prerequisites
- Python 3.10 or higher
- pip (Python package manager)
- Mosquitto MQTT broker (only required for live mode)

### Step-by-Step Setup

```bash
# 1. Clone the repository
git clone <repository-url>
cd smart-vaccine-monitor

# 2. Create and activate virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate

# macOS/Linux:
source venv/bin/activate

# 3. Install all dependencies
pip install -r requirements.txt

# 4. Copy environment configuration
cp .env.example .env

# 5. (Optional) Edit .env with your API keys
# FAST2SMS_API_KEY=your_actual_key
# ANTHROPIC_API_KEY=your_actual_key

# 6. Start the application
uvicorn main:app --reload

# 7. Open http://localhost:8000 in your browser
```

### Mosquitto Installation (Live Mode Only)

```bash
# Windows (via Chocolatey)
choco install mosquitto

# macOS (via Homebrew)
brew install mosquitto

# Ubuntu/Debian
sudo apt install mosquitto mosquitto-clients
```

## Running the System

### Live Mode (with Raspberry Pi)
1. Set `SIMULATION_MODE=false` in `.env`
2. Configure `MQTT_BROKER_HOST` to your Mosquitto broker address
3. Start Mosquitto: `mosquitto -v`
4. Start the application: `uvicorn main:app --reload`
5. Publish sensor data to `vaccines/sensor/data` topic

### Simulation Mode (Demo/Hackathon)
1. Ensure `SIMULATION_MODE=true` in `.env` (default)
2. Start: `uvicorn main:app --reload`
3. Dashboard auto-populates with simulated data every 3 seconds

### Running ML Training Manually
```bash
python -m ml.trainer
```

## API Reference

### Health Check
```bash
curl http://localhost:8000/health
# {"status": "ok", "mode": "simulation", "websocket_connections": 1}
```

### Get Recent Readings
```bash
curl "http://localhost:8000/api/readings?limit=10"
```

### Get Latest Reading
```bash
curl http://localhost:8000/api/readings/latest
```

### Get Current Status
```bash
curl http://localhost:8000/api/status
```

### Get Incidents
```bash
curl http://localhost:8000/api/incidents
```

### Get Latest Report
```bash
curl http://localhost:8000/api/report/latest
```

### Download PDF Passport
```bash
curl -O http://localhost:8000/api/pdf/1
```

### Manual Trigger (Demo)
```bash
curl -X POST http://localhost:8000/api/simulate/trigger \
  -H "Content-Type: application/json" \
  -d '{"temp_internal": 15.0, "temp_external": 30.0, "humidity": 55.0}'
```

## Demo Flow (Hackathon)

1. **Launch**: Run `uvicorn main:app --reload` and open `http://localhost:8000`
2. **Normal Operation** (readings 1-60): All green, temperature 3.5-5.5°C, risk score low
3. **Warming Trend** (readings 61-90): Watch temperature rise, risk score climbing
4. **WARNING Alert** (~reading 75): Status badge turns amber, SMS fires, ETA appears
5. **CRITICAL Breach** (~reading 95): Status turns red, pulsing animation, incident report generates
6. **AI Report**: Incident report panel populates with Claude-generated analysis
7. **PDF Available**: Download vaccine passport from the API
8. **Recovery** (readings 121-150): Temperature drops, system returns to SAFE
9. **Anomaly Spikes** (readings 158, 167, 175): Brief red flashes on temperature card
10. **Second Excursion** (readings 181-200): Mild WARNING demonstrates continuous monitoring

## Future Scalability

- **PostgreSQL + TimescaleDB**: Migrate from SQLite for production-scale time-series storage with automatic data partitioning and retention policies
- **AWS IoT Core**: Replace local Mosquitto with managed MQTT service for global, scalable sensor fleet management
- **Docker + Kubernetes**: Containerize for cloud-native deployment with auto-scaling and rolling updates
- **React/Next.js Frontend**: Upgrade to component-based architecture with TanStack Query for complex data management
- **Multi-sensor Network**: Extend to monitor multiple refrigerators, transport vehicles, and distribution points simultaneously
- **Edge Computing**: Deploy ML inference on Raspberry Pi using TensorFlow Lite for offline anomaly detection
- **Historical Analytics**: Add time-series trend analysis, predictive maintenance scoring, and compliance dashboards
- **Mobile Notifications**: Push alerts via Firebase Cloud Messaging for field workers
