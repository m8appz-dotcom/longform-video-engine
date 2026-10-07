from __future__ import annotations

from collections import Counter
from typing import Any


def review_art_direction(plan: dict[str, Any], viewer: dict[str, Any] | None = None) -> dict[str, Any]:
    """Non-blocking art-direction report built from renderer provenance and review notes.

    Objective composition defects remain owned by composition_qa. This report
    may guide the next renderer revision but cannot discard evidence or fail a run.
    """
    viewer = viewer or {}
    shots = list(plan.get("shots") or [])
    renderers = Counter(str(shot.get("rendererVersion") or "semantic-v1") for shot in shots)
    patterns = Counter(str(shot.get("motionPattern") or "") for shot in shots if shot.get("motionPattern"))
    directions = Counter(str(shot.get("artDirection") or "") for shot in shots if shot.get("artDirection"))
    notes: list[str] = []
    supported_v1 = [
        str(shot.get("shotId") or "")
        for shot in shots
        if str(shot.get("rendererVersion") or "") == "semantic-v1"
        and (
            str(shot.get("uiTemplate") or (shot.get("uiSpec") or {}).get("template") or "") in {"anatomy-explainer", "body-distinction"}
            or str(shot.get("uiVariant") or (shot.get("uiSpec") or {}).get("variant") or "") in {"claim-evidence", "protocol-diagram"}
        )
    ]
    if supported_v1:
        notes.append("Escenas compatibles aun en semantic-v1: %s" % ", ".join(supported_v1))
    if patterns and len(patterns) == 1 and len(shots) > 2:
        notes.append("La coreografia usa un solo patron durante todo el programa")
    if shots and not any(str(shot.get("visualStrategy") or "") in {"media", "hybrid"} for shot in shots):
        notes.append("El programa no contiene contraste editorial entre evidencia real y motion graphics")
    end_screen = plan.get("cta") or {}
    if end_screen and not str(end_screen.get("thumbnail_url") or ""):
        notes.append("CTA verificado sin URL de miniatura; el renderer usara fallback tipografico")
    notes.extend(str(item) for item in (viewer.get("improvements") or []) if str(item).strip())
    return {
        "status": "ADVISORY",
        "blocking": False,
        "policy": "art-direction-shadow-v1",
        "objective_defects_owned_by": "composition_qa",
        "renderer_mix": dict(renderers),
        "motion_pattern_mix": dict(patterns),
        "art_direction_mix": dict(directions),
        "notes": list(dict.fromkeys(notes))[:20],
        "next_run_feedback_allowed": True,
        "current_run_asset_rejection_allowed": False,
    }
