import io
from datetime import datetime
from typing import Dict, Any, List
from app.elevenlabs_service import format_seconds

def export_to_txt(transcription_data: Dict[str, Any], include_timestamps: bool = True) -> io.BytesIO:
    """
    Generate clean UTF-8 plain text export (.txt).
    """
    title_text = transcription_data.get("title") or transcription_data.get("filename") or "เอกสารการถอดเสียง"
    filename = transcription_data.get("filename", "-")
    duration_sec = transcription_data.get("duration") or 0.0
    lang = transcription_data.get("language_code") or "th"
    created_at = transcription_data.get("created_at", "")
    speaker_map = transcription_data.get("speaker_map") or {}
    segments: List[Dict[str, Any]] = transcription_data.get("segments") or []
    full_text = transcription_data.get("formatted_text") or transcription_data.get("full_text") or ""

    lines = []
    lines.append("=" * 60)
    lines.append(f" {title_text}")
    lines.append("=" * 60)
    lines.append(f"ไฟล์ต้นฉบับ : {filename}")
    lines.append(f"ความยาวเสียง : {format_seconds(duration_sec)}")
    lines.append(f"ภาษาที่ตรวจพบ : {lang.upper()}")
    lines.append(f"วันที่ถอดเสียง : {created_at[:19] if created_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if speaker_map:
        lines.append(f"ผู้พูด : {', '.join(speaker_map.values())}")
    lines.append("=" * 60)
    lines.append("")

    if segments and include_timestamps:
        for seg in segments:
            spk_id = seg.get("speaker_id") or "speaker_0"
            spk_name = speaker_map.get(spk_id, spk_id)
            start_str = format_seconds(seg.get("start", 0.0))
            end_str = format_seconds(seg.get("end", 0.0))
            text_content = seg.get("text", "").strip()

            lines.append(f"[{start_str} - {end_str}] {spk_name}:")
            lines.append(f"  {text_content}")
            lines.append("")
    else:
        lines.append(full_text)

    content = "\n".join(lines)
    buffer = io.BytesIO(content.encode("utf-8-sig")) # UTF-8 with BOM for perfect Windows Notepad display
    buffer.seek(0)
    return buffer
