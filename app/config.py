from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"
VOICES_DIR = DATA_DIR / "voices"

for d in [DATA_DIR, RESULTS_DIR, VOICES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin_pass_123"
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DATA_DIR / 'db.sqlite3'}"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    CLOUDFLARED_ENABLED: bool = False
    SERVER_URL: str = "http://localhost:8000"

settings = Settings()
