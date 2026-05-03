from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CHARCOAL = colors.HexColor("#212121")
ELEVATED = colors.HexColor("#2a2a2a")
CORAL = colors.HexColor("#ff7759")
TEXT = colors.HexColor("#212121")
BORDER = colors.HexColor("#3a3a3a")

SEVERITY_COLORS = {
    "NORMAL": colors.HexColor("#4ade80"),
    "WATCH": colors.HexColor("#facc15"),
    "AT_RISK": colors.HexColor("#fb923c"),
    "CRITICAL": colors.HexColor("#ef4444"),
    "healthy": colors.HexColor("#4ade80"),
    "watch": colors.HexColor("#facc15"),
    "risk": colors.HexColor("#fb923c"),
    "critical": colors.HexColor("#ef4444"),
}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "incident_report": "INCIDENT REPORT",
        "generated": "Generated",
        "status": "Trust score {trust}/100, drift {drift}, {alerts} alerts in last 24 hours",
        "executive_summary": "EXECUTIVE SUMMARY",
        "what_happened": "What happened",
        "recommended_actions": "Recommended actions",
        "technical_evidence": "TECHNICAL EVIDENCE",
        "timeline": "TIMELINE",
        "appendix": "APPENDIX",
        "top_deviations": "Top deviating features",
        "drift_signals": "Drift signals fired",
        "policy_violations": "Policy violations",
        "attack_pattern": "Attack pattern",
        "trust_chart": "Trust score over last 60 windows",
        "alerts": "Alerts",
        "recovery": "Recovery trajectory",
        "raw_snapshot": "Raw 22-feature snapshot",
        "baseline": "Baseline summary",
        "glossary": "Glossary",
        "stable": "stable",
        "confirmed": "confirmed",
    },
    "hi": {
        "incident_report": "घटना रिपोर्ट",
        "generated": "बनाया गया",
        "status": "Trust score {trust}/100, drift {drift}, पिछले 24 घंटों में {alerts} alerts",
        "executive_summary": "कार्यकारी सारांश",
        "what_happened": "क्या हुआ",
        "recommended_actions": "अनुशंसित कार्रवाई",
        "technical_evidence": "तकनीकी साक्ष्य",
        "timeline": "समयरेखा",
        "appendix": "परिशिष्ट",
        "top_deviations": "सबसे बड़े विचलन",
        "drift_signals": "Drift signals fired",
        "policy_violations": "Policy violations",
        "attack_pattern": "Attack pattern",
        "trust_chart": "पिछले 60 windows में trust score",
        "alerts": "Alerts",
        "recovery": "Recovery trajectory",
        "raw_snapshot": "Raw 22-feature snapshot",
        "baseline": "Baseline summary",
        "glossary": "Glossary",
        "stable": "स्थिर",
        "confirmed": "पुष्टि",
    },
    "kn": {
        "incident_report": "ಘಟನೆ ವರದಿ",
        "generated": "ರಚಿಸಿದ ಸಮಯ",
        "status": "Trust score {trust}/100, drift {drift}, ಕಳೆದ 24 ಗಂಟೆಗಳಲ್ಲಿ {alerts} alerts",
        "executive_summary": "ಕಾರ್ಯನಿರ್ವಾಹಕ ಸಾರಾಂಶ",
        "what_happened": "ಏನು ಸಂಭವಿಸಿದೆ",
        "recommended_actions": "ಶಿಫಾರಸು ಮಾಡಿದ ಕ್ರಮಗಳು",
        "technical_evidence": "ತಾಂತ್ರಿಕ ಪುರಾವೆ",
        "timeline": "ಸಮಯರೇಖೆ",
        "appendix": "ಅನುಬಂಧ",
        "top_deviations": "ಅತಿ ಹೆಚ್ಚು ವಿಚಲನಗಳು",
        "drift_signals": "Drift signals fired",
        "policy_violations": "Policy violations",
        "attack_pattern": "Attack pattern",
        "trust_chart": "ಕಳೆದ 60 windows ನಲ್ಲಿ trust score",
        "alerts": "Alerts",
        "recovery": "Recovery trajectory",
        "raw_snapshot": "Raw 22-feature snapshot",
        "baseline": "Baseline summary",
        "glossary": "Glossary",
        "stable": "ಸ್ಥಿರ",
        "confirmed": "ದೃಢಪಟ್ಟಿದೆ",
    },
    "ta": {
        "incident_report": "சம்பவ அறிக்கை",
        "generated": "உருவாக்கப்பட்டது",
        "status": "Trust score {trust}/100, drift {drift}, last 24 hours இல் {alerts} alerts",
        "executive_summary": "சுருக்கம்",
        "what_happened": "என்ன நடந்தது",
        "recommended_actions": "பரிந்துரைக்கப்பட்ட நடவடிக்கைகள்",
        "technical_evidence": "தொழில்நுட்ப ஆதாரம்",
        "timeline": "Timeline",
        "appendix": "Appendix",
        "top_deviations": "Top deviations",
        "drift_signals": "Drift signals fired",
        "policy_violations": "Policy violations",
        "attack_pattern": "Attack pattern",
        "trust_chart": "Trust score over last 60 windows",
        "alerts": "Alerts",
        "recovery": "Recovery trajectory",
        "raw_snapshot": "Raw 22-feature snapshot",
        "baseline": "Baseline summary",
        "glossary": "Glossary",
        "stable": "stable",
        "confirmed": "confirmed",
    },
    "te": {
        "incident_report": "సంఘటన నివేదిక",
        "generated": "రూపొందించిన సమయం",
        "status": "Trust score {trust}/100, drift {drift}, last 24 hours లో {alerts} alerts",
        "executive_summary": "సారాంశం",
        "what_happened": "ఏం జరిగింది",
        "recommended_actions": "సిఫార్సు చేసిన చర్యలు",
        "technical_evidence": "సాంకేతిక సాక్ష్యం",
        "timeline": "Timeline",
        "appendix": "Appendix",
        "top_deviations": "Top deviations",
        "drift_signals": "Drift signals fired",
        "policy_violations": "Policy violations",
        "attack_pattern": "Attack pattern",
        "trust_chart": "Trust score over last 60 windows",
        "alerts": "Alerts",
        "recovery": "Recovery trajectory",
        "raw_snapshot": "Raw 22-feature snapshot",
        "baseline": "Baseline summary",
        "glossary": "Glossary",
        "stable": "stable",
        "confirmed": "confirmed",
    },
}


def build_incident_report_pdf(payload: dict[str, Any], language: str = "en") -> bytes:
    register_report_font()
    labels = STRINGS.get(language, STRINGS["en"])
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Prahari AI Incident Report",
    )
    styles = _styles()
    story: list[Any] = []

    story.extend(_cover(payload, labels, styles))
    story.append(PageBreak())
    story.extend(_executive_summary(payload, labels, styles))
    story.append(PageBreak())
    story.extend(_technical_evidence(payload, labels, styles))
    story.append(PageBreak())
    story.extend(_timeline(payload, labels, styles))
    story.append(PageBreak())
    story.extend(_appendix(payload, labels, styles))

    doc.build(story)
    return buffer.getvalue()


def register_report_font() -> None:
    if "SentinelSans" in pdfmetrics.getRegisteredFontNames():
        return
    candidates = [
        Path("C:/Windows/Fonts/Nirmala.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            pdfmetrics.registerFont(TTFont("SentinelSans", str(candidate)))
            return


def _font() -> str:
    return "SentinelSans" if "SentinelSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    font = _font()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName=font, fontSize=34, leading=38, textColor=colors.white, alignment=TA_CENTER),
        "subtitle": ParagraphStyle("ReportSubtitle", parent=base["Heading2"], fontName=font, fontSize=15, leading=18, textColor=CORAL, alignment=TA_CENTER),
        "h1": ParagraphStyle("ReportH1", parent=base["Heading1"], fontName=font, fontSize=18, leading=22, textColor=CHARCOAL, spaceAfter=10),
        "h2": ParagraphStyle("ReportH2", parent=base["Heading2"], fontName=font, fontSize=12, leading=15, textColor=CORAL, spaceBefore=8, spaceAfter=6),
        "body": ParagraphStyle("ReportBody", parent=base["BodyText"], fontName=font, fontSize=9.5, leading=14, textColor=TEXT),
        "small": ParagraphStyle("ReportSmall", parent=base["BodyText"], fontName=font, fontSize=7.5, leading=10, textColor=TEXT),
        "mono": ParagraphStyle("ReportMono", parent=base["Code"], fontName="Courier", fontSize=7, leading=9, textColor=TEXT),
        "cover_meta": ParagraphStyle("CoverMeta", parent=base["BodyText"], fontName=font, fontSize=11, leading=16, textColor=colors.white, alignment=TA_CENTER),
    }


def _cover(payload: dict[str, Any], labels: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[Any]:
    device = payload["device"]
    severity = str(payload.get("severity", "NORMAL"))
    trust = payload.get("current_trust", 0)
    drift = labels["confirmed"] if payload.get("drift_confirmed") else labels["stable"]
    alert_count = len(payload.get("alerts_24h", []))
    status = labels["status"].format(trust=trust, drift=drift, alerts=alert_count)
    badge_color = SEVERITY_COLORS.get(severity, CORAL)
    generated = payload.get("generated_at") or datetime.now(timezone.utc).isoformat()

    table = Table(
        [
            [Paragraph("PRAHARI AI", styles["title"])],
            [Paragraph(labels["incident_report"], styles["subtitle"])],
            [Spacer(1, 18 * mm)],
            [Paragraph(f"{device.get('name')} | {device.get('ip')} | {device.get('type') or device.get('device_type')}", styles["cover_meta"])],
            [Paragraph(f"{labels['generated']}: {generated}", styles["cover_meta"])],
            [Paragraph(f"<b>{severity}</b>", styles["cover_meta"])],
            [Paragraph(status, styles["cover_meta"])],
        ],
        colWidths=[170 * mm],
        rowHeights=[38 * mm, 18 * mm, 24 * mm, 18 * mm, 14 * mm, 14 * mm, 18 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CHARCOAL),
                ("BACKGROUND", (0, 5), (0, 5), badge_color),
                ("BOX", (0, 0), (-1, -1), 1, CHARCOAL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    return [Spacer(1, 14 * mm), table]


def _executive_summary(payload: dict[str, Any], labels: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[Any]:
    story = [Paragraph(labels["executive_summary"], styles["h1"]), Paragraph(labels["what_happened"], styles["h2"])]
    story.append(Paragraph(_para(payload.get("narration") or payload.get("fallback_narrative")), styles["body"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(labels["recommended_actions"], styles["h2"]))
    for item in payload.get("remediation", {}).get("playbook", [])[:5]:
        story.append(Paragraph(f"- {_para(item)}", styles["body"]))
    rationale = payload.get("remediation", {}).get("rationale")
    if rationale:
        story.extend([Spacer(1, 4 * mm), Paragraph(_para(rationale), styles["body"])])
    return story


def _technical_evidence(payload: dict[str, Any], labels: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[Any]:
    evidence = payload.get("evidence", {})
    rows = [["Feature", "Baseline mean +/- std", "Observed", "z-score"]]
    for item in payload.get("top_deviations", [])[:10]:
        rows.append(
            [
                item["feature"],
                item.get("baseline", "n/a"),
                item.get("observed", "n/a"),
                str(item.get("z_score", "n/a")),
            ]
        )
    story = [Paragraph(labels["technical_evidence"], styles["h1"]), Paragraph(labels["top_deviations"], styles["h2"]), _table(rows)]
    story.append(Paragraph(labels["drift_signals"], styles["h2"]))
    drift_rows = [["Window", "Timestamp", "Signals"]]
    for row in payload.get("drift_signals", []):
        signals = ", ".join(row.get("signals_fired", []) or row.get("fired", []) or [])
        drift_rows.append([str(row.get("window_id", "")), str(row.get("timestamp", "")), signals or "none"])
    story.append(_table(drift_rows[:18]))
    story.append(Paragraph(labels["policy_violations"], styles["h2"]))
    violations = evidence.get("policy_violations", [])
    story.append(Paragraph(_para("; ".join(_policy_text(item) for item in violations) or "None observed."), styles["body"]))
    story.append(Paragraph(labels["attack_pattern"], styles["h2"]))
    story.append(Paragraph(f"{evidence.get('attack_pattern_match', 'unknown')} | confidence {evidence.get('confidence', 0)}", styles["body"]))
    return story


def _timeline(payload: dict[str, Any], labels: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[Any]:
    story = [Paragraph(labels["timeline"], styles["h1"]), Paragraph(labels["trust_chart"], styles["h2"])]
    chart = _trust_chart(payload.get("trust_history", []))
    if chart:
        story.append(Image(chart, width=165 * mm, height=58 * mm))
    else:
        story.append(Paragraph(_ascii_trust_chart(payload.get("trust_history", [])), styles["mono"]))
    story.append(Paragraph(labels["alerts"], styles["h2"]))
    rows = [["Timestamp", "Anomaly", "Drift state"]]
    evidence = payload.get("evidence", {})
    for alert in payload.get("alerts", []):
        rows.append([alert.get("timestamp_iso", ""), str(evidence.get("smoothed_score", "")), str(payload.get("drift_confirmed", False))])
    if len(rows) == 1:
        rows.append(["No alerts recorded", "", ""])
    story.append(_table(rows[:24]))
    story.append(Paragraph(labels["recovery"], styles["h2"]))
    story.append(Paragraph(_recovery_text(payload.get("trust_history", [])), styles["body"]))
    return story


def _appendix(payload: dict[str, Any], labels: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[Any]:
    story = [Paragraph(labels["appendix"], styles["h1"]), Paragraph(labels["raw_snapshot"], styles["h2"])]
    features = payload.get("current_window_features", {})
    feature_rows = [["Feature", "Value"]]
    feature_rows.extend([[name, str(value)] for name, value in features.items()])
    story.append(_table(feature_rows[:24]))
    story.append(Paragraph(labels["baseline"], styles["h2"]))
    baseline_rows = [["Feature", "Mean", "Std"]]
    for feature, values in payload.get("baseline_summary", {}).items():
        baseline_rows.append([feature, str(values.get("mean", "")), str(values.get("std", ""))])
    story.append(_table(baseline_rows))
    story.append(Paragraph(labels["glossary"], styles["h2"]))
    glossary = [
        "Drift: this device's behavior has been changing in a coordinated way for several minutes.",
        "z-score: how many standard deviations the latest value is from normal.",
        "ADWIN: an online detector that watches whether the recent stream changed statistically.",
        "Policy violation: a direct rule hit such as forbidden ports or abnormal bandwidth.",
    ]
    for item in glossary:
        story.append(Paragraph(item, styles["small"]))
    return story


def _table(rows: list[list[Any]]) -> Table:
    table = Table(rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _font()),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("LEADING", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), ELEVATED),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
            ]
        )
    )
    return table


def _trust_chart(history: list[dict[str, Any]]) -> io.BytesIO | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    values = [float(row.get("trust_score", row.get("trust", 0)) or 0) for row in history[-60:]]
    if not values:
        return None
    output = io.BytesIO()
    fig, ax = plt.subplots(figsize=(7.2, 2.2), dpi=150)
    ax.plot(range(1, len(values) + 1), values, color="#ff7759", linewidth=2)
    ax.fill_between(range(1, len(values) + 1), values, [0] * len(values), color="#ff7759", alpha=0.12)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Trust")
    ax.set_xlabel("Window")
    ax.grid(True, color="#3a3a3a", alpha=0.25, linewidth=0.6)
    fig.tight_layout()
    fig.savefig(output, format="png", transparent=False)
    plt.close(fig)
    output.seek(0)
    return output


def _ascii_trust_chart(history: list[dict[str, Any]]) -> str:
    values = [float(row.get("trust_score", row.get("trust", 0)) or 0) for row in history[-60:]]
    if not values:
        return "No trust history available."
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(blocks[min(7, max(0, int(value / 12.5)))] for value in values)


def _recovery_text(history: list[dict[str, Any]]) -> str:
    values = [float(row.get("trust_score", row.get("trust", 0)) or 0) for row in history[-6:]]
    if len(values) < 2:
        return "Not enough recent windows to determine recovery trajectory."
    delta = values[-1] - values[0]
    if delta > 3:
        return f"Trust has improved by {delta:.1f} points across the recent windows."
    if delta < -3:
        return f"Trust is still declining, down {abs(delta):.1f} points across the recent windows."
    return "Trust has been broadly stable across the recent windows."


def _policy_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("detail") or item.get("rule") or item)
    return str(item)


def _para(value: Any) -> str:
    text = str(value or "No narrative available.")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
