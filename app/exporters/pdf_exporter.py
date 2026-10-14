import io
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.config import FONTS_DIR
from app.elevenlabs_service import format_seconds

# Register Sarabun font if present
SARABUN_FONT_NAME = "Helvetica"
SARABUN_BOLD_NAME = "Helvetica-Bold"

regular_path = FONTS_DIR / "Sarabun-Regular.ttf"
bold_path = FONTS_DIR / "Sarabun-Bold.ttf"

if regular_path.exists() and bold_path.exists():
    try:
        pdfmetrics.registerFont(TTFont("Sarabun", str(regular_path)))
        pdfmetrics.registerFont(TTFont("Sarabun-Bold", str(bold_path)))
        SARABUN_FONT_NAME = "Sarabun"
        SARABUN_BOLD_NAME = "Sarabun-Bold"
    except Exception as e:
        pass

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for total page count calculation and headers/footers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont(SARABUN_FONT_NAME, 9)
        self.setFillColor(colors.HexColor("#64748B"))

        # Header (Pages 2+)
        if self._pageNumber > 1:
            self.drawString(2 * cm, 28.5 * cm, "Transcriptor Pro - รายงานการถอดเสียง")
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(2 * cm, 28.3 * cm, 19 * cm, 28.3 * cm)

        # Footer
        footer_text = f"หน้าที่ {self._pageNumber} จาก {page_count}"
        self.drawRightString(19 * cm, 1.2 * cm, footer_text)
        self.drawString(2 * cm, 1.2 * cm, "สร้างโดย Transcriptor Pro (ElevenLabs Scribe)")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(2 * cm, 1.5 * cm, 19 * cm, 1.5 * cm)

        self.restoreState()

def export_to_pdf(transcription_data: Dict[str, Any]) -> io.BytesIO:
    """
    Generate a polished PDF document from transcription data.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.2 * cm,
        bottomMargin=2.2 * cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        fontName=SARABUN_BOLD_NAME,
        fontSize=20,
        leading=26,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )

    subtitle_style = ParagraphStyle(
        "DocSub",
        fontName=SARABUN_FONT_NAME,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=14,
    )

    meta_label_style = ParagraphStyle(
        "MetaLbl",
        fontName=SARABUN_FONT_NAME,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#64748B"),
    )

    meta_val_style = ParagraphStyle(
        "MetaVal",
        fontName=SARABUN_BOLD_NAME,
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1E293B"),
    )

    h2_style = ParagraphStyle(
        "SecH2",
        fontName=SARABUN_BOLD_NAME,
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=14,
        spaceAfter=8,
    )

    spk_style = ParagraphStyle(
        "SpeakerH",
        fontName=SARABUN_BOLD_NAME,
        fontSize=10.5,
        leading=15,
        textColor=colors.HexColor("#1D4ED8"),
        spaceBefore=8,
        spaceAfter=2,
    )

    body_style = ParagraphStyle(
        "DialogueBody",
        fontName=SARABUN_FONT_NAME,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6,
        leftIndent=12,
    )

    story = []

    title_text = transcription_data.get("title") or transcription_data.get("filename") or "เอกสารการถอดเสียง"
    filename = transcription_data.get("filename", "-")
    duration_sec = transcription_data.get("duration") or 0.0
    lang = transcription_data.get("language_code") or "th"
    model_id = transcription_data.get("model_id") or "scribe_v1"
    created_at = transcription_data.get("created_at", "")
    speaker_map = transcription_data.get("speaker_map") or {}
    segments: List[Dict[str, Any]] = transcription_data.get("segments") or []
    full_text = transcription_data.get("formatted_text") or transcription_data.get("full_text") or ""

    # Title & Subtitle
    story.append(Paragraph(title_text, title_style))
    story.append(Paragraph("เอกสารรายงานผลการถอดเสียงอัตโนมัติ (ElevenLabs Scribe)", subtitle_style))

    # Metadata Card Table
    meta_table_data = [
        [
            Paragraph("📁 ไฟล์ต้นฉบับ<br/><b>" + filename[:30] + "</b>", meta_val_style),
            Paragraph("⏱️ ความยาวเสียง<br/><b>" + format_seconds(duration_sec) + "</b>", meta_val_style),
            Paragraph("🌐 ภาษาตรวจพบ<br/><b>" + lang.upper() + "</b>", meta_val_style),
        ],
        [
            Paragraph("🤖 โมเดล<br/><b>" + model_id + "</b>", meta_val_style),
            Paragraph("👥 ผู้พูดทั้งหมด<br/><b>" + (f"{len(speaker_map)} คน" if speaker_map else "1 คน") + "</b>", meta_val_style),
            Paragraph("📅 วันที่ถอดเสียง<br/><b>" + (created_at[:10] if created_at else datetime.now().strftime("%Y-%m-%d")) + "</b>", meta_val_style),
        ]
    ]

    col_w = (doc.width) / 3.0
    meta_table = Table(meta_table_data, colWidths=[col_w, col_w, col_w])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    # Dialogue Section
    story.append(Paragraph("บทสนทนาและข้อความที่ถอดได้", h2_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=10))

    speaker_colors = [
        "#2563EB", "#0D9488", "#D97706", "#9333EA", "#E11D48", "#4F46E5"
    ]
    color_map = {}
    c_idx = 0

    if segments:
        for seg in segments:
            spk_id = seg.get("speaker_id") or "speaker_0"
            spk_name = speaker_map.get(spk_id, spk_id)
            start_str = format_seconds(seg.get("start", 0.0))
            end_str = format_seconds(seg.get("end", 0.0))
            text_content = seg.get("text", "").strip()

            if spk_id not in color_map:
                color_map[spk_id] = speaker_colors[c_idx % len(speaker_colors)]
                c_idx += 1

            spk_color = color_map[spk_id]
            header_html = f"<font color='#94A3B8'>[{start_str} - {end_str}]</font> <font color='{spk_color}'><b>{spk_name}:</b></font>"

            # Keep speaker header with first paragraph of text
            block = [
                Paragraph(header_html, spk_style),
                Paragraph(text_content, body_style)
            ]
            story.append(KeepTogether(block))
    else:
        for para in full_text.split("\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), body_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer
