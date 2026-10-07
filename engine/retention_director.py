from __future__ import annotations

import collections
from typing import Any


GRAPHIC_ROUTES = {"ui", "motion-card"}


def _composition_style(shot: dict[str, Any], index: int) -> str:
    explicit = str(shot.get("compositionStyle") or "").strip()
    if explicit:
        return explicit
    route = str(shot.get("route") or "")
    kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
    temporal = str(shot.get("temporalEvidenceMode") or "")
    if route in GRAPHIC_ROUTES:
        return str(shot.get("uiTemplate") or (shot.get("motionSpec") or {}).get("visualPrimitive") or "editorial")
    if temporal == "initial_final":
        return "controlled-pair-%s" % ("wide" if index % 2 else "detail")
    base = {
        "product_inspection": "product-macro",
        "human_action": "action-detail",
        "physiological_mechanism": "mechanism-layer",
        "comparison": "comparison-split",
        "presenter": "presenter-anchor",
        "abstract_concept": "editorial-concept",
    }.get(kind, "contextual-evidence")
    return "%s-%s" % (base, ("wide", "close", "overhead")[index % 3])


def direct_plan(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Vary feasible media without changing what evidence a beat requires."""
    recent: list[str] = []
    for index, shot in enumerate(shots):
        route = str(shot.get("route") or "")
        if len(recent) >= 2 and recent[-1] == recent[-2] == route and not shot.get("requiresReadableData"):
            forbidden = set(shot.get("forbiddenSubstitutions") or [])
            alternative = next((item for item in shot.get("routePlan") or [] if item != route and item not in forbidden and not (shot.get("requiresObservedTransition") and item in {"image", "image_pair"})), None)
            if alternative:
                shot["route"] = alternative
                shot["routePlan"] = [alternative] + [item for item in shot.get("routePlan") or [] if item != alternative]
                shot["routingAdjustment"] = "retention-alternate-medium"
                route = alternative
        recent.append(route)
        shot["compositionStyle"] = _composition_style(shot, index)
    return shots


def validate_retention(plan: dict[str, Any]) -> dict[str, Any]:
    shots = list(plan.get("shots") or [])
    errors: list[str] = []
    warnings: list[str] = []
    max_same_medium = 0
    max_same_template = 0
    same_medium = 0
    same_template = 0
    same_semantic_pattern = 0
    max_same_semantic_pattern = 0
    previous_medium = ""
    previous_template = ""
    previous_pattern: tuple[str, str, str] | None = None
    novelty: dict[str, list[str]] = collections.defaultdict(list)
    chapter_proof: dict[str, int] = collections.Counter()
    for shot in shots:
        sid = str(shot.get("shotId") or "shot")
        medium = str(shot.get("provider") or shot.get("route") or "")
        visual_kind = str(shot.get("visualKind") or "")
        # A resolved still/video may retain a planning uiSpec, but that
        # template is not rendered. Count the composition viewers actually see.
        template = (
            str((shot.get("uiSpec") or {}).get("template") or shot.get("cardVariant") or visual_kind)
            if visual_kind in {"ui-card", "motion-card"}
            else str(shot.get("compositionStyle") or visual_kind)
        )
        same_medium = same_medium + 1 if medium == previous_medium else 1
        same_template = same_template + 1 if template and template == previous_template else 1
        pattern = (medium, template, visual_kind)
        same_semantic_pattern = same_semantic_pattern + 1 if pattern == previous_pattern else 1
        max_same_medium = max(max_same_medium, same_medium)
        max_same_template = max(max_same_template, same_template)
        max_same_semantic_pattern = max(max_same_semantic_pattern, same_semantic_pattern)
        previous_medium, previous_template = medium, template
        previous_pattern = pattern
        novelty[str(shot.get("noveltyKey") or "")].append(sid)
        if shot.get("beatRole") == "proof" and shot.get("visualKind") != "motion-card":
            chapter_proof[str(shot.get("chapterId") or "") ] += 1
        if shot.get("beatRole") == "proof" and shot.get("visualKind") == "motion-card":
            errors.append("%s usa tarjeta de texto en lugar de evidencia" % sid)
        if int(shot.get("endMs") or 0) - int(shot.get("startMs") or 0) > 8200:
            warnings.append("%s mantiene el mismo beat visual mas de 8.2 s" % sid)
    if max_same_medium > 3:
        warnings.append("hay %d escenas consecutivas del mismo proveedor; revisar ritmo humano" % max_same_medium)
    if max_same_semantic_pattern > 2:
        errors.append("hay %d escenas consecutivas con el mismo medio y composicion" % max_same_semantic_pattern)
    if max_same_template > 2:
        errors.append("hay %d composiciones consecutivas de la misma plantilla" % max_same_template)
    repeated = {key: ids for key, ids in novelty.items() if key and len(ids) > 1 and not key.startswith("recap:")}
    if repeated:
        errors.append("noveltyKey repetido fuera de recap: %s" % repeated)
    chapters = {str(shot.get("chapterId") or "") for shot in shots}
    missing = sorted(chapter for chapter in chapters if chapter and not chapter_proof.get(chapter))
    if missing:
        errors.append("capitulos sin beat de evidencia: %s" % ", ".join(missing))
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "metrics": {"max_same_medium": max_same_medium, "max_same_template": max_same_template, "max_same_semantic_pattern": max_same_semantic_pattern, "chapters_with_proof": len(chapter_proof), "novelty_keys": len([key for key in novelty if key])},
    }
