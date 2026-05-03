from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.ai.narrator import narrate_device
from app.ai.tools import ToolExecutionError, explain_drift, get_device_trust, system_remediation
from app.models.schemas import Language
from app.reports.pdf_builder import build_incident_report_pdf
from app.store.memory_store import store

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/devices/{device_id}/report")
async def get_device_report(device_id: str, language: Language = Query(default="en")) -> Response:
    detail = await store.get_device(device_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        trust_context = await get_device_trust(device_id)
    except ToolExecutionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        evidence = await explain_drift(device_id)
    except ToolExecutionError:
        evidence = await store.read_evidence_card(device_id) or {}

    remediation = await system_remediation(device_id, "iptables")
    narration = await narrate_device(device_id, language)
    alerts = [alert for alert in await store.alerts() if alert["device_id"] == device_id]
    generated_at = datetime.now(timezone.utc)
    alerts_24h = [alert for alert in alerts if _timestamp(alert.get("timestamp_iso")) >= generated_at - timedelta(hours=24)]

    payload = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "device": trust_context["device"],
        "current_trust": trust_context["current_trust"],
        "severity": trust_context["severity"],
        "drift_confirmed": trust_context["drift_confirmed"],
        "trust_history": trust_context["trust_history"],
        "drift_signals": _drift_rows_with_timestamps(trust_context),
        "baseline_summary": trust_context["baseline_summary"],
        "current_window_features": trust_context["current_window_features"],
        "top_deviations": _top_deviations(trust_context),
        "evidence": evidence,
        "remediation": remediation,
        "alerts": alerts,
        "alerts_24h": alerts_24h,
        "narration": narration,
        "fallback_narrative": _fallback_narrative(trust_context, evidence),
    }
    pdf = build_incident_report_pdf(payload, language)
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    filename = f"prahari-{_safe_filename(device_id)}-{timestamp}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _top_deviations(trust_context: dict[str, Any]) -> list[dict[str, Any]]:
    baseline = trust_context.get("baseline_summary", {})
    features = trust_context.get("current_window_features", {})
    z_scores = trust_context.get("z_scores", {})
    rows = []
    for feature, z_score in sorted(z_scores.items(), key=lambda item: abs(float(item[1])), reverse=True)[:10]:
        base = baseline.get(feature, {})
        if base:
            base_text = f"{base.get('mean', 'n/a')} +/- {base.get('std', 'n/a')}"
        else:
            base_text = "n/a"
        rows.append(
            {
                "feature": feature,
                "baseline": base_text,
                "observed": features.get(feature, "n/a"),
                "z_score": z_score,
            }
        )
    return rows


def _drift_rows_with_timestamps(trust_context: dict[str, Any]) -> list[dict[str, Any]]:
    timestamp_by_window = {row.get("window_id"): row.get("timestamp") for row in trust_context.get("trust_history", [])}
    rows = []
    for row in trust_context.get("drift_status_history", []):
        enriched = dict(row)
        enriched["timestamp"] = timestamp_by_window.get(row.get("window_id"), "")
        rows.append(enriched)
    return rows


def _fallback_narrative(trust_context: dict[str, Any], evidence: dict[str, Any]) -> str:
    device = trust_context["device"]
    attack = evidence.get("attack_pattern_match", "unknown")
    return (
        f"{device['name']} at {device['ip']} is currently at trust score {trust_context['current_trust']}. "
        f"The latest evidence classifies the behavior as {attack}, with drift confirmed set to {trust_context['drift_confirmed']}. "
        "Review the top deviations and consider containment if this behavior is not expected."
    )


def _timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {".", "-", "_"} else "-" for char in value)
