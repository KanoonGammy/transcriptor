import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
import bcrypt

from app.config import (
    DB_PATH,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_NAME,
    ENV_ELEVENLABS_API_KEY,
    DEFAULT_RETENTION_POLICY,
)

logger = logging.getLogger("transcriptor.db")

def get_db_connection() -> sqlite3.Connection:
    """Return a connection with WAL enabled and row factory as Row."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initialize database tables and create initial admin user if not present."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );
        """)

        # System settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT,
                updated_by INTEGER
            );
        """)

        # Transcriptions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transcriptions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT,
                file_size INTEGER,
                duration REAL,
                status TEXT NOT NULL DEFAULT 'queued',
                language_code TEXT,
                model_id TEXT DEFAULT 'scribe_v1',
                diarize INTEGER DEFAULT 1,
                num_speakers INTEGER,
                raw_response TEXT,
                formatted_text TEXT,
                segments TEXT,
                speaker_map TEXT,
                created_by_user_id INTEGER NOT NULL,
                created_by_username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT,
                FOREIGN KEY (created_by_user_id) REFERENCES users (id)
            );
        """)

        # Activity logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                ip_address TEXT,
                action TEXT NOT NULL,
                target TEXT,
                details TEXT
            );
        """)

        conn.commit()

        # Seed initial admin if no users exist
        cursor.execute("SELECT COUNT(*) FROM users;")
        user_count = cursor.fetchone()[0]
        if user_count == 0:
            salt = bcrypt.gensalt()
            hashed_pwd = bcrypt.hashpw(DEFAULT_ADMIN_PASSWORD.encode("utf-8"), salt).decode("utf-8")
            now_iso = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO users (username, password_hash, full_name, role, is_active, created_at)
                VALUES (?, ?, ?, 'admin', 1, ?);
            """, (DEFAULT_ADMIN_USERNAME, hashed_pwd, DEFAULT_ADMIN_NAME, now_iso))
            conn.commit()
            logger.info("Created default administrator: %s", DEFAULT_ADMIN_USERNAME)

            # Log this event
            log_activity(
                user_id=1,
                username=DEFAULT_ADMIN_USERNAME,
                ip_address="127.0.0.1",
                action="SYSTEM_INIT",
                target="users",
                details="Initial administrator account created automatically."
            )

        # Initialize default settings if missing
        default_settings = {
            "elevenlabs_api_key": ENV_ELEVENLABS_API_KEY,
            "default_model": "scribe_v1",
            "retention_policy": DEFAULT_RETENTION_POLICY,
            "system_name": "Transcriptor Pro",
        }
        for k, v in default_settings.items():
            cursor.execute("SELECT key FROM settings WHERE key = ?;", (k,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO settings (key, value, updated_at, updated_by)
                    VALUES (?, ?, ?, 1);
                """, (k, v, datetime.now().isoformat()))
        conn.commit()

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve setting value by key."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?;", (key,))
        row = cursor.fetchone()
        if row and row["value"] is not None:
            return row["value"]
        return default

def set_setting(key: str, value: str, updated_by_user_id: int):
    """Set or update setting value."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO settings (key, value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by;
        """, (key, value, now_iso, updated_by_user_id))
        conn.commit()

def log_activity(
    action: str,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    ip_address: Optional[str] = None,
    target: Optional[str] = None,
    details: Optional[str] = None
):
    """Record an audit trail activity in activity_logs."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO activity_logs (timestamp, user_id, username, ip_address, action, target, details)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (
                datetime.now().isoformat(),
                user_id,
                username or "System",
                ip_address or "-",
                action,
                target or "-",
                details or ""
            ))
            conn.commit()
    except Exception as e:
        logger.error("Failed to write activity log: %s", e)
