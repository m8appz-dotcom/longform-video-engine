from __future__ import annotations

from typing import Any


TEMPLATES = {
    "state-change", "label-focus", "product-label", "product-inspection",
    "mechanism", "anatomy-explainer", "procedure", "process-steps",
    "checklist", "comparison", "timeline", "concept", "editorial-card",
    "body-distinction", "verified-next-video", "evaluation-dashboard",
}


def validate_ui_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if str(spec.get("template") or "") not in TEMPLATES:
        errors.append("template UI invalido")
    headline = str(spec.get("headline") or "").strip()
    if not headline or len(headline) > 32 or len(headline.split()) > 4:
        errors.append("headline UI debe tener 1-4 palabras y maximo 32 caracteres")
    if spec.get("dataSource") != "locked_narration":
        errors.append("UI dataSource debe ser locked_narration")
    if not isinstance(spec.get("items") or [], list) or not isinstance(spec.get("values") or [], list):
        errors.append("UI items/values deben ser listas")
    return errors


def materialize_shot(shot: dict[str, Any]) -> dict[str, Any]:
    spec = dict(shot.get("uiSpec") or {})
    errors = validate_ui_spec(spec)
    if errors:
        raise ValueError("UI spec invalido: " + "; ".join(errors))
    shot.update({
        "visualKind": "ui-card",
        "source": "",
        "mediaType": "card",
        "sourceInMs": 0,
        "sourceOutMs": 0,
        "provider": "deterministic-ui",
        "uiSpec": spec,
    })
    return shot
