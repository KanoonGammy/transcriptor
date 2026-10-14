import os
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import uuid

from app.config import UPLOADS_DIR, EXPORTS_DIR, DB_PATH
from app.database import get_db_connection, get_setting, log_activity

logger = logging.getLogger("transcriptor.storage")

def save_uploaded_audio(file_obj, filename: str) -> Tuple[str, Path, int]:
    """
    Save incoming file stream to UPLOADS_DIR with a unique UUID.
    Returns: (file_id, saved_path, file_size_bytes)
    """
    file_id = str(uuid.uuid4())
    suffix = Path(filename).suffix.lower()
    if not suffix:
        suffix = ".mp3"
    
    saved_filename = f"{file_id}{suffix}"
    saved_path = UPLOADS_DIR / saved_filename

    file_size = 0
    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file_obj, buffer)
        file_size = saved_path.stat().st_size

    return file_id, saved_path, file_size

def get_storage_stats() -> Dict[str, Any]:
    """
    Get detailed storage breakdown:
    - Audio upload files count and total size
    - Exports cache size
    - Database size
    - Disk free / total space
    """
    upload_count = 0
    upload_bytes = 0
    if UPLOADS_DIR.exists():
        for f in UPLOADS_DIR.iterdir():
            if f.is_file():
                upload_count += 1
                upload_bytes += f.stat().st_size

    exports_bytes = 0
    if EXPORTS_DIR.exists():
        for f in EXPORTS_DIR.iterdir():
            if f.is_file():
                exports_bytes += f.stat().st_size

    db_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0

    # Disk space
    disk_total = 0
    disk_free = 0
    try:
        usage = shutil.disk_usage(str(UPLOADS_DIR))
        disk_total = usage.total
        disk_free = usage.free
    except Exception:
        pass

    return {
        "upload_files_count": upload_count,
        "upload_bytes": upload_bytes,
        "exports_bytes": exports_bytes,
        "db_bytes": db_bytes,
        "total_app_bytes": upload_bytes + exports_bytes + db_bytes,
        "disk_free_bytes": disk_free,
        "disk_total_bytes": disk_total,
        "retention_policy": get_setting("retention_policy", "7_days")
    }

def run_retention_cleanup(enforced_policy: Optional[str] = None, triggered_by_user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Execute storage retention cleanup according to policy:
    - immediate: delete file as soon as completed
    - 1_day, 3_days, 7_days, 30_days: delete files older than threshold
    - keep_all: skip
    """
    policy = enforced_policy or get_setting("retention_policy", "7_days")
    if policy == "keep_all":
        return {"deleted_files": 0, "freed_bytes": 0, "policy": policy}

    days_map = {
        "immediate": 0,
        "1_day": 1,
        "3_days": 3,
        "7_days": 7,
        "30_days": 30,
    }
    threshold_days = days_map.get(policy, 7)
    cutoff_time = datetime.now() - timedelta(days=threshold_days)

    deleted_count = 0
    freed_bytes = 0

    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Query completed transcriptions with local file_path
        if policy == "immediate":
            cursor.execute("""
                SELECT id, file_path, title FROM transcriptions 
                WHERE status = 'completed' AND file_path IS NOT NULL;
            """)
        else:
            cursor.execute("""
                SELECT id, file_path, title FROM transcriptions 
                WHERE status = 'completed' AND file_path IS NOT NULL AND completed_at <= ?;
            """, (cutoff_time.isoformat(),))

        rows = cursor.fetchall()
        for row in rows:
            f_path_str = row["file_path"]
            if f_path_str:
                p = Path(f_path_str)
                if p.exists() and p.is_file():
                    try:
                        sz = p.stat().st_size
                        p.unlink()
                        freed_bytes += sz
                        deleted_count += 1
                    except Exception as e:
                        logger.warning("Could not delete file %s: %s", p, e)
            
            # Update transcription record: file is purged, transcript preserved
            cursor.execute("UPDATE transcriptions SET file_path = NULL WHERE id = ?;", (row["id"],))

        conn.commit()

    if deleted_count > 0:
        log_activity(
            action="FILE_CLEANUP",
            user_id=triggered_by_user_id,
            username="System/Admin",
            target="uploads",
            details=f"Cleaned up {deleted_count} audio files ({freed_bytes / (1024*1024):.2f} MB freed) using policy '{policy}'."
        )

    return {
        "deleted_files": deleted_count,
        "freed_bytes": freed_bytes,
        "policy": policy
    }

def delete_single_audio_file(file_path_str: Optional[str]):
    """Safely delete a single audio file from disk."""
    if not file_path_str:
        return
    try:
        p = Path(file_path_str)
        if p.exists() and p.is_file():
            p.unlink()
    except Exception as e:
        logger.warning("Failed to delete audio file %s: %s", file_path_str, e)
