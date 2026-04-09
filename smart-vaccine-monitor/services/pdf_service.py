"""Vaccine passport PDF generation using ReportLab."""

import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.pdf_service")

REPORTS_DIR = "reports"


async def generate_vaccine_passport(
    incident_id: int,
    readings: list[dict],
    vvm_damage: float,
    potency_percent: float,
    report_text: str = None,
    temp_stats: dict = None,
) -> str | None:
    """Generate a professional Vaccine Cold-Chain Passport PDF.

    Args:
        incident_id: Associated incident ID.
        readings: List of reading dictionaries for the data table.
        vvm_damage: Current VVM damage score.
        potency_percent: Current vaccine potency percentage.
        report_text: Claude-generated incident report text.
        temp_stats: Temperature statistics dict with min_temp, max_temp, avg_temp.

    Returns:
        File path to generated PDF, or None on failure.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"passport_{incident_id}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    try:
        doc = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        elements = []

        # Custom styles
        title_style = ParagraphStyle(
            "PDFTitle",
            parent=styles["Title"],
            fontSize=22,
            textColor=colors.HexColor("#1a365d"),
            spaceAfter=6 * mm,
            alignment=TA_CENTER,
        )

        subtitle_style = ParagraphStyle(
            "PDFSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#4a5568"),
            alignment=TA_CENTER,
            spaceAfter=8 * mm,
        )

        section_style = ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontSize=14,
            textColor=colors.HexColor("#2d3748"),
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
            borderPadding=(0, 0, 2 * mm, 0),
        )

        body_style = ParagraphStyle(
            "BodyText",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#2d3748"),
            spaceAfter=2 * mm,
            leading=14,
        )

        # === HEADER ===
        elements.append(Paragraph("🏥 VACCINE COLD-CHAIN PASSPORT", title_style))
        elements.append(Paragraph(
            f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} | "
            f"Incident ID: {incident_id}",
            subtitle_style,
        ))
        elements.append(HRFlowable(
            width="100%", thickness=2,
            color=colors.HexColor("#3182ce"), spaceAfter=6 * mm
        ))

        # === SECTION 1: Batch Information ===
        elements.append(Paragraph("1. Batch Information", section_style))
        batch_data = [
            ["Parameter", "Value"],
            ["Monitoring Start", readings[0].get("timestamp", "N/A")[:19] if readings else "N/A"],
            ["Monitoring End", readings[-1].get("timestamp", "N/A")[:19] if readings else "N/A"],
            ["Total Readings", str(len(readings))],
            ["Report Generated", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")],
        ]
        batch_table = Table(batch_data, colWidths=[6 * cm, 10 * cm])
        batch_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ebf8ff")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2b6cb0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bee3f8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(batch_table)
        elements.append(Spacer(1, 4 * mm))

        # === SECTION 2: Temperature Summary ===
        elements.append(Paragraph("2. Temperature Summary", section_style))
        if temp_stats:
            min_t = temp_stats.get("min_temp", 0)
            max_t = temp_stats.get("max_temp", 0)
            avg_t = temp_stats.get("avg_temp", 0)
        elif readings:
            temps = [r.get("temp_internal", 0) for r in readings]
            min_t = min(temps) if temps else 0
            max_t = max(temps) if temps else 0
            avg_t = sum(temps) / len(temps) if temps else 0
        else:
            min_t = max_t = avg_t = 0

        temp_data = [
            ["Metric", "Value", "Safe Range"],
            ["Minimum Temperature", f"{min_t:.1f}°C", "2.0°C – 8.0°C"],
            ["Maximum Temperature", f"{max_t:.1f}°C", "2.0°C – 8.0°C"],
            ["Mean Temperature", f"{avg_t:.1f}°C", "2.0°C – 8.0°C"],
        ]
        temp_table = Table(temp_data, colWidths=[5.5 * cm, 5 * cm, 5.5 * cm])
        temp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0fff4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#276749")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c6f6d5")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(temp_table)
        elements.append(Spacer(1, 4 * mm))

        # === SECTION 3: VVM Status ===
        elements.append(Paragraph("3. VVM (Vaccine Vial Monitor) Status", section_style))
        vvm_color = "#276749" if potency_percent > 80 else ("#c05621" if potency_percent > 50 else "#c53030")
        vvm_data = [
            ["Parameter", "Value"],
            ["VVM Damage Score", f"{vvm_damage:.6f}"],
            ["Remaining Potency", f"{potency_percent:.1f}%"],
            ["Discard Threshold", "1.000000"],
            ["VVM Status", "WITHIN LIMITS" if vvm_damage < 1.0 else "EXCEEDED — DISCARD"],
        ]
        vvm_table = Table(vvm_data, colWidths=[6 * cm, 10 * cm])
        vvm_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fefcbf")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#975a16")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f6e05e")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(vvm_table)
        elements.append(Spacer(1, 6 * mm))

        # === SECTION 4: Verdict ===
        is_safe = potency_percent > 50 and vvm_damage < 1.0
        verdict_text = "✓ SAFE FOR USE" if is_safe else "✗ COMPROMISED — DO NOT USE"
        verdict_color = "#276749" if is_safe else "#c53030"
        verdict_bg = "#f0fff4" if is_safe else "#fff5f5"

        verdict_style = ParagraphStyle(
            "Verdict",
            parent=styles["Title"],
            fontSize=20,
            textColor=colors.HexColor(verdict_color),
            alignment=TA_CENTER,
            spaceBefore=4 * mm,
            spaceAfter=4 * mm,
        )

        verdict_data = [[Paragraph(verdict_text, verdict_style)]]
        verdict_table = Table(verdict_data, colWidths=[16 * cm])
        verdict_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(verdict_bg)),
            ("BOX", (0, 0), (-1, -1), 2, colors.HexColor(verdict_color)),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(verdict_table)
        elements.append(Spacer(1, 6 * mm))

        # === SECTION 5: Incident Report ===
        if report_text:
            elements.append(Paragraph("5. Incident Report", section_style))
            # Wrap long text with proper line breaks
            report_lines = report_text.replace("\n", "<br/>")
            report_para_style = ParagraphStyle(
                "ReportBody",
                parent=styles["Normal"],
                fontSize=8,
                textColor=colors.HexColor("#2d3748"),
                leading=11,
                spaceAfter=2 * mm,
            )
            elements.append(Paragraph(report_lines, report_para_style))
            elements.append(Spacer(1, 4 * mm))

        # === SECTION 6: Recent Data Table ===
        elements.append(Paragraph("6. Recent Sensor Data", section_style))
        data_rows = [["Time", "Temp(°C)", "Humidity", "Risk", "Status", "VVM"]]
        for r in readings[-20:]:
            data_rows.append([
                r.get("timestamp", "")[:16],
                f"{r.get('temp_internal', 0):.1f}",
                f"{r.get('humidity', 0):.0f}%",
                f"{r.get('risk_score', 0):.0f}",
                r.get("status", "N/A"),
                f"{r.get('vvm_damage', 0):.4f}",
            ])

        data_table = Table(data_rows, colWidths=[3.5 * cm, 2 * cm, 2 * cm, 1.8 * cm, 2.2 * cm, 2.5 * cm])
        data_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
        ]))
        elements.append(data_table)

        # Build PDF
        doc.build(elements)
        logger.info(f"Vaccine passport PDF generated: {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return None
