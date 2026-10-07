from __future__ import annotations

from typing import Any


MOTION_PATTERNS = {
    "technical-reveal",
    "layer-build",
    "evidence-scan",
    "editorial-split",
    "focus-pull",
    "cta-path",
}


def _preferred_pattern(shot: dict[str, Any]) -> str:
    template = str(shot.get("uiTemplate") or (shot.get("uiSpec") or {}).get("template") or "")
    variant = str(shot.get("uiVariant") or (shot.get("uiSpec") or {}).get("variant") or "")
    strategy = str(shot.get("visualStrategy") or "")
    if shot.get("ctaAnchor"):
        return "cta-path"
    if variant == "protocol-diagram":
        return "technical-reveal"
    if template in {"anatomy-explainer", "body-distinction"}:
        return "layer-build"
    if variant == "claim-evidence":
        return "evidence-scan"
    if template == "comparison":
        return "editorial-split"
    if strategy == "hybrid":
        return "focus-pull"
    if str(shot.get("beatRole") or "") in {"proof", "payoff", "decision"}:
        return "evidence-scan"
    return "technical-reveal"


def _apply_project_rendering(shot: dict[str, Any], rendering: dict[str, Any]) -> None:
    proof_kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
    motion_spec = shot.get("motionSpec") if isinstance(shot.get("motionSpec"), dict) else {}
    primitive = str(motion_spec.get("visualPrimitive") or "")
    allow_three = bool(rendering.get("allowThree") or rendering.get("allowWebgl"))
    allow_particles = bool(rendering.get("allowParticles"))

    # Project style can authorize a rendering grammar, but evidence semantics
    # still decide the medium. Literal and physiological scenes are never
    # converted into decorative 3D or particles by brand configuration.
    if proof_kind == "abstract_concept" and str(shot.get("representation") or "") == "3d" and allow_three:
        motion_spec["visualPrimitive"] = "three_scene"
        shot["motionSpec"] = motion_spec
        shot["evidenceLayer"] = "3d"
    elif primitive == "three_scene" and not allow_three:
        motion_spec["visualPrimitive"] = "editorial"
        shot["motionSpec"] = motion_spec
        shot["representation"] = "ui"
        shot["evidenceLayer"] = "ui"
    elif primitive == "particles" and not allow_particles:
        motion_spec["visualPrimitive"] = "editorial"
        shot["motionSpec"] = motion_spec

    shot["designGrammar"] = {
        "spatialMode": str(rendering.get("spatialMode") or "flat"),
        "surfaceStyle": str(rendering.get("surfaceStyle") or "solid"),
        "threeAllowed": allow_three,
        "particlesAllowed": allow_particles,
    }


def apply_motion_choreography(plan: dict[str, Any]) -> dict[str, Any]:
    rendering = ((plan.get("designProfile") or {}).get("rendering") or (plan.get("designTheme") or {}).get("rendering") or {})
    previous = ""
    repeated = 0
    alternates = ["technical-reveal", "editorial-split", "focus-pull", "evidence-scan"]
    for index, shot in enumerate(plan.get("shots") or []):
        _apply_project_rendering(shot, rendering)
        requested = str(shot.get("motionPattern") or "").strip().lower()
        pattern = requested if requested in MOTION_PATTERNS else _preferred_pattern(shot)
        repeated = repeated + 1 if pattern == previous else 1
        if repeated > 2 and pattern != "cta-path":
            pattern = next(value for value in alternates[index % len(alternates):] + alternates[:index % len(alternates)] if value != previous)
            repeated = 1
        shot["motionPattern"] = pattern
        previous = pattern
    plan.setdefault("rules", {})["motionChoreographyPolicy"] = "semantic-role-project-profile-v2"
    return plan


def validate_motion_choreography(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    previous = ""
    repeated = 0
    for shot in plan.get("shots") or []:
        sid = str(shot.get("shotId") or "shot")
        pattern = str(shot.get("motionPattern") or "")
        if pattern not in MOTION_PATTERNS:
            errors.append("%s motionPattern invalido" % sid)
        repeated = repeated + 1 if pattern == previous else 1
        if repeated > 2 and pattern != "cta-path":
            errors.append("%s repite motionPattern mas de dos escenas" % sid)
        previous = pattern
    return errors
