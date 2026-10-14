import os
import json
import logging
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    Request,
    Response,
    HTTPException,
    status,
    Depends,
    Query
)
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from app.database import get_db_connection, get_setting, log_activity
from app.auth import get_current_user
from app.storage_manager import save_uploaded_audio, delete_single_audio_file
from app.elevenlabs_service import (
    transcribe_audio_file,
    build_segments,
    format_seconds
)
from app.exporters import export_to_docx, export_to_pdf, export_to_txt

logger = logging.getLogger("transcriptor.api")
router = APIRouter(prefix="/api/transcriptions", tags=["transcriptions"])

def background_transcribe_task(
    transcription_id: str,
    user_id: int,
    username: str,
    client_ip: str
):
    """
    Background worker to call ElevenLabs Speech-to-Text and update DB.
    """
    logger.info("Starting background transcription task for ID: %s", transcription_id)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transcriptions WHERE id = ?;", (transcription_id,))
        task_row = cursor.fetchone()
        if not task_row:
            return

        file_path = Path(task_row["file_path"]) if task_row["file_path"] else None
        model_id = task_row["model_id"] or "scribe_v1"
        language_code = task_row["language_code"]
        diarize = bool(task_row["diarize"])
        num_speakers = task_row["num_speakers"]

        # Fetch ElevenLabs API Key
        api_key = get_setting("elevenlabs_api_key", "")
        if not api_key:
            err_msg = "ElevenLabs API Key ยังไม่ได้ตั้งค่า กรุณาใส่ API Key ในหน้า Settings ก่อนใช้งาน"
            cursor.execute("""
                UPDATE transcriptions 
                SET status = 'failed', error_message = ?
                WHERE id = ?;
            """, (err_msg, transcription_id))
            conn.commit()
            log_activity(
                action="TRANSCRIBE_FAIL",
                user_id=user_id,
                username=username,
                ip_address=client_ip,
                target=transcription_id,
                details=err_msg
            )
            return

        # Mark as processing
        cursor.execute("UPDATE transcriptions SET status = 'processing' WHERE id = ?;", (transcription_id,))
        conn.commit()

        log_activity(
            action="TRANSCRIBE_START",
            user_id=user_id,
            username=username,
            ip_address=client_ip,
            target=transcription_id,
            details=f"Processing file '{task_row['filename']}' using {model_id}"
        )

        try:
            # Call ElevenLabs Scribe API
            raw_res = transcribe_audio_file(
                file_path=file_path,
                api_key=api_key,
                model_id=model_id,
                language_code=language_code,
                diarize=diarize,
                num_speakers=num_speakers
            )

            # Build segments & speaker map
            processed = build_segments(raw_res)
            now_iso = datetime.now().isoformat()

            cursor.execute("""
                UPDATE transcriptions SET
                    status = 'completed',
                    duration = ?,
                    language_code = ?,
                    raw_response = ?,
                    formatted_text = ?,
                    segments = ?,
                    speaker_map = ?,
                    completed_at = ?,
                    error_message = NULL
                WHERE id = ?;
            """, (
                processed["duration"],
                processed["language_code"],
                json.dumps(raw_res, ensure_ascii=False),
                processed["formatted_text"],
                json.dumps(processed["segments"], ensure_ascii=False),
                json.dumps(processed["speaker_map"], ensure_ascii=False),
                now_iso,
                transcription_id
            ))
            conn.commit()

            log_activity(
                action="TRANSCRIBE_DONE",
                user_id=user_id,
                username=username,
                ip_address=client_ip,
                target=transcription_id,
                details=f"Completed transcription for '{task_row['filename']}' (Duration: {format_seconds(processed['duration'])})"
            )

            # Immediate cleanup check if retention policy is "immediate"
            retention_policy = get_setting("retention_policy", "7_days")
            if retention_policy == "immediate" and file_path and file_path.exists():
                try:
                    file_path.unlink()
                    cursor.execute("UPDATE transcriptions SET file_path = NULL WHERE id = ?;", (transcription_id,))
                    conn.commit()
                except Exception as e:
                    logger.warning("Could not immediately purge audio file: %s", e)

        except Exception as e:
            err_msg = str(e)
            logger.error("Transcription failed for ID %s: %s", transcription_id, err_msg)
            cursor.execute("""
                UPDATE transcriptions SET
                    status = 'failed',
                    error_message = ?
                WHERE id = ?;
            """, (err_msg, transcription_id))
            conn.commit()

            log_activity(
                action="TRANSCRIBE_FAIL",
                user_id=user_id,
                username=username,
                ip_address=client_ip,
                target=transcription_id,
                details=f"Error transcribing '{task_row['filename']}': {err_msg}"
            )

@router.post("/upload")
def upload_and_transcribe(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    model_id: Optional[str] = Form(None),
    language_code: Optional[str] = Form(None),
    diarize: bool = Form(True),
    num_speakers: Optional[int] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Upload an audio or video file and enqueue transcription.
    """
    client_ip = request.client.host if request.client else "unknown"

    # Validate file extension
    original_filename = file.filename or "audio_file.mp3"
    allowed_exts = {".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".webm", ".flac", ".aac", ".wma"}
    ext = Path(original_filename).suffix.lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"รูปแบบไฟล์ไม่รองรับ ({ext}) รองรับเฉพาะ: {', '.join(allowed_exts)}"
        )

    # Save uploaded file
    file_id, saved_path, file_size = save_uploaded_audio(file.file, original_filename)

    task_title = (title or "").strip()
    if not task_title:
        task_title = Path(original_filename).stem

    default_model = get_setting("default_model", "scribe_v1")
    chosen_model = model_id or default_model
    now_iso = datetime.now().isoformat()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transcriptions (
                id, title, filename, file_path, file_size, status,
                language_code, model_id, diarize, num_speakers,
                created_by_user_id, created_by_username, created_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?);
        """, (
            file_id,
            task_title,
            original_filename,
            str(saved_path),
            file_size,
            language_code or "auto",
            chosen_model,
            1 if diarize else 0,
            num_speakers,
            current_user["id"],
            current_user["username"],
            now_iso
        ))
        conn.commit()

    log_activity(
        action="UPLOAD",
        user_id=current_user["id"],
        username=current_user["username"],
        ip_address=client_ip,
        target=file_id,
        details=f"Uploaded file '{original_filename}' ({file_size / (1024*1024):.2f} MB)"
    )

    # Schedule background transcription task
    background_tasks.add_task(
        background_transcribe_task,
        transcription_id=file_id,
        user_id=current_user["id"],
        username=current_user["username"],
        client_ip=client_ip
    )

    return {
        "id": file_id,
        "title": task_title,
        "filename": original_filename,
        "file_size": file_size,
        "status": "queued",
        "message": "อัปโหลดไฟล์สำเร็จ และระบบกำลังเริ่มถอดเสียงในพื้นหลัง"
    }

@router.get("")
def list_transcriptions(
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    List transcriptions.
    Admins see all; normal users see only their own.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        conditions = []
        params = []

        if current_user["role"] != "admin":
            conditions.append("created_by_user_id = ?")
            params.append(current_user["id"])

        if search and search.strip():
            conditions.append("(title LIKE ? OR filename LIKE ?)")
            term = f"%{search.strip()}%"
            params.extend([term, term])

        if status_filter and status_filter.strip():
            conditions.append("status = ?")
            params.append(status_filter.strip())

        where_str = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor.execute(f"""
            SELECT 
                id, title, filename, file_size, duration, status,
                language_code, model_id, diarize,
                created_by_user_id, created_by_username, created_at, completed_at,
                error_message, (file_path IS NOT NULL) AS has_audio
            FROM transcriptions
            {where_str}
            ORDER BY created_at DESC;
        """, tuple(params))

        items = [dict(row) for row in cursor.fetchall()]
        return {"transcriptions": items}

@router.get("/{transcription_id}")
def get_transcription_detail(
    transcription_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get full details of a transcription including segments and speaker map."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transcriptions WHERE id = ?;", (transcription_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcription not found")

        # Access check
        if current_user["role"] != "admin" and row["created_by_user_id"] != current_user["id"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        data = dict(row)
        # Parse JSON fields
        if data.get("segments"):
            try:
                data["segments"] = json.loads(data["segments"])
            except Exception:
                data["segments"] = []
        else:
            data["segments"] = []

        if data.get("speaker_map"):
            try:
                data["speaker_map"] = json.loads(data["speaker_map"])
            except Exception:
                data["speaker_map"] = {}
        else:
            data["speaker_map"] = {}

        data["has_audio"] = bool(data.get("file_path") and Path(data["file_path"]).exists())
        # Drop raw_response from standard payload for fast network transmission
        data.pop("raw_response", None)

        return data

class UpdateSpeakersRequest(BaseModel):
    speaker_map: Dict[str, str]

@router.put("/{transcription_id}/speakers")
def update_speakers(
    transcription_id: str,
    req: UpdateSpeakersRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Update custom speaker display names."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT created_by_user_id, segments, full_text FROM transcriptions WHERE id = ?;", (transcription_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        if current_user["role"] != "admin" and row["created_by_user_id"] != current_user["id"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        new_map = req.speaker_map
        # Recalculate formatted text
        segments = []
        if row["segments"]:
            try:
                segments = json.loads(row["segments"])
            except Exception:
                pass

        formatted_dialogue_lines = []
        if segments:
            for seg in segments:
                spk_id = seg.get("speaker_id") or "speaker_0"
                spk_name = new_map.get(spk_id, spk_id)
                time_tag = f"[{format_seconds(seg.get('start', 0.0))} - {format_seconds(seg.get('end', 0.0))}]"
                formatted_dialogue_lines.append(f"{time_tag} {spk_name}:\n{seg.get('text', '')}\n")
        
        new_formatted_text = "\n".join(formatted_dialogue_lines)

        cursor.execute("""
            UPDATE transcriptions SET
                speaker_map = ?,
                formatted_text = ?
            WHERE id = ?;
        """, (json.dumps(new_map, ensure_ascii=False), new_formatted_text, transcription_id))
        conn.commit()

        return {"message": "บันทึกชื่อผู้พูดสำเร็จ", "speaker_map": new_map}

@router.get("/{transcription_id}/audio")
def stream_audio(
    transcription_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Stream audio file for the Webapp player."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, created_by_user_id, filename FROM transcriptions WHERE id = ?;", (transcription_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Transcription not found")

        if current_user["role"] != "admin" and row["created_by_user_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        if not row["file_path"]:
            raise HTTPException(status_code=404, detail="ไฟล์เสียงถูกลบตามนโยบายจัดเก็บแล้ว (Audio file has been purged)")

        audio_path = Path(row["file_path"])
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Audio file not found on disk")

        ext = audio_path.suffix.lower()
        mime_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".mp4": "video/mp4",
            ".ogg": "audio/ogg",
            ".webm": "audio/webm",
            ".flac": "audio/flac",
            ".aac": "audio/aac",
        }
        content_type = mime_map.get(ext, "audio/mpeg")

        return FileResponse(
            path=str(audio_path),
            media_type=content_type,
            filename=row["filename"]
        )

@router.get("/{transcription_id}/export/{export_format}")
def export_transcription(
    transcription_id: str,
    export_format: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Download transcription as Word (.docx), PDF (.pdf), or Plain Text (.txt).
    """
    client_ip = request.client.host if request.client else "unknown"
    clean_format = export_format.lower().strip()
    if clean_format not in ("docx", "pdf", "txt"):
        raise HTTPException(status_code=400, detail="Invalid export format. Must be docx, pdf, or txt.")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transcriptions WHERE id = ?;", (transcription_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Transcription not found")

        if current_user["role"] != "admin" and row["created_by_user_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        if row["status"] != "completed":
            raise HTTPException(status_code=400, detail="การถอดเสียงยังไม่เสร็จสมบูรณ์")

        data = dict(row)
        if data.get("segments"):
            try:
                data["segments"] = json.loads(data["segments"])
            except Exception:
                data["segments"] = []
        else:
            data["segments"] = []

        if data.get("speaker_map"):
            try:
                data["speaker_map"] = json.loads(data["speaker_map"])
            except Exception:
                data["speaker_map"] = {}
        else:
            data["speaker_map"] = {}

    title_safe = (data.get("title") or "transcript").replace(" ", "_")
    # Clean filename for header
    base_name = f"{title_safe}_{transcription_id[:8]}"

    if clean_format == "docx":
        stream = export_to_docx(data)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = f"{base_name}.docx"
        action_name = "DOWNLOAD_DOCX"
    elif clean_format == "pdf":
        stream = export_to_pdf(data)
        media_type = "application/pdf"
        filename = f"{base_name}.pdf"
        action_name = "DOWNLOAD_PDF"
    else:
        stream = export_to_txt(data)
        media_type = "text/plain; charset=utf-8"
        filename = f"{base_name}.txt"
        action_name = "DOWNLOAD_TXT"

    # Log download activity
    log_activity(
        action=action_name,
        user_id=current_user["id"],
        username=current_user["username"],
        ip_address=client_ip,
        target=transcription_id,
        details=f"Downloaded '{filename}'"
    )

    # Encode RFC 5987 filename for non-ascii characters
    encoded_fn = urllib.parse.quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{encoded_fn}\"; filename*=UTF-8''{encoded_fn}"
    }

    return StreamingResponse(
        stream,
        media_type=media_type,
        headers=headers
    )

@router.delete("/{transcription_id}")
def delete_transcription(
    transcription_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Delete a transcription record and its local audio file."""
    client_ip = request.client.host if request.client else "unknown"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, filename, file_path, created_by_user_id FROM transcriptions WHERE id = ?;", (transcription_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Transcription not found")

        if current_user["role"] != "admin" and row["created_by_user_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        # Delete local file if still present
        delete_single_audio_file(row["file_path"])

        cursor.execute("DELETE FROM transcriptions WHERE id = ?;", (transcription_id,))
        conn.commit()

        log_activity(
            action="DELETE_TRANSCRIPT",
            user_id=current_user["id"],
            username=current_user["username"],
            ip_address=client_ip,
            target=transcription_id,
            details=f"Deleted transcription '{row['title']}' ({row['filename']})"
        )

        return {"message": "ลบรายการถอดเสียงเรียบร้อยแล้ว"}
