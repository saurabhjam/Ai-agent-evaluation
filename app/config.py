from datetime import datetime, timezone
from pathlib import Path

from pydantic import field_validator, SecretStr
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    # Judge model
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Simulated user model (Groq)
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    calling_diagnostics_enabled: bool = False
    calling_diagnostics_encrypted_text: bool = False
    calling_diagnostics_encryption_key: SecretStr = SecretStr("")

    # Simulated user model
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # Seeded Defects
    defect_generic_greeting_loop: bool = False

    # User Action Engine
    enable_user_action_engine: bool = False
    chatbot_execution_mode: str = "legacy"
    interaction_timeout_seconds: float = 300.0


    # Storage
    db_path: str = "./eval_results.db"
    management_baseline_at: datetime = datetime(2026, 10, 21, 11, 0, 22, tzinfo=timezone.utc)

    # Backend validation limits — enforced in schemas.py
    max_turns_per_run: int = 12
    min_turns_per_run: int = 2

    class Config:
        env_file = PROJECT_ROOT / ".env"
        extra = "ignore"


settings = Settings()
