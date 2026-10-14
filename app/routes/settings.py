from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel

from app.database import get_db_connection, get_setting, set_setting, log_activity
from app.auth import require_admin
from app.elevenlabs_service import test_api_key
from app.storage_manager import get_storage_stats, run_retention_cleanup

router = APIRouter(prefix="/api/settings", tags=["settings"])

class UpdateSettingsRequest(BaseModel):
    elevenlabs_api_key: Optional[str] = None
    default_model: Optional[str] = None
    retention_policy: Optional[str] = None
    system_name: Optional[str] = None

class TestKeyRequest(BaseModel):
    api_key: Optional[str] = None

def mask_key(k: Optional[str]) -> str:
    """Mask API key for safe UI display: sk_abc...1234"""
    if not k:
        return ""
    k = k.strip()
    if len(k) <= 8:
        return "********"
    return f"{k[:4]}...{k[-4:]}"

@router.get("")
def get_settings(current_admin: Dict[str, Any] = Depends(require_admin)):
    """Fetch current system configuration and storage statistics."""
    raw_key = get_setting("elevenlabs_api_key", "")
    default_model = get_setting("default_model", "scribe_v1")
    retention_policy = get_setting("retention_policy", "7_days")
    system_name = get_setting("system_name", "Transcriptor Pro")

    storage_stats = get_storage_stats()

    return {
        "settings": {
            "has_api_key": bool(raw_key and raw_key.strip()),
            "masked_api_key": mask_key(raw_key),
            "default_model": default_model,
            "retention_policy": retention_policy,
            "system_name": system_name,
        },
        "storage": storage_stats
    }

@router.post("")
def save_settings(
    req: UpdateSettingsRequest,
    request: Request,
    current_admin: Dict[str, Any] = Depends(require_admin)
):
    """Save updated system settings."""
    client_ip = request.client.host if request.client else "unknown"
    user_id = current_admin["id"]

    updated_fields = []

    if req.elevenlabs_api_key is not None:
        key_val = req.elevenlabs_api_key.strip()
        # Don't overwrite with masked string
        if not key_val.startswith("...") and not "..." in key_val:
            set_setting("elevenlabs_api_key", key_val, user_id)
            updated_fields.append("ElevenLabs API Key")

    if req.default_model is not None:
        if req.default_model in ("scribe_v1", "scribe_v2"):
            set_setting("default_model", req.default_model, user_id)
            updated_fields.append(f"Default Model ({req.default_model})")

    if req.retention_policy is not None:
        valid_policies = ("keep_all", "immediate", "1_day", "3_days", "7_days", "30_days")
        if req.retention_policy in valid_policies:
            set_setting("retention_policy", req.retention_policy, user_id)
            updated_fields.append(f"Retention Policy ({req.retention_policy})")

    if req.system_name is not None and req.system_name.strip():
        set_setting("system_name", req.system_name.strip(), user_id)
        updated_fields.append("System Name")

    log_activity(
        action="UPDATE_SETTINGS",
        user_id=user_id,
        username=current_admin["username"],
        ip_address=client_ip,
        target="settings",
        details=f"Admin updated settings: {', '.join(updated_fields)}"
    )

    return {"message": "บันทึกการตั้งค่าเรียบร้อยแล้ว", "updated": updated_fields}

@router.post("/test-elevenlabs")
def test_elevenlabs_key(
    req: TestKeyRequest,
    current_admin: Dict[str, Any] = Depends(require_admin)
):
    """Verify ElevenLabs API key against API."""
    key_to_test = req.api_key
    if not key_to_test or not key_to_test.strip():
        key_to_test = get_setting("elevenlabs_api_key", "")

    if not key_to_test:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="กรุณาระบุ ElevenLabs API Key หรือบันทึกไว้ในระบบก่อนทดสอบ"
        )

    result = test_api_key(key_to_test)
    return result

@router.post("/cleanup-storage")
def trigger_storage_cleanup(
    request: Request,
    current_admin: Dict[str, Any] = Depends(require_admin)
):
    """Manually invoke retention cleanup to delete old audio files and free space."""
    res = run_retention_cleanup(triggered_by_user_id=current_admin["id"])
    stats = get_storage_stats()
    return {
        "message": f"ล้างไฟล์เสียงเก่าสำเร็จ: ลบ {res['deleted_files']} ไฟล์ (คืนพื้นที่ {res['freed_bytes'] / (1024*1024):.2f} MB)",
        "result": res,
        "current_storage": stats
    }
