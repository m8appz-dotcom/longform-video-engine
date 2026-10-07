from __future__ import annotations

import re
from typing import Any


STOP_MOTION_INTENTS = {
    "transformative_compression",
    "playful_surreal",
    "technical_choreography",
    "visual_anchor",
}
TEMPORAL_EVIDENCE_MODES = {"implied", "initial_final", "continuous"}
MOTION_PURPOSES = {"explain", "compare", "emphasize", "transform", "transition"}
MOTION_PRIMITIVES = {
    "diagram", "timeline", "chart", "callout", "process", "anatomy",
    "particles", "three_scene", "comparison", "magnifier", "editorial",
}


def _text(shot: dict[str, Any]) -> str:
    return " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof", "requiredEvidence", "screenCopy")).lower()


def infer_temporal_evidence(shot: dict[str, Any], direction: dict[str, Any] | None = None) -> tuple[str, bool, int]:
    direction = direction or {}
    explicit = str(direction.get("temporal_evidence_mode") or direction.get("temporalEvidenceMode") or shot.get("temporalEvidenceMode") or "").lower()
    explicit_transition = direction.get("requires_observed_transition") if "requires_observed_transition" in direction else direction.get("requiresObservedTransition")
    text = _text(shot)
    continuous = bool(re.search(r"\b(trayectoria|velocidad|ritmo|t[eé]cnica|paso a paso|movimiento continuo|durante el movimiento|orden exacto|secuencia de clics)\b", text))
    initial_final = bool(re.search(r"\b(antes y despu[eé]s|estado inicial|estado final|posici[oó]n inicial|posici[oó]n final|mismo.+[aá]ngulo|otro [aá]ngulo)\b", text))
    unjustified_continuous = explicit == "continuous" and not continuous
    if unjustified_continuous:
        # The visual director may request motion for energy, but continuous
        # footage is mandatory only when the path/timing of the movement is
        # itself evidence. Distinct actions can be shown honestly as two
        # controlled states; a single state may use implied motion.
        mode = "initial_final" if initial_final or (
            shot.get("temporalAction") == "multi_step"
            and shot.get("proofKind") in {"human_action", "comparison", "exact_ui_state"}
        ) else "implied"
    elif explicit in TEMPORAL_EVIDENCE_MODES:
        mode = explicit
    elif continuous:
        mode = "continuous"
    elif initial_final or (shot.get("temporalAction") == "multi_step" and shot.get("proofKind") in {"human_action", "comparison", "exact_ui_state"}):
        mode = "initial_final"
    else:
        mode = "implied"
    required = False if unjustified_continuous else bool(explicit_transition) if explicit_transition is not None else mode == "continuous"
    return mode, required, 2 if mode == "initial_final" else 1


def stop_motion_decision(shot: dict[str, Any], direction: dict[str, Any] | None = None) -> dict[str, Any]:
    direction = direction or {}
    requested = str(direction.get("stop_motion_intent") or direction.get("stopMotionIntent") or shot.get("stopMotionIntent") or "").strip().lower()
    reason = str(direction.get("why_stop_motion") or direction.get("whyStopMotion") or shot.get("whyStopMotion") or "").strip()
    evidence_mode = str(shot.get("evidenceMode") or "")
    kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
    text = _text(shot)
    disallowed = evidence_mode in {"documentary", "data_exact"} or kind in {
        "real_event", "third_party_commentary", "cultural_reference", "presenter", "exact_ui_state",
    }
    if kind == "human_action" and bool(re.search(r"\b(corre|camina|baila|ejercicio|sentadilla|t[eé]cnica|movimiento continuo)\b", text)):
        disallowed = True
    enabled = requested in STOP_MOTION_INTENTS and len(reason) >= 18 and not disallowed
    return {
        "eligible": enabled,
        "intent": requested if requested in STOP_MOTION_INTENTS else "",
        "why": reason,
        "evidenceRole": "supporting",
        "toneCompatible": not disallowed,
        "durationSeconds": min(8, max(3, round((int(shot.get("endMs") or 0) - int(shot.get("startMs") or 0)) / 1000))) if enabled else 0,
    }


def compile_motion_spec(shot: dict[str, Any], direction: dict[str, Any] | None = None) -> dict[str, Any]:
    direction = direction or {}
    kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "abstract_concept")
    role = str(shot.get("beatRole") or "explanation")
    purpose = str(direction.get("motion_purpose") or direction.get("motionPurpose") or "").lower()
    if purpose not in MOTION_PURPOSES:
        purpose = "compare" if kind == "comparison" else "explain" if role in {"proof", "explanation"} else "emphasize"
    primitive = str(direction.get("motion_primitive") or direction.get("motionPrimitive") or "").lower()
    if primitive not in MOTION_PRIMITIVES:
        primitive = {
            "comparison": "comparison",
            "physiological_mechanism": "anatomy",
            "exact_ui_state": "diagram",
            "product_inspection": "magnifier",
            "human_action": "process",
        }.get(kind, "editorial")
    template = str(shot.get("uiTemplate") or (shot.get("uiSpec") or {}).get("template") or "")
    variant = str(shot.get("uiVariant") or (shot.get("uiSpec") or {}).get("variant") or "")
    if template in {"anatomy-explainer", "body-distinction"}:
        primitive = "anatomy"
    elif template == "mechanism":
        primitive = "diagram"
    elif variant == "protocol-diagram":
        primitive = "diagram"
    text = _text(shot)
    if re.search(r"\b(semanas|meses|primero|luego|finalmente|progresi[oó]n)\b", text):
        primitive = "timeline"
    motion_role = "primary" if str(shot.get("route") or "") == "ui" else "supporting" if shot.get("hybridTemplate") else "decorative"
    timeline = [
        {"at": 0.00, "action": "stage", "target": "primary"},
        {"at": 0.18, "action": "reveal", "target": "headline"},
        {"at": 0.36, "action": "progress", "target": primitive},
        {"at": 0.82, "action": "resolve", "target": "primary"},
    ]
    sfx = [
        {"at": 0.18, "kind": "line-draw" if primitive in {"timeline", "chart", "diagram"} else "reveal", "volume": 0.09},
        {"at": 0.82, "kind": "confirmation" if purpose in {"explain", "compare"} else "impact", "volume": 0.08},
    ]
    return {
        "purpose": purpose,
        "evidenceRole": motion_role,
        "visualPrimitive": primitive,
        "timeline": timeline,
        "camera": {"behavior": "subtle", "maxScale": 1.06},
        "transitions": [{"kind": "match" if kind == "comparison" else "reveal", "frames": 14}],
        "sfxCues": sfx,
        "mustNotCover": ["face", "subject", "data"],
        "safeZone": "auto",
        "fallback": "image_pair" if kind == "comparison" else "image",
        "meaningfulChanges": 2 if primitive in {"comparison", "timeline", "process", "anatomy", "diagram"} else 1,
    }


def apply_motion_contract(shot: dict[str, Any], direction: dict[str, Any] | None = None) -> dict[str, Any]:
    mode, required, state_count = infer_temporal_evidence(shot, direction)
    shot["temporalEvidenceMode"] = mode
    shot["requiresObservedTransition"] = required
    shot["stateCount"] = state_count
    shot["motionSpec"] = compile_motion_spec(shot, direction)
    stop = stop_motion_decision(shot, direction)
    shot["stopMotion"] = stop
    shot["stopMotionIntent"] = stop["intent"]
    shot["whyStopMotion"] = stop["why"]
    return shot


def validate_motion_contract(shot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    label = str(shot.get("shotId") or "shot")
    mode = str(shot.get("temporalEvidenceMode") or "")
    if mode not in TEMPORAL_EVIDENCE_MODES:
        errors.append("%s temporalEvidenceMode invalido" % label)
    if bool(shot.get("requiresObservedTransition")) != (mode == "continuous"):
        errors.append("%s requiresObservedTransition contradice temporalEvidenceMode" % label)
    spec = shot.get("motionSpec") or {}
    if str(spec.get("purpose") or "") not in MOTION_PURPOSES:
        errors.append("%s motionSpec.purpose invalido" % label)
    if str(spec.get("visualPrimitive") or "") not in MOTION_PRIMITIVES:
        errors.append("%s motionSpec.visualPrimitive invalido" % label)
    if not isinstance(spec.get("timeline"), list) or not spec.get("timeline"):
        errors.append("%s motionSpec.timeline vacio" % label)
    if str(shot.get("route") or "") in {"ui", "motion-card"} and int(spec.get("meaningfulChanges") or 0) < 1:
        errors.append("%s motion graphic sin cambio visual significativo" % label)
    if not isinstance(spec.get("mustNotCover") or [], list):
        errors.append("%s motionSpec.mustNotCover invalido" % label)
    stop = shot.get("stopMotion") or {}
    if str(shot.get("route") or "") == "cutout_motion" and stop.get("eligible") is not True:
        errors.append("%s cutout_motion sin intencion narrativa elegible" % label)
    return errors
