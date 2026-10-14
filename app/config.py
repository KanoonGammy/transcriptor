import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
EXPORTS_DIR = DATA_DIR / "exports"
FONTS_DIR = BASE_DIR / "assets" / "fonts"
DB_PATH = DATA_DIR / "transcriptor.db"

# Create directories if they do not exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# Server config
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

# Security
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-change-this-in-production-1234567890")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "72"))

# Default Admin credentials
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "AdminPassword123!")
DEFAULT_ADMIN_NAME = os.getenv("DEFAULT_ADMIN_NAME", "System Administrator")

# ElevenLabs Initial Key (if passed in env)
ENV_ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Default Retention Policy: "keep_all", "1_day", "3_days", "7_days", "30_days", "immediate"
DEFAULT_RETENTION_POLICY = os.getenv("AUDIO_RETENTION_POLICY", "7_days")
