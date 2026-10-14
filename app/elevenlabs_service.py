import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import requests

logger = logging.getLogger("transcriptor.elevenlabs")

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"

def format_seconds(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds is None:
        return "00:00"
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def test_api_key(api_key: str) -> Dict[str, Any]:
    """
    Test ElevenLabs API key validity against their user endpoint.
    """
    if not api_key:
        return {"valid": False, "error": "API Key is empty"}

    url = f"{ELEVENLABS_BASE_URL}/user"
    headers = {"xi-api-key": api_key.strip()}

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            sub = data.get("subscription", {})
            return {
                "valid": True,
                "tier": sub.get("tier", "Unknown"),
                "character_count": sub.get("character_count", 0),
                "character_limit": sub.get("character_limit", 0),
                "status": sub.get("status", "active")
            }
        else:
            try:
                err_json = response.json()
                detail = err_json.get("detail", {}).get("message") or err_json.get("detail") or str(err_json)
            except Exception:
                detail = response.text
            return {"valid": False, "error": f"API Error ({response.status_code}): {detail}"}
    except requests.exceptions.RequestException as e:
        return {"valid": False, "error": f"Connection failed: {str(e)}"}

def transcribe_audio_file(
    file_path: Path,
    api_key: str,
    model_id: str = "scribe_v1",
    language_code: Optional[str] = None,
    diarize: bool = True,
    num_speakers: Optional[int] = None,
    tag_audio_events: bool = True
) -> Dict[str, Any]:
    """
    Submit audio/video file to ElevenLabs Speech-to-Text API (Scribe).
    """
    if not api_key:
        raise ValueError("ElevenLabs API Key is not configured. Please set it in Settings.")

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    url = f"{ELEVENLABS_BASE_URL}/speech-to-text"
    headers = {
        "xi-api-key": api_key.strip()
    }

    form_data = {
        "model_id": model_id or "scribe_v1",
        "diarize": "true" if diarize else "false",
        "tag_audio_events": "true" if tag_audio_events else "false",
        "timestamps_granularity": "word"
    }

    if language_code and language_code.strip() and language_code != "auto":
        form_data["language_code"] = language_code.strip()

    if num_speakers and num_speakers > 0:
        form_data["num_speakers"] = str(num_speakers)

    # Determine mime-type
    ext = file_path.suffix.lower()
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
    content_type = mime_map.get(ext, "application/octet-stream")

    logger.info("Sending file %s to ElevenLabs Scribe (model: %s, diarize: %s)", file_path.name, model_id, diarize)

    with open(file_path, "rb") as f:
        files = {
            "file": (file_path.name, f, content_type)
        }
        # ElevenLabs Scribe processing can take up to several minutes for large files
        response = requests.post(url, headers=headers, data=form_data, files=files, timeout=900)

    if response.status_code != 200:
        try:
            err_data = response.json()
            err_msg = err_data.get("detail", {}).get("message") or err_data.get("detail") or str(err_data)
        except Exception:
            err_msg = response.text
        raise RuntimeError(f"ElevenLabs Scribe API error ({response.status_code}): {err_msg}")

    result_json = response.json()
    return result_json

def build_segments(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse raw response and group words into dialogue segments.
    Returns:
    {
        "full_text": "...",
        "language_code": "tha",
        "segments": [
            {
                "speaker_id": "speaker_0",
                "start": 0.12,
                "end": 4.50,
                "text": "ข้อความ...",
                "words": [...]
            }
        ],
        "speaker_map": {
            "speaker_0": "ผู้พูด 1"
        },
        "duration": 120.5
    }
    """
    full_text = raw_data.get("text", "").strip()
    words = raw_data.get("words", [])
    lang = raw_data.get("language_code", "unknown")

    segments: List[Dict[str, Any]] = []
    speaker_set = set()
    max_end = 0.0

    if not words:
        # Fallback if no word-level timestamps returned
        return {
            "full_text": full_text,
            "language_code": lang,
            "segments": [{
                "speaker_id": "speaker_0",
                "start": 0.0,
                "end": 0.0,
                "text": full_text,
                "words": []
            }] if full_text else [],
            "speaker_map": {"speaker_0": "ผู้พูด 1"},
            "duration": 0.0
        }

    current_segment: Optional[Dict[str, Any]] = None

    for item in words:
        w_text = item.get("text", "")
        w_start = item.get("start", 0.0)
        w_end = item.get("end", w_start)
        w_type = item.get("type", "word")
        speaker = item.get("speaker_id") or "speaker_0"
        speaker_set.add(speaker)

        if w_end > max_end:
            max_end = w_end

        # Check if we should continue current segment or start a new one
        should_split = False
        if current_segment is None:
            should_split = True
        elif current_segment["speaker_id"] != speaker:
            # Different speaker
            should_split = True
        elif (w_start - current_segment["end"]) > 2.0:
            # Long pause (> 2 seconds) even if same speaker
            should_split = True

        if should_split:
            if current_segment:
                current_segment["text"] = current_segment["text"].strip()
                if current_segment["text"]:
                    segments.append(current_segment)
            current_segment = {
                "speaker_id": speaker,
                "start": w_start,
                "end": w_end,
                "text": w_text,
                "words": [item]
            }
        else:
            # Append word to current segment
            # Add space if previous didn't end with space or type is word in non-spacing languages
            current_segment["end"] = w_end
            current_segment["words"].append(item)
            if w_type == "spacing":
                current_segment["text"] += w_text
            else:
                # Add naturally
                if current_segment["text"] and not current_segment["text"].endswith(" ") and not w_text.startswith(" "):
                    current_segment["text"] += " " + w_text
                else:
                    current_segment["text"] += w_text

    if current_segment:
        current_segment["text"] = current_segment["text"].strip()
        if current_segment["text"]:
            segments.append(current_segment)

    # Build default speaker map
    speaker_map = {}
    sorted_speakers = sorted(list(speaker_set))
    for idx, spk in enumerate(sorted_speakers):
        speaker_map[spk] = f"ผู้พูด {idx + 1}"

    # Also build clean formatted dialogue text
    formatted_dialogue_lines = []
    for seg in segments:
        spk_name = speaker_map.get(seg["speaker_id"], seg["speaker_id"])
        time_tag = f"[{format_seconds(seg['start'])} - {format_seconds(seg['end'])}]"
        formatted_dialogue_lines.append(f"{time_tag} {spk_name}:\n{seg['text']}\n")

    formatted_text = "\n".join(formatted_dialogue_lines) if formatted_dialogue_lines else full_text

    return {
        "full_text": full_text,
        "formatted_text": formatted_text,
        "language_code": lang,
        "segments": segments,
        "speaker_map": speaker_map,
        "duration": max_end
    }
