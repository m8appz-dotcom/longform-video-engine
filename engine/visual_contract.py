from __future__ import annotations

import hashlib
import json
import re
from typing import Any


REPRESENTATIONS = {
    "photo",
    "video",
    "editorial_illustration",
    "semantic_diagram",
    "ui",
    "3d",
}

VISUAL_STRATEGIES = {"media", "motion", "hybrid"}
TEXT_OWNERS = {"asset", "remotion", "none"}
BACKGROUND_TEXT_POLICIES = {"forbidden", "incidental", "focal"}
RENDERER_VERSIONS = {"semantic-v1", "semantic-v2"}
ART_DIRECTIONS = {"editorial", "technical", "documentary", "data"}
EVIDENCE_LAYERS = {"media", "vector", "ui", "3d"}
ANNOTATION_LAYERS = {"remotion", "none"}

SEMANTIC_V2_TEMPLATES = {"anatomy-explainer", "body-distinction"}
SEMANTIC_V2_VARIANTS = {"claim-evidence", "protocol-diagram"}
LITERAL_EVIDENCE_TEMPLATES = {"anatomy-explainer", "body-distinction"}
LITERAL_EVIDENCE_VARIANTS = {"protocol-diagram", "surface-swelling-fat"}

KNOWN_UI_TEMPLATES = {
    "anatomy-explainer",
    "body-distinction",
    "comparison",
    "concept",
    "evaluation-dashboard",
    "mechanism",
    "process-steps",
    "procedure",
    "product-inspection",
    "product-label",
    "safety-sequence",
    "timeline",
    "verified-next-video",
}

KNOWN_UI_VARIANTS = {
    "claim-evidence",
    "controlled-same-area",
    "evaluation-grid",
    "four-questions",
    "observable-distinction",
    "protocol-diagram",
    "purchase-checklist",
    "safety-sequence",
    "surface-depth",
    "surface-observable",
    "surface-swelling-fat",
}

TRANSIENT_PLAN_FIELDS = {
    "assetOcrAvailable",
    "assetOcrText",
    "assetOcrWords",
    "avatarFailure",
    "candidateSelection",
    "draftRepair",
    "provider",
    "source",
    "sourceInMs",
    "sourceOutMs",
    "sourceWidth",
    "sourceHeight",
    "secondarySource",
    "secondarySourceInMs",
    "secondarySourceOutMs",
    "backgroundSource",
    "fallbackBackgroundSource",
    "fallbackSecondarySource",
    "visualKind",
    "mediaType",
}


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable(item)
            for key, item in sorted(value.items())
            if key not in TRANSIENT_PLAN_FIELDS
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def stable_hash(value: Any) -> str:
    payload = json.dumps(_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def repair_plan_hash(plan: dict[str, Any]) -> str:
    return stable_hash({
        "scriptHash": plan.get("scriptHash"),
        "designProfileId": plan.get("designProfileId"),
        "durationMs": plan.get("durationMs"),
        "shots": plan.get("shots") or [],
    })


def repair_shot_hash(shot: dict[str, Any]) -> str:
    return stable_hash(shot)


def _representation_for(shot: dict[str, Any]) -> str:
    explicit = str(shot.get("representation") or "").strip().lower()
    if explicit in REPRESENTATIONS:
        return explicit
    route = str(shot.get("route") or shot.get("preferredMedium") or "")
    proof_kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
    if route in {"clip_extractor", "pexels", "user", "avatar", "omni", "cutout_motion"}:
        return "video"
    if route == "ui":
        return "ui" if proof_kind == "exact_ui_state" else "semantic_diagram"
    if route == "motion-card":
        return "ui"
    if route in {"image", "image_pair"}:
        return "editorial_illustration" if proof_kind == "physiological_mechanism" else "photo"
    return "ui" if proof_kind in {"exact_ui_state", "abstract_concept"} else "photo"


def _semantic_objects_for(shot: dict[str, Any]) -> list[str]:
    explicit = [str(item).strip() for item in shot.get("semanticObjects") or [] if str(item).strip()]
    if explicit:
        return explicit[:8]
    template = str(shot.get("uiTemplate") or "")
    variant = str(shot.get("uiVariant") or "")
    if variant == "protocol-diagram":
        return ["camera", "subject", "light_45deg", "distance_line", "floor_marks"]
    if template == "anatomy-explainer":
        return ["topical_product", "skin_barrier", "dermis", "subcutaneous_fat"]
    if template == "body-distinction" or variant == "surface-swelling-fat":
        return ["skin_surface", "temporary_swelling", "subcutaneous_fat"]
    if variant == "claim-evidence":
        return ["commercial_claim", "measured_evidence", "decision"]
    if template in {"product-inspection", "product-label"}:
        return ["product_package", "label", "inspection_marker"]
    return []


def normalize_visual_composition(shot: dict[str, Any]) -> dict[str, Any]:
    has_background = bool(shot.get("backgroundSource"))
    route = str(shot.get("route") or "")
    visual_kind = str(shot.get("visualKind") or "")
    strategy = str(shot.get("visualStrategy") or "").strip().lower()
    template = str(shot.get("uiTemplate") or (shot.get("uiSpec") or {}).get("template") or "")
    variant = str(shot.get("uiVariant") or (shot.get("uiSpec") or {}).get("variant") or "")
    literal_evidence = template in LITERAL_EVIDENCE_TEMPLATES or variant in LITERAL_EVIDENCE_VARIANTS
    if literal_evidence and (has_background or shot.get("hybridTemplate")):
        strategy = "hybrid"
    elif strategy not in VISUAL_STRATEGIES:
        if has_background and visual_kind == "ui-card":
            strategy = "hybrid"
        elif route in {"ui", "motion-card"} or visual_kind in {"ui-card", "motion-card"}:
            strategy = "motion"
        else:
            strategy = "media"
    shot["visualStrategy"] = strategy
    shot["representation"] = _representation_for(shot)
    representation = str(shot["representation"])
    shot["semanticObjects"] = _semantic_objects_for(shot)
    shot["freehandDrawingAllowed"] = False

    text_owner = str(shot.get("textOwner") or "").strip().lower()
    if text_owner not in TEXT_OWNERS:
        if strategy in {"motion", "hybrid"}:
            text_owner = "remotion"
        elif shot.get("requiresReadableData"):
            text_owner = "asset"
        elif shot.get("screenCopy") or shot.get("evidenceOverlayHeadline"):
            text_owner = "remotion"
        else:
            text_owner = "none"
    shot["textOwner"] = text_owner

    policy = str(shot.get("backgroundTextPolicy") or "").strip().lower()
    if policy not in BACKGROUND_TEXT_POLICIES:
        if strategy == "hybrid" and str(shot.get("proofKind") or "") == "product_inspection":
            policy = "incidental"
        elif strategy == "hybrid" or text_owner == "remotion":
            policy = "forbidden"
        elif text_owner == "asset":
            policy = "focal"
        else:
            policy = "incidental"
    shot["backgroundTextPolicy"] = policy
    shot["maxBackgroundWords"] = int(shot.get("maxBackgroundWords") or (8 if policy == "incidental" else 0 if policy == "forbidden" else 40))

    safe_zone = str((shot.get("motionSpec") or {}).get("safeZone") or "auto")
    overlay_zones = list(shot.get("overlayZones") or ([] if text_owner != "remotion" else [safe_zone if safe_zone != "auto" else "right"]))
    shot["overlayZones"] = overlay_zones
    if not shot.get("evidenceZone"):
        shot["evidenceZone"] = "left" if "right" in overlay_zones else "right" if "left" in overlay_zones else "full"

    requested_renderer = str(shot.get("rendererVersion") or "").strip().lower()
    supports_v2 = template in SEMANTIC_V2_TEMPLATES or variant in SEMANTIC_V2_VARIANTS
    shot["rendererVersion"] = requested_renderer if requested_renderer in RENDERER_VERSIONS else ("semantic-v2" if supports_v2 else "semantic-v1")
    if shot["rendererVersion"] == "semantic-v2" and not supports_v2:
        shot["rendererVersion"] = "semantic-v1"
    shot["fallbackRenderer"] = "semantic-v1"

    art_direction = str(shot.get("artDirection") or "").strip().lower()
    if art_direction not in ART_DIRECTIONS:
        if variant == "protocol-diagram" or template in {"anatomy-explainer", "body-distinction"}:
            art_direction = "technical"
        elif strategy == "hybrid":
            art_direction = "editorial"
        elif representation in {"photo", "video"}:
            art_direction = "documentary"
        else:
            art_direction = "data"
    shot["artDirection"] = art_direction

    layer = str(shot.get("evidenceLayer") or "").strip().lower()
    if layer not in EVIDENCE_LAYERS:
        layer = "media" if strategy in {"media", "hybrid"} else "3d" if representation == "3d" else "ui" if representation == "ui" else "vector"
    shot["evidenceLayer"] = layer
    shot["annotationLayer"] = "remotion" if text_owner == "remotion" else "none"
    return shot


def normalize_plan_visual_composition(plan: dict[str, Any]) -> dict[str, Any]:
    for shot in plan.get("shots") or []:
        normalize_visual_composition(shot)
    return plan


def validate_visual_composition(shot: dict[str, Any], *, resolved: bool = False) -> list[str]:
    errors: list[str] = []
    sid = str(shot.get("shotId") or "shot")
    strategy = str(shot.get("visualStrategy") or "")
    representation = str(shot.get("representation") or "")
    text_owner = str(shot.get("textOwner") or "")
    policy = str(shot.get("backgroundTextPolicy") or "")
    renderer = str(shot.get("rendererVersion") or "")
    fallback_renderer = str(shot.get("fallbackRenderer") or "")
    art_direction = str(shot.get("artDirection") or "")
    evidence_layer = str(shot.get("evidenceLayer") or "")
    annotation_layer = str(shot.get("annotationLayer") or "")
    if strategy not in VISUAL_STRATEGIES:
        errors.append("%s visualStrategy invalido" % sid)
    if representation not in REPRESENTATIONS:
        errors.append("%s representation invalida" % sid)
    if text_owner not in TEXT_OWNERS:
        errors.append("%s textOwner invalido" % sid)
    if policy not in BACKGROUND_TEXT_POLICIES:
        errors.append("%s backgroundTextPolicy invalido" % sid)
    if renderer not in RENDERER_VERSIONS:
        errors.append("%s rendererVersion invalido" % sid)
    if fallback_renderer != "semantic-v1":
        errors.append("%s fallbackRenderer debe ser semantic-v1" % sid)
    if art_direction not in ART_DIRECTIONS:
        errors.append("%s artDirection invalida" % sid)
    if evidence_layer not in EVIDENCE_LAYERS:
        errors.append("%s evidenceLayer invalida" % sid)
    if annotation_layer not in ANNOTATION_LAYERS:
        errors.append("%s annotationLayer invalida" % sid)

    route = str(shot.get("route") or "")
    template = str(shot.get("uiTemplate") or (shot.get("uiSpec") or {}).get("template") or "")
    variant = str(shot.get("uiVariant") or (shot.get("uiSpec") or {}).get("variant") or "")
    primitive = str((shot.get("motionSpec") or {}).get("visualPrimitive") or "")
    if route == "ui" or str(shot.get("visualKind") or "") == "ui-card":
        if not template:
            errors.append("%s UI sin plantilla semantica; fallback Diagram prohibido" % sid)
        if template and template not in KNOWN_UI_TEMPLATES and primitive in {"", "diagram", "editorial"}:
            errors.append("%s plantilla UI desconocida %s" % (sid, template))
        if variant and variant not in KNOWN_UI_VARIANTS and template not in KNOWN_UI_TEMPLATES:
            errors.append("%s variante UI desconocida %s" % (sid, variant))
    if strategy == "hybrid" and text_owner != "remotion":
        errors.append("%s visual hibrido debe tener texto controlado por Remotion" % sid)
    if renderer == "semantic-v2" and template not in SEMANTIC_V2_TEMPLATES and variant not in SEMANTIC_V2_VARIANTS:
        errors.append("%s semantic-v2 no soporta template=%s variant=%s" % (sid, template, variant))
    literal_evidence = template in LITERAL_EVIDENCE_TEMPLATES or variant in LITERAL_EVIDENCE_VARIANTS
    if literal_evidence and strategy != "hybrid":
        errors.append("%s evidencia fisica/anatomica requiere imagen editorial + anotacion Remotion" % sid)
    if literal_evidence and route in {"ui", "motion-card"}:
        errors.append("%s evidencia fisica/anatomica no admite UI como medio primario" % sid)
    if literal_evidence and not resolved and not shot.get("hybridTemplate") and not shot.get("backgroundSource"):
        errors.append("%s evidencia fisica/anatomica sin ruta hibrida" % sid)
    if literal_evidence and resolved and not shot.get("backgroundSource"):
        errors.append("%s evidencia fisica/anatomica sin asset literal" % sid)
    if resolved and strategy == "hybrid" and not shot.get("backgroundSource"):
        errors.append("%s visual hibrido sin evidencia de fondo" % sid)

    ocr_available = shot.get("assetOcrAvailable")
    ocr_words = int(shot.get("assetOcrWords") or 0)
    max_words = int(shot.get("maxBackgroundWords") or 0)
    if resolved and strategy == "hybrid":
        if ocr_available is True and ocr_words > max_words:
            errors.append("%s fondo contiene %d palabras; maximo %d para overlay Remotion" % (sid, ocr_words, max_words))
    return errors


def visual_grammar(shot: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(shot.get("representation") or ""),
        str(shot.get("uiTemplate") or (shot.get("uiSpec") or {}).get("template") or shot.get("compositionStyle") or ""),
        str(shot.get("uiVariant") or (shot.get("uiSpec") or {}).get("variant") or ""),
    )


def validate_plan_visual_composition(plan: dict[str, Any], *, resolved: bool = False) -> list[str]:
    errors: list[str] = []
    shots = list(plan.get("shots") or [])
    consecutive = 0
    previous: tuple[str, str, str] | None = None
    filmable = 0
    actual_video = 0
    for shot in shots:
        errors.extend(validate_visual_composition(shot, resolved=resolved))
        grammar = visual_grammar(shot)
        consecutive = consecutive + 1 if grammar == previous else 1
        previous = grammar
        if consecutive > 2 and grammar[0] in {"ui", "semantic_diagram"}:
            errors.append("%s repite la misma gramatica visual mas de dos escenas" % str(shot.get("shotId") or "shot"))
        proof_kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
        if proof_kind in {"human_action", "real_event", "third_party_commentary", "cultural_reference"}:
            filmable += 1
        if (
            str(shot.get("mediaType") or "") == "video"
            or str(shot.get("backgroundMediaType") or "") == "video"
        ) and not shot.get("avatarFallback"):
            actual_video += 1
    if resolved and filmable and actual_video == 0:
        errors.append("plan contiene %d beats filmables pero ningun video real" % filmable)
    return errors


def repair_payload_matches(payload: dict[str, Any], plan: dict[str, Any], policy: str) -> bool:
    if str(payload.get("policy") or "") != policy:
        return False
    if str(payload.get("scriptHash") or "") != str(plan.get("scriptHash") or ""):
        return False
    if str(payload.get("designProfileId") or "") != str(plan.get("designProfileId") or ""):
        return False
    if str(payload.get("sourcePlanHash") or "") != repair_plan_hash(plan):
        return False
    if int(payload.get("expiresAfterAttempt") or 0) < int(payload.get("attempt") or 1):
        return False
    by_id = {str(shot.get("shotId") or ""): shot for shot in plan.get("shots") or []}
    for sid, patch in (payload.get("patches") or {}).items():
        if sid not in by_id or not isinstance(patch, dict):
            return False
        if str(patch.get("sourceShotHash") or "") != repair_shot_hash(by_id[sid]):
            return False
    return True


def strip_repair_metadata(patch: dict[str, Any]) -> dict[str, Any]:
    clean = _copy(patch)
    for key in ("sourceShotHash", "targetBlocker", "sourceFrameHash", "sourceReviewHash"):
        clean.pop(key, None)
    return clean


def internal_id_visible(text: str, target_video_id: str) -> bool:
    clean = re.sub(r"\s+", "", str(text or ""))
    target = re.sub(r"\s+", "", str(target_video_id or ""))
    return bool(target and target.lower() in clean.lower())
