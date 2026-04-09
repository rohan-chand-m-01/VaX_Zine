"""Configuration settings module using pydantic-settings."""

from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    MQTT_BROKER_HOST: str = Field(default="localhost")
    MQTT_BROKER_PORT: int = Field(default=1883)
    MQTT_TOPIC: str = Field(default="vaccines/sensor/data")
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./vaccine_monitor.db")
    SMS_PROVIDER: str = Field(default="twilio")  # "twilio" or "fast2sms"
    FAST2SMS_API_KEY: str = Field(default="your_key_here")
    FAST2SMS_PHONE_NUMBER: str = Field(default="9999999999")
    TWILIO_ACCOUNT_SID: str = Field(default="your_sid_here")
    TWILIO_AUTH_TOKEN: str = Field(default="your_token_here")
    TWILIO_FROM_NUMBER: str = Field(default="+1234567890")
    TWILIO_TO_NUMBER: str = Field(default="+916204675554")
    ANTHROPIC_API_KEY: str = Field(default="your_key_here")
    SIMULATION_MODE: bool = Field(default=False)
    SIMULATION_CSV_PATH: str = Field(default="simulation/sample_data.csv")
    SIMULATION_INTERVAL_SECONDS: int = Field(default=3)
    LOG_LEVEL: str = Field(default="INFO")
    SAFE_TEMP_MIN: float = Field(default=2.0)
    SAFE_TEMP_MAX: float = Field(default=8.0)
    BASELINE_WINDOW: int = Field(default=50)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


settings = Settings()
