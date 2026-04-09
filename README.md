# Smart Vaccine Monitoring System

## Overview

The Smart Vaccine Monitoring System is a real-time IoT + AI solution for vaccine cold-chain surveillance. It continuously monitors storage temperature, detects anomalies using machine learning, computes cumulative heat damage via the Arrhenius equation (VVM model), and generates formal incident reports when breaches occur.

The system addresses a critical global health challenge: ensuring vaccine potency through proper cold-chain management. The WHO estimates that up to 50% of vaccines are wasted globally, partly due to temperature excursions during storage and transport. This system provides real-time monitoring, predictive analytics, and automated compliance reporting to prevent vaccine wastage.

 cd smart-vaccine-monitor
 venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000

## Architecture

```
[Raspberry Pi / CSV Simulator]
        │
        │ JSON payload every 60s:
        │ {temp_internal, temp_external, humidity, timestamp}
        │
        ▼
┌──────────────────────┐
│   MQTT Subscriber    │  Topic: vaccines/sensor/data (QoS: 1)
│   mqtt/subscriber.py │  OR: CSV Simulator (sim mode)
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Pydantic Validation │  Reject out-of-range values
│  models/schemas.py   │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│           Processing Pipeline                     │
│  ┌────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │ Baseline   │  │  Anomaly    │  │ Exposure  │ │
│  │ Learner    │  │  Detector   │  │ Tracker   │ │
│  │(rolling μ) │  │(IsolForest) │  │(time@risk)│ │
│  └────────────┘  └─────────────┘  └───────────┘ │
│  ┌────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │    VVM     │  │    Risk     │  │   ETA     │ │
│  │  Arrhenius │  │   Engine    │  │ Predictor │ │
│  │  (damage)  │  │  (0-100)   │  │(GradBoost)│ │
│  └────────────┘  └─────────────┘  └───────────┘ │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌──────────────────────┐     ┌────────────────────┐
│   SQLite Database    │     │  Trigger Engine     │
│   (async, via ORM)   │     │  Status Changes:    │
└──────────────────────┘     │  → SMS (Fast2SMS)   │
                             │  → Report (Claude)  │
                             │  → PDF (ReportLab)  │
                             └────────┬───────────┘
                                      │
                                      ▼
                             ┌────────────────────┐
                             │  WebSocket Broadcast│
                             │  → Dashboard UI     │
                             └────────────────────┘
```

## Tech Stack Decisions

| Technology | Purpose | Why This Choice |
|---|---|---|
| **FastAPI** | Backend framework | Native async support, auto-generated OpenAPI docs, WebSocket built-in, high performance |
| **paho-mqtt** | MQTT client | Industry standard for IoT messaging, reliable QoS support, wide hardware compatibility |
| **SQLite + aiosqlite** | Database | Zero-config, file-based, perfect for edge deployment (Raspberry Pi), async via aiosqlite |
| **SQLAlchemy 2.0** | ORM | Modern async engine, declarative models, easy migration path to PostgreSQL |
| **scikit-learn** | ML models | Lightweight, well-tested IsolationForest and GradientBoosting implementations |
| **Chart.js** | Frontend charts | CDN-ready, responsive, excellent line chart with annotations |
| **ReportLab** | PDF generation | Pure Python, no external dependencies, professional layout capabilities |
| **Fast2SMS** | SMS alerts | Simple REST API, no SDK overhead, reliable delivery |
| **Anthropic Claude** | AI reports | High-quality text generation, structured output, domain expertise |
| **WebSockets** | Real-time push | Native FastAPI support, browser-native API, bi-directional communication |

## Module Breakdown

### `config/settings.py`
Centralized configuration using pydantic-settings BaseSettings. All environment variables are loaded from `.env` with sensible defaults. This ensures no secrets are hardcoded and config is easily changed per environment.

### `models/`
Database layer: `database.py` provides the async SQLAlchemy engine and session factory. `orm_models.py` defines the `sensor_readings` and `incidents` tables. `schemas.py` defines Pydantic models for API request/response validation with range checking.

### `processing/`
The core analytics pipeline. `baseline.py` maintains a rolling window of temperature statistics. `exposure.py` tracks cumulative time outside the safe range. `vvm.py` implements the Arrhenius equation for irreversible heat damage. `risk_engine.py` combines four signals into a 0-100 risk score. `pipeline.py` orchestrates all stages per reading.

### `ml/`
Machine learning layer. `anomaly_detector.py` wraps IsolationForest for real-time anomaly detection. `prediction_model.py` wraps GradientBoostingClassifier to predict ETA to CRITICAL status. `trainer.py` provides offline training from CSV data. Models auto-train on synthetic data if no saved model exists.

### `services/`
External service integrations. `sms_service.py` sends alerts via Fast2SMS. `report_service.py` generates formal incident reports using Claude AI with a comprehensive fallback. `pdf_service.py` creates professional vaccine passport PDFs using ReportLab.

### `triggers/`
The `trigger_engine.py` monitors status changes and fires all output actions (SMS, report, PDF) in parallel when a status escalation is detected.

### `api/`
REST API routes and WebSocket management. `routes.py` defines all HTTP endpoints. `websocket_manager.py` handles multi-client WebSocket broadcasting.

### `mqtt/`
Data ingestion layer. `subscriber.py` connects to Mosquitto and bridges MQTT messages to the async pipeline. `simulator.py` replays CSV data for demo/hackathon mode.

### `frontend/`
Professional dark-themed medical dashboard. `index.html` provides the structure, `style.css` the clinical-precision design, and `dashboard.js` the Chart.js integration and WebSocket client logic.

## Environment Setup

### Prerequisites
- Python 3.10+
- pip (Python package manager)
- Mosquitto MQTT broker (only for live mode)

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd smart-vaccine-monitor

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
cp .env.example .env

# Edit .env with your API keys (optional for sim mode)
```

### Environment Variables

Edit `.env` file:
- `SIMULATION_MODE=true` — Use CSV simulator (default for demo)
- `FAST2SMS_API_KEY` — Your Fast2SMS API key (optional)
- `ANTHROPIC_API_KEY` — Your Anthropic API key (optional, fallback reports work without it)

## Running the System

### Simulation Mode (Demo/Hackathon)

```bash
# Make sure SIMULATION_MODE=true in .env
uvicorn main:app --reload
```

Open `http://localhost:8000` in your browser.

### Live Mode (with Raspberry Pi + MQTT)

```bash
# 1. Install and start Mosquitto
mosquitto -v

# 2. Set SIMULATION_MODE=false in .env
# 3. Configure MQTT_BROKER_HOST if not localhost

uvicorn main:app --reload
```

### Running ML Training Manually

```bash
python -m ml.trainer
```

## API Reference

| Method | Path | Description | Example |
|---|---|---|---|
| GET | `/` | Dashboard UI | `curl http://localhost:8000/` |
| GET | `/health` | Health check | `curl http://localhost:8000/health` |
| GET | `/api/readings?limit=60` | Last N readings | `curl http://localhost:8000/api/readings?limit=10` |
| GET | `/api/readings/latest` | Latest reading | `curl http://localhost:8000/api/readings/latest` |
| GET | `/api/status` | Current status | `curl http://localhost:8000/api/status` |
| GET | `/api/incidents` | All incidents | `curl http://localhost:8000/api/incidents` |
| GET | `/api/report/latest` | Latest report | `curl http://localhost:8000/api/report/latest` |
| GET | `/api/pdf/{id}` | Download PDF | `curl -O http://localhost:8000/api/pdf/1` |
| POST | `/api/simulate/trigger` | Manual trigger | `curl -X POST http://localhost:8000/api/simulate/trigger -H 'Content-Type: application/json' -d '{"temp_internal": 15}'` |
| WS | `/ws` | Live stream | WebSocket client |

## Demo Flow (Hackathon)

1. **Start the system**: `uvicorn main:app --reload`
2. **Open dashboard**: Navigate to `http://localhost:8000`
3. **Watch normal operation**: First 60 readings show stable temperature (3.5-5.5°C), all green
4. **Warming trend begins**: Around reading 61, temperature starts rising gradually
5. **WARNING triggered**: Status badge turns amber, SMS alert fires, ETA countdown appears
6. **CRITICAL breach**: Status turns red, Claude generates formal incident report, PDF passport created
7. **Recovery**: Temperature drops back to safe range, status returns to SAFE
8. **Anomaly spikes**: Brief spikes trigger anomaly detection (red flash on temp card)
9. **Second excursion**: Mild WARNING demonstrates recurring monitoring
10. **Show outputs**: Click refresh on report panel, download PDF from `/api/pdf/1`

## Future Scalability

- **PostgreSQL/TimescaleDB**: Migrate from SQLite for production-scale time-series storage
- **AWS IoT Core**: Replace local Mosquitto with managed MQTT for global deployments
- **Docker/Kubernetes**: Containerize for cloud deployment and horizontal scaling
- **React Frontend**: Upgrade to React with TanStack Query for complex dashboard features
- **Multi-sensor support**: Extend to monitor multiple vaccine refrigerators simultaneously
- **Historical analytics**: Add trend analysis, predictive maintenance, compliance scoring
- **Mobile app**: Push notifications via Firebase Cloud Messaging
