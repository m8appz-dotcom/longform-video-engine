from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

from PIL import Image, ImageOps

from engine.config import ROOT, REMOTION_DIR, production_mode, subprocess_env
from engine.longform_contract import chapter_spoken_text, forbidden_spoken_terms, full_script, load_approved_script
from engine import media_tools
from engine import asset_library
from engine.provider_runtime import ProviderRuntime
from engine.provider_manager import ProviderManager
from engine.provider_telemetry import ProviderTelemetry
from engine.media_router import assign_evidence_beats, balance_graphic_routes, cutout_enabled, infer_media_need, normalize_media_contract, route_order, validate_media_contract, validate_plan_media_contract
from engine.query_compilers import compile_all, compile_ui_spec, rejection_feedback
from engine.media_prefilter import prefilter as media_prefilter
from engine.evidence_set_qa import contact_sheet as evidence_contact_sheet, validate_set as validate_evidence_set
from engine.candidate_ranker import choose_best, score_candidate
from engine.retention_director import direct_plan, validate_retention
from engine.channel_learning import apply_biases as apply_learning_biases, record_run as record_learning_run
from engine.suno_prompt import build_suno_request
from engine.design_profile import design_prompt_scope, resolve_design_profile, remotion_theme
from engine.motion_spec import apply_motion_contract, infer_temporal_evidence, validate_motion_contract
from engine.visual_contract import (
    internal_id_visible,
    normalize_plan_visual_composition,
    normalize_visual_composition,
    repair_payload_matches,
    repair_plan_hash,
    repair_shot_hash,
    stable_hash,
    strip_repair_metadata,
    validate_plan_visual_composition,
)
from engine.composition_qa import measure_rendered_motion, validate_composed_frames
from engine.motion_choreography import apply_motion_choreography, validate_motion_choreography
from engine.art_direction_qa import review_art_direction
from providers.deterministic_ui import materialize_shot as materialize_ui_shot
from providers.core import get_providers


WIDTH = int(os.environ.get("LONGFORM_WIDTH", "1920"))
HEIGHT = int(os.environ.get("LONGFORM_HEIGHT", "1080"))
FPS = int(os.environ.get("LONGFORM_FPS", "30"))
TARGET_SHOT_MS = int(float(os.environ.get("LONGFORM_TARGET_SHOT_SECONDS", "5.5")) * 1000)
MAX_SHOT_MS = int(float(os.environ.get("LONGFORM_MAX_SHOT_SECONDS", "8")) * 1000)
RUNS_ROOT = pathlib.Path(ROOT) / "work" / "longform_runs"
OUT_ROOT = pathlib.Path(ROOT) / "out" / "longform"
PUBLIC_ROOT = pathlib.Path(REMOTION_DIR) / "public" / "runs"
PLAN_POLICY_VERSION = "feasibility-v53-frontier-default"
DRAFT_REPAIR_POLICY_VERSION = "draft-evidence-repair-v35-literal-evidence"
DRAFT_REPAIR_FIELDS = {
    "proofKind", "mediaNeedKind", "beatRole", "requiredEvidence", "preferredMedium", "forbiddenSubstitutions", "detailSalience",
    "requiresReadableData", "requiresContinuity", "requiresStateContinuity", "temporalAction", "temporalEvidenceMode",
    "requiresObservedTransition", "stateCount", "movingVisualRequired", "motionSpec", "stopMotion", "stopMotionIntent", "whyStopMotion",
    "peoplePolicy", "presenterAllowed", "maxFaceAreaRatio", "requiresVisibleFace", "evidenceMustRemainDominant", "route", "routePlan",
    "fallbackStrategy", "skipLibrary", "prompt", "hookRequirement", "screenCopy", "suppressScreenCopy", "subcopy", "uiTemplate", "uiVariant",
    "uiItems", "uiValues", "hybridTemplate", "backgroundSource", "backgroundMediaType", "backgroundObjectPosition",
    "pinnedAsset", "verifiedCtaEndScreen", "fallbackComposite", "fallbackBackgroundSource", "fallbackBackgroundMediaType",
    "fallbackBackgroundObjectPosition", "fallbackSecondarySource", "fallbackSecondaryMediaType", "compositionStyle",
    "evidenceOverlayHeadline", "evidenceOverlayItems", "reuseLeftPanel", "surfaceSheenRight",
    "visualStrategy", "representation", "semanticObjects", "textOwner", "backgroundTextPolicy",
    "maxBackgroundWords", "overlayZones", "evidenceZone", "freehandDrawingAllowed", "ctaAnchor",
    "rendererVersion", "fallbackRenderer", "artDirection", "evidenceLayer", "annotationLayer", "motionPattern",
}


class DraftReviewFailed(RuntimeError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("draft/avatar review fallo; master cancelado")


class GlobalVisualReplanRequired(RuntimeError):
    pass


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def enforce_hard_route_priority(shot: dict[str, Any]) -> dict[str, Any]:
    """Reassert feasibility decisions after editorial diversity passes."""
    repaired_hybrid = bool(
        shot.get("draftRepair")
        and str(shot.get("route") or "") in {"image", "image_pair"}
        and str(shot.get("hybridTemplate") or "")
    )
    if shot.get("complexComparison") and not repaired_hybrid:
        routes = ["image", "omni"] + [route for route in (shot.get("routePlan") or []) if route not in {"image", "omni", "ui"}]
        shot.update({
            "route": "image",
            "routePlan": routes,
            "preferredMedium": "image",
            "fallbackStrategy": "bounded-provider-search",
            "uiTemplate": "body-distinction",
            "hybridTemplate": "body-distinction",
            "uiItems": ["HINCHAZÓN ≠ GRASA", "PIEL LUMINOSA ≠ MENOS GRASA"],
            "continuityGroup": "%s-body-distinction" % str(shot.get("shotId") or "comparison").lower(),
            "requiresContinuity": False,
            "requiresStateContinuity": False,
            "evidenceMustRemainDominant": True,
            "forbiddenSubstitutions": list(dict.fromkeys(list(shot.get("forbiddenSubstitutions") or []) + ["ui", "motion-card", "text-only-ui", "wireframe-diagram"])),
        })
    if shot.get("controlledComparison"):
        routes = ["image_pair"] + [route for route in (shot.get("routePlan") or []) if route != "image_pair"]
        base_group = str(shot.get("continuityGroup") or shot.get("shotId") or "controlled-comparison")
        if not base_group.endswith("-visual"):
            base_group += "-visual"
        shot.update({
            "route": "image_pair",
            "routePlan": routes,
            "preferredMedium": "image_pair",
            "fallbackStrategy": "bounded-provider-search",
            "continuityGroup": base_group,
        })
    if shot.get("protocolComparisonSetup"):
        routes = ["image", "omni"] + [route for route in (shot.get("routePlan") or []) if route not in {"image", "omni", "ui"}]
        shot.update({
            "route": "image",
            "routePlan": routes,
            "preferredMedium": "image",
            "fallbackStrategy": "bounded-provider-search",
            "uiTemplate": "process-steps",
            "hybridTemplate": "process-steps",
            "uiVariant": "protocol-diagram",
            "uiItems": ["MISMA LUZ", "MISMA DISTANCIA", "MISMA POSTURA"],
            "requiresContinuity": False,
            "requiresStateContinuity": False,
            "evidenceMustRemainDominant": True,
            "forbiddenSubstitutions": list(dict.fromkeys(list(shot.get("forbiddenSubstitutions") or []) + ["ui", "motion-card", "text-only-ui", "wireframe-diagram"])),
        })
    return shot


def restore_directed_repair_media(shot: dict[str, Any]) -> dict[str, Any]:
    """Keep viewer-approved media intent from being overwritten by generic upgrades."""
    if not shot.get("draftRepair"):
        return shot
    if str(shot.get("proofKind") or shot.get("mediaNeedKind") or "") == "presenter" or shot.get("avatarRequested") is True or shot.get("avatarFallback") is True:
        return shot
    provider = str(shot.get("provider") or "")
    provider_base = provider.split("+", 1)[0]
    has_visual = bool(str(shot.get("source") or shot.get("backgroundSource") or ""))
    if not has_visual or provider_base not in {"image", "image_pair"}:
        return shot
    if provider_base == "image_pair" or "+remotion" in provider:
        kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
        shot.update({
            "route": "image_pair",
            "routePlan": ["image_pair", "ui", "omni"],
            "preferredMedium": "image_pair",
            "hybridTemplate": str(shot.get("hybridTemplate") or ("process-steps" if kind == "human_action" else "comparison")),
        })
    else:
        shot.update({
            "route": "image",
            "routePlan": ["image", "ui"],
            "preferredMedium": "image",
            "requiresReadableData": False,
        })
    return shot


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _draft_blocker_text(blocker: Any) -> tuple[str, str]:
    if isinstance(blocker, dict):
        return str(blocker.get("label") or ""), str(
            blocker.get("reason") or blocker.get("message") or blocker.get("shot") or ""
        )
    text = str(blocker or "")
    match = re.search(r"\b(S\d{4})\b", text)
    return (match.group(1) if match else ""), text


def _product_background(plan: dict[str, Any]) -> tuple[str, str]:
    for shot in plan.get("shots") or []:
        if str(shot.get("proofKind") or shot.get("mediaNeedKind") or "") != "product_inspection":
            continue
        source = str(shot.get("source") or shot.get("backgroundSource") or "")
        media_type = str(shot.get("mediaType") or shot.get("backgroundMediaType") or "")
        if source and media_type == "image":
            return source, "image"
    return "", ""


def _apply_draft_repair_specs(plan: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    patches = payload.get("patches") or {}
    for shot in plan.get("shots") or []:
        patch = patches.get(str(shot.get("shotId") or ""))
        if not isinstance(patch, dict):
            continue
        selected_presenter_anchor = bool(
            shot.get("avatarRequested") is True
            or shot.get("avatarFallback") is True
            or shot.get("presenterReason") == "trust_anchor_without_competing_evidence"
        )
        for transient in (
            "pinnedAsset", "backgroundSource", "backgroundMediaType", "backgroundObjectPosition",
            "secondarySource", "secondaryMediaType", "secondaryProvider", "hybridTemplate",
            "uiTemplate", "uiVariant", "uiItems", "uiValues", "fallbackComposite",
            "fallbackBackgroundSource", "fallbackBackgroundMediaType", "fallbackBackgroundObjectPosition",
            "fallbackSecondarySource", "fallbackSecondaryMediaType",
        ):
            shot.pop(transient, None)
        if patch.get("prompt"):
            shot.pop("imageBasePrompt", None)
            shot.pop("imagePairPrompt", None)
            for key in ("query", "clipQuery", "clipBaseQuery", "pexelsQuery", "pexelsBaseQuery", "omniPrompt"):
                shot.pop(key, None)
        shot.pop("queryVariants", None)
        shot.pop("uiSpec", None)
        applied_patch = strip_repair_metadata(patch)
        shot.update(json.loads(json.dumps(applied_patch)))
        if str(shot.get("route") or "") == "ui":
            # A directed UI repair must not inherit search or generative prompts
            # from the rejected provider. Those stale fields can contradict the
            # deterministic contract (for example readable data + "no text").
            for key in (
                "prompt", "imageBasePrompt", "imagePairPrompt", "omniPrompt",
                "query", "clipQuery", "clipBaseQuery", "pexelsQuery",
                "pexelsBaseQuery", "queryVariants", "source", "mediaType", "provider",
            ):
                shot.pop(key, None)
        if str(patch.get("route") or "") != "avatar" and not selected_presenter_anchor:
            for key in (
                "avatarRequested", "avatarFallback", "avatarFailure", "presenterReason",
                "companionRoute", "companionRoutePlan", "companionContract",
            ):
                shot.pop(key, None)
            if str(shot.get("noveltyKey") or "").startswith("presenter-"):
                shot.pop("noveltyKey", None)
        shot["draftRepair"] = {
            "policy": str(payload.get("policy") or DRAFT_REPAIR_POLICY_VERSION),
            "attempt": int(payload.get("attempt") or 1),
            "reason": str(patch.get("draftRepairReason") or "viewer_blocker"),
        }
        normalize_media_contract(shot, shot)
        enforce_hard_route_priority(shot)
        requested_route = str(patch.get("route") or "")
        if requested_route in {"image", "image_pair"} and not shot.get("requiresReadableData"):
            # A viewer-directed photographic repair is more specific than the
            # generic protocol/comparison heuristic. Keep its real evidence and
            # let Remotion add explanatory overlays instead of replacing it.
            requested_plan = list(patch.get("routePlan") or [requested_route])
            if not bool((shot.get("stopMotion") or {}).get("eligible")):
                requested_plan = [item for item in requested_plan if item != "cutout_motion"]
            shot["route"] = requested_route
            shot["routePlan"] = [requested_route] + [item for item in requested_plan if item != requested_route]
            shot["preferredMedium"] = requested_route
            shot["fallbackStrategy"] = "bounded-provider-search"
            if patch.get("hybridTemplate"):
                shot["hybridTemplate"] = str(patch["hybridTemplate"])
        if shot.get("requiresStateContinuity") and not patch.get("continuityGroup"):
            shot["continuityGroup"] = "%s-directed-repair" % str(shot.get("shotId") or "shot").lower()
        if str(shot.get("route") or "") == "ui":
            shot.pop("hybridTemplate", None)
            # The directed repair is more specific than generic comparison
            # heuristics. Preserve its selected visual grammar after routing.
            for key in ("uiTemplate", "uiVariant", "uiItems", "uiValues"):
                if key in patch:
                    shot[key] = json.loads(json.dumps(patch[key]))
        compile_all(shot)
        apply_motion_contract(shot, shot)
        normalize_visual_composition(shot)
    return plan


def apply_persisted_draft_repairs(plan: dict[str, Any], paths: dict[str, pathlib.Path]) -> dict[str, Any]:
    repair_path = paths["work"] / "07c_draft_repair_plan.json"
    if not repair_path.is_file():
        return plan
    payload = read_json(repair_path)
    if not repair_payload_matches(payload, plan, DRAFT_REPAIR_POLICY_VERSION):
        return plan
    return _apply_draft_repair_specs(plan, payload)


def _enforce_temporal_repair_media(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Keep directed repairs compatible with the shot's temporal evidence contract."""
    probe = dict(current)
    probe.update(patch)
    mode, requires_transition, state_count = infer_temporal_evidence(probe, patch)
    patch["temporalEvidenceMode"] = mode
    patch["requiresObservedTransition"] = requires_transition
    patch["stateCount"] = state_count
    route = str(patch.get("route") or current.get("route") or "")
    routes = list(patch.get("routePlan") or current.get("routePlan") or [])
    if mode == "implied":
        return patch

    kind = str(patch.get("proofKind") or current.get("proofKind") or patch.get("mediaNeedKind") or current.get("mediaNeedKind") or "")
    if mode == "initial_final":
        if kind == "exact_ui_state" and route == "ui":
            # Exact UI can represent both states and animate their transition
            # without inventing a photographic pair.
            patch["route"] = "ui"
            patch["routePlan"] = ["ui"]
            patch["preferredMedium"] = "ui"
            return patch
        patch["route"] = "image_pair"
        patch["routePlan"] = ["image_pair", "ui", "omni"]
        patch["preferredMedium"] = "image_pair"
        patch.setdefault("hybridTemplate", "comparison" if kind != "human_action" else "process-steps")
        patch.setdefault("uiTemplate", patch["hybridTemplate"])
    elif requires_transition and route in {"image", "image_pair"}:
        viable = [candidate for candidate in routes if candidate not in {"image", "image_pair", "cutout_motion"}]
        if kind == "human_action" and "pexels" not in viable:
            viable.insert(0, "pexels")
        if "omni" not in viable:
            viable.append("omni")
        if "ui" not in viable:
            viable.append("ui")
        patch["route"] = viable[0]
        patch["routePlan"] = viable
        patch["preferredMedium"] = viable[0]
    return patch


def build_draft_repair_plan(data: dict[str, Any], plan: dict[str, Any], report: dict[str, Any], paths: dict[str, pathlib.Path]) -> dict[str, Any]:
    viewer = report.get("viewer") or {}
    existing_path = paths["work"] / "07c_draft_repair_plan.json"
    attempt = 1
    product_source, product_type = _product_background(plan)
    existing_by_id = {str(shot.get("shotId") or ""): shot for shot in plan.get("shots") or []}
    raw_blockers = list(viewer.get("blockers") or [])
    blocker_labels = {
        _draft_blocker_text(blocker)[0]
        for blocker in raw_blockers
        if _draft_blocker_text(blocker)[0]
    }
    if len(blocker_labels) > max(2, math.ceil(len(existing_by_id) * 0.30)):
        raise GlobalVisualReplanRequired(
            "QA rechazo %d de %d escenas; se requiere recompilar el plan en vez de acumular parches"
            % (len(blocker_labels), len(existing_by_id))
        )
    patches: dict[str, dict[str, Any]] = {}
    source_review_hash = stable_hash(report)
    source_plan_hash = repair_plan_hash(plan)
    for blocker in raw_blockers:
        label, reason = _draft_blocker_text(blocker)
        if not label:
            continue
        low = reason.lower()
        raw_label = label
        if label.upper().startswith("HOOK") and plan.get("shots"):
            label = str((plan.get("shots") or [{}])[0].get("shotId") or label)
        current = existing_by_id.get(label) or {}
        current_context = " ".join(str(current.get(key) or "") for key in ("tts", "visualProof", "requiredEvidence")).lower()
        if any(term in low for term in ("anatomía/proceso", "afirmar que la grasa", "esquema simplificado", "roza evidencia falsa")) and str(current.get("proofKind") or "") != "physiological_mechanism":
            ordered = list(plan.get("shots") or [])
            index = next((idx for idx, shot in enumerate(ordered) if str(shot.get("shotId") or "") == label), -1)
            if index > 0 and str(ordered[index - 1].get("proofKind") or "") == "physiological_mechanism":
                label = str(ordered[index - 1].get("shotId") or label)
                current = existing_by_id.get(label) or {}
        patch: dict[str, Any] = {
            "draftRepairReason": reason[:500],
            "skipLibrary": True,
            "sourceShotHash": repair_shot_hash(current),
            "sourceReviewHash": source_review_hash,
            "targetBlocker": reason[:500],
        }
        if label == str((plan.get("shots") or [{}])[0].get("shotId") or "") and any(term in low for term in (
            "no es claramente legible", "no ofrecer una etiqueta grande", "no ofrece una etiqueta grande",
            "overlay adicional tapa", "tapa más el frente", "tapa mas el frente",
            "comparación close-up lado a lado", "comparación de la misma zona de piel", "solo aparece el envase",
        )):
            patch.update({
                "proofKind": "product_inspection", "mediaNeedKind": "product_inspection",
                "route": "image", "routePlan": ["image", "omni"], "preferredMedium": "image",
                "fallbackStrategy": "bounded-provider-search", "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0,
                "screenCopy": str(data.get("thumbnail_promise") or current.get("screenCopy") or "ANTES DE COMPRARLA")[:48],
                "suppressScreenCopy": True, "subcopy": "", "evidenceOverlayHeadline": "", "evidenceOverlayItems": [],
                "requiresReadableData": False,
                "detailSalience": "focal", "hybridTemplate": "", "uiTemplate": "", "uiVariant": "", "uiItems": [], "uiValues": [],
                "temporalAction": "single", "temporalEvidenceMode": "implied", "requiresObservedTransition": False,
                "stateCount": 1, "movingVisualRequired": False, "backgroundSource": "", "backgroundMediaType": "",
                "requiredEvidence": "A front-facing open body-cream jar with a large readable fictional label validates the purchase-inspection promise in the first three seconds.",
                "visualProof": "A readable body-cream package is inspected before purchase; the topical product is unmistakable.",
                "forbiddenSubstitutions": ["blank-packaging", "small-print", "gibberish-label", "skin-before-after"],
                "prompt": "Landscape 16:9 premium editorial macro of ONE open wide amber body-cream jar, front-facing, centered and occupying at least 60 percent of the frame, thick white cream visible. Keep the complete front label unobstructed. The label contains ONLY these four very large high-contrast readable lines: LUMERA / CREMA CORPORAL / HIDRATACIÓN INTENSA / 200 ML. No overlay, no card, no ingredients panel, no side label, no fine print, no other text, no logo symbol, no trademark, no blank packaging. Warm natural bathroom light, realistic glass and paper.",
                "hookRequirement": "En el primer segundo debe verse un tarro ancho abierto de crema corporal con LUMERA, CREMA CORPORAL, HIDRATACIÓN INTENSA y 200 ML legibles. La promesa es inspeccionar el producto antes de comprarlo, no mostrar un antes/después corporal.",
            })
        elif label == str((plan.get("shots") or [{}])[0].get("shotId") or "") and any(term in low for term in (
            "texto lateral ilegible", "etiquetas ilegibles", "demasiado pequeño en el envase",
            "texto fino", "fine print", "mayormente ilegible", "etiqueta ilegible",
        )):
            patch.update({
                "proofKind": "product_inspection", "mediaNeedKind": "product_inspection",
                "route": "image", "routePlan": ["image", "ui"], "preferredMedium": "image",
                "fallbackStrategy": "deterministic-ui", "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0,
                "screenCopy": "ANTES DE COMPRARLA", "requiresReadableData": False,
                "forbiddenSubstitutions": ["blank-packaging", "small-print", "gibberish-label"],
                "prompt": "Landscape 16:9 premium editorial macro of one open wide amber body-cream jar, front-facing and centered, thick white cream visible. The label contains ONLY these four large readable lines: LUMERA / CREMA CORPORAL / HIDRATACIÓN INTENSA / 200 ML. No ingredients panel, no side label, no fine print, no other text, no logo symbol, no trademark, no blank packaging. Warm natural bathroom light, realistic glass and paper, generous safe margins.",
                "hookRequirement": "En el primer segundo debe verse un tarro ancho abierto de crema corporal. La etiqueta solo puede mostrar LUMERA, CREMA CORPORAL, HIDRATACIÓN INTENSA y 200 ML en letras grandes; rechaza texto pequeño, ingredientes inventados, goteros, sérums y envases blancos.",
            })
        elif (
            any(term in low for term in ("anatomía/proceso", "afirmar que la grasa", "esquema simplificado", "roza evidencia falsa", "aplicación tópica no la derrite", "esquema/ilustración", "separación pedida", "capas anatómicas", "layered anatomy", "surface vs subcutaneous"))
            or (
                str(current.get("proofKind") or current.get("mediaNeedKind") or "") == "physiological_mechanism"
                and "motion-card sustituye" in low
            )
        ):
            patch.update({
                "proofKind": "physiological_mechanism", "mediaNeedKind": "physiological_mechanism",
                "route": "image", "routePlan": ["image", "omni"], "preferredMedium": "image",
                "fallbackStrategy": "bounded-provider-search", "uiTemplate": "anatomy-explainer", "hybridTemplate": "anatomy-explainer",
                "uiVariant": "surface-depth", "uiItems": ["CREMA", "PIEL", "GRASA SUBCUTÁNEA"],
                "uiValues": ["SUPERFICIE", "BARRERA", "SIN CAMBIO"], "screenCopy": "LA GRASA ESTÁ DEBAJO",
                "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0, "evidenceMustRemainDominant": True,
                "temporalAction": "multi_step", "movingVisualRequired": True,
                "forbiddenSubstitutions": ["ui", "motion-card", "text-only-ui", "generic-block-diagram", "wireframe-diagram"],
                "requiredEvidence": "A premium anatomical editorial cutaway visibly separates the topical skin surface, the skin barrier and deeper unchanged subcutaneous fat.",
                "prompt": "Landscape 16:9 premium 3D medical-editorial cutaway of adult human skin. Show a realistic skin surface and barrier above clearly deeper subcutaneous fat lobules; any topical cream remains only on the surface. Anatomically plausible, simplified for a general audience, non-gory, natural organic texture, warm cream background, muted teal and restrained gold accents. No text, no labels, no arrows, no bars, no chart circles, no wireframe, no before-and-after transformation.",
            })
        elif any(term in low for term in ("hidratación superficial vs transformación", "hidratación superficial", "transformación permanente")) and any(term in low for term in ("evidencia falsa", "comparación verificable", "demostración real")):
            patch.update({
                "proofKind": "comparison", "mediaNeedKind": "comparison", "route": "image_pair",
                "routePlan": ["image_pair", "omni"], "preferredMedium": "image_pair",
                "fallbackStrategy": "bounded-provider-search", "hybridTemplate": "comparison", "uiTemplate": "comparison",
                "uiVariant": "surface-observable", "uiItems": ["ANTES", "DESPUÉS"],
                "uiValues": ["SUPERFICIE SECA", "MÁS BRILLO"], "screenCopy": "NO ES PERMANENTE",
                "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0, "evidenceMustRemainDominant": True,
                "temporalAction": "multi_step", "movingVisualRequired": True,
                "forbiddenSubstitutions": ["anatomy", "diagram", "motion-card", "text-only-ui"],
                "prompt": "Landscape 16:9 controlled two-panel documentary macro of the exact same adult thigh area, no face. Left: before body cream, normal matte skin surface. Right: shortly after a small amount of thick white body cream has been absorbed, the identical marked area under the same camera, light, distance and contour, showing only a slightly more hydrated surface sheen. Body outline and volume remain exactly unchanged. No anatomy, no cross-section, no slimming, no body transformation, no text, no logo, no product bottle.",
            })
        elif any(term in low for term in ("fenómeno real", "comparación observable", "más allá del gráfico", "evidencia visual suficiente")) and any(term in low for term in ("hinchazón", "brillo", "tejido adiposo", "grasa")):
            patch.update({
                "proofKind": "comparison", "mediaNeedKind": "comparison", "route": "image",
                "routePlan": ["image", "omni"], "preferredMedium": "image",
                "fallbackStrategy": "bounded-provider-search", "hybridTemplate": "comparison", "uiTemplate": "comparison",
                "uiVariant": "observable-distinction", "uiItems": ["HINCHAZÓN TEMPORAL", "TEJIDO ESTABLE", "BRILLO SUPERFICIAL"],
                "uiValues": ["MARCA DE CALCETÍN", "CONTORNO ESTABLE", "CAMBIA CON LA LUZ"], "screenCopy": "NO LOS CONFUNDAS",
                "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0, "evidenceMustRemainDominant": True,
                "forbiddenSubstitutions": ["anatomy", "diagram", "motion-card", "text-only-ui"],
                "prompt": "Landscape 16:9 three-panel documentary health photography, no face and no text. Left: close-up of an adult lower leg with a mild temporary sock indentation and slight puffiness, realistic and non-dramatic. Center: a stable soft body contour on an adult thigh under neutral flat light, no before-after implication. Right: macro of normal skin under raking side light with temporary surface shine. Three distinct observable phenomena, consistent neutral setting, no anatomy, no cross-section, no medical diagram, no product, no body transformation, no watermark.",
            })
        elif any(term in low for term in ("diagramas abstractos", "anatomía o comparación visual suficiente", "no muestra anatomía", "sin anatomía", "sólo muestra tarjetas", "solo muestra tarjetas", "demasiado abstracta", "esquema/card", "comparación o evidencia visual")) and (
            str(current.get("uiTemplate") or "") == "body-distinction" or ("grasa" in low and "hinchazón" in low)
        ):
            patch.update({
                "proofKind": "comparison", "mediaNeedKind": "comparison", "route": "image_pair",
                "routePlan": ["image_pair", "cutout_motion", "omni"], "preferredMedium": "image_pair",
                "fallbackStrategy": "bounded-provider-search", "hybridTemplate": "comparison", "uiTemplate": "comparison",
                "uiVariant": "anatomy-contrast",
                "uiItems": ["HINCHAZÓN TEMPORAL", "GRASA SUBCUTÁNEA", "BRILLO SUPERFICIAL"],
                "uiValues": ["VA Y VIENE", "TEJIDO DEBAJO", "NO ES MENOS GRASA"],
                "screenCopy": "NO LOS CONFUNDAS", "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0,
                "temporalAction": "multi_step", "movingVisualRequired": True,
                "forbiddenSubstitutions": ["motion-card", "text-only-ui"],
                "prompt": "Landscape 16:9 medical editorial comparison, no person and no face. Left: clean anatomical skin cross-section showing temporary superficial fluid swelling and surface light reflection, labeled areas left blank for later overlay. Right: clean anatomical cross-section showing distinct subcutaneous fat lobules below dermis. Accurate educational anatomy, realistic tissue colors, no grotesque detail, no before-after body transformation, no text, no logo.",
            })
        elif any(term in low for term in ("piel más luminosa", "piel mas luminosa", "luminosidad superficial", "segundo contraste exigido")) and any(term in low for term in ("grasa", "tejido adiposo")):
            patch.update({
                "proofKind": "comparison", "mediaNeedKind": "comparison", "route": "ui", "routePlan": ["ui"],
                "preferredMedium": "ui", "fallbackStrategy": "deterministic-ui", "requiresReadableData": False,
                "uiTemplate": "body-distinction", "uiVariant": "surface-swelling-fat",
                "uiItems": ["PIEL LUMINOSA", "HINCHAZÓN", "GRASA"],
                "uiValues": ["BRILLO SUPERFICIAL", "TEMPORAL", "SUBCUTÁNEA"],
                "screenCopy": "NO LOS CONFUNDAS", "temporalAction": "multi_step", "movingVisualRequired": True,
                "requiredEvidence": "An animated three-part distinction shows superficial skin luminosity, temporary swelling and subcutaneous fat as separate phenomena; brighter skin never implies less fat.",
                "forbiddenSubstitutions": ["generic-card", "missing-surface-shine", "body-before-after"],
            })
        elif any(term in low for term in ("efecto de la luz", "cierta luz", "cambio de iluminación")) or (
            "contraste narrado" in low and any(term in low for term in ("luz", "iluminación", "iluminacion", "brillo"))
        ):
            patch.update({
                "proofKind": "comparison", "mediaNeedKind": "comparison", "route": "image_pair",
                "routePlan": ["image_pair", "cutout_motion", "omni"], "preferredMedium": "image_pair",
                "fallbackStrategy": "bounded-provider-search", "hybridTemplate": "comparison", "uiTemplate": "comparison",
                "uiItems": ["LUZ PLANA", "LUZ LATERAL"], "uiValues": ["MISMA PIEL", "OTRO BRILLO"],
                "screenCopy": "LA LUZ CAMBIA TODO", "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0,
                "temporalAction": "multi_step", "movingVisualRequired": True,
                "forbiddenSubstitutions": ["motion-card", "text-only-ui"],
                "prompt": "Landscape 16:9 controlled macro comparison of the exact same adult lower leg skin area, no face and no identifiable person. Left: flat soft frontal light showing neutral skin texture. Right: raking side light on the identical marked area creating more shine and apparent smoothness. Same camera, distance, posture and skin; no body-shape change, no product claim, no text.",
            })
        elif any(term in low for term in ("anatom", "piel/grasa", "hinchazón temporal", "tejido adiposo", "grasa está bajo la piel", "grasa esta bajo la piel", "grasa está debajo", "grasa esta debajo")):
            body_distinction = any(term in low for term in ("hinchazón", "piel luminosa", "contraste visual entre conceptos"))
            patch.update({
                "proofKind": "comparison" if body_distinction else "physiological_mechanism",
                "mediaNeedKind": "comparison" if body_distinction else "physiological_mechanism",
                "route": "image",
                "routePlan": ["image", "omni"],
                "preferredMedium": "image",
                "fallbackStrategy": "bounded-provider-search",
                "requiresReadableData": False,
                "uiTemplate": "body-distinction" if body_distinction else "anatomy-explainer",
                "hybridTemplate": "body-distinction" if body_distinction else "anatomy-explainer",
                "uiItems": ["PIEL", "HINCHAZÓN", "GRASA"] if body_distinction else ["CREMA", "PIEL", "GRASA"],
                "uiValues": ["SUPERFICIE", "TEMPORAL", "SUBCUTÁNEA"] if body_distinction else ["SUPERFICIE", "BARRERA", "DEBAJO"],
                "screenCopy": "NO LOS CONFUNDAS" if body_distinction else "LA GRASA ESTÁ DEBAJO",
                "temporalAction": "multi_step",
                "movingVisualRequired": True,
                "evidenceMustRemainDominant": True,
                "forbiddenSubstitutions": ["ui", "motion-card", "text-only-ui", "wireframe-diagram"],
            })
        elif str(current.get("proofKind") or current.get("mediaNeedKind") or "") == "product_inspection" and any(term in low for term in ("ui-card sustituye", "motion-card sustituye", "depende demasiado del texto", "principalmente una motion-card")) and any(term in low for term in ("envase", "etiqueta", "packaging", "claim")) and not any(term in low for term in ("irritación", "irritante", "reacción", "suspende", "suspenderlo")):
            claim_compare = any(term in low for term in ("promesa vs evidencia", "comparación", "claim responsable", "responsable/exagerado"))
            patch.update({
                "proofKind": "product_inspection", "mediaNeedKind": "product_inspection",
                "route": "image", "routePlan": ["image", "ui"], "preferredMedium": "image",
                "fallbackStrategy": "deterministic-ui", "requiresReadableData": False,
                "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0, "evidenceMustRemainDominant": True,
                "compositionStyle": "dual-package-contrast" if claim_compare else "single-package-macro",
                "screenCopy": "PROMESA VS EVIDENCIA" if claim_compare else "MIRA EL CLAIM",
                "forbiddenSubstitutions": ["motion-card", "text-only-ui", "blank-packaging", "fine-print", "gibberish-label"],
                "prompt": (
                    "Landscape 16:9 premium editorial close-up of two fictional body-cream packages side by side, both front-facing and filling the frame. Left package label contains ONLY the large readable Spanish lines LUMERA / PROMESA EXAGERADA / ELIMINA GRASA / 200 ML. Right package label contains ONLY LUMERA / PROMESA RESPONSABLE / MEJORA APARIENCIA Y TEXTURA / 200 ML. No fine print, no side label, no other words, no logo symbol, no trademark, no blank packaging. Realistic paper labels and open cream jar, warm natural bathroom light."
                    if claim_compare else
                    "Landscape 16:9 premium editorial macro of one fictional body-cream jar and matching carton, front-facing and filling the frame. The carton label contains ONLY these large readable Spanish lines: LUMERA / MENOS CENTÍMETROS? / TIEMPO: NO ACLARA / USO: MASAJE DIARIO / LÍMITE: NO REDUCE GRASA / 200 ML. No fine print, no side label, no other words, no logo symbol, no trademark, no blank packaging. Open jar with thick white cream visible, realistic paper and glass, warm natural bathroom light."
                ),
                "hookRequirement": (
                    "Deben verse dos envases de crema corporal ocupando el plano, con claims grandes y legibles: ELIMINA GRASA frente a MEJORA APARIENCIA Y TEXTURA. Rechaza texto pequeño, absurdo o marcas reales."
                    if claim_compare else
                    "Debe verse un close-up del envase y cartón de crema corporal con MENOS CENTÍMETROS?, TIEMPO: NO ACLARA, USO: MASAJE DIARIO y LÍMITE: NO REDUCE GRASA legibles. Rechaza texto pequeño, absurdo o marcas reales."
                ),
            })
        elif any(term in low for term in ("retiene el dinero", "retener dinero", "acción de compra", "decisión de compra", "purchase-decision", "purchase decision visual contrast", "exaggerated claim", "measured checklist")):
            patch.update({
                "proofKind": "exact_ui_state", "mediaNeedKind": "exact_ui_state",
                "route": "ui", "routePlan": ["ui"], "preferredMedium": "ui",
                "fallbackStrategy": "deterministic-ui", "requiresReadableData": True,
                "uiTemplate": "comparison", "uiVariant": "claim-evidence",
                "uiItems": ["CLAIM", "EVIDENCIA", "DECISIÓN"],
                "uiValues": ["REDUCE CENTÍMETROS", "NO REDUCE GRASA", "NO COMPRES"],
                "screenCopy": "NO PAGUES LA PROMESA",
                "requiredEvidence": "A deterministic claim-versus-evidence purchase panel visibly ends in the decision NO COMPRES.",
                "forbiddenSubstitutions": ["generic-card", "missing-decision"],
            })
        elif any(term in low for term in ("same skin area comparison", "exact same skin area", "mismo área", "misma zona", "contour visible on both sides", "contorno permanezca igual")) and str(current.get("shotId") or ""):
            patch.update({
                "proofKind": "comparison", "mediaNeedKind": "comparison",
                "route": "image_pair", "routePlan": ["image_pair", "cutout_motion", "omni"],
                "preferredMedium": "image_pair", "fallbackStrategy": "bounded-provider-search",
                "hybridTemplate": "comparison", "uiTemplate": "comparison", "uiVariant": "controlled-same-area",
                "reuseLeftPanel": True, "surfaceSheenRight": True,
                "uiItems": ["MISMA ZONA", "MÁS HIDRATADA"],
                "uiValues": ["MISMO CONTORNO", "SOLO SUPERFICIE"],
                "screenCopy": "BENEFICIO REALISTA", "temporalAction": "multi_step", "movingVisualRequired": True,
                "requiredEvidence": "The exact same skin area and contour appear on both sides; only surface hydration and sheen change.",
                "forbiddenSubstitutions": ["different-person", "different-body-part", "body-shape-change"],
                "fictionalLabel": "LUMERA",
                "prompt": "Landscape 16:9 controlled split-screen documentary macro of the EXACT SAME marked forearm skin area, no face. Preserve the same small freckle, two tiny non-text alignment marks, camera distance, flat neutral light, gray reference card at frame edge, background and arm contour in both panels. Left panel: baseline skin is clean, matte and untreated. Right panel: the identical marked area shortly after body cream, with only a subtle hydrated surface sheen; every freckle, contour and scale remains in the same position. No hand applying product, no body transformation, no slimming, no anatomy, no text, no logo, no package.",
                "temporalEvidenceMode": "initial_final",
            })
        elif any(term in low for term in ("lista de ingredientes", "ingredient list", "panel de uso", "ingredientes y panel")) and any(term in current_context for term in ("regla de compra", "ingredientes", "tolerancia")):
            patch.update({
                "proofKind": "exact_ui_state", "mediaNeedKind": "exact_ui_state",
                "route": "ui", "routePlan": ["ui"], "preferredMedium": "ui",
                "fallbackStrategy": "deterministic-ui", "requiresReadableData": True,
                "uiTemplate": "product-label", "uiVariant": "purchase-checklist",
                "uiItems": ["PROMESA", "INGREDIENTES", "TIEMPO", "TOLERANCIA"],
                "uiValues": ["¿QUÉ CAMBIA?", "LISTA LEGIBLE", "PLAZO REALISTA", "PRUEBA EN ZONA"],
                "screenCopy": "REGLA DE COMPRA",
                "requiredEvidence": "A deterministic purchase checklist visibly separates promise, identifiable ingredients, realistic timing and skin tolerance without inventing a formula.",
                "forbiddenSubstitutions": ["invented-ingredients", "fake-product-label", "generic-card"],
            })
        elif any(term in low for term in ("falta la cuarta", "cuarta dimensión", "cuarta dimension", "tolerancia/tu piel")) and (
            str(current.get("uiTemplate") or "") == "product-label"
            or any(term in low for term in ("checklist requerida", "cuarta dimensión de tolerancia"))
        ):
            patch.update({
                "proofKind": "exact_ui_state", "mediaNeedKind": "exact_ui_state",
                "route": "ui", "routePlan": ["ui"], "preferredMedium": "ui",
                "fallbackStrategy": "deterministic-ui", "requiresReadableData": True,
                "uiTemplate": "product-label", "uiVariant": "purchase-checklist",
                "uiItems": ["PROMESA", "INGREDIENTES", "TIEMPO", "TOLERANCIA"],
                "uiValues": ["¿QUÉ CAMBIA?", "LISTA LEGIBLE", "PLAZO REALISTA", "PRUEBA EN ZONA"],
                "screenCopy": "REGLA DE COMPRA",
                "requiredEvidence": "All four purchase dimensions are visible together: promise, ingredients, realistic timing and skin tolerance.",
                "forbiddenSubstitutions": ["three-item-list", "generic-card", "new-presenter-anchor"],
            })
        elif "no compres" in current_context and any(term in low for term in ("envase", "etiqueta", "packaging")):
            # The decision panel is already the correct evidence. A label-quality
            # rejection must repair how the product is framed, not replace the
            # purchase decision with a generic package checklist.
            patch.update({
                "proofKind": "exact_ui_state", "mediaNeedKind": "exact_ui_state",
                "route": "ui", "routePlan": ["ui"], "preferredMedium": "ui",
                "fallbackStrategy": "deterministic-ui", "requiresReadableData": True,
                "uiTemplate": "comparison", "uiVariant": "claim-evidence",
                "uiItems": ["CLAIM", "EVIDENCIA", "DECISIÓN"],
                "uiValues": ["REDUCE CENTÍMETROS", "NO REDUCE GRASA", "NO COMPRES"],
                "screenCopy": "NO PAGUES LA PROMESA",
                "requiredEvidence": "A deterministic claim-versus-evidence purchase panel visibly ends in the decision NO COMPRES.",
                "forbiddenSubstitutions": ["generic-card", "missing-decision"],
            })
        elif "same skin area" in current_context and any(term in low for term in ("envase", "etiqueta", "packaging")):
            # Packaging is incidental in this beat. Remove it from the visible
            # proof instead of converting a skin comparison into product UI.
            patch.update({
                "proofKind": "comparison", "mediaNeedKind": "comparison",
                "route": "image_pair", "routePlan": ["image_pair", "cutout_motion", "omni"],
                "preferredMedium": "image_pair", "fallbackStrategy": "bounded-provider-search",
                "hybridTemplate": "comparison", "uiTemplate": "comparison", "uiVariant": "controlled-same-area",
                "reuseLeftPanel": True, "surfaceSheenRight": True,
                "uiItems": ["MISMA ZONA", "MÁS HIDRATADA"],
                "uiValues": ["MISMO CONTORNO", "SOLO SUPERFICIE"],
                "screenCopy": "BENEFICIO REALISTA", "temporalAction": "multi_step", "movingVisualRequired": True,
                "requiredEvidence": "The exact same skin area and contour appear on both sides; only surface hydration and sheen change.",
                "forbiddenSubstitutions": ["different-person", "different-body-part", "body-shape-change", "visible-packaging"],
                "prompt": "Landscape 16:9 controlled split-screen documentary macro of the EXACT SAME marked forearm skin area, no face. Preserve the same small freckle, two tiny non-text alignment marks, camera distance, flat neutral light, gray reference card at frame edge, background and arm contour in both panels. Left panel: baseline skin is clean, matte and untreated. Right panel: the identical marked area shortly after body cream, with only a subtle hydrated surface sheen; every freckle, contour and scale remains in the same position. No hand applying product, no body transformation, no slimming, no anatomy, no text, no logo, no package.",
                "temporalEvidenceMode": "initial_final",
            })
        elif any(term in low for term in ("envase", "etiqueta", "packaging", "claim legible")) and not any(term in low for term in ("frasco genérico", "envase resulta ambiguo", "no un cosmético tópico", "gotero", "serum", "sérum", "irritación", "irritante", "ardor", "reacción", "suspende", "suspenderlo", "acción de suspender", "acción de apartarlo", "cuatro preguntas", "4 preguntas")):
            variant = "claim-evidence" if any(term in low for term in ("promesa vs evidencia", "comparar promesa", "etiqueta responsable", "promesa a revisar", "promesa revisa", "claim del producto")) else "package-claims"
            patch.update({
                "proofKind": "product_inspection",
                "mediaNeedKind": "product_inspection",
                "route": "ui",
                "routePlan": ["ui"],
                "preferredMedium": "ui",
                "fallbackStrategy": "deterministic-ui",
                "requiresReadableData": True,
                "uiTemplate": "product-inspection",
                "uiVariant": variant,
                "uiItems": ["CLAIM COMERCIAL", "LO QUE NO HACE", "LO QUE SÍ HACE"] if variant == "claim-evidence" else ["CLAIM DEL ENVASE", "TIEMPO", "MODO DE USO", "LÍMITE"],
                "uiValues": ["REDUCE CENTÍMETROS", "NO REDUCE GRASA", "HIDRATA SUPERFICIE"] if variant == "claim-evidence" else ["¿MENOS CM?", "NO LO ACLARA", "MASAJE DIARIO", "NO REDUCE GRASA"],
                "backgroundSource": product_source,
                "backgroundMediaType": product_type,
                "screenCopy": "PROMESA VS EVIDENCIA" if variant == "claim-evidence" else "MIRA EL ENVASE",
                "forbiddenSubstitutions": ["motion-card", "blank-packaging"],
            })
        elif any(term in low for term in ("gotero", "serum", "sérum", "cosmético facial distinto", "producto central del video")) and not all(
            term in current_context for term in ("textura", "hidratación", "comodidad")
        ):
            patch.update({
                "proofKind": "comparison",
                "mediaNeedKind": "comparison",
                "route": "image_pair",
                "routePlan": ["image_pair", "cutout_motion", "omni"],
                "preferredMedium": "image_pair",
                "fallbackStrategy": "bounded-provider-search",
                "hybridTemplate": "comparison",
                "uiTemplate": "comparison",
                "uiVariant": "surface-vs-permanent",
                "uiItems": ["SUPERFICIE HIDRATADA", "GRASA SIN CAMBIO"],
                "uiValues": ["EFECTO TEMPORAL", "NO TRANSFORMACIÓN"],
                "screenCopy": "NO ES PERMANENTE",
                "peoplePolicy": "forbidden",
                "maxFaceAreaRatio": 0.0,
                "temporalAction": "multi_step",
                "movingVisualRequired": True,
                "forbiddenSubstitutions": ["serum", "dropper", "face-collage", "motion-card", "text-only-ui"],
                "prompt": "Landscape 16:9 controlled two-panel body-care demonstration, no face. Left: close-up of an adult thigh with a pea-sized amount of thick white LUMERA body cream from an open wide jar, showing only temporary hydrated surface sheen. Right: accurate clean cross-section of skin beneath the same area with the subcutaneous fat layer visibly unchanged. No body transformation, no facial skincare, no serum, no dropper, no pump bottle, no text, no logo.",
                "hookRequirement": "Debe verse crema corporal espesa aplicada en muslo o brazo y un contraste inequívoco entre hidratación superficial temporal y grasa subcutánea sin cambio. Rechaza rostro, sérum, gotero y cosmética facial.",
            })
        elif any(term in low for term in ("misma cantidad", "zona pequeña", "tomar una foto", "toma una foto", "fotografiar", "foto 'antes'", "foto antes", "mostrar la acción")) and not all(term in low for term in ("luz", "distancia", "postura")):
            patch.update({
                "proofKind": "human_action",
                "mediaNeedKind": "human_action",
                "route": "image_pair",
                "routePlan": ["image_pair", "cutout_motion", "omni"],
                "preferredMedium": "image_pair",
                "fallbackStrategy": "bounded-provider-search",
                "hybridTemplate": "process-steps",
                "uiTemplate": "process-steps",
                "uiVariant": "controlled-test",
                "uiItems": ["MISMA CANTIDAD", "ZONA PEQUEÑA", "FOTO ANTES"],
                "uiValues": ["MIDE", "APLICA", "REGISTRA"],
                "screenCopy": "PRUEBA CONTROLADA",
                "temporalAction": "multi_step",
                "movingVisualRequired": True,
                "peoplePolicy": "contextual",
                "compositionStyle": "controlled-test-sequence",
                "forbiddenSubstitutions": ["motion-card", "text-only-ui"],
                "prompt": "Landscape 16:9 split-screen documentary close-up, no face. Left panel: a fingertip holds one clearly visible pea-sized dab of thick white cream beside an open wide jar labeled LUMERA CREMA CORPORAL 200 ML; a small square test zone is marked on the forearm. Right panel: a smartphone camera photographs that exact clean marked zone before application, with the same jar and lighting visible. Hands and measurable actions dominate. No serum, no dropper, no pump bottle, no blank container, no real logo, no text outside the fictional jar label.",
            })
        elif all(term in low for term in ("luz", "distancia", "postura")) or "procedimiento comparativo" in low or any(term in low for term in ("guías de alineación", "guias de alineacion", "mismo encuadre", "interfaz determinista de cámara", "interfaz determinista de camara", "mockup de cámara", "mockup de camara", "rejilla", "horizonte")):
            patch.update({
                "proofKind": "comparison",
                "mediaNeedKind": "comparison",
                "route": "image",
                "routePlan": ["image", "omni"],
                "preferredMedium": "image",
                "fallbackStrategy": "bounded-provider-search",
                "requiresReadableData": False,
                "compositionStyle": "protocol-measurement-diagram",
                "continuityGroup": "%s-measurement-protocol" % str(label or "protocol").lower(),
                "continuityLock": "same camera, fixed 45-degree light, 2.0-meter marks and identical posture",
                "uiTemplate": "process-steps",
                "hybridTemplate": "process-steps",
                "uiVariant": "protocol-diagram",
                "uiItems": ["LUZ FIJA", "DISTANCIA", "POSTURA"],
                "uiValues": ["45°", "2,0 M", "MISMA MARCA"],
                "screenCopy": "REPLICA EL ENCUADRE",
                "temporalAction": "multi_step",
                "movingVisualRequired": True,
                "peoplePolicy": "contextual",
                "maxFaceAreaRatio": 0.12,
                "evidenceMustRemainDominant": True,
                "forbiddenSubstitutions": ["ui", "motion-card", "text-only-ui", "wireframe-diagram", "unmeasured-photo-pair", "different-people"],
                "requiredEvidence": "Instructional protocol visibly marks the fixed 45-degree light, 2.0-meter camera distance, camera and subject floor marks, and identical repeated posture.",
                "prompt": "Landscape 16:9 premium editorial photograph of a standardized body-comparison setup in a clean neutral studio. A real camera on a tripod, a fixed soft light at 45 degrees, discreet floor distance markers, and an adult woman standing naturally in the same marked position. Wide side view, all equipment visible, face not identifiable, realistic proportions, no text, no logos, no wireframe, no diagram.",
            })
        elif any(term in low for term in ("evitar pagar", "resultado que el producto no puede cumplir", "gasto")):
            patch.update({
                "proofKind": "exact_ui_state", "mediaNeedKind": "exact_ui_state", "route": "ui", "routePlan": ["ui"],
                "preferredMedium": "ui", "fallbackStrategy": "deterministic-ui", "requiresReadableData": True,
                "uiTemplate": "comparison", "uiVariant": "claim-evidence",
                "uiItems": ["CLAIM COMERCIAL", "LO QUE NO HACE", "LO QUE SÍ HACE"],
                "uiValues": ["REDUCE CENTÍMETROS", "NO REDUCE GRASA", "HIDRATA SUPERFICIE"],
                "screenCopy": "NO PAGUES LA PROMESA", "forbiddenSubstitutions": ["motion-card", "blank-packaging"],
            })
        elif any(term in low for term in ("gotero", "serum", "sérum", "cosmética facial", "cosmetica facial", "envase en blanco")) and all(
            term in current_context for term in ("textura", "hidratación", "comodidad")
        ):
            patch.update({
                "proofKind": "exact_ui_state", "mediaNeedKind": "exact_ui_state",
                "route": "ui", "routePlan": ["ui"], "preferredMedium": "ui",
                "fallbackStrategy": "deterministic-ui", "requiresReadableData": True,
                "uiTemplate": "evaluation-dashboard", "uiVariant": "evaluation-grid",
                "uiItems": ["TEXTURA", "HIDRATACIÓN", "COMODIDAD"],
                "uiValues": ["OBSERVA", "COMPARA", "ANOTA"],
                "screenCopy": "SEPÁRALO EN 3", "temporalAction": "multi_step",
                "movingVisualRequired": True, "peoplePolicy": "forbidden", "maxFaceAreaRatio": 0.0,
                "continuityGroup": "%s-evaluation-method" % str(label or "evaluation").lower(),
                "continuityLock": "same light, camera angle and distance across all three observations",
                "forbiddenSubstitutions": ["face", "serum", "dropper", "food-shopping", "generic-stock", "single-label"],
                "requiredEvidence": "Instructional dashboard separates skin texture, hydration and comfort while fixing light, camera angle and distance.",
                "prompt": "Deterministic animated evaluation dashboard with large readable labels for texture, hydration and comfort, plus a fixed-light, fixed-angle and fixed-distance protocol.",
            })
        elif any(term in low for term in ("frasco genérico", "envase resulta ambiguo", "no un cosmético tópico", "etiqueta pequeña", "irritación es débil", "reacción persistente", "reacción al producto", "acción de suspender", "acción de apartarlo", "producto irritante", "suspenderlo", "ardor", "acción completa requerida", "persistencia verificable", "secuencia realista inequívoca", "aplicar crema, notar")):
            patch.update({
                "proofKind": "human_action",
                "mediaNeedKind": "human_action",
                "route": "image_pair",
                "routePlan": ["image_pair", "cutout_motion", "omni"],
                "preferredMedium": "image_pair",
                "fallbackStrategy": "bounded-provider-search",
                "hybridTemplate": "process-steps",
                "uiTemplate": "process-steps",
                "uiVariant": "safety-sequence",
                "uiItems": ["APLICA", "OBSERVA", "IRRITA", "SUSPENDE"],
                "uiValues": ["USO", "REVISA", "ROJEZ", "APARTA"],
                "screenCopy": "SI IRRITA, SUSPENDE",
                "peoplePolicy": "contextual",
                "detailSalience": "incidental",
                "compositionStyle": "reaction-action-sequence",
                "temporalAction": "multi_step",
                "movingVisualRequired": True,
                "requiredEvidence": "A four-state visual sequence shows topical application, observation, visible irritation and immediate discontinuation with the jar moved away.",
                "forbiddenSubstitutions": ["pump-bottle", "dropper", "serum", "blank-package", "missing-discontinuation-action"],
                "prompt": "Landscape 16:9 two-panel editorial health demonstration with the same adult woman and table. Left: mild visible redness on forearm beside an OPEN WIDE BODY-CREAM JAR with thick white cream visible. Right: her hand clearly pushes that same jar away. Use a plausible non-blank fictional body-cream label; LUMERA CREMA CORPORAL is preferred, but minor lettering variation is acceptable when the label is secondary and not salient. No pump bottle, no dropper, no serum, no supplement, no blank packaging, no real trademark.",
                "hookRequirement": "Debe verse inequívocamente un tarro ancho abierto de crema corporal espesa, con una etiqueta ficticia plausible y no vacía, mientras la persona lo aparta por irritación. El texto exacto de la marca no bloquea si es un detalle secundario; sí bloquean dispensadores, goteros, sérums, envases en blanco o la ausencia de la acción de suspender.",
            })
        elif any(term in low for term in ("cuatro preguntas", "4 preguntas", "solo muestra el rótulo", "falta la cuarta sobre tolerancia")):
            patch.update({
                "proofKind": "exact_ui_state", "mediaNeedKind": "exact_ui_state", "route": "ui", "routePlan": ["ui"],
                "preferredMedium": "ui", "fallbackStrategy": "deterministic-ui", "requiresReadableData": True,
                "screenCopy": "4 PREGUNTAS", "presenterAllowed": False, "peoplePolicy": "forbidden",
                "evidenceMustRemainDominant": True, "uiTemplate": "process-steps", "uiVariant": "four-questions",
                "uiItems": ["¿QUÉ PROMETE?", "¿QUÉ CONTIENE?", "¿EN CUÁNTO TIEMPO?", "¿TU PIEL LO TOLERA?"],
                "uiValues": ["PROMESA", "INGREDIENTES", "PLAZO", "TOLERANCIA"],
                "requiredEvidence": "Shows all four purchase questions explicitly in one deterministic animated process.",
                "forbiddenSubstitutions": ["single-label", "generic-motion-card", "new-presenter-anchor"],
            })
        elif any(term in low for term in ("repetición evidente", "mismo modelo", "misma persona/locación", "beneficio específico narrado", "mejora de apariencia y comodidad", "mejora realista en apariencia", "comodidad tras el uso", "same person observing", "después del producto", "tocando la zona tratada")):
            patch.update({
                "proofKind": "comparison",
                "mediaNeedKind": "comparison",
                "route": "image_pair",
                "routePlan": ["image_pair", "cutout_motion", "omni"],
                "preferredMedium": "image_pair",
                "fallbackStrategy": "bounded-provider-search",
                "hybridTemplate": "comparison",
                "uiTemplate": "comparison", "uiVariant": "controlled-same-person",
                "reuseLeftPanel": True, "surfaceSheenRight": True,
                "uiItems": ["MÁS HIDRATADA", "MÁS CÓMODA"],
                "uiValues": ["SUPERFICIE", "SENSACIÓN"],
                "screenCopy": "BENEFICIO REALISTA",
                "peoplePolicy": "contextual",
                "maxFaceAreaRatio": 0.18,
                "requiresVisibleFace": True,
                "requiredEvidence": "The same adult woman visibly evaluates the same treated forearm before and after; only surface hydration, appearance and comfort improve, never body volume or fat.",
                "forbiddenSubstitutions": ["skin-crop-without-person", "no-visible-evaluation", "different-person", "body-shape-change"],
                "prompt": "Landscape 16:9 controlled documentary comparison of the SAME Hispanic woman age 45 to 55 in the same room, clothing, camera, light and posture. Her face and the same marked forearm must both be clearly visible in each state; never use an isolated skin crop. An OPEN WIDE BODY-CREAM JAR labeled LUMERA CREMA CORPORAL 200 ML, with thick white cream visible, must remain secondary but clearly identifiable in both states. Never substitute a pump bottle, dispenser, dropper, tube, serum, blank package or real trademark. Left: she visibly evaluates that forearm before body cream, looking at it with a neutral expression; skin is slightly dry and matte. Right: she visibly evaluates the identical forearm after the cream, gently touching it with a subtle relieved, comfortable expression; the surface looks softly hydrated while arm contour and body volume remain exactly unchanged. No slimming claim, no body-shape change, no exaggerated beauty retouching.",
            })
        elif any(term in low for term in (
            "sigue con este video", "título ni un id verificado", "titulo ni un id verificado",
            "lacks the verified", "missing verified", "catalog identity", "identidad de catálogo",
            "identidad de catalogo", "cierre vago", "id verificado", "título verificado", "titulo verificado",
        )):
            patch.update({
                "ctaAnchor": True,
            })
        else:
            continue
        patch = _enforce_temporal_repair_media(current, patch)
        patches[label] = patch
    payload = {
        "policy": DRAFT_REPAIR_POLICY_VERSION,
        "attempt": attempt,
        "expiresAfterAttempt": 1,
        "scriptHash": str(plan.get("scriptHash") or data.get("script_hash") or ""),
        "designProfileId": str(plan.get("designProfileId") or ""),
        "sourcePlanHash": source_plan_hash,
        "sourceReviewHash": source_review_hash,
        "source_review": str(paths["work"] / "07b_draft_avatar_review.json"),
        "patches": patches,
    }
    write_json(existing_path, payload)
    return _apply_draft_repair_specs(plan, payload)


def run_paths(data: dict[str, Any]) -> dict[str, pathlib.Path]:
    rid = data["run_id"]
    work = RUNS_ROOT / rid
    public = PUBLIC_ROOT / rid
    out = OUT_ROOT / rid
    for path in (work, public, out, work / "voice", work / "plans", work / "reviews", public / "assets", public / "audio", out / "chapters"):
        path.mkdir(parents=True, exist_ok=True)
    return {"work": work, "public": public, "out": out}


def reset_visual_plan_for_global_replan(paths: dict[str, pathlib.Path], reason: str) -> None:
    archive = paths["work"] / "plans" / ("global-replan-%d" % int(time.time()))
    archive.mkdir(parents=True, exist_ok=True)
    names = (
        "03_visual_plan.json",
        "03_visual_plan_invalid.json",
        "04_assets_manifest.json",
        "04_evidence_set_qa.json",
        "04_provider_summary.json",
        "04_scene_decisions.json",
        "05_resolved_plan.json",
        "06_plan_qa.json",
        "07b_draft_avatar_review.json",
        "07c_draft_repair_plan.json",
        "longform-props.json",
    )
    for name in names:
        source = paths["work"] / name
        if not source.is_file():
            continue
        shutil.copy2(source, archive / name)
        source.unlink()
    write_json(archive / "reason.json", {"reason": reason, "createdAt": int(time.time())})


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and exit_code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def run_lock(paths: dict[str, pathlib.Path], stage: str):
    lock = paths["work"] / "pipeline.lock"
    payload = {"pid": os.getpid(), "stage": stage}
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            break
        except FileExistsError:
            try:
                existing = read_json(lock)
            except Exception:
                existing = {}
            if _pid_alive(int(existing.get("pid") or 0)):
                raise RuntimeError("run_id ocupado por pid=%s stage=%s" % (existing.get("pid"), existing.get("stage")))
            lock.unlink(missing_ok=True)
    else:
        raise RuntimeError("no se pudo adquirir lock de corrida")
    try:
        yield
    finally:
        try:
            existing = read_json(lock)
            if int(existing.get("pid") or 0) == os.getpid():
                lock.unlink(missing_ok=True)
        except Exception:
            pass


def record_state(paths: dict[str, pathlib.Path], stage: str, ok: bool, detail: str) -> None:
    path = paths["work"] / "pipeline_state.json"
    state = read_json(path) if path.exists() else {"history": [], "status": "running"}
    state["history"].append({"stage": stage, "ok": ok, "detail": str(detail)[:500]})
    state["status"] = "ready" if ok and stage == "qa" else ("failed" if not ok else "running")
    write_json(path, state)


def ffprobe(path: pathlib.Path) -> dict[str, Any]:
    command = [media_tools.find_binary("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
    if result.returncode:
        raise RuntimeError("ffprobe fallo para %s: %s" % (path, result.stderr[-300:]))
    data = json.loads(result.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    rate = str(video.get("r_frame_rate") or "0/1")
    num, den = (rate.split("/", 1) + ["1"])[:2]
    return {
        "duration_ms": round(float((data.get("format") or {}).get("duration") or 0) * 1000),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": float(num) / max(1.0, float(den)),
        "has_audio": bool(audio),
    }


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def has_mojibake(value: Any) -> bool:
    text = str(value or "")
    return any(marker in text for marker in ("Ã", "Â", "â€", "â€™", "�"))


def compact_pexels_query(value: str, shot: dict[str, Any] | None = None) -> str:
    """Pexels works best with broad stock concepts, not narrated sentences."""
    raw = str(value or "").strip().lower()
    if raw and len(re.findall(r"[a-z]+", raw)) <= 8:
        return raw
    context = " ".join([
        raw,
        str((shot or {}).get("visualProof") or ""),
        str((shot or {}).get("prompt") or ""),
        str((shot or {}).get("tts") or ""),
    ]).lower()
    families = [
        (("label", "etiqueta", "ingredient", "ingrediente", "envase", "package"), "body lotion label"),
        (("cream", "crema", "skincare", "retinol", "cafeína", "caffeine"), "body cream skincare"),
        (("calendar", "month", "meses", "semanas"), "calendar months passing"),
        (("photo", "foto", "camera", "cámara", "postura", "distance", "distancia"), "woman taking progress photo"),
        (("irritation", "irritación", "patch", "reacción", "reaction"), "skin patch test"),
        (("asthma", "asma", "inhaler"), "woman using inhaler"),
        (("shopping", "compra", "store", "tienda"), "woman comparing skincare products"),
        (("skin", "piel", "cellulite", "celulitis", "fat", "grasa"), "body skincare application"),
    ]
    for terms, query in families:
        if any(term in context for term in terms):
            return query
    return "skincare product routine"


def visual_fingerprints(path: pathlib.Path, media_type: str) -> list[int]:
    """Small dHashes catch re-encoded excerpts of the same stock shot."""
    fractions = (0.2, 0.5, 0.8) if media_type == "video" else (0.0,)
    duration = ffprobe(path)["duration_ms"] / 1000 if media_type == "video" else 0.0
    hashes: list[int] = []
    for fraction in fractions:
        command = [media_tools.find_binary("ffmpeg"), "-v", "error"]
        if media_type == "video":
            command += ["-ss", "%.3f" % max(0.05, duration * fraction)]
        command += ["-i", str(path), "-vf", "scale=9:8,format=gray", "-frames:v", "1", "-f", "rawvideo", "-"]
        result = subprocess.run(command, capture_output=True, env=subprocess_env())
        pixels = result.stdout
        if result.returncode or len(pixels) < 72:
            continue
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | int(pixels[y * 9 + x] > pixels[y * 9 + x + 1])
        hashes.append(bits)
    return hashes


def perceptual_duplicate(candidate: list[int], accepted: list[tuple[str, list[int]]], threshold: int = 10) -> str:
    for shot_id, known in accepted:
        if any((left ^ right).bit_count() <= threshold for left in candidate for right in known):
            return shot_id
    return ""


def provider_fingerprints(path: pathlib.Path, media_type: str, provider: Any) -> list[int]:
    if getattr(provider, "mode", "") == "mock":
        return [int(sha256(path)[:16], 16)]
    return visual_fingerprints(path, media_type)


def stage_validate(input_path: pathlib.Path) -> dict[str, Any]:
    data = load_approved_script(input_path)
    data["_input_dir"] = str(input_path.parent)
    if production_mode() and str(data.get("schema_version") or "") == "1.2":
        from engine.cta_resolver import verify_cta

        expected = data.get("cta") or {}
        verified = verify_cta(expected)
        if str(verified.get("target_channel_id") or "") != str(expected.get("target_channel_id") or ""):
            raise RuntimeError("CTA cambio de canal entre aprobacion y produccion")
        data["cta"] = verified
    missing_clips = []
    for clip in data.get("user_clips") or []:
        raw = pathlib.Path(str(clip["path"]))
        source = raw if raw.is_absolute() else input_path.parent / raw
        if not source.is_file():
            missing_clips.append(str(source))
    if missing_clips:
        raise ValueError("clips del usuario no encontrados:\n- " + "\n- ".join(missing_clips))
    paths = run_paths(data)
    design_profile = resolve_design_profile(data, pathlib.Path(ROOT) / "work" / "design_profiles")
    data["_design_profile"] = design_profile
    data["_design_style_scope"] = design_prompt_scope(design_profile)
    write_json(paths["work"] / "00_design_profile.json", design_profile)
    locked_copy = paths["work"] / "approved_script.json"
    if locked_copy.exists():
        previous = read_json(locked_copy)
        if previous.get("script_hash") != data["script_hash"]:
            raise ValueError("run_id ya pertenece a otro script_hash; usa un run_id nuevo para no mezclar caches")
    if input_path.resolve() != locked_copy.resolve():
        shutil.copy2(input_path, locked_copy)
    report = {
        "status": "PASS",
        "run_id": data["run_id"],
        "script_hash": data["script_hash"],
        "chapters": len(data["chapters"]),
        "words": len(re.findall(r"\b\w+\b", full_script(data), re.UNICODE)),
        "script_locked": True,
        "design_profile_id": design_profile.get("id"),
        "design_source": design_profile.get("source"),
    }
    write_json(paths["work"] / "01_contract_validation.json", report)
    record_state(paths, "validate", True, "approved script locked")
    return data


def stage_provider_preflight(data: dict[str, Any]) -> dict[str, Any]:
    """Validate tools and real service readiness, auto-starting managed services."""
    paths = run_paths(data)
    mode = "real" if production_mode() else "mock"
    codex_home = pathlib.Path(os.environ.get("CODEX_HOME") or (pathlib.Path.home() / ".codex"))
    checks = {
        "ffmpeg": bool(media_tools.find_binary("ffmpeg", required=False)),
        "ffprobe": bool(media_tools.find_binary("ffprobe", required=False)),
        "node": bool(shutil.which("node")),
        "remotion_dependencies": (pathlib.Path(REMOTION_DIR) / "node_modules" / "@remotion").is_dir(),
        "elevenlabs": mode == "mock" or bool(os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID")),
        "clip_extractor_configured": bool(os.environ.get("CLIP_EXTRACTOR_BASE_URL", "http://100.121.147.73:8765")),
        "pexels_configured": bool(os.environ.get("PEXELS_API_KEY")),
        "codex_image_auth": (codex_home / "auth.json").is_file(),
        "gemini_omni_configured": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
        "kreado_configured": bool(os.environ.get("KREADO_BACKEND_URL", "http://localhost:8787")),
        "cutout_enabled": cutout_enabled(),
        "cutout_configured": bool(os.environ.get("CUTOUT_BASE_URL", "http://127.0.0.1:8000")),
    }
    report_path = paths["work"] / "00_provider_preflight.json"
    provider_states: dict[str, Any] = {}
    if mode == "real":
        provider_states = ProviderManager(paths["work"] / "provider_manager.json").ensure_all()
        checks["clip_extractor_healthy"] = provider_states.get("clip_extractor", {}).get("status") == "healthy"
        checks["kreado_healthy"] = provider_states.get("avatar", {}).get("status") == "healthy"
        checks["cutout_healthy"] = provider_states.get("cutout_motion", {}).get("status") == "healthy"
    signature = hashlib.sha256(json.dumps({"mode": mode, "checks": checks, "providers": provider_states}, sort_keys=True).encode("utf-8")).hexdigest()
    required = ["ffmpeg", "ffprobe", "node", "remotion_dependencies", "elevenlabs"]
    blockers = [name for name in required if not checks[name]]
    report = {
        "status": "FAIL" if blockers else "PASS",
        "mode": mode,
        "signature": signature,
        "checks": checks,
        "blockers": blockers,
        "providers": provider_states,
        "optional_ladder": {
            "clip_extractor": checks["clip_extractor_configured"],
            "pexels": checks["pexels_configured"],
            "image": checks["codex_image_auth"],
            "cutout_motion": checks["cutout_enabled"] and checks["cutout_configured"],
            "omni": checks["gemini_omni_configured"],
        },
        "note": "Preflight real: comprueba salud, intenta un arranque administrado y limpia circuitos al recuperarse. Proveedores opcionales no bloquean si existe una ruta compatible.",
    }
    write_json(report_path, report)
    record_state(paths, "preflight", not blockers, "mode=%s blockers=%s" % (mode, blockers))
    if blockers:
        raise RuntimeError("preflight bloqueo la corrida: %s" % ", ".join(blockers))
    return report


def extract_audio_segment(source: pathlib.Path, start_ms: int, duration_ms: int, output: pathlib.Path) -> None:
    command = [media_tools.find_binary("ffmpeg"), "-y", "-ss", "%.3f" % (start_ms / 1000), "-t", "%.3f" % (duration_ms / 1000), "-i", str(source), "-ar", "48000", "-ac", "1", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
    if result.returncode:
        raise RuntimeError("audio segment fallo: %s" % result.stderr[-400:])


def effective_tts_speed(words: int, target_minutes: float, configured_speed: float = 0.98, calibrated_wpm: float = 195, min_speed: float = 0.98, max_speed: float = 1.05, allow_slowdown: bool = False) -> float:
    desired = configured_speed * words / max(1.0, target_minutes * calibrated_wpm)
    floor = min_speed if allow_slowdown else configured_speed
    return max(floor, min(max_speed, desired))


def natural_voice_density_error(words: int, target_minutes: float, min_wpm: float = 180, max_wpm: float = 200) -> str:
    density = words / max(0.01, target_minutes)
    if min_wpm <= density <= max_wpm:
        return ""
    minimum = math.ceil(target_minutes * min_wpm)
    maximum = math.floor(target_minutes * max_wpm)
    return (
        "SCRIPT_DURATION_MISMATCH: guion de %d palabras para %.2f min (%.1f palabras/min); "
        "regenera el guion con %d-%d palabras. La voz permanece natural y no se ralentiza para rellenar tiempo."
        % (words, target_minutes, density, minimum, maximum)
    )


def tts_voice_profile(effective_speed: float) -> dict[str, Any]:
    profile = {
        "provider": "elevenlabs",
        "voice_id": os.environ.get("ELEVENLABS_VOICE_ID", ""),
        "model": os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        "stability": float(os.environ.get("ELEVENLABS_STABILITY", "0.68")),
        "similarity": float(os.environ.get("ELEVENLABS_SIMILARITY", "0.84")),
        "style": float(os.environ.get("ELEVENLABS_STYLE", "0.12")),
        "speaker_boost": os.environ.get("ELEVENLABS_USE_SPEAKER_BOOST", "1").lower() in {"1", "true", "yes", "on"},
        "configured_speed": float(os.environ.get("ELEVENLABS_SPEED", "0.98")),
        "effective_speed": round(effective_speed, 3),
        "speed_locked": os.environ.get("LONGFORM_TTS_LOCK_SPEED", "1").lower() in {"1", "true", "yes", "on"},
    }
    profile["signature"] = hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return profile


def stage_voice(data: dict[str, Any]) -> dict[str, Any]:
    from engine.aligner import get_aligner

    paths = run_paths(data)
    aligner = get_aligner()
    spoken_script = full_script(data)
    forbidden = forbidden_spoken_terms(spoken_script)
    if forbidden:
        raise RuntimeError("TTS bloqueado por metadata de produccion: %s" % forbidden)
    (paths["work"] / "voice" / "spoken_text.txt").write_text(spoken_script + "\n", encoding="utf-8")
    script_words = len(re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ]+\b", spoken_script, re.UNICODE))
    target_minutes = float(data["target_minutes"])
    target_ms = round(target_minutes * 60_000)
    configured_speed = float(os.environ.get("ELEVENLABS_SPEED", "0.98"))
    lock_speed = os.environ.get("LONGFORM_TTS_LOCK_SPEED", "1").lower() in {"1", "true", "yes", "on"}
    if production_mode() and lock_speed:
        density_error = natural_voice_density_error(
            script_words,
            target_minutes,
            float(os.environ.get("LONGFORM_SCRIPT_MIN_WPM", "180")),
            float(os.environ.get("LONGFORM_SCRIPT_MAX_WPM", "200")),
        )
        if density_error:
            raise RuntimeError(density_error)
    effective_speed = configured_speed
    if production_mode() and not lock_speed:
        calibrated_wpm = float(os.environ.get("LONGFORM_TTS_CALIBRATED_WPM", "195"))
        prior_correction_path = paths["work"] / "02_voice_duration_correction.json"
        if prior_correction_path.is_file():
            prior_correction = read_json(prior_correction_path)
            if prior_correction.get("script_hash") == data["script_hash"] and float(prior_correction.get("corrected_calibrated_wpm") or 0) > 0:
                calibrated_wpm = float(prior_correction["corrected_calibrated_wpm"])
        min_speed = float(os.environ.get("ELEVENLABS_MIN_SPEED", "0.98"))
        max_speed = float(os.environ.get("ELEVENLABS_MAX_SPEED", "1.05"))
        effective_speed = effective_tts_speed(script_words, target_minutes, configured_speed, calibrated_wpm, min_speed, max_speed, allow_slowdown=os.environ.get("LONGFORM_TTS_ALLOW_SLOWDOWN", "0").lower() in {"1", "true", "yes", "on"})
        os.environ["ELEVENLABS_SPEED"] = "%.3f" % effective_speed
    profile = tts_voice_profile(effective_speed)
    cached_voice_path = paths["work"] / "02_voice_alignment.json"
    if cached_voice_path.is_file():
        cached_voice = read_json(cached_voice_path)
        cached_variance = abs(int(cached_voice.get("duration_ms") or 0) - target_ms) / max(1, target_ms)
        cached_files = [paths["work"] / "voice" / "voiceover.wav"] + [paths["work"] / "voice" / (chapter["id"] + ".wav") for chapter in data["chapters"]]
        if cached_voice.get("script_hash") == data["script_hash"] and cached_voice.get("voice_profile_signature") == profile["signature"] and cached_variance <= float(os.environ.get("LONGFORM_DURATION_TOLERANCE", "0.12")) and all(path.is_file() and path.stat().st_size > 0 for path in cached_files):
            print("[longform] voice cache hit script=%s duration=%dms" % (data["script_hash"][:12], int(cached_voice["duration_ms"])))
            record_state(paths, "voice", True, "cache hit %dms" % int(cached_voice["duration_ms"]))
            return cached_voice
    # Provider settings are read during construction. Instantiate only after
    # the per-script speed has been calculated so ElevenLabs receives it.
    provider = get_providers(WIDTH, HEIGHT, FPS)
    chapters_meta: list[dict[str, Any]] = []
    all_words: list[dict[str, Any]] = []
    audio_files: list[pathlib.Path] = []
    offset = 0
    for index, chapter in enumerate(data["chapters"]):
        spoken = chapter_spoken_text(chapter)
        wav = paths["work"] / "voice" / (chapter["id"] + ".wav")
        estimate = max(10.0, len(spoken.split()) / 2.35)
        provider.tts_voiceover(spoken, estimate, str(wav))
        alignment = aligner.align(str(wav), spoken.split())
        probe = ffprobe(wav)
        if not production_mode() and alignment.get("words") and int(alignment.get("duration_ms") or 0) < probe["duration_ms"] * 0.90:
            scale = probe["duration_ms"] / max(1, int(alignment.get("duration_ms") or 1))
            for word in alignment["words"]:
                word["start_ms"] = round(int(word["start_ms"]) * scale)
                word["end_ms"] = round(int(word["end_ms"]) * scale)
            alignment["duration_ms"] = probe["duration_ms"]
        duration = max(probe["duration_ms"], int(alignment.get("duration_ms") or 0))
        local_words = []
        for word in alignment.get("words") or []:
            item = dict(word)
            item["start_ms"] = int(item["start_ms"]) + offset
            item["end_ms"] = int(item["end_ms"]) + offset
            item["chapter_id"] = chapter["id"]
            item["i"] = len(all_words)
            local_words.append(item)
            all_words.append(item)
        public_wav = paths["public"] / "audio" / (chapter["id"] + ".wav")
        shutil.copy2(wav, public_wav)
        chapters_meta.append({"id": chapter["id"], "title": chapter["title"], "start_ms": offset, "end_ms": offset + duration, "duration_ms": duration, "audio_src": "runs/%s/audio/%s.wav" % (data["run_id"], chapter["id"]), "word_count": len(local_words)})
        audio_files.append(wav)
        offset += duration
    concat_file = paths["work"] / "voice" / "concat.txt"
    concat_file.write_text("\n".join("file '%s'" % str(path).replace("'", "''") for path in audio_files) + "\n", encoding="utf-8")
    voice = paths["work"] / "voice" / "voiceover.wav"
    command = [media_tools.find_binary("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(voice)]
    result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
    if result.returncode:
        raise RuntimeError("concat TTS fallo: %s" % result.stderr[-500:])
    public_voice = paths["public"] / "audio" / "voiceover.wav"
    shutil.copy2(voice, public_voice)
    aligned_transcript = " ".join(str(item.get("word") or "") for item in all_words)
    forbidden_after_tts = forbidden_spoken_terms(aligned_transcript)
    if forbidden_after_tts:
        raise RuntimeError("post-TTS QA detecto metadata hablada: %s" % forbidden_after_tts)
    variance = abs(offset - target_ms) / max(1, target_ms)
    if production_mode() and variance > float(os.environ.get("LONGFORM_DURATION_TOLERANCE", "0.12")) and not lock_speed:
        retry_count = int(os.environ.get("LONGFORM_TTS_DURATION_RETRY", "0") or 0)
        if retry_count < 2:
            observed_wpm = script_words / max(0.1, offset / 60_000)
            corrected_calibration = observed_wpm * configured_speed / max(0.01, effective_speed)
            corrected_speed = effective_tts_speed(script_words, target_minutes, configured_speed, corrected_calibration, min_speed, max_speed, allow_slowdown=os.environ.get("LONGFORM_TTS_ALLOW_SLOWDOWN", "0").lower() in {"1", "true", "yes", "on"})
            correction = {
                "script_hash": data["script_hash"],
                "first_duration_ms": offset,
                "target_duration_ms": target_ms,
                "first_speed": round(effective_speed, 3),
                "observed_wpm": round(observed_wpm, 1),
                "corrected_calibrated_wpm": round(corrected_calibration, 1),
                "corrected_speed": round(corrected_speed, 3),
                "retry": abs(corrected_speed - effective_speed) >= 0.015,
            }
            write_json(paths["work"] / "02_voice_duration_correction.json", correction)
            if correction["retry"]:
                previous_calibration = os.environ.get("LONGFORM_TTS_CALIBRATED_WPM")
                os.environ["LONGFORM_TTS_CALIBRATED_WPM"] = "%.3f" % corrected_calibration
                os.environ["LONGFORM_TTS_DURATION_RETRY"] = str(retry_count + 1)
                print("[longform] TTS %.1fs fuera de objetivo; correccion %d/2 speed %.3f -> %.3f" % (offset / 1000, retry_count + 1, effective_speed, corrected_speed))
                try:
                    return stage_voice(data)
                finally:
                    os.environ.pop("LONGFORM_TTS_DURATION_RETRY", None)
                    if previous_calibration is None:
                        os.environ.pop("LONGFORM_TTS_CALIBRATED_WPM", None)
                    else:
                        os.environ["LONGFORM_TTS_CALIBRATED_WPM"] = previous_calibration
        raise RuntimeError("TTS dura %.1fs; objetivo %.1fs; desviacion %.1f%% supera tolerancia" % (offset / 1000, target_ms / 1000, variance * 100))
    if production_mode() and variance > float(os.environ.get("LONGFORM_DURATION_TOLERANCE", "0.12")) and lock_speed:
        raise RuntimeError("TTS_NATURAL_DURATION_MISMATCH: la voz natural dura %.1fs y el objetivo es %.1fs; regenera el guion, no cambies speed" % (offset / 1000, target_ms / 1000))
    payload = {"script_hash": data["script_hash"], "duration_ms": offset, "target_duration_ms": target_ms, "duration_variance": round(variance, 4), "tts_speed": round(effective_speed, 3), "voice_profile": profile, "voice_profile_signature": profile["signature"], "audio_src": "runs/%s/audio/voiceover.wav" % data["run_id"], "spoken_text_path": str(paths["work"] / "voice" / "spoken_text.txt"), "forbidden_speech_terms": forbidden_after_tts, "chapters": chapters_meta, "words": all_words}
    write_json(paths["work"] / "02_voice_alignment.json", payload)
    record_state(paths, "voice", True, "%dms, %d words" % (offset, len(all_words)))
    return payload


def chunk_words(voice: dict[str, Any]) -> list[dict[str, Any]]:
    shots: list[dict[str, Any]] = []
    chapter_lookup = {item["id"]: item for item in voice["chapters"]}
    by_chapter: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for word in voice["words"]:
        by_chapter[word["chapter_id"]].append(word)
    counter = 1
    for chapter in voice["chapters"]:
        words = by_chapter[chapter["id"]]
        cursor = 0
        chapter_shots: list[dict[str, Any]] = []
        while cursor < len(words):
            start = cursor
            start_ms = int(words[start]["start_ms"])
            cursor += 1
            while cursor < len(words):
                is_final_word = cursor == len(words) - 1
                projected_end = int(chapter["end_ms"]) if is_final_word else int(words[cursor]["end_ms"])
                projected = projected_end - start_ms
                limit = MAX_SHOT_MS if is_final_word else MAX_SHOT_MS - 100
                if projected > limit:
                    break
                elapsed = int(words[cursor - 1]["end_ms"]) - start_ms
                punctuation = bool(re.search(r"[.!?;:]$", str(words[cursor - 1]["word"])))
                if elapsed >= TARGET_SHOT_MS and punctuation:
                    break
                cursor += 1
            segment = words[start:cursor]
            shot_start = start_ms
            shot_end = int(segment[-1]["end_ms"])
            chapter_shots.append({"shotId": "S%04d" % counter, "chapterId": chapter["id"], "chapterTitle": chapter["title"], "startMs": shot_start, "endMs": shot_end, "tts": " ".join(str(item["word"]) for item in segment)})
            counter += 1
        if chapter_shots:
            chapter_shots[0]["startMs"] = chapter["start_ms"]
            chapter_shots[-1]["endMs"] = chapter["end_ms"]
            shots.extend(chapter_shots)
    for current, following in zip(shots, shots[1:]):
        boundary = int(following["startMs"])
        if boundary - int(current["startMs"]) > MAX_SHOT_MS:
            boundary = int(current["startMs"]) + MAX_SHOT_MS
        current["endMs"] = boundary
        following["startMs"] = boundary
    if shots:
        shots[-1]["endMs"] = voice["duration_ms"]
        if shots[-1]["endMs"] - shots[-1]["startMs"] > MAX_SHOT_MS:
            raise RuntimeError("silencio final excede LONGFORM_MAX_SHOT_SECONDS; corrige alineacion/TTS")
    return shots


def parse_json_response(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except Exception:
        match = re.search(r"\{.*\}", clean, re.S)
        if not match:
            raise RuntimeError("director visual no devolvio JSON")
        return json.loads(match.group(0))


def fallback_direction(shot: dict[str, Any]) -> dict[str, Any]:
    text = shot["tts"].lower()
    exact = any(term in text for term in ("aplica", "masaje", "etiqueta", "ingrediente", "mide", "compara", "piel", "crema"))
    mechanism = any(term in text for term in ("porque", "mecanismo", "agua", "grasa", "circulación", "temporal", "evidencia"))
    route = "pexels" if exact else ("image" if mechanism else "pexels")
    query = "woman applying body cream" if "crema" in text else "woman reading skincare label" if "etiqueta" in text else "mature woman skincare"
    words = [w.strip(".,:;!?\"") for w in shot["tts"].split() if len(w.strip(".,:;!?\"")) > 3]
    selected = []
    for word in words[:4]:
        if len(" ".join(selected + [word])) > 32:
            break
        selected.append(word)
    screen = " ".join(selected).upper() or "IDEA CLAVE"
    moving = any(term in text for term in ("aplica", "abre", "compara", "mide", "masaje", "camina", "lee", "muestra"))
    return {"shot_id": shot["shotId"], "route": route, "clip_query": "", "pexels_query": compact_pexels_query(query, shot), "query": query, "prompt": "Landscape 16:9 editorial health visual. Packaging must look commercially plausible when visible; never use blank packaging or real trademarks. " + shot["tts"], "screen_copy": screen, "subcopy": "", "visual_proof": shot["tts"][:180], "moving_visual_required": moving}


def product_context(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("product_context") or {}
    return {
        "brand": str(raw.get("fictional_brand") or "MARCA FICTICIA").strip().upper(),
        "name": str(raw.get("product_name") or "PRODUCTO").strip().upper(),
        "size": str(raw.get("product_size") or "").strip().upper(),
        "language": str(raw.get("label_language") or data.get("language") or "es").strip(),
    }


def visual_directions(data: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from providers import codex_oauth

    instructions = (pathlib.Path(ROOT) / "prompts" / "longform_visual_director.md").read_text(encoding="utf-8")
    compact = [{"shot_id": item["shotId"], "chapter": item["chapterTitle"], "start_ms": item["startMs"], "end_ms": item["endMs"], "narration": item["tts"]} for item in shots]
    user = "Title: %s\nThumbnail promise: %s\nAudience: %s\nDesign profile:\n%s\nTimed chunks:\n%s" % (data["title"], data["thumbnail_promise"], data["audience_profile"], json.dumps(data.get("_design_profile") or {}, ensure_ascii=False), json.dumps(compact, ensure_ascii=False))
    if not production_mode():
        return {shot["shotId"]: fallback_direction(shot) for shot in shots}
    try:
        text = codex_oauth.responses([{"role": "user", "content": [{"type": "input_text", "text": user}]}], instructions=instructions)
        payload = parse_json_response(text)
        rows = payload.get("shots") or []
        result = {str(row.get("shot_id")): row for row in rows if row.get("shot_id")}
    except Exception as exc:
        print("[longform] director visual LLM fallo, fallback deterministico: %s" % str(exc)[:180])
        result = {}
    for shot in shots:
        result.setdefault(shot["shotId"], fallback_direction(shot))
    return result


def concise_display_copy(value: str) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip(" .,:;!?")
    return clean if clean and len(clean) <= 32 and len(clean.split()) <= 4 else ""


def select_avatar_targets(shots: list[dict[str, Any]]) -> set[int]:
    """Pick two trust beats without displacing exact data or multi-step proof."""
    if len(shots) < 4:
        return {0, max(0, len(shots) - 1)}
    eligible = [
        index for index, shot in enumerate(shots)
        if not shot.get("requiresReadableData")
        and shot.get("temporalAction") != "multi_step"
        and shot.get("beatRole") not in {"proof", "demonstration", "comparison"}
        and shot.get("mediaNeedKind") not in {"exact_ui_state", "comparison", "measurement_protocol", "label_or_ingredient"}
    ]
    if len(eligible) < 2:
        eligible = list(range(len(shots)))
    targets = []
    for fraction, low, high in ((0.20, 0.08, 0.38), (0.68, 0.52, 0.86)):
        pool = [index for index in eligible if low <= index / max(1, len(shots) - 1) <= high and index not in targets]
        pool = pool or [index for index in eligible if index not in targets]
        targets.append(min(pool, key=lambda index: abs(index / max(1, len(shots) - 1) - fraction)))
    return set(targets)


FILMABLE_OVERRIDES = (
    (r"\b(se vea m[aá]s lisa|superficie m[aá]s lisa)\b", "woman applies body lotion to her arm during a skincare routine close up", "woman applying body lotion", "A woman visibly applies body lotion to her upper-body skin in a close skincare shot.", False),
    (r"\b(prueba una (?:pequeña|pequena) zona|patch test|revisa si aparece)\b", "how to apply a skincare patch test to the forearm", "applying cream forearm", "A small amount of skincare cream is visibly applied to one clearly defined test area on the forearm.", True),
    (r"\b(consulta a un profesional|health professional|dermatologist|dermat[oó]log)\b", "mature woman consults a health professional and listens to practical guidance", "mature woman doctor consultation", "A mature woman visibly consults a health professional and listens to practical guidance.", False),
)


def apply_purchase_evidence_routes(shots: list[dict[str, Any]], product: dict[str, str] | None = None) -> None:
    """Render purchase criteria as readable evidence instead of generic stock."""
    product = product or {"brand": "MARCA FICTICIA", "name": "PRODUCTO", "size": ""}
    for shot in shots:
        text = " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof")).lower()
        if not re.search(r"\bregla de compra\b", text, re.I):
            continue
        shot.update({
            "proofKind": "exact_ui_state",
            "mediaNeedKind": "exact_ui_state",
            "proofKindLocked": True,
            "evidenceMode": "demonstrative",
            "requiresReadableData": True,
            "requiresStateContinuity": False,
            "temporalAction": "multi_step",
            "route": "ui",
            "routePlan": ["ui"],
            "fallbackStrategy": "deterministic-ui",
            "movingVisualRequired": True,
            "visualProof": "A product label checklist visibly highlights promise, ingredients, expected time and tolerance.",
            "requiredEvidence": "A deterministic purchase checklist visibly separates promise, identifiable ingredients, realistic timing and skin tolerance without inventing a formula.",
            "screenCopy": "REGLA DE COMPRA",
            "subcopy": "PROMESA, TIEMPO Y TOLERANCIA",
            "uiTemplate": "product-label",
            "uiItems": ["PROMESA", "INGREDIENTES", "TIEMPO", "TOLERANCIA"],
            "uiValues": ["¿QUÉ CAMBIA?", "LISTA LEGIBLE", "PLAZO REALISTA", "PRUEBA EN ZONA"],
            "productBrand": product["brand"],
            "productName": product["name"],
            "productSize": product["size"],
            "filmableOverride": False,
        })
        for key in ("evidenceOverlayHeadline", "evidenceOverlayItems", "evidenceOverlayProductBrand", "evidenceOverlayProduct"):
            shot.pop(key, None)
        # This is a complete deterministic checklist, not a hybrid requiring
        # a generated package behind it. Remove stale director metadata.
        for key in ("hybridTemplate", "backgroundSource", "backgroundMediaType", "backgroundObjectPosition"):
            shot.pop(key, None)


def align_observable_evidence_contracts(shots: list[dict[str, Any]]) -> None:
    """Describe what the selected visual can truthfully demonstrate, without impossible cues."""
    for shot in shots:
        text = " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof")).lower()
        if str(shot.get("proofKind") or shot.get("mediaNeedKind") or "") in {"human_action", "physiological_mechanism"} and any(
            term in text for term in ("calor", "cosquilleo", "sudor", "warming", "tingling")
        ):
            shot.update({
                "proofKind": "physiological_mechanism",
                "mediaNeedKind": "physiological_mechanism",
                "proofKindLocked": True,
                "evidenceMode": "demonstrative",
                "requiresReadableData": False,
                "requiresStateContinuity": False,
                "temporalAction": "single",
                "temporalEvidenceMode": "implied",
                "requiresObservedTransition": False,
                "route": "ui",
                "routePlan": ["ui", "image", "omni"],
                "preferredMedium": "ui",
                "fallbackStrategy": "deterministic-ui",
                "movingVisualRequired": True,
                "visualProof": "An animated surface-versus-composition diagram separates heat, tingling or sweat from any change in body fat.",
                "requiredEvidence": "A deterministic animated diagram shows that heat, tingling and sweat are surface sensations, not proof of reduced body fat.",
                "screenCopy": "SENSACIÓN ≠ GRASA",
                "subcopy": "ACTÚA EN LA SUPERFICIE",
                "uiTemplate": "mechanism",
                "uiItems": ["CALOR", "COSQUILLEO", "SUDOR", "GRASA SIN CAMBIO"],
                "uiValues": ["SUPERFICIE", "SUPERFICIE", "SUPERFICIE", "NO DEMOSTRADO"],
                "filmableOverride": False,
            })
            shot.pop("hybridTemplate", None)


def apply_early_context_broll(data: dict[str, Any], shots: list[dict[str, Any]]) -> None:
    """Anchor an abstract opening claim with one truthful topical-cream action."""
    if len(shots) < 2 or "crema" not in str(data.get("title") or "").lower():
        return
    shot = shots[1]
    if shot.get("requiresReadableData"):
        return
    pexels_query = "woman applying body lotion leg"
    shot.update({
        "proofKind": "human_action",
        "mediaNeedKind": "human_action",
        "proofKindLocked": True,
        "evidenceMode": "illustrative",
        "requiresReadableData": False,
        "requiresStateContinuity": False,
        "temporalAction": "single",
        "route": "pexels",
        "routePlan": ["pexels", "image", "omni"],
        "fallbackStrategy": "bounded-provider-search",
        "movingVisualRequired": True,
        "visualProof": "A woman visibly applies body lotion to the skin of her leg; this illustrates topical use without implying fat loss.",
        "query": pexels_query,
        "clipQuery": "",
        "clipBaseQuery": "",
        "pexelsQuery": pexels_query,
        "pexelsBaseQuery": pexels_query,
        "hookRequirement": "Debe verse crema o locion aplicada sobre piel real. No debe implicar que la grasa desaparece y ningun envase blanco sin etiqueta puede ser el protagonista.",
        "filmableOverride": True,
    })


def apply_closing_distinction_route(shots: list[dict[str, Any]]) -> None:
    """Reset stale shopping routes when the narration needs a body-state distinction."""
    for shot in shots:
        text = str(shot.get("tts") or "").lower()
        if "ahora mira" in text or not ("disting" in text and "piel" in text and "grasa" in text):
            continue
        shot.update({
            "proofKind": "physiological_mechanism",
            "mediaNeedKind": "physiological_mechanism",
            "proofKindLocked": True,
            "evidenceMode": "demonstrative",
            "requiresReadableData": False,
            "requiresStateContinuity": True,
            "temporalAction": "multi_step",
            "route": "image",
            "routePlan": ["image", "ui", "omni"],
            "fallbackStrategy": "bounded-provider-search",
            "movingVisualRequired": True,
            "visualProof": "An animated three-part abdomen diagram clearly distinguishes skin surface, temporary bloating and deeper fat.",
            "screenCopy": "DISTINGUE ANTES DE COMPRAR",
            "subcopy": "PIEL, HINCHAZON Y GRASA",
            "uiTemplate": "anatomy-explainer",
            "hybridTemplate": "anatomy-explainer",
            "uiItems": ["PIEL", "HINCHAZON", "GRASA"],
            "uiValues": ["SUPERFICIE", "TEMPORAL", "SUBCUTANEA"],
            "hookRequirement": "Debe distinguir visualmente superficie de piel, hinchazon temporal y grasa subcutanea con un diagrama animado, sin transformaciones corporales exageradas.",
            "query": "",
            "clipQuery": "",
            "clipBaseQuery": "",
            "pexelsQuery": "",
            "pexelsBaseQuery": "",
            "prompt": "",
            "imageBasePrompt": "",
            "filmableOverride": False,
            "continuityGroup": "skin-bloating-fat-anatomy",
            "preferredMedium": "image",
            "forbiddenSubstitutions": ["generic-stock-as-proof", "text-card-as-proof"],
        })


def apply_cta_end_screen_route(data: dict[str, Any], shots: list[dict[str, Any]]) -> None:
    """Mark one spoken CTA anchor; the global end-screen owns its rendering."""
    cta = data.get("cta") or {}
    target = str(cta.get("target_video_title") or "").strip()
    if cta and cta.get("verified") is not True:
        raise RuntimeError("CTA no verificado: no se puede fabricar una recomendacion de pantalla final")
    anchor_set = False
    for shot in shots:
        was_embedded_cta = bool(shot.pop("verifiedCtaEndScreen", None)) or str(shot.get("uiTemplate") or "") == "verified-next-video"
        shot.pop("ctaAnchor", None)
        if was_embedded_cta:
            for key in ("uiTemplate", "uiVariant", "uiItems", "uiValues", "uiSpec", "proofKindLocked"):
                shot.pop(key, None)
            inferred = infer_media_need(shot, {"visual_proof": shot.get("visualProof") or shot.get("tts")})
            if inferred == "exact_ui_state":
                inferred = "abstract_concept"
            routes = route_order(
                inferred,
                readable=False,
                continuity=bool(shot.get("requiresStateContinuity")),
                temporal_action=str(shot.get("temporalAction") or "single"),
            )
            shot.update({
                "proofKind": inferred,
                "mediaNeedKind": inferred,
                "route": routes[0],
                "routePlan": routes,
                "preferredMedium": routes[0],
                "requiresReadableData": False,
                "screenCopy": concise_display_copy(shot.get("tts") or target or "SIGUIENTE VIDEO"),
            })
        text = str(shot.get("tts") or "")
        if not anchor_set and ("ahora mira" in text.lower() or (target and target.lower() in text.lower())):
            shot["ctaAnchor"] = True
            anchor_set = True


def apply_filmable_overrides(shots: list[dict[str, Any]], product: dict[str, str] | None = None) -> None:
    """Prefer observable human action when it truthfully supports the narration."""
    product = product or {"brand": "MARCA FICTICIA", "name": "PRODUCTO", "size": ""}
    for shot in shots:
        if shot.get("proofKindLocked"):
            continue
        text = " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof")).lower()
        for pattern, clip_query, pexels_query, visual_proof, movement_required in FILMABLE_OVERRIDES:
            if not re.search(pattern, text, re.I):
                continue
            shot.update({
                "proofKind": "human_action",
                "mediaNeedKind": "human_action",
                "proofKindLocked": True,
                "evidenceMode": "demonstrative" if movement_required else "illustrative",
                "requiresReadableData": False,
                "requiresStateContinuity": movement_required,
                "temporalAction": "single",
                "route": "pexels",
                "routePlan": ["pexels", "omni", "ui"] if movement_required else ["pexels", "image", "omni"],
                "fallbackStrategy": "deterministic-ui" if movement_required else "bounded-provider-search",
                "movingVisualRequired": movement_required,
                "visualProof": visual_proof,
                "requiredEvidence": visual_proof,
                "query": pexels_query,
                "clipQuery": "",
                "clipBaseQuery": "",
                "pexelsQuery": pexels_query,
                "pexelsBaseQuery": pexels_query,
                "filmableOverride": True,
            })
            stale_hook = str(shot.get("hookRequirement") or "")
            if product["brand"] in stale_hook or "etiqueta comercial ficticia" in stale_hook.lower() or re.search(r"\b(etiqueta|envase|packaging|marca)\b", stale_hook, re.I):
                shot["hookRequirement"] = "Debe verse una accion humana real con un producto de cuidado personal reconocible. La etiqueta no necesita ser legible en este plano ilustrativo, pero no puede haber watermarks, logos de stock ni un envase blanco usado como producto protagonista."
            if re.search(r"\b(consulta a un profesional|health professional|dermatologist|dermat[oó]log)\b", text, re.I):
                shot["hookRequirement"] = "Debe verse una mujer adulta en una consulta activa con un profesional de salud. El producto no necesita aparecer; rechaza planos de un profesional solo, una sala vacia o una conversacion no medica."
                shot["screenCopy"] = "CONSULTA A UN PROFESIONAL"
                shot["subcopy"] = "SI TIENES DUDAS"
                shot["headlinePosition"] = "bottom-left"
            if re.search(r"\b(regla de compra|antes de elegir)\b", text, re.I):
                shot["evidenceOverlayHeadline"] = "REGLA DE COMPRA"
                shot["evidenceOverlayItems"] = ["PROMESA", "INGREDIENTES", "TIEMPO", "TOLERANCIA"]
                shot["evidenceOverlayProductBrand"] = product["brand"]
                shot["evidenceOverlayProduct"] = product["name"]
            if movement_required:
                shot.update({
                    "continuityGroup": str(shot.get("continuityGroup") or "patch-test-protocol"),
                    "uiTemplate": "procedure",
                    "uiItems": ["APLICA POCO", "ESPERA", "REVISA"],
                    "uiValues": ["ZONA PEQUEÑA", "SIN INSISTIR", "TOLERANCIA"],
                })
            break


def stage_plan(data: dict[str, Any], voice: dict[str, Any]) -> dict[str, Any]:
    paths = run_paths(data)
    design_profile = data.get("_design_profile") or resolve_design_profile(data, pathlib.Path(ROOT) / "work" / "design_profiles")
    theme = remotion_theme(design_profile)
    design_scope = design_prompt_scope(design_profile)
    product = product_context(data)
    cached_plan_path = paths["work"] / "03_visual_plan.json"
    if cached_plan_path.is_file():
        cached_plan = read_json(cached_plan_path)
        expected_mode = "real" if production_mode() else "mock"
        if cached_plan.get("scriptHash") == data["script_hash"] and int(cached_plan.get("durationMs") or 0) == int(voice["duration_ms"]) and cached_plan.get("providerMode") == expected_mode and cached_plan.get("designProfileId") == design_profile.get("id"):
            if (cached_plan.get("rules") or {}).get("planPolicyVersion") != PLAN_POLICY_VERSION:
                cached_plan = upgrade_visual_plan(data, cached_plan)
                write_json(cached_plan_path, cached_plan)
            cached_plan = apply_persisted_draft_repairs(cached_plan, paths)
            normalize_plan_visual_composition(cached_plan)
            apply_motion_choreography(cached_plan)
            composition_errors = validate_plan_visual_composition(cached_plan, resolved=False) + validate_motion_choreography(cached_plan)
            if composition_errors:
                raise RuntimeError("plan cacheado viola contrato visual: %s" % composition_errors[:8])
            record_state(paths, "plan", True, "cache hit %d shots" % len(cached_plan.get("shots") or []))
            print("[longform] plan cache hit %d shots" % len(cached_plan.get("shots") or []))
            return cached_plan
    invalid_plan_path = paths["work"] / "03_visual_plan_invalid.json"
    if invalid_plan_path.is_file():
        invalid_payload = read_json(invalid_plan_path)
        recoverable = invalid_payload.get("plan") or {}
        if recoverable.get("scriptHash") == data["script_hash"] and int(recoverable.get("durationMs") or 0) == int(voice["duration_ms"]):
            try:
                recovered = upgrade_visual_plan(data, recoverable)
                write_json(cached_plan_path, recovered)
                invalid_plan_path.unlink(missing_ok=True)
                record_state(paths, "plan", True, "auto-repaired invalid plan %d shots" % len(recovered.get("shots") or []))
                print("[longform] plan invalido reparado sin repetir director LLM")
                return recovered
            except Exception as exc:
                print("[longform] reparacion automatica del plan invalido no aplico: %s" % str(exc)[:240])
    shots = chunk_words(voice)
    directions = visual_directions(data, shots)
    for index, shot in enumerate(shots):
        direction = directions[shot["shotId"]]
        shot.update({
            "route": str(direction.get("route") or "image"),
            "companionRoute": "",
            "query": str(direction.get("query") or "")[:180],
            "clipQuery": str(direction.get("clip_query") or direction.get("query") or direction.get("visual_proof") or shot["tts"])[:500],
            "pexelsQuery": compact_pexels_query(str(direction.get("pexels_query") or direction.get("query") or ""), {**shot, "visualProof": direction.get("visual_proof"), "prompt": direction.get("prompt")}),
            "prompt": str(direction.get("prompt") or "")[:1200],
            "cutoutBackground": str(direction.get("cutout_background") or "")[:180],
            "cutoutProps": [str(value)[:100] for value in (direction.get("cutout_props") or [])[:3]] if isinstance(direction.get("cutout_props"), list) else [],
            "cutoutRelation": str(direction.get("cutout_relation") or "")[:30],
            "sourceTitle": str(direction.get("source_title") or "")[:180],
            "sourceChannel": str(direction.get("source_channel") or "")[:120],
            "sourceUrl": str(direction.get("source_url") or "")[:500],
            "screenCopy": concise_display_copy(direction.get("screen_copy") or ""),
            "subcopy": concise_display_copy(direction.get("subcopy") or ""),
            "visualProof": str(direction.get("visual_proof") or shot["tts"])[:300],
            "movingVisualRequired": bool(direction.get("moving_visual_required")),
            "cardVariant": "chapter" if index == 0 or shots[index - 1]["chapterId"] != shot["chapterId"] else "statement",
        })
        normalize_media_contract(shot, direction)
        if "crema" in str(data.get("title") or "").lower() and any(term in (shot["tts"] + " " + shot["visualProof"]).lower() for term in ("etiqueta", "ingrediente", "envase", "frasco", "tarro", "botella", "label", "package")):
            shot["pexelsQuery"] = "body lotion label"
            packaging_requirement = "Si aparece un envase como sujeto visible, debe tener una etiqueta comercial ficticia coherente: marca %s, producto %s y contenido %s. Rechaza envases visiblemente blancos o sin etiqueta, texto absurdo perceptible y logos de marcas reales." % (product["brand"], product["name"], product["size"] or "plausible")
            shot["hookRequirement"] = " ".join(filter(None, (shot.get("hookRequirement"), packaging_requirement)))
            shot["prompt"] = (shot.get("prompt") or "") + "\nNon-negotiable: " + packaging_requirement
            exact_label = any(term in (shot["tts"] + " " + shot["visualProof"]).lower() for term in ("etiqueta", "label", "distingue", "promesa", "promete", "absoluto", "contenido", "eliminar grasa"))
            if exact_label:
                shot.update({"proofKind": "product_inspection", "mediaNeedKind": "product_inspection", "proofKindLocked": True, "requiresReadableData": True, "route": "ui", "routePlan": ["ui", "image"], "fallbackStrategy": "deterministic-ui", "uiTemplate": "product-inspection", "uiItems": ["PROMESA", "TIPO", "CONTENIDO"], "uiValues": ["REVISA", product["name"], product["size"]], "productBrand": product["brand"], "productName": product["name"], "productSize": product["size"]})
    if shots:
        # The first rendered words and first overlay must pay the packaging promise.
        shots[0]["screenCopy"] = concise_display_copy(data["thumbnail_promise"])
        shots[0]["subcopy"] = "MIRA EL ENVASE"
        shots[0]["visualProof"] = "A readable body-cream package is inspected before purchase; the topical product is unmistakable."
        shots[0]["requiredEvidence"] = "A front-facing open body-cream jar with a large readable fictional label validates the purchase-inspection promise in the first three seconds."
        shots[0]["hookRequirement"] = "Debe verse inequívocamente un cosmético tópico: tarro o tubo de crema corporal, idealmente con crema visible. El envase debe mostrar una etiqueta comercial ficticia, coherente y legible en español; nunca puede estar blanco o sin etiqueta. Rechaza botellas de suplemento, cápsulas, tabletas, productos capilares y logos de marcas reales."
        shots[0]["clipQuery"] = "macro close-up, a hand opens an unbranded body cream jar and touches visible white cream, cosmetic jar centered, no pills, no logos, no watermark"
        shots[0]["pexelsQuery"] = "body cream jar"
        shots[0]["prompt"] = "Landscape 16:9 premium editorial close-up of an open topical cosmetic with product visible. Packaging has a realistic coherent fictional label: %s / %s / %s. No visibly blank packaging, no pills, no real trademark." % (product["brand"], product["name"], product["size"])
        shots[0]["movingVisualRequired"] = False
        shots[0].update({
            "proofKind": "product_inspection",
            "mediaNeedKind": "product_inspection",
            "proofKindLocked": True,
            "requiresReadableData": False,
            "route": "image",
            "routePlan": ["image", "pexels", "omni"],
            "fallbackStrategy": "bounded-provider-search",
            "productBrand": product["brand"],
            "productName": product["name"],
            "productSize": product["size"],
        })
    apply_filmable_overrides(shots, product)
    apply_purchase_evidence_routes(shots, product)
    apply_early_context_broll(data, shots)
    apply_closing_distinction_route(shots)
    apply_cta_end_screen_route(data, shots)
    align_observable_evidence_contracts(shots)
    for shot in shots:
        shot["designStyleScope"] = design_scope
        normalize_media_contract(shot, shot)
    assign_evidence_beats(shots)
    balance_graphic_routes(shots)
    direct_plan(shots)
    apply_learning_biases(shots)
    for shot in shots:
        shot["continuityLock"] = str(shot.get("continuityLock") or ("preserve all declared state in %s" % shot["continuityGroup"] if shot.get("continuityGroup") else ""))
        enforce_hard_route_priority(shot)
        compile_all(shot)
        apply_motion_contract(shot, shot)
        normalize_visual_composition(shot)
    avatar_targets = select_avatar_targets(shots)
    for index in avatar_targets:
        shot = shots[index]
        shot["companionContract"] = sanitize_avatar_companion(shot, {key: json.loads(json.dumps(shot.get(key))) for key in (
            "proofKind", "mediaNeedKind", "beatRole", "requiredEvidence", "preferredMedium",
            "forbiddenSubstitutions", "peoplePolicy", "presenterAllowed", "maxFaceAreaRatio",
            "evidenceMustRemainDominant", "route", "routePlan", "queryVariants", "uiSpec",
        ) if key in shot})
        shot["companionRoute"] = shot["route"]
        shot["companionRoutePlan"] = list(shot.get("routePlan") or [])
        shot["route"] = "avatar"
        shot["routePlan"] = ["avatar"]
        shot.update({"proofKind": "presenter", "mediaNeedKind": "presenter", "beatRole": "pattern_interrupt", "peoplePolicy": "required", "presenterAllowed": True, "maxFaceAreaRatio": 0.50, "evidenceMustRemainDominant": False, "preferredMedium": "avatar", "forbiddenSubstitutions": [], "requiredEvidence": "Trusted presenter delivers the approved narration without replacing simultaneous proof.", "noveltyKey": "presenter-%s" % shot["shotId"]})
        shot["presenterReason"] = "trust_anchor_without_competing_evidence"
        apply_motion_contract(shot, shot)
        normalize_visual_composition(shot)
    plan = {"schemaVersion": "3.2", "scriptHash": data["script_hash"], "runId": data["run_id"], "providerMode": "real" if production_mode() else "mock", "thumbnailPromise": data["thumbnail_promise"], "durationMs": voice["duration_ms"], "width": WIDTH, "height": HEIGHT, "fps": FPS, "designProfileId": design_profile.get("id"), "designProfile": design_profile, "designTheme": theme, "designStyleScope": design_scope, "shots": shots, "chapters": voice["chapters"], "cta": data.get("cta") or {}, "rules": {"scriptLocked": True, "allowLoop": False, "avatarAppearances": 2, "maxShotMs": MAX_SHOT_MS, "routingPolicy": "feasibility-v3", "planPolicyVersion": PLAN_POLICY_VERSION, "queryVariantsPerProvider": 3, "maxVideoCandidatesPerProvider": 2, "maxDirectedRetry": 1}}
    normalize_plan_visual_composition(plan)
    apply_motion_choreography(plan)
    contract_errors = validate_plan_media_contract(plan) + validate_plan_visual_composition(plan, resolved=False) + validate_motion_choreography(plan)
    if contract_errors:
        invalid_shots = [shot for shot in shots if validate_media_contract(shot)]
        write_json(paths["work"] / "03_visual_plan_invalid.json", {"errors": contract_errors, "shots": invalid_shots, "plan": plan})
        summary = [{"shotId": shot.get("shotId"), "proofKind": shot.get("proofKind"), "route": shot.get("route"), "routePlan": shot.get("routePlan"), "errors": validate_media_contract(shot)} for shot in invalid_shots]
        raise RuntimeError("media contract invalido antes de providers: %s" % summary[:8])
    write_json(paths["work"] / "03_visual_plan.json", plan)
    record_state(paths, "plan", True, "%d shots" % len(shots))
    return plan


def normalize_user_clip(source: pathlib.Path, output: pathlib.Path, duration_ms: int, start_ms: int = 0) -> None:
    command = [media_tools.find_binary("ffmpeg"), "-y", "-ss", "%.3f" % (start_ms / 1000), "-i", str(source), "-t", "%.3f" % (duration_ms / 1000), "-an", "-vf", "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d,format=yuv420p" % (WIDTH, HEIGHT, WIDTH, HEIGHT, FPS), "-r", str(FPS), "-pix_fmt", "yuv420p", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
    if result.returncode:
        raise RuntimeError("normalizacion user clip fallo: %s" % result.stderr[-300:])


def media_fit(media_rel: str, shot: dict[str, Any]) -> tuple[bool, str]:
    if not production_mode():
        return True, "mock mode"
    from engine import qa
    scene = {"role": "hook" if int(shot.get("startMs") or 0) == 0 else "broll", "source": shot.get("route"), "intent": shot["tts"], "visual_targets": [shot["visualProof"]], "visual_proof": shot["visualProof"], "editorial_point": shot["tts"], "why_it_matters": shot["visualProof"], "screen_copy": shot.get("screenCopy", ""), "subcopy": shot.get("subcopy", ""), "hook_requirement": shot.get("hookRequirement", ""), "fictional_label": shot.get("fictionalLabel") or shot.get("productBrand") or ""}
    try:
        return qa.media_fit_check(media_rel, scene, spoken=shot["tts"])
    except Exception as exc:
        return False, "fit-check fallo: %s" % str(exc)[:180]


def cached_media_fit(path: pathlib.Path, media_rel: str, shot: dict[str, Any], route: str) -> tuple[bool, str]:
    from engine.qa import MEDIA_FIT_CRITERION_VERSION
    sidecar = pathlib.Path(str(path) + ".fit.json")
    semantic_payload = {key: shot.get(key) for key in (
        "tts", "visualProof", "requiredEvidence", "forbiddenSubstitutions",
        "peoplePolicy", "maxFaceAreaRatio", "requiresVisibleFace", "temporalEvidenceMode",
        "screenCopy", "subcopy", "hookRequirement", "fictionalLabel", "productBrand",
    )}
    semantic_signature = hashlib.sha256(json.dumps(semantic_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    if sidecar.is_file():
        cached = read_json(sidecar)
        if cached.get("criterion_version") == MEDIA_FIT_CRITERION_VERSION and cached.get("shot_id") == shot["shotId"] and cached.get("route") == route and cached.get("asset_sha256") == sha256(path) and cached.get("semantic_signature") == semantic_signature:
            return bool(cached.get("fit")), str(cached.get("reason") or "")
    fit, reason = media_fit(media_rel, shot)
    write_json(sidecar, {"fit": fit, "reason": reason, "route": route, "shot_id": shot["shotId"], "asset_sha256": sha256(path), "semantic_signature": semantic_signature, "criterion_version": MEDIA_FIT_CRITERION_VERSION})
    return fit, reason


def cached_generated_request_matches(path: pathlib.Path, shot: dict[str, Any], route: str) -> bool:
    """Reject generated-image bytes that predate the currently compiled prompt."""
    variants = list((shot.get("queryVariants") or {}).get(route) or [])
    if route == "image_pair":
        meta_path = pathlib.Path(str(path) + ".image_pair.json")
        if not meta_path.is_file():
            return False
        actual = str(read_json(meta_path).get("signature") or "")
        expected: set[str] = set()
        for value in variants or [shot.get("imagePairPrompt") or ""]:
            try:
                pair = json.loads(str(value))
            except Exception:
                continue
            if isinstance(pair, dict) and str(pair.get("left") or "").strip() and str(pair.get("right") or "").strip():
                expected.add(hashlib.sha256(json.dumps(pair, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest())
        return bool(actual and actual in expected)
    if route == "image":
        meta_path = pathlib.Path(str(path) + ".image.json")
        if not meta_path.is_file():
            return False
        actual = str(read_json(meta_path).get("signature") or "")
        hook = ("\nNon-negotiable: " + str(shot.get("hookRequirement") or "")) if shot.get("hookRequirement") else ""
        prompts = variants or [shot.get("prompt") or shot.get("visualProof") or ""]
        expected = {hashlib.sha256((str(value) + hook).encode("utf-8")).hexdigest() for value in prompts if str(value).strip()}
        return bool(actual and actual in expected)
    return True


def create_asset(provider: Any, data: dict[str, Any], paths: dict[str, pathlib.Path], shot: dict[str, Any], route: str, suffix: str = "", query_override: str = "", variant_index: int = 0) -> tuple[str, pathlib.Path, str]:
    variant_tag = "" if variant_index == 0 else "_v%d" % (variant_index + 1)
    sid = shot["shotId"] + suffix + variant_tag
    duration_ms = shot["endMs"] - shot["startMs"]
    public_dir = paths["public"] / "assets"
    mock_tag = (" " + sid) if getattr(provider, "mode", "") == "mock" else ""
    def reusable_video(path: pathlib.Path, request_signature: str) -> bool:
        from engine.qa import MEDIA_FIT_CRITERION_VERSION
        sidecar = pathlib.Path(str(path) + ".fit.json")
        request_sidecar = pathlib.Path(str(path) + ".request.json")
        if not path.exists() or path.stat().st_size <= 0 or not request_sidecar.exists():
            return False
        if read_json(request_sidecar).get("signature") != request_signature:
            return False
        if not sidecar.exists():
            # A provider may have completed immediately before a process stop.
            # Reuse the bytes and let the current local/semantic QA judge them.
            return True
        fit = read_json(sidecar)
        if fit.get("criterion_version") != MEDIA_FIT_CRITERION_VERSION:
            # Same requested asset, new judge criterion: reuse bytes and re-judge.
            return True
        if fit.get("asset_sha256") != sha256(path):
            return False
        # Reuse provider bytes even after a semantic rejection. The semantic
        # signature is checked by cached_media_fit below, so a refined proof can
        # re-judge the same footage without another download.
        return fit.get("fit") is True or fit.get("fit") is False or fit.get("reason") == "archivo no existe"
    if route == "clip_extractor":
        if str(shot.get("proofKind") or shot.get("mediaNeedKind") or "") not in {"real_event", "third_party_commentary", "cultural_reference"}:
            raise RuntimeError("Clip Extractor solo acepta un suceso o fuente real identificable")
        output = public_dir / (sid + "_clip.mp4")
        clip_query = (query_override or shot.get("clipQuery") or shot["query"] or shot["tts"]) + mock_tag
        request_signature = hashlib.sha256((clip_query + "|" + str(duration_ms)).encode("utf-8")).hexdigest()
        if reusable_video(output, request_signature):
            return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "video"
        provider.clip_extractor_clip(clip_query, duration_ms / 1000, str(output), characteristics={"orientation": "landscape", "resolution": "highest", "focus": shot["visualProof"], "must_have_visuals": [shot.get("hookRequirement") or shot["visualProof"]], "source_title": shot.get("sourceTitle"), "source_channel": shot.get("sourceChannel"), "source_url": shot.get("sourceUrl"), "proof_kind": shot.get("proofKind"), "avoid": ["watermark", "stock logo", "editor UI", "supplement bottle", "pills"]})
        write_json(pathlib.Path(str(output) + ".request.json"), {"signature": request_signature, "query": clip_query, "evidence_beat_id": shot.get("evidenceBeatId"), "media_need_kind": shot.get("mediaNeedKind"), "variant_index": variant_index})
        return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "video"
    if route == "pexels":
        output = public_dir / (sid + "_pexels.mp4")
        pexels_query = compact_pexels_query(query_override or shot.get("pexelsQuery") or shot.get("query") or "", shot) + mock_tag
        candidate_offset = max(0, int(variant_index))
        request_signature = hashlib.sha256((pexels_query + "|" + str(duration_ms) + "|candidate:" + str(candidate_offset)).encode("utf-8")).hexdigest()
        if reusable_video(output, request_signature):
            return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "video"
        provider.pexels_clip(pexels_query, duration_ms / 1000, str(output), characteristics={
            "media_need_kind": shot.get("mediaNeedKind"),
            "proof_kind": shot.get("proofKind"),
            "required_evidence": shot.get("requiredEvidence"),
            "requires_readable_data": bool(shot.get("requiresReadableData")),
            "temporal_action": shot.get("temporalAction"),
            "continuity_group": shot.get("continuityGroup"),
            "candidate_offset": candidate_offset,
        })
        write_json(pathlib.Path(str(output) + ".request.json"), {"signature": request_signature, "query": pexels_query, "evidence_beat_id": shot.get("evidenceBeatId"), "media_need_kind": shot.get("mediaNeedKind"), "variant_index": variant_index, "candidate_offset": candidate_offset})
        return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "video"
    if route == "cutout_motion":
        output = public_dir / (sid + "_cutout.mp4")
        cutout_script = query_override or shot.get("cutoutPrompt") or ""
        if not cutout_script or not (shot.get("stopMotion") or {}).get("eligible"):
            raise RuntimeError("cutout_motion requiere intención narrativa y coreografía compilada")
        style_scope = str(shot.get("designStyleScope") or data.get("_design_style_scope") or "project design profile")
        request_signature = hashlib.sha256((cutout_script + "|" + style_scope + "|" + str(duration_ms)).encode("utf-8")).hexdigest()
        if reusable_video(output, request_signature):
            return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "video"
        provider.cutout_clip(cutout_script, duration_ms / 1000, str(output), characteristics={
            "media_need_kind": shot.get("mediaNeedKind"),
            "evidence_mode": shot.get("evidenceMode"),
            "requires_readable_data": bool(shot.get("requiresReadableData")),
            "temporal_action": shot.get("temporalAction"),
            "continuity_group": shot.get("continuityGroup"),
            "expected_props": list(shot.get("cutoutProps") or []),
            "stop_motion_intent": str((shot.get("stopMotion") or {}).get("intent") or ""),
            "why_stop_motion": str((shot.get("stopMotion") or {}).get("why") or ""),
            "style_scope": style_scope,
            "client_ref": "%s:%s:%s" % (data["run_id"], sid, request_signature[:16]),
        })
        write_json(pathlib.Path(str(output) + ".request.json"), {"signature": request_signature, "script": cutout_script, "evidence_beat_id": shot.get("evidenceBeatId"), "media_need_kind": shot.get("mediaNeedKind"), "variant_index": variant_index})
        return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "video"
    if route == "omni":
        output = public_dir / (sid + "_omni.mp4")
        omni_prompt = (query_override or shot.get("omniPrompt") or shot["prompt"] or shot["visualProof"]) + ("\nNon-negotiable: " + shot["hookRequirement"] if shot.get("hookRequirement") else "") + mock_tag
        request_signature = hashlib.sha256((omni_prompt + "|" + str(duration_ms)).encode("utf-8")).hexdigest()
        if reusable_video(output, request_signature):
            return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "video"
        provider.omni_clip(omni_prompt, duration_ms / 1000, str(output))
        write_json(pathlib.Path(str(output) + ".request.json"), {"signature": request_signature, "prompt": omni_prompt, "evidence_beat_id": shot.get("evidenceBeatId"), "media_need_kind": shot.get("mediaNeedKind"), "variant_index": variant_index})
        return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "video"
    if route == "image_pair":
        output = public_dir / (sid + "_image_pair.png")
        left = public_dir / (sid + "_pair_a.png")
        right = public_dir / (sid + "_pair_b.png")
        raw_pair = query_override or shot.get("imagePairPrompt") or ""
        try:
            pair = json.loads(raw_pair)
        except Exception as exc:
            raise RuntimeError("image_pair requiere dos prompts estructurados: %s" % exc)
        if not isinstance(pair, dict) or not str(pair.get("left") or "").strip() or not str(pair.get("right") or "").strip():
            raise RuntimeError("image_pair incompleto: faltan left/right")
        if str(shot.get("textOwner") or "") == "remotion":
            clean_background = " No captions, no infographic, no labels, no callout boxes, no overlay text. Reserve clean negative space for editorial overlays."
            pair["left"] = str(pair["left"]) + clean_background
            pair["right"] = str(pair["right"]) + clean_background
        pair_signature = hashlib.sha256(json.dumps(pair, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        image_meta = pathlib.Path(str(output) + ".image_pair.json")
        if output.is_file() and image_meta.is_file() and read_json(image_meta).get("signature") == pair_signature:
            return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "image"
        provider.image_clip(str(pair["left"]), str(left))
        provider.image_clip(str(pair["right"]), str(right))
        if not left.is_file() or not right.is_file():
            raise RuntimeError("image_pair no produjo ambos estados")
        panel_width = (WIDTH - 24) // 2
        with Image.open(left).convert("RGB") as left_image, Image.open(right).convert("RGB") as right_image:
            pair_bg = str(((data.get("_design_profile") or {}).get("tokens") or {}).get("colors", {}).get("background") or "#0A0A0A")
            canvas = Image.new("RGB", (WIDTH, HEIGHT), pair_bg)
            canvas.paste(ImageOps.fit(left_image, (panel_width, HEIGHT), method=Image.Resampling.LANCZOS), (0, 0))
            canvas.paste(ImageOps.fit(right_image, (panel_width, HEIGHT), method=Image.Resampling.LANCZOS), (panel_width + 24, 0))
            canvas.save(output, format="PNG", optimize=True)
        write_json(image_meta, {"signature": pair_signature, "prompts": pair, "sources": [str(left), str(right)], "continuity_group": shot.get("continuityGroup"), "evidence_beat_id": shot.get("evidenceBeatId"), "variant_index": variant_index})
        return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "image"
    output = public_dir / (sid + "_image.png")
    image_prompt = (query_override or shot["prompt"] or ("Landscape 16:9 editorial visual, no text, no logos. " + shot["visualProof"])) + ("\nNon-negotiable: " + shot["hookRequirement"] if shot.get("hookRequirement") else "") + mock_tag
    if str(shot.get("textOwner") or "") == "remotion":
        image_prompt += "\nNo captions, no infographic, no callout boxes, no explanatory overlay text. Any incidental package label must remain minimal and confined to the package. Reserve the declared overlay zone as clean negative space."
    image_meta = pathlib.Path(str(output) + ".image.json")
    image_signature = hashlib.sha256(image_prompt.encode("utf-8")).hexdigest()
    if output.exists() and output.stat().st_size > 0 and not image_meta.exists() and not shot.get("hookRequirement"):
        # One-time adoption: legacy images are still forced through current media-fit.
        write_json(image_meta, {"signature": image_signature, "prompt": image_prompt, "legacy_adopted": True})
    if output.exists() and output.stat().st_size > 0 and image_meta.is_file() and read_json(image_meta).get("signature") == image_signature:
        return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "image"
    provider.image_clip(image_prompt, str(output))
    write_json(image_meta, {"signature": image_signature, "prompt": image_prompt, "evidence_beat_id": shot.get("evidenceBeatId"), "media_need_kind": shot.get("mediaNeedKind"), "variant_index": variant_index})
    return "runs/%s/assets/%s" % (data["run_id"], output.name), output, "image"


def _tokens(value: str) -> set[str]:
    stop = {"para", "como", "esta", "este", "esto", "sobre", "mujer", "plano", "video", "clip", "body", "woman", "with", "from", "that"}
    return {token for token in re.findall(r"[a-záéíóúñ0-9]+", str(value).lower()) if len(token) > 3 and token not in stop}


def matching_user_clips(data: dict[str, Any], shot: dict[str, Any], used_user_clips: set[str]) -> list[dict[str, Any]]:
    target = _tokens(" ".join([shot.get("tts", ""), shot.get("visualProof", ""), shot.get("query", "")]))
    ranked = []
    for index, clip in enumerate(data.get("user_clips") or []):
        raw = pathlib.Path(str(clip["path"]))
        source = raw if raw.is_absolute() else pathlib.Path(data["_input_dir"]) / raw
        key = str(source.resolve()).lower()
        if key in used_user_clips or not source.is_file():
            continue
        explicit = shot["shotId"] in (clip.get("shot_ids") or [])
        overlap = len(target & _tokens(clip.get("description", "")))
        if explicit or overlap:
            ranked.append((1000 if explicit else overlap, -index, {**clip, "_source": source.resolve(), "_key": key}))
    return [row[2] for row in sorted(ranked, reverse=True)]


def attach_prefilter_metadata(shot: dict[str, Any], report: dict[str, Any]) -> None:
    metrics = report.get("metrics") or {}
    shot["assetOcrText"] = str(report.get("ocr_text") or "")[:1000]
    shot["assetOcrAvailable"] = bool(metrics.get("ocr_available"))
    shot["assetOcrWords"] = int(metrics.get("ocr_words") or 0)


EXTERNAL_MEDIA_ROUTES = {"clip_extractor", "pexels", "image", "image_pair", "cutout_motion", "omni"}
DETERMINISTIC_MEDIA_ROUTES = {"ui", "motion-card"}


def provider_routes_before_deterministic(shot: dict[str, Any]) -> list[str]:
    full_routes = list(shot.get("companionRoutePlan") or shot.get("routePlan") or [])
    proof_kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
    if proof_kind not in {"real_event", "third_party_commentary", "cultural_reference"}:
        full_routes = [route for route in full_routes if route != "clip_extractor"]
    routes: list[str] = []
    for index, route in enumerate(full_routes):
        if route in EXTERNAL_MEDIA_ROUTES:
            routes.append(route)
        elif route in DETERMINISTIC_MEDIA_ROUTES and routes:
            # When a real-footage route was deliberately selected to break a
            # graphic sequence, exhaust both bounded real-footage providers
            # before falling back to deterministic graphics.
            if routes[0] in {"clip_extractor", "pexels"}:
                routes.extend(candidate for candidate in full_routes[index + 1:] if candidate in {"clip_extractor", "pexels"} and candidate not in routes)
            break
    return routes


def still_image_forbidden(shot: dict[str, Any]) -> bool:
    """Forbid stills only when the transition path itself is required evidence."""
    return bool(shot.get("requiresObservedTransition"))


def deterministic_fallback_route(shot: dict[str, Any]) -> str:
    proof_kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
    if proof_kind not in {"abstract_concept", "physiological_mechanism", "comparison", "exact_ui_state", "product_inspection", "human_action"}:
        return ""
    full_routes = list(shot.get("companionRoutePlan") or shot.get("routePlan") or [])
    if proof_kind == "product_inspection" and shot.get("hybridTemplate"):
        # A pure CSS/UI fallback would recreate the fake package defect this
        # contract is designed to prevent. Keep the real/generated package as
        # a hard dependency of the hybrid.
        return ""
    if proof_kind == "human_action" and not shot.get("requiresObservedTransition"):
        return ""
    if shot.get("beatRole") == "proof":
        return "ui" if "ui" in full_routes else ""
    return next((route for route in full_routes if route in DETERMINISTIC_MEDIA_ROUTES), "")


def resolve_support_asset(provider: Any, data: dict[str, Any], paths: dict[str, pathlib.Path], shot: dict[str, Any], used_hashes: set[str], used_user_clips: set[str], used_visuals: list[tuple[str, list[int]]], suffix: str = "", beat_feedback: dict[str, dict[str, Any]] | None = None) -> tuple[str, pathlib.Path, str, str]:
    failures = []
    telemetry = ProviderTelemetry(paths.get("work", paths["public"].parent) / "provider_events.jsonl")
    scene_started = time.monotonic()
    total_budget = float(os.environ.get("LONGFORM_SCENE_ASSET_BUDGET_SECONDS", "180"))
    deadline = scene_started + total_budget
    search_route_budgets = {
        "clip_extractor": float(os.environ.get("LONGFORM_CLIP_EXTRACTOR_BUDGET_SECONDS", "70")),
        "pexels": float(os.environ.get("LONGFORM_PEXELS_BUDGET_SECONDS", "35")),
    }
    evidence_beat_id = str(shot.get("evidenceBeatId") or "")
    beat_id = "%s:%s" % (evidence_beat_id, str(shot.get("shotId") or ""))
    feedback_store = beat_feedback if beat_feedback is not None else {}
    beat_state = feedback_store.setdefault(beat_id, {"rejected_because": [], "next_query_constraints": [], "directed_retry_used": False})
    for clip in matching_user_clips(data, shot, used_user_clips):
        try:
            output = paths["public"] / "assets" / (shot["shotId"] + suffix + "_user.mp4")
            normalize_user_clip(clip["_source"], output, shot["endMs"] - shot["startMs"], int(clip.get("start_ms") or 0))
            meta = ffprobe(output)
            needed = shot["endMs"] - shot["startMs"]
            if meta["duration_ms"] + 100 < needed:
                raise RuntimeError("clip del usuario corto %dms < %dms" % (meta["duration_ms"], needed))
            digest = sha256(output)
            if digest in used_hashes:
                raise RuntimeError("clip del usuario duplicado por SHA-256")
            fingerprints = visual_fingerprints(output, "video")
            duplicate_of = perceptual_duplicate(fingerprints, used_visuals)
            if duplicate_of:
                raise RuntimeError("clip visualmente repetido de %s" % duplicate_of)
            rel = "runs/%s/assets/%s" % (data["run_id"], output.name)
            cheap = media_prefilter(output, "video", shot, "user")
            write_json(pathlib.Path(str(output) + ".prefilter.json"), cheap)
            if cheap["status"] != "PASS":
                raise RuntimeError("prefilter: %s" % "; ".join(cheap["errors"]))
            fit, reason = cached_media_fit(output, rel, shot, "user")
            if not fit:
                raise RuntimeError("media-fit rechazo: %s" % reason)
            used_hashes.add(digest)
            used_visuals.append((shot["shotId"] + suffix, fingerprints))
            used_user_clips.add(clip["_key"])
            attach_prefilter_metadata(shot, cheap)
            telemetry.emit(provider="user", scene=shot["shotId"] + suffix, query_or_prompt=str(clip.get("description") or shot.get("visualProof") or ""), result="selected", asset_before=str(clip["_source"]), asset_after=str(output), estimated_cost_usd=0)
            return rel, output, "video", "user"
        except Exception as exc:
            failures.append("user: %s" % str(exc)[:180])
            telemetry.emit(provider="user", scene=shot["shotId"] + suffix, query_or_prompt=str(clip.get("description") or ""), result="rejected", rejection_reason=str(exc), asset_before=str(clip.get("_source") or ""), estimated_cost_usd=0)
    library_query = " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof", "query", "prompt"))
    library_candidates = [] if getattr(provider, "mode", "") == "mock" or shot.get("skipLibrary") else asset_library.search(library_query, kinds=("video", "image"), run_id=data["run_id"], used_hashes=used_hashes, limit=3)
    for candidate in library_candidates:
        try:
            source = pathlib.Path(candidate["path"])
            media_type = str(candidate["kind"])
            if still_image_forbidden(shot) and media_type != "video":
                continue
            output = paths["public"] / "assets" / (shot["shotId"] + suffix + "_library" + source.suffix.lower())
            if media_type == "video":
                normalize_user_clip(source, output, shot["endMs"] - shot["startMs"])
                if ffprobe(output)["duration_ms"] + 100 < shot["endMs"] - shot["startMs"]:
                    raise RuntimeError("asset de biblioteca demasiado corto")
            else:
                shutil.copy2(source, output)
            digest = sha256(output)
            fingerprints = visual_fingerprints(output, media_type)
            duplicate_of = perceptual_duplicate(fingerprints, used_visuals)
            if digest in used_hashes or duplicate_of:
                raise RuntimeError("asset de biblioteca repetido")
            rel = "runs/%s/assets/%s" % (data["run_id"], output.name)
            cheap = media_prefilter(output, media_type, shot, "library")
            write_json(pathlib.Path(str(output) + ".prefilter.json"), cheap)
            if cheap["status"] != "PASS":
                raise RuntimeError("prefilter: %s" % "; ".join(cheap["errors"]))
            fit, reason = cached_media_fit(output, rel, shot, "library")
            if not fit:
                raise RuntimeError("media-fit rechazo: %s" % reason)
            used_hashes.add(digest)
            used_visuals.append((shot["shotId"] + suffix, fingerprints))
            asset_library.mark_used(int(candidate["id"]), data["run_id"], shot["shotId"] + suffix)
            shot["libraryOriginalProvider"] = str(candidate.get("provider") or "unknown")
            shot["librarySourceUrl"] = str(candidate.get("source_url") or "")
            shot["libraryLicense"] = str(candidate.get("license") or "")
            attach_prefilter_metadata(shot, cheap)
            telemetry.emit(provider="library", scene=shot["shotId"] + suffix, query_or_prompt=library_query, result="selected", asset_before=str(source), asset_after=str(output), estimated_cost_usd=0, metadata={"library_asset_id": candidate.get("id"), "original_provider": shot["libraryOriginalProvider"], "source_url": shot["librarySourceUrl"], "license": shot["libraryLicense"]})
            return rel, output, media_type, "library"
        except Exception as exc:
            failures.append("library: %s" % str(exc)[:180])
            telemetry.emit(provider="library", scene=shot["shotId"] + suffix, query_or_prompt=library_query, result="rejected", rejection_reason=str(exc), asset_before=str(candidate.get("path") or ""), estimated_cost_usd=0, metadata={"library_asset_id": candidate.get("id")})
    routes = provider_routes_before_deterministic(shot)
    if not routes:
        requested = str(shot.get("companionRoute") or shot.get("route") or "")
        if requested in EXTERNAL_MEDIA_ROUTES:
            routes = [requested]
        else:
            raise RuntimeError("el contrato no autoriza providers externos para %s" % (shot.get("proofKind") or shot.get("mediaNeedKind")))
    if still_image_forbidden(shot):
        routes = [route for route in routes if route not in {"image", "image_pair"}]
    runtime = ProviderRuntime(paths.get("work", paths["public"].parent) / "provider_runtime.json")
    from engine.qa import MEDIA_FIT_CRITERION_VERSION
    sid = shot["shotId"] + suffix
    cached_names = {"clip_extractor": sid + "_clip.mp4", "pexels": sid + "_pexels.mp4", "image": sid + "_image.png", "image_pair": sid + "_image_pair.png", "cutout_motion": sid + "_cutout.mp4", "omni": sid + "_omni.mp4"}

    def cached_route_paths(route: str) -> list[pathlib.Path]:
        base = paths["public"] / "assets" / cached_names[route]
        tail = cached_names[route][len(sid):]
        variants = sorted(
            (path for path in (paths["public"] / "assets").glob("%s_v*%s" % (sid, tail)) if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [base] + [path for path in variants if path != base]

    for cached_route in routes:
        approved = False
        for cached_path in cached_route_paths(cached_route):
            fit_path = pathlib.Path(str(cached_path) + ".fit.json")
            if not cached_path.is_file() or not fit_path.is_file():
                continue
            if not cached_generated_request_matches(cached_path, shot, cached_route):
                continue
            cached_rel = "runs/%s/assets/%s" % (data["run_id"], cached_path.name)
            fit_ok, _ = cached_media_fit(cached_path, cached_rel, shot, cached_route)
            if fit_ok:
                approved = True
                break
        if approved:
            # A current approved asset proves earlier rungs were exhausted in this run.
            routes = routes[routes.index(cached_route):]
            print("[longform] %s reanuda desde asset aprobado %s" % (shot["shotId"], cached_route))
            break
    search_video_candidates = {"clip_extractor": 0, "pexels": 0}
    generated_video_candidates = 0
    directed_retry_used = bool(beat_state.get("directed_retry_used"))
    feedback_constraints: list[str] = list(beat_state.get("next_query_constraints") or [])
    compiled_with_feedback = None
    if feedback_constraints:
        revised = dict(shot)
        compile_all(revised, feedback_constraints)
        compiled_with_feedback = revised.get("queryVariants") or {}
    accepted_candidates: list[dict[str, Any]] = []

    def finalize_candidate(candidate: dict[str, Any]) -> tuple[str, pathlib.Path, str, str]:
        path = candidate["path"]
        media_type = candidate["media_type"]
        route = candidate["route"]
        digest = candidate["digest"]
        fingerprints = candidate["fingerprints"]
        query_value = candidate["query"]
        used_hashes.add(digest)
        used_visuals.append((shot["shotId"] + suffix, fingerprints))
        meta = ffprobe(path) if media_type == "video" else {"width": WIDTH, "height": HEIGHT, "duration_ms": 0}
        library_id = asset_library.register(path, kind=media_type, description=str(shot.get("visualProof") or shot.get("tts") or ""), provider=route,
                               tags=sorted(_tokens(library_query)), objects=sorted(_tokens(str(shot.get("visualProof") or ""))),
                               actions=sorted(_tokens(str(shot.get("tts") or ""))), prompt_query=query_value,
                               width=int(meta.get("width") or 0), height=int(meta.get("height") or 0), duration_ms=int(meta.get("duration_ms") or 0),
                               license_name="owned generated cutout" if route == "cutout_motion" else "provider terms; see source manifest", ocr_text=str(candidate["prefilter"].get("ocr_text") or ""), visual_fingerprints=fingerprints)
        asset_library.mark_used(library_id, data["run_id"], shot["shotId"] + suffix)
        shot["candidateSelection"] = {"winner": route, "score": candidate["ranking"]["score"], "quality": candidate["ranking"]["quality"], "considered": [{"provider": item["route"], "variant": item["variant_index"] + 1, "score": item["ranking"]["score"], "quality": item["ranking"]["quality"]} for item in accepted_candidates]}
        attach_prefilter_metadata(shot, candidate["prefilter"])
        runtime.telemetry.emit(provider=route, scene=shot["shotId"] + suffix, query_or_prompt=query_value, result="selected", asset_after=str(path), estimated_cost_usd=0, metadata={"stage": "ranked_final_selection", "evidence_beat_id": beat_id, "library_asset_id": library_id, "ranking": candidate["ranking"]})
        return candidate["rel"], path, media_type, route

    manager = ProviderManager(paths.get("work", paths["public"].parent) / "provider_manager.json") if production_mode() else None
    for route_index, route in enumerate(routes):
        if time.monotonic() >= deadline:
            failures.append("presupuesto temporal de escena agotado")
            break
        for cached_path in cached_route_paths(route):
            cached_rel = "runs/%s/assets/%s" % (data["run_id"], cached_path.name)
            cached_media_type = "image" if cached_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else "video"
            if not cached_path.is_file():
                continue
            if not cached_generated_request_matches(cached_path, shot, route):
                continue
            cached_fit, _ = cached_media_fit(cached_path, cached_rel, shot, route)
            if cached_fit:
                cheap = media_prefilter(cached_path, cached_media_type, shot, route)
                if getattr(provider, "mode", "") == "mock" and cheap["status"] != "PASS":
                    cheap = {**cheap, "status": "PASS", "warnings": list(cheap.get("warnings") or []) + ["mock fixture: " + "; ".join(cheap.get("errors") or [])], "errors": []}
                digest = sha256(cached_path)
                fingerprints = provider_fingerprints(cached_path, cached_media_type, provider)
                duplicate_of = perceptual_duplicate(fingerprints, used_visuals)
                duration_ok = cached_media_type != "video" or ffprobe(cached_path)["duration_ms"] + 100 >= shot["endMs"] - shot["startMs"]
                if cheap["status"] == "PASS" and digest not in used_hashes and not duplicate_of and duration_ok:
                    query_value = str(((shot.get("queryVariants") or {}).get(route) or [shot.get("prompt") or shot.get("visualProof") or ""])[0])
                    ranking = score_candidate(shot, route, cheap, route_index=route_index, variant_index=0)
                    candidate = {"rel": cached_rel, "path": cached_path, "media_type": cached_media_type, "route": route, "digest": digest, "fingerprints": fingerprints, "query": query_value, "variant_index": 0, "prefilter": cheap, "ranking": ranking}
                    accepted_candidates.append(candidate)
                    runtime.telemetry.emit(provider=route, scene=shot["shotId"] + suffix, query_or_prompt=query_value, result="cache_hit", asset_after=str(cached_path), estimated_cost_usd=0, metadata={"stage": "approved_cache_before_provider", "evidence_beat_id": beat_id, "ranking": ranking})
                    return finalize_candidate(candidate)
        if manager and route in manager.specs:
            readiness = manager.ensure(route)
            if readiness.get("status") != "healthy":
                failures.append("%s: provider %s" % (route, readiness.get("status")))
                continue
        route_deadline = min(deadline, time.monotonic() + search_route_budgets.get(route, total_budget))
        variants = list((compiled_with_feedback or shot.get("queryVariants") or {}).get(route) or [])[:3]
        if not variants:
            route_defaults = {
                "clip_extractor": shot.get("clipQuery"),
                "pexels": shot.get("pexelsQuery"),
                "image": shot.get("prompt"),
                "image_pair": shot.get("imagePairPrompt"),
                "cutout_motion": shot.get("cutoutPrompt"),
                "omni": shot.get("omniPrompt"),
            }
            variants = [str(route_defaults.get(route) or library_query)]
        variant_index = 0
        while variant_index < len(variants):
            if time.monotonic() >= deadline:
                failures.append("%s: presupuesto temporal de escena agotado" % route)
                break
            if route in {"clip_extractor", "pexels"} and time.monotonic() >= route_deadline:
                failures.append("%s: presupuesto propio de busqueda agotado" % route)
                break
            if route in {"clip_extractor", "pexels"} and search_video_candidates[route] >= 2:
                failures.append("%s: presupuesto de 2 candidatos del proveedor agotado" % route)
                break
            if route == "omni" and generated_video_candidates >= 1:
                failures.append("omni: presupuesto de 1 generacion por beat agotado")
                break
            query_value = variants[variant_index]
            try:
                signature = hashlib.sha256((route + "|" + query_value + "|" + str(shot["endMs"] - shot["startMs"])).encode("utf-8")).hexdigest()
                rel, path, media_type = runtime.call(
                    route,
                    signature,
                    lambda route=route, query_value=query_value, variant_index=variant_index: create_asset(provider, data, paths, shot, route, suffix=suffix, query_override=query_value, variant_index=variant_index),
                    scene=str(shot.get("shotId") or ""),
                    query_or_prompt=query_value,
                    estimated_cost_usd=0.0 if getattr(provider, "mode", "") == "mock" else None,
                    metadata={"evidence_beat_id": shot.get("evidenceBeatId"), "variant_index": variant_index, "media_need_kind": shot.get("mediaNeedKind")},
                )
                if media_type == "video" and route in {"clip_extractor", "pexels"}:
                    search_video_candidates[route] += 1
                if media_type == "video" and route == "omni":
                    generated_video_candidates += 1
                cheap = media_prefilter(path, media_type, shot, route)
                if getattr(provider, "mode", "") == "mock" and cheap["status"] != "PASS":
                    cheap = {**cheap, "status": "PASS", "warnings": list(cheap.get("warnings") or []) + ["mock fixture: " + "; ".join(cheap.get("errors") or [])], "errors": []}
                write_json(pathlib.Path(str(path) + ".prefilter.json"), cheap)
                if cheap["status"] != "PASS":
                    reason = "prefilter: " + "; ".join(cheap["errors"])
                    runtime.telemetry.emit(provider=route, scene=shot["shotId"], query_or_prompt=query_value, result="rejected", rejection_reason=reason, asset_after=str(path), estimated_cost_usd=0, metadata={"stage": "prefilter", "evidence_beat_id": shot.get("evidenceBeatId")})
                    raise RuntimeError(reason)
                digest = sha256(path)
                if digest in used_hashes:
                    raise RuntimeError("asset duplicado por SHA-256")
                fingerprints = provider_fingerprints(path, media_type, provider)
                duplicate_of = perceptual_duplicate(fingerprints, used_visuals)
                if duplicate_of:
                    raise RuntimeError("asset visualmente repetido de %s" % duplicate_of)
                if media_type == "video":
                    meta = ffprobe(path)
                    needed = shot["endMs"] - shot["startMs"]
                    if meta["duration_ms"] + 100 < needed:
                        raise RuntimeError("clip corto %dms < %dms" % (meta["duration_ms"], needed))
                    if (meta["width"], meta["height"]) != (WIDTH, HEIGHT):
                        raise RuntimeError("video no normalizado: %dx%d" % (meta["width"], meta["height"]))
                fit, reason = cached_media_fit(path, rel, shot, route)
                if not fit:
                    feedback = rejection_feedback(reason)
                    runtime.telemetry.emit(provider=route, scene=shot["shotId"], query_or_prompt=query_value, result="rejected", rejection_reason=reason, asset_after=str(path), estimated_cost_usd=0, metadata={"stage": "semantic_qa", **feedback})
                    raise RuntimeError("media-fit rechazo: %s" % reason)
                ranking = score_candidate(shot, route, cheap, route_index=route_index, variant_index=variant_index)
                accepted_candidates.append({"rel": rel, "path": path, "media_type": media_type, "route": route, "digest": digest, "fingerprints": fingerprints, "query": query_value, "variant_index": variant_index, "prefilter": cheap, "ranking": ranking})
                runtime.telemetry.emit(provider=route, scene=shot["shotId"], query_or_prompt=query_value, result="accepted_candidate", asset_after=str(path), estimated_cost_usd=0, metadata={"stage": "candidate_ranking", "ranking": ranking})
                variant_index += 1
                route_candidates = [item for item in accepted_candidates if item["route"] == route]
                if route not in {"clip_extractor", "pexels"} or len(route_candidates) >= 2 or ranking["score"] >= 98:
                    break
                continue
            except Exception as exc:
                failures.append("%s[v%d]: %s" % (route, variant_index + 1, str(exc)[:180]))
                print("[longform] %s %s v%d fallo: %s" % (shot["shotId"], route, variant_index + 1, str(exc)[:130]))
                if not directed_retry_used:
                    feedback = rejection_feedback(str(exc))
                    directed_retry_used = True
                    feedback_constraints = feedback["next_query_constraints"]
                    beat_state["directed_retry_used"] = True
                    beat_state["rejected_because"] = sorted(set((beat_state.get("rejected_because") or []) + feedback["rejected_because"]))
                    beat_state["next_query_constraints"] = sorted(set((beat_state.get("next_query_constraints") or []) + feedback_constraints))
                    revised = dict(shot)
                    compile_all(revised, beat_state["next_query_constraints"])
                    variants = list((revised.get("queryVariants") or {}).get(route) or variants)[:3]
                variant_index += 1
                if directed_retry_used and variant_index >= 2:
                    break
        route_candidates = [item for item in accepted_candidates if item["route"] == route]
        if route_candidates:
            winner = choose_best(route_candidates)
            if len(route_candidates) >= 2 or winner["ranking"]["score"] >= 92 or route_index == len(routes) - 1:
                return finalize_candidate(winner)
    if accepted_candidates:
        return finalize_candidate(choose_best(accepted_candidates))
    raise RuntimeError("asset ladder agotada para %s | %s" % (shot["shotId"], " | ".join(failures)))


def sanitize_avatar_companion(shot: dict[str, Any], companion: dict[str, Any]) -> dict[str, Any]:
    """Keep presenter-only constraints out of the visual used when avatar fails."""
    clean = json.loads(json.dumps(companion or {}))
    summary_text = " ".join(str(shot.get(key) or "") for key in ("tts", "screenCopy", "visualProof")).lower()
    if "cuatro preguntas" in summary_text or "4 preguntas" in summary_text:
        return {
            "proofKind": "abstract_concept", "mediaNeedKind": "abstract_concept", "beatRole": "pattern_interrupt",
            "requiredEvidence": "Shows the four purchase questions explicitly when the presenter is unavailable.",
            "preferredMedium": "ui", "route": "ui", "routePlan": ["ui"], "fallbackStrategy": "deterministic-ui",
            "peoplePolicy": "forbidden", "presenterAllowed": False, "maxFaceAreaRatio": 0.0,
            "evidenceMustRemainDominant": True, "uiTemplate": "process-steps", "uiVariant": "four-questions",
            "screenCopy": "4 PREGUNTAS",
            "uiItems": ["¿QUÉ PROMETE?", "¿QUÉ CONTIENE?", "¿EN CUÁNTO TIEMPO?", "¿TU PIEL LO TOLERA?"],
            "uiValues": ["PROMESA", "INGREDIENTES", "PLAZO", "TOLERANCIA"],
            "forbiddenSubstitutions": ["single-label", "generic-motion-card"],
        }
    kind = str(clean.get("proofKind") or clean.get("mediaNeedKind") or "").strip().lower()
    if kind == "presenter" or not kind:
        seed = dict(shot)
        for key in ("proofKind", "mediaNeedKind", "peoplePolicy", "presenterAllowed", "maxFaceAreaRatio", "evidenceMustRemainDominant"):
            seed.pop(key, None)
        kind = infer_media_need(seed, {"visual_proof": shot.get("visualProof")})
        if kind == "presenter":
            kind = "abstract_concept"
        clean["proofKind"] = kind
        clean["mediaNeedKind"] = kind
    people_policy = "contextual" if kind in {"human_action", "real_event", "third_party_commentary", "cultural_reference", "comparison"} else "forbidden"
    clean["peoplePolicy"] = people_policy
    clean["presenterAllowed"] = False
    clean["maxFaceAreaRatio"] = 0.20 if people_policy == "contextual" else 0.0
    clean["evidenceMustRemainDominant"] = True
    if "presenter" in str(clean.get("requiredEvidence") or "").lower():
        clean["requiredEvidence"] = str(shot.get("visualProof") or shot.get("tts") or "").strip()[:360]
    clean["routePlan"] = [route for route in (clean.get("routePlan") or shot.get("companionRoutePlan") or []) if route != "avatar"]
    if not clean["routePlan"]:
        clean["routePlan"] = route_order(kind, readable=bool(shot.get("requiresReadableData")), continuity=bool(shot.get("requiresStateContinuity")), temporal_action=str(shot.get("temporalAction") or "single"))
    clean["route"] = next((route for route in clean["routePlan"] if route != "avatar"), "motion-card")
    clean["preferredMedium"] = clean["route"]
    return clean


def upgrade_visual_plan(data: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Migrate resumable runs without regenerating or touching approved narration."""
    design_profile = data.get("_design_profile") or resolve_design_profile(data, pathlib.Path(ROOT) / "work" / "design_profiles")
    design_scope = design_prompt_scope(design_profile)
    product = product_context(data)
    cream_project = "crema" in (str(data.get("title") or "") + " " + product["name"]).lower()
    plan["thumbnailPromise"] = data["thumbnail_promise"]
    plan["providerMode"] = "real" if production_mode() else "mock"
    plan["designProfileId"] = design_profile.get("id")
    plan["designProfile"] = design_profile
    plan["designTheme"] = remotion_theme(design_profile)
    plan["designStyleScope"] = design_scope
    avatar_ids = {
        shot.get("shotId")
        for shot in plan.get("shots") or []
        if shot.get("route") == "avatar"
        or shot.get("visualKind") == "avatar-full"
        or shot.get("avatarRequested") is True
        or shot.get("avatarFallback") is True
        or str(shot.get("noveltyKey") or "").startswith("presenter-")
    }
    for shot in plan.get("shots") or []:
        if shot.get("shotId") not in avatar_ids:
            continue
        companion = dict(shot.get("companionContract") or {})
        if not companion:
            for key in ("proofKind", "mediaNeedKind"):
                shot.pop(key, None)
            normalize_media_contract(shot, {"route": next((route for route in (shot.get("companionRoutePlan") or []) if route != "avatar"), "")})
            companion = {key: json.loads(json.dumps(shot.get(key))) for key in (
                "proofKind", "mediaNeedKind", "beatRole", "requiredEvidence", "preferredMedium",
                "forbiddenSubstitutions", "peoplePolicy", "presenterAllowed", "maxFaceAreaRatio",
                "evidenceMustRemainDominant", "route", "routePlan", "queryVariants", "uiSpec", "motionSpec",
            ) if key in shot}
        companion = sanitize_avatar_companion(shot, companion)
        shot["companionContract"] = companion
        shot.update(companion)
    for shot in plan.get("shots") or []:
        current_clip_query = str(shot.get("clipQuery") or "").strip()
        if not current_clip_query:
            current_clip_query = str(shot.get("query") or shot.get("visualProof") or shot.get("tts") or "")
        shot["clipQuery"] = current_clip_query[:500]
        shot["pexelsQuery"] = compact_pexels_query(shot.get("pexelsQuery") or shot.get("query") or "", shot)
        if "crema" in str(data.get("title") or "").lower() and any(term in (str(shot.get("tts") or "") + " " + str(shot.get("visualProof") or "")).lower() for term in ("etiqueta", "ingrediente", "envase", "frasco", "tarro", "botella", "label", "package")):
            shot["pexelsQuery"] = "body lotion label"
            packaging_requirement = "Si aparece un envase como sujeto visible, debe tener una etiqueta comercial ficticia coherente: marca %s, producto %s y contenido %s. Rechaza envases visiblemente blancos o sin etiqueta, texto absurdo perceptible y logos de marcas reales." % (product["brand"], product["name"], product["size"] or "plausible")
            if packaging_requirement not in str(shot.get("hookRequirement") or ""):
                shot["hookRequirement"] = " ".join(filter(None, (shot.get("hookRequirement"), packaging_requirement)))
            if packaging_requirement not in str(shot.get("prompt") or ""):
                shot["prompt"] = (shot.get("prompt") or "") + "\nNon-negotiable: " + packaging_requirement
    if plan.get("shots") and cream_project:
        plan["shots"][0]["screenCopy"] = str(data["thumbnail_promise"])[:48]
        plan["shots"][0]["subcopy"] = "MIRA EL ENVASE"
        plan["shots"][0]["visualProof"] = "A readable body-cream package is inspected before purchase; the topical product is unmistakable."
        plan["shots"][0]["requiredEvidence"] = "A front-facing open body-cream jar with a large readable fictional label validates the purchase-inspection promise in the first three seconds."
        plan["shots"][0]["hookRequirement"] = "Debe verse inequívocamente un cosmético tópico: tarro o tubo de crema corporal, idealmente con crema visible. El envase debe mostrar una etiqueta comercial ficticia, coherente y legible en español; nunca puede estar blanco o sin etiqueta. Rechaza botellas de suplemento, cápsulas, tabletas, productos capilares y logos de marcas reales."
        plan["shots"][0]["clipQuery"] = "macro close-up, a hand opens an unbranded body cream jar and touches visible white cream, cosmetic jar centered, no pills, no logos, no watermark"
        plan["shots"][0]["pexelsQuery"] = "body cream jar"
        plan["shots"][0]["prompt"] = "Landscape 16:9 premium editorial close-up of an open topical cosmetic with product visible. Packaging has a realistic coherent fictional label: %s / %s / %s. No visibly blank packaging, no pills, no real trademark." % (product["brand"], product["name"], product["size"])
        plan["shots"][0]["movingVisualRequired"] = False
        plan["shots"][0]["proofKindLocked"] = True
    for shot in plan.get("shots") or []:
        shot["designStyleScope"] = design_scope
        normalize_media_contract(shot, {"route": shot.get("companionRoute") or shot.get("route")})
        exact_label = "crema" in str(data.get("title") or "").lower() and any(term in (str(shot.get("tts") or "") + " " + str(shot.get("visualProof") or "")).lower() for term in ("etiqueta", "label", "distingue", "promesa", "promete", "absoluto", "contenido", "eliminar grasa"))
        if exact_label and shot.get("shotId") not in avatar_ids:
            shot.update({"proofKind": "product_inspection", "mediaNeedKind": "product_inspection", "proofKindLocked": True, "requiresReadableData": True, "route": "ui", "routePlan": ["ui", "image"], "fallbackStrategy": "deterministic-ui", "uiTemplate": "product-inspection", "uiItems": ["PROMESA", "TIPO", "CONTENIDO"], "uiValues": ["REVISA", product["name"], product["size"]], "productBrand": product["brand"], "productName": product["name"], "productSize": product["size"]})
    if plan.get("shots") and cream_project:
        plan["shots"][0].update({
            "proofKind": "product_inspection",
            "mediaNeedKind": "product_inspection",
            "proofKindLocked": True,
            "requiresReadableData": False,
            "route": "image",
            "routePlan": ["image", "pexels", "omni"],
            "fallbackStrategy": "bounded-provider-search",
            "productBrand": product["brand"],
            "productName": product["name"],
            "productSize": product["size"],
        })
    apply_filmable_overrides(plan.get("shots") or [], product)
    apply_purchase_evidence_routes(plan.get("shots") or [], product)
    apply_early_context_broll(data, plan.get("shots") or [])
    apply_closing_distinction_route(plan.get("shots") or [])
    apply_cta_end_screen_route(data, plan.get("shots") or [])
    align_observable_evidence_contracts(plan.get("shots") or [])
    locked_avatar_companions = {
        str(shot.get("shotId") or ""): json.loads(json.dumps(shot.get("companionContract") or {}))
        for shot in plan.get("shots") or []
        if shot.get("shotId") in avatar_ids and shot.get("draftRepair") and shot.get("companionContract")
    }
    for shot in plan.get("shots") or []:
        normalize_media_contract(shot, shot)
    assign_evidence_beats(plan.get("shots") or [])
    balance_graphic_routes(plan.get("shots") or [])
    direct_plan(plan.get("shots") or [])
    apply_learning_biases(plan.get("shots") or [])
    for shot in plan.get("shots") or []:
        shot["continuityLock"] = str(shot.get("continuityLock") or ("preserve all declared state in %s" % shot["continuityGroup"] if shot.get("continuityGroup") else ""))
        restore_directed_repair_media(shot)
        enforce_hard_route_priority(shot)
        compile_all(shot)
        apply_motion_contract(shot, shot)
        normalize_visual_composition(shot)
        if shot.get("shotId") in avatar_ids:
            requested_companion = locked_avatar_companions.get(str(shot.get("shotId") or "")) or {key: json.loads(json.dumps(shot.get(key))) for key in (
                "proofKind", "mediaNeedKind", "beatRole", "requiredEvidence", "preferredMedium",
                "forbiddenSubstitutions", "peoplePolicy", "presenterAllowed", "maxFaceAreaRatio",
                "evidenceMustRemainDominant", "route", "routePlan", "queryVariants", "uiSpec",
            ) if key in shot}
            shot["companionContract"] = sanitize_avatar_companion(shot, requested_companion)
            shot["companionRoute"] = str(shot["companionContract"].get("route") or "motion-card")
            shot["companionRoutePlan"] = list(shot["companionContract"].get("routePlan") or [shot["companionRoute"]])
            shot["route"] = "avatar"
            shot["routePlan"] = ["avatar"]
            shot.update({"proofKind": "presenter", "mediaNeedKind": "presenter", "beatRole": "pattern_interrupt", "peoplePolicy": "required", "presenterAllowed": True, "maxFaceAreaRatio": 0.50, "evidenceMustRemainDominant": False, "preferredMedium": "avatar", "forbiddenSubstitutions": [], "requiredEvidence": "Trusted presenter delivers the approved narration without replacing simultaneous proof.", "noveltyKey": "presenter-%s" % shot["shotId"]})
            apply_motion_contract(shot, shot)
            normalize_visual_composition(shot)
    plan["schemaVersion"] = "3.2"
    plan.setdefault("rules", {}).pop("maxVideoCandidatesPerBeat", None)
    plan.setdefault("rules", {}).update({"routingPolicy": "feasibility-v3", "planPolicyVersion": PLAN_POLICY_VERSION, "queryVariantsPerProvider": 3, "maxVideoCandidatesPerProvider": 2, "maxDirectedRetry": 1})
    plan = apply_persisted_draft_repairs(plan, run_paths(data))
    normalize_plan_visual_composition(plan)
    apply_motion_choreography(plan)
    contract_errors = validate_plan_media_contract(plan) + validate_plan_visual_composition(plan, resolved=False) + validate_motion_choreography(plan)
    if contract_errors:
        raise RuntimeError("plan reanudado viola media contract: %s" % contract_errors[:8])
    return plan


def resolution_input_signature(plan: dict[str, Any]) -> str:
    resolved_fields = {"visualKind", "source", "mediaType", "sourceInMs", "sourceOutMs", "provider", "secondarySource", "secondaryMediaType", "secondarySourceInMs", "secondarySourceOutMs", "secondaryObjectPosition", "secondaryProvider", "sourceWidth", "sourceHeight", "avatarRequested", "avatarFallback", "avatarFailure", "visualMixRepair", "queryVariants", "clipBaseQuery", "pexelsBaseQuery", "imageBasePrompt", "imagePairPrompt", "cutoutPrompt", "omniPrompt", "uiSpec"}
    payload = {"scriptHash": plan.get("scriptHash"), "providerMode": plan.get("providerMode") or ("real" if production_mode() else "mock"), "shots": [{key: value for key, value in shot.items() if key not in resolved_fields} for shot in plan.get("shots") or []]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def assert_provider_mode(plan: dict[str, Any], stage: str) -> None:
    """Prevent a resumable run from mixing mock and real artifacts."""
    expected = "real" if production_mode() else "mock"
    actual = str(plan.get("providerMode") or "").lower()
    if actual != expected:
        raise RuntimeError(
            "%s bloqueado: el plan es providerMode=%s y la corrida actual es providerMode=%s; "
            "reanuda desde un plan generado en el mismo modo" % (stage, actual or "ausente", expected)
        )


def shot_input_signature(plan: dict[str, Any], shot: dict[str, Any]) -> str:
    # Compiled queries/UI specs are deterministic products of the raw contract.
    # Excluding them keeps a compiler upgrade from regenerating already approved
    # assets while raw prompt, evidence, route and repair intent still invalidate.
    resolved_fields = {"visualKind", "source", "mediaType", "sourceInMs", "sourceOutMs", "provider", "secondarySource", "secondaryMediaType", "secondarySourceInMs", "secondarySourceOutMs", "secondaryObjectPosition", "secondaryProvider", "sourceWidth", "sourceHeight", "avatarRequested", "avatarFallback", "avatarFailure", "visualMixRepair", "queryVariants", "clipBaseQuery", "pexelsBaseQuery", "imageBasePrompt", "imagePairPrompt", "cutoutPrompt", "omniPrompt", "uiSpec"}
    payload = {"scriptHash": plan.get("scriptHash"), "providerMode": plan.get("providerMode") or ("real" if production_mode() else "mock"), "shot": {key: value for key, value in shot.items() if key not in resolved_fields}}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def checkpoint_resolution_compatible(requested: dict[str, Any], resolved: dict[str, Any]) -> bool:
    """Reject resumable outputs that no longer satisfy the requested evidence route."""
    if requested.get("route") == "avatar" and resolved.get("avatarFallback") is True:
        companion_route = str(requested.get("companionRoute") or "")
        if companion_route == "ui":
            return resolved.get("visualKind") == "ui-card" and bool(resolved.get("uiSpec"))
        return True
    route = str(requested.get("route") or "")
    proof_kind = str(requested.get("proofKind") or requested.get("mediaNeedKind") or "")
    resolved_kind = str(resolved.get("proofKind") or resolved.get("mediaNeedKind") or "")
    if proof_kind != resolved_kind:
        return False
    if str(requested.get("temporalEvidenceMode") or "") != str(resolved.get("temporalEvidenceMode") or ""):
        return False
    if bool(requested.get("hybridTemplate")) != bool(resolved.get("hybridTemplate")):
        return False
    has_visual_asset = bool(str(resolved.get("source") or resolved.get("backgroundSource") or ""))
    if route in EXTERNAL_MEDIA_ROUTES and not has_visual_asset:
        return False
    if proof_kind == "product_inspection" and route in {"image", "image_pair"} and not has_visual_asset:
        return False
    return True


def prepare_avatar_companion(shot: dict[str, Any]) -> dict[str, Any]:
    """Compile the requested non-presenter companion before provider validation."""
    fallback_shot = dict(shot)
    fallback_shot.update(json.loads(json.dumps(shot.get("companionContract") or {})))
    companion_routes = list(shot.get("companionRoutePlan") or fallback_shot.get("routePlan") or [])
    fallback_shot["routePlan"] = companion_routes
    fallback_shot["route"] = str(shot.get("companionRoute") or fallback_shot.get("route") or (companion_routes[0] if companion_routes else "motion-card"))
    fallback_shot.pop("uiSpec", None)
    if fallback_shot["route"] == "ui":
        fallback_shot["uiSpec"] = compile_ui_spec(fallback_shot)
    return fallback_shot


GRAPHIC_VISUAL_KINDS = {"motion-card", "ui-card"}


def visual_mix_snapshot(shots: list[dict[str, Any]]) -> dict[str, int | float]:
    consecutive = 0
    max_consecutive = 0
    videos = 0
    for shot in shots:
        if shot.get("visualKind") in GRAPHIC_VISUAL_KINDS:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0
        if shot.get("mediaType") == "video":
            videos += 1
    return {
        "shots": len(shots),
        "video_shots": videos,
        "required_video_shots": math.ceil(len(shots) * 0.20),
        "video_share": videos / max(1, len(shots)),
        "max_consecutive_graphics": max_consecutive,
    }


def rank_visual_mix_repairs(shots: list[dict[str, Any]], public_assets: pathlib.Path | None = None, attempted: set[str] | None = None) -> list[dict[str, Any]]:
    """Rank filmable graphic fallbacks by how much one video fixes the set."""
    attempted = attempted or set()
    before = int(visual_mix_snapshot(shots)["max_consecutive_graphics"])
    ranked: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for index, shot in enumerate(shots):
        shot_id = str(shot.get("shotId") or "")
        if shot_id in attempted or shot.get("visualKind") not in GRAPHIC_VISUAL_KINDS:
            continue
        if shot.get("requiresReadableData") or not (
            shot.get("filmableOverride")
            or shot.get("mediaNeedKind") == "human_action"
            or shot.get("avatarFallback") is True
        ):
            continue
        simulated = [dict(row) for row in shots]
        simulated[index]["visualKind"] = "broll"
        simulated[index]["mediaType"] = "video"
        after = int(visual_mix_snapshot(simulated)["max_consecutive_graphics"])
        left = index
        while left > 0 and shots[left - 1].get("visualKind") in GRAPHIC_VISUAL_KINDS:
            left -= 1
        right = index
        while right + 1 < len(shots) and shots[right + 1].get("visualKind") in GRAPHIC_VISUAL_KINDS:
            right += 1
        run_length = right - left + 1
        existing = 0
        if public_assets and public_assets.is_dir():
            existing = int(any(path.stat().st_size > 0 for path in public_assets.glob(shot_id + "*_pexels.mp4")))
        ranked.append(((before - after, run_length, existing, -index), shot))
    return [shot for _, shot in sorted(ranked, key=lambda row: row[0], reverse=True)]


def repair_visual_mix(
    provider: Any,
    data: dict[str, Any],
    paths: dict[str, pathlib.Path],
    plan: dict[str, Any],
    used_hashes: set[str],
    used_user_clips: set[str],
    used_visuals: list[tuple[str, list[int]]],
    asset_rows: list[dict[str, Any]],
    beat_feedback: dict[str, dict[str, Any]],
    telemetry: ProviderTelemetry,
    checkpoint: Any,
) -> None:
    """Repair set-level rhythm with targeted Pexels footage after normal routing."""
    shots = plan.get("shots") or []
    attempted: set[str] = set()
    while True:
        snapshot = visual_mix_snapshot(shots)
        if int(snapshot["max_consecutive_graphics"]) <= 5 and int(snapshot["video_shots"]) >= int(snapshot["required_video_shots"]):
            return
        candidates = rank_visual_mix_repairs(shots, paths["public"] / "assets", attempted)
        if not candidates:
            return
        repaired = False
        for shot in candidates:
            shot_id = str(shot["shotId"])
            attempted.add(shot_id)
            repair_shot = dict(shot)
            repair_shot.update({
                "route": "pexels",
                "routePlan": ["pexels"],
                "companionRoute": "",
                "companionRoutePlan": [],
                "movingVisualRequired": True,
                "skipLibrary": True,
            })
            try:
                rel, path, media_type, used_route = resolve_support_asset(
                    provider,
                    data,
                    paths,
                    repair_shot,
                    used_hashes,
                    used_user_clips,
                    used_visuals,
                    beat_feedback=beat_feedback,
                )
                if media_type != "video":
                    raise RuntimeError("la reparacion de mezcla no produjo video")
                duration_ms = int(shot["endMs"]) - int(shot["startMs"])
                shot.update({
                    "visualKind": "broll",
                    "source": rel,
                    "mediaType": "video",
                    "sourceInMs": 0,
                    "sourceOutMs": duration_ms,
                    "provider": used_route,
                    "visualMixRepair": True,
                })
                asset_rows[:] = [row for row in asset_rows if row.get("shot_id") != shot_id]
                asset_rows.append({"shot_id": shot_id, "provider": used_route, "path": str(path), "sha256": sha256(path), "status": "APPROVED_VISUAL_MIX_REPAIR"})
                telemetry.emit(provider="visual-mix-repair", scene=shot_id, query_or_prompt=str(repair_shot.get("pexelsQuery") or ""), result="selected", asset_after=str(path), estimated_cost_usd=0, metadata={"source_provider": used_route, "before": snapshot})
                checkpoint(shot_id)
                print("[longform] %s reparado con video %s para equilibrar la mezcla visual" % (shot_id, used_route))
                repaired = True
                break
            except Exception as exc:
                telemetry.emit(provider="visual-mix-repair", scene=shot_id, query_or_prompt=str(repair_shot.get("pexelsQuery") or ""), result="failed", rejection_reason=str(exc), estimated_cost_usd=0, metadata={"before": snapshot})
                print("[longform] reparacion visual %s fallo: %s" % (shot_id, str(exc)[:160]))
        if not repaired:
            return


def materialize_hybrid_shot(shot: dict[str, Any], rel: str, media_type: str, provider: str) -> None:
    """Animate generated/real evidence with Remotion without hiding the evidence behind a text card."""
    shot["uiTemplate"] = str(shot.get("hybridTemplate") or shot.get("uiTemplate") or "process-steps")
    shot["uiSpec"] = compile_ui_spec(shot)
    shot.update({
        "visualKind": "ui-card",
        "source": "",
        "mediaType": "card",
        "sourceInMs": 0,
        "sourceOutMs": 0,
        "backgroundSource": rel,
        "backgroundMediaType": media_type,
        "provider": "%s+remotion" % provider,
        "evidenceMustRemainDominant": True,
    })
    if str(shot.get("hybridTemplate") or "") == "product-inspection":
        shot["backgroundObjectPosition"] = "left center"
    normalize_visual_composition(shot)


def stage_assets(data: dict[str, Any], voice: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    paths = run_paths(data)
    plan = upgrade_visual_plan(data, plan)
    write_json(paths["work"] / "03_visual_plan.json", plan)
    provider = get_providers(WIDTH, HEIGHT, FPS)
    voice_path = paths["work"] / "voice" / "voiceover.wav"
    input_signature = resolution_input_signature(plan)
    partial_path = paths["work"] / "04_assets_partial.json"
    used_hashes: set[str] = set()
    used_user_clips: set[str] = set()
    used_visuals: list[tuple[str, list[int]]] = []
    asset_rows = []
    completed: set[str] = set()
    beat_feedback: dict[str, dict[str, Any]] = {}
    telemetry = ProviderTelemetry(paths["work"] / "provider_events.jsonl")
    shot_signatures = {shot["shotId"]: shot_input_signature(plan, shot) for shot in plan.get("shots") or []}
    checkpoint_sources: list[dict[str, Any]] = []
    final_plan_path = paths["work"] / "05_resolved_plan.json"
    final_manifest_path = paths["work"] / "04_assets_manifest.json"
    if final_plan_path.is_file() and final_manifest_path.is_file():
        prior_plan = read_json(final_plan_path)
        if prior_plan.get("scriptHash") == plan.get("scriptHash") and prior_plan.get("providerMode") == plan.get("providerMode"):
            prior_shots = list(prior_plan.get("shots") or [])
            checkpoint_sources.append({
                "name": "resolved-plan",
                "shot_signatures": {shot["shotId"]: shot_input_signature(prior_plan, shot) for shot in prior_shots},
                "completed_shot_ids": [shot["shotId"] for shot in prior_shots],
                "shots": prior_shots,
                "assets": list((read_json(final_manifest_path).get("assets") or [])),
                "used_user_clips": [],
                "beat_feedback": {},
            })
    if partial_path.is_file():
        partial_checkpoint = read_json(partial_path)
        partial_shots = list(partial_checkpoint.get("shots") or [])
        if partial_shots:
            # Checkpoints survive signature-policy/compiler upgrades. Recompute
            # from their stored raw contracts instead of trusting stale hashes.
            partial_checkpoint["shot_signatures"] = {
                shot["shotId"]: shot_input_signature(plan, shot) for shot in partial_shots
            }
        checkpoint_sources.append({"name": "partial", **partial_checkpoint})
    if checkpoint_sources:
        resolved: dict[str, dict[str, Any]] = {}
        accepted_assets: dict[str, dict[str, Any]] = {}
        for checkpoint_source in checkpoint_sources:
            prior_signatures = checkpoint_source.get("shot_signatures") or {}
            current_by_id = {str(shot.get("shotId") or ""): shot for shot in plan.get("shots") or []}
            prior_by_id = {str(shot.get("shotId") or ""): shot for shot in checkpoint_source.get("shots") or []}
            eligible = {
                shot_id for shot_id in (checkpoint_source.get("completed_shot_ids") or [])
                if prior_signatures.get(shot_id) == shot_signatures.get(shot_id)
                and checkpoint_resolution_compatible(current_by_id.get(shot_id) or {}, prior_by_id.get(shot_id) or {})
            }
            for prior_shot in checkpoint_source.get("shots") or []:
                shot_id = str(prior_shot.get("shotId") or "")
                if shot_id in eligible and shot_id not in resolved:
                    resolved[shot_id] = prior_shot
            for row in checkpoint_source.get("assets") or []:
                shot_id = str(row.get("shot_id") or "")
                if shot_id in eligible and shot_id not in accepted_assets:
                    accepted_assets[shot_id] = row
            used_user_clips.update(checkpoint_source.get("used_user_clips") or [])
            if checkpoint_source.get("name") == "partial":
                beat_feedback = dict(checkpoint_source.get("beat_feedback") or {})
        completed = set(resolved)
        asset_rows = list(accepted_assets.values())
        for shot in plan.get("shots") or []:
            shot_id = shot["shotId"]
            if shot_id in resolved:
                shot.clear()
                shot.update(resolved[shot_id])
        for shot in plan.get("shots") or []:
            if shot["shotId"] not in completed:
                continue
            for key in ("source", "secondarySource"):
                rel = str(shot.get(key) or "")
                path = pathlib.Path(REMOTION_DIR) / "public" / rel
                if not rel or not path.is_file():
                    continue
                used_hashes.add(sha256(path))
                if key == "secondarySource" or shot.get("visualKind") != "avatar-full":
                    media_type = str(shot.get("secondaryMediaType" if key == "secondarySource" else "mediaType") or "video")
                    used_visuals.append((shot["shotId"] + ("_support" if key == "secondarySource" else ""), visual_fingerprints(path, media_type)))
        print("[longform] checkpoint assets permanente: %d shots restaurados" % len(completed))
    avatar_count = sum(1 for shot in plan["shots"] if shot["shotId"] in completed and shot.get("visualKind") == "avatar-full")
    avatar_fallback_count = sum(1 for shot in plan["shots"] if shot["shotId"] in completed and shot.get("avatarFallback") is True)
    avatar_failures: list[dict[str, str]] = []
    def checkpoint(shot_id: str) -> None:
        completed.add(shot_id)
        write_json(partial_path, {"input_signature": input_signature, "shot_signatures": shot_signatures, "completed_shot_ids": sorted(completed), "assets": asset_rows, "used_user_clips": sorted(used_user_clips), "beat_feedback": beat_feedback, "shots": plan["shots"]})
    for shot in plan["shots"]:
        if shot["shotId"] in completed:
            continue
        duration_ms = shot["endMs"] - shot["startMs"]
        pinned = shot.get("pinnedAsset") or {}
        if pinned:
            rel = str(pinned.get("source") or "")
            path = (pathlib.Path(REMOTION_DIR) / "public" / rel).resolve()
            public_root = (pathlib.Path(REMOTION_DIR) / "public").resolve()
            if not path.is_file() or not path.is_relative_to(public_root):
                raise RuntimeError("%s pinnedAsset invalido: %s" % (shot["shotId"], rel))
            media_type = str(pinned.get("mediaType") or ("video" if path.suffix.lower() == ".mp4" else "image"))
            digest = sha256(path)
            if digest in used_hashes:
                raise RuntimeError("%s pinnedAsset duplicado por SHA-256" % shot["shotId"])
            fingerprints = visual_fingerprints(path, media_type)
            duplicate_of = perceptual_duplicate(fingerprints, used_visuals)
            if duplicate_of:
                raise RuntimeError("%s pinnedAsset visualmente repetido de %s" % (shot["shotId"], duplicate_of))
            fit, reason = cached_media_fit(path, rel, shot, str(pinned.get("provider") or "image"))
            if not fit:
                raise RuntimeError("%s pinnedAsset no aprobado: %s" % (shot["shotId"], reason))
            used_hashes.add(digest)
            used_visuals.append((shot["shotId"], fingerprints))
            pinned_provider = str(pinned.get("provider") or "image")
            if shot.get("hybridTemplate"):
                materialize_hybrid_shot(shot, rel, media_type, pinned_provider)
            else:
                shot.update({"visualKind": "broll" if media_type == "video" else "image", "source": rel, "mediaType": media_type, "sourceInMs": 0, "sourceOutMs": duration_ms if media_type == "video" else 0, "provider": pinned_provider})
            asset_rows.append({"shot_id": shot["shotId"], "provider": shot["provider"], "source_provider": pinned_provider, "path": str(path), "sha256": digest, "status": "APPROVED_PINNED"})
            telemetry.emit(provider=str(shot["provider"]), scene=shot["shotId"], query_or_prompt=str(shot.get("visualProof") or ""), result="selected", asset_after=str(path), estimated_cost_usd=0, metadata={"source": "pinned"})
            checkpoint(shot["shotId"])
            continue
        if shot["route"] == "ui":
            materialize_ui_shot(shot)
            background_rel = str(shot.get("backgroundSource") or "")
            background_path = pathlib.Path(REMOTION_DIR) / "public" / background_rel if background_rel else None
            if background_rel and (background_path is None or not background_path.is_file()):
                raise RuntimeError("%s UI hibrida sin evidencia de fondo materializada" % shot["shotId"])
            if background_rel:
                shot["provider"] = "deterministic-ui+evidence"
            if shot.get("avatarFallback") is True:
                avatar_fallback_count += 1
                shot["provider"] = "deterministic-ui-avatar-fallback"
            asset_status = "APPROVED_AVATAR_FALLBACK" if shot.get("avatarFallback") is True else ("APPROVED_DETERMINISTIC_EVIDENCE" if background_rel else "APPROVED_DETERMINISTIC")
            asset_rows.append({"shot_id": shot["shotId"], "provider": shot["provider"], "path": str(background_path or ""), "sha256": sha256(background_path) if background_path else "", "status": asset_status, "ui_spec": shot.get("uiSpec"), "background_source": background_rel})
            telemetry.emit(provider="deterministic-ui", scene=shot["shotId"], query_or_prompt=json.dumps(shot.get("uiSpec") or {}, ensure_ascii=False, sort_keys=True), result="selected", estimated_cost_usd=0, metadata={"evidence_beat_id": shot.get("evidenceBeatId")})
            checkpoint(shot["shotId"])
            continue
        if shot["route"] == "motion-card":
            if shot.get("beatRole") == "proof":
                raise RuntimeError("%s motion-card no puede reemplazar requiredEvidence" % shot["shotId"])
            shot.update({"visualKind": "motion-card", "source": "", "mediaType": "card", "sourceInMs": 0, "sourceOutMs": 0, "provider": "remotion"})
            telemetry.emit(provider="remotion", scene=shot["shotId"], query_or_prompt=str(shot.get("screenCopy") or shot.get("visualProof") or ""), result="selected", estimated_cost_usd=0, metadata={"template": "motion-card", "evidence_beat_id": shot.get("evidenceBeatId")})
            checkpoint(shot["shotId"])
            continue
        if shot["route"] == "avatar":
            segment = paths["work"] / "voice" / (shot["shotId"] + "_avatar.wav")
            extract_audio_segment(voice_path, shot["startMs"], duration_ms, segment)
            avatar = paths["public"] / "assets" / (shot["shotId"] + "_avatar.mp4")
            avatar_started = time.time()
            try:
                if not avatar.exists() or avatar.stat().st_size <= 0:
                    provider.avatar_clip(str(segment), duration_ms / 1000, str(avatar), prompt="Presentadora hispana adulta, plano medio centrado, fondo limpio, horizontal 16:9", script_segment=shot["tts"])
                    telemetry.emit(provider="avatar", scene=shot["shotId"], query_or_prompt=shot["tts"], started_at=avatar_started, result="produced", asset_after=str(avatar), estimated_cost_usd=0.0 if getattr(provider, "mode", "") == "mock" else None, metadata={"presenter_reason": shot.get("presenterReason")})
                meta = ffprobe(avatar)
                ratio = meta["width"] / max(1, meta["height"])
                if not (1.74 <= ratio <= 1.80):
                    raise RuntimeError("avatar %s no es 16:9: %dx%d" % (shot["shotId"], meta["width"], meta["height"]))
                if meta["duration_ms"] + 100 < duration_ms:
                    raise RuntimeError("avatar %s mas corto que su shot" % shot["shotId"])
                digest = sha256(avatar)
                if digest in used_hashes:
                    raise RuntimeError("avatar repetido por SHA-256")
                used_hashes.add(digest)
                avatar_count += 1
                shot.update({"visualKind": "avatar-full", "source": "runs/%s/assets/%s" % (data["run_id"], avatar.name), "mediaType": "video", "sourceInMs": 0, "sourceOutMs": duration_ms, "provider": "avatar", "sourceWidth": meta["width"], "sourceHeight": meta["height"], "avatarRequested": True, "avatarFallback": False})
                asset_rows.append({"shot_id": shot["shotId"], "provider": "avatar", "path": str(avatar), "sha256": digest, "status": "APPROVED"})
                telemetry.emit(provider="avatar", scene=shot["shotId"], query_or_prompt=shot["tts"], result="selected", asset_after=str(avatar), estimated_cost_usd=0, metadata={"presenter_reason": shot.get("presenterReason")})
                avatar_asset_id = asset_library.register(avatar, kind="video", description="Avatar Kreado 16:9 centrado", provider="kreado", tags=["avatar", "presentadora", "16:9"], duration_ms=meta["duration_ms"], width=meta["width"], height=meta["height"], license_name="owned generated avatar")
                asset_library.mark_used(avatar_asset_id, data["run_id"], shot["shotId"])
            except Exception as exc:
                avatar.unlink(missing_ok=True)
                failure = str(exc)[:500]
                avatar_failures.append({"shot_id": shot["shotId"], "reason": failure})
                telemetry.emit(provider="avatar", scene=shot["shotId"], query_or_prompt=shot["tts"], started_at=avatar_started, result="failed", rejection_reason=failure, estimated_cost_usd=0.0 if getattr(provider, "mode", "") == "mock" else None, metadata={"presenter_reason": shot.get("presenterReason"), "fallback_required": True})
                fallback_shot = prepare_avatar_companion(shot)
                fallback_semantics = {
                    key: json.loads(json.dumps(fallback_shot.get(key)))
                    for key in ("proofKind", "mediaNeedKind", "evidenceMode", "requiredEvidence", "visualProof", "peoplePolicy", "presenterAllowed", "maxFaceAreaRatio", "evidenceMustRemainDominant")
                    if key in fallback_shot
                }
                try:
                    if fallback_shot["route"] == "ui":
                        materialize_ui_shot(fallback_shot)
                        shot.update({**fallback_semantics, "visualKind": "ui-card", "source": "", "mediaType": "card", "sourceInMs": 0, "sourceOutMs": 0, "provider": "deterministic-ui-avatar-fallback", "uiSpec": fallback_shot.get("uiSpec"), "avatarRequested": True, "avatarFallback": True, "avatarFailure": failure})
                        asset_rows.append({"shot_id": shot["shotId"], "provider": "deterministic-ui-avatar-fallback", "path": "", "sha256": "", "status": "APPROVED_AVATAR_FALLBACK", "reason": failure, "ui_spec": shot.get("uiSpec")})
                    elif fallback_shot["route"] == "motion-card":
                        shot.update({**fallback_semantics, "visualKind": "motion-card", "source": "", "mediaType": "card", "sourceInMs": 0, "sourceOutMs": 0, "provider": "remotion-avatar-fallback", "avatarRequested": True, "avatarFallback": True, "avatarFailure": failure})
                        asset_rows.append({"shot_id": shot["shotId"], "provider": "remotion-avatar-fallback", "path": "", "sha256": "", "status": "APPROVED_AVATAR_FALLBACK", "reason": failure})
                    else:
                        rel, path, media_type, used_route = resolve_support_asset(provider, data, paths, fallback_shot, used_hashes, used_user_clips, used_visuals, beat_feedback=beat_feedback)
                        shot.update({**fallback_semantics, "visualKind": "broll" if media_type == "video" else "image", "source": rel, "mediaType": media_type, "sourceInMs": 0, "sourceOutMs": duration_ms if media_type == "video" else 0, "provider": used_route, "avatarRequested": True, "avatarFallback": True, "avatarFailure": failure})
                        asset_rows.append({"shot_id": shot["shotId"], "provider": used_route, "path": str(path), "sha256": sha256(path), "status": "APPROVED_AVATAR_FALLBACK", "reason": failure})
                except Exception as fallback_exc:
                    shot.update({"visualKind": "motion-card", "source": "", "mediaType": "card", "sourceInMs": 0, "sourceOutMs": 0, "provider": "remotion-avatar-fallback", "avatarRequested": True, "avatarFallback": True, "avatarFailure": failure, "screenCopy": concise_display_copy(shot.get("screenCopy") or shot.get("tts") or "IDEA CLAVE")})
                    asset_rows.append({"shot_id": shot["shotId"], "provider": "remotion-avatar-fallback", "path": "", "sha256": "", "status": "APPROVED_AVATAR_FALLBACK", "reason": "%s | fallback providers: %s" % (failure, str(fallback_exc)[:300])})
                    telemetry.emit(provider="remotion-avatar-fallback", scene=shot["shotId"], query_or_prompt=str(shot.get("screenCopy") or ""), result="selected", rejection_reason=str(fallback_exc), estimated_cost_usd=0, metadata={"source": "avatar_failure", "avatar_failure": failure})
                avatar_fallback_count += 1
            checkpoint(shot["shotId"])
            continue
        try:
            rel, path, media_type, used_route = resolve_support_asset(provider, data, paths, shot, used_hashes, used_user_clips, used_visuals, beat_feedback=beat_feedback)
        except RuntimeError as exc:
            if int(shot.get("startMs") or 0) == 0:
                raise RuntimeError("hook sin asset visual válido; no se permite motion-card: %s" % str(exc))
            fallback_background = str(shot.get("fallbackBackgroundSource") or "")
            fallback_secondary = str(shot.get("fallbackSecondarySource") or "")
            fallback_background_path = pathlib.Path(REMOTION_DIR) / "public" / fallback_background if fallback_background else None
            fallback_secondary_path = pathlib.Path(REMOTION_DIR) / "public" / fallback_secondary if fallback_secondary else None
            if shot.get("fallbackComposite") and fallback_background_path and fallback_background_path.is_file() and fallback_secondary_path and fallback_secondary_path.is_file():
                materialize_hybrid_shot(shot, fallback_background, str(shot.get("fallbackBackgroundMediaType") or "image"), "deterministic-composite")
                shot.update({
                    "backgroundObjectPosition": str(shot.get("fallbackBackgroundObjectPosition") or "center"),
                    "secondarySource": fallback_secondary,
                    "secondaryMediaType": str(shot.get("fallbackSecondaryMediaType") or "image"),
                    "secondaryProvider": "verified-run-asset",
                })
                asset_rows.append({"shot_id": shot["shotId"], "provider": shot["provider"], "path": str(fallback_background_path), "secondary_path": str(fallback_secondary_path), "sha256": sha256(fallback_background_path), "status": "APPROVED_DETERMINISTIC_COMPOSITE", "reason": str(exc)[:500]})
                telemetry.emit(provider="deterministic-composite", scene=shot["shotId"], query_or_prompt=str(shot.get("fallbackComposite") or ""), result="selected", rejection_reason=str(exc), asset_before=str(fallback_background_path), asset_after=str(fallback_secondary_path), estimated_cost_usd=0, metadata={"source": "directed_provider_failure", "evidence_beat_id": shot.get("evidenceBeatId")})
                checkpoint(shot["shotId"])
                continue
            deterministic_route = deterministic_fallback_route(shot)
            if deterministic_route == "ui":
                materialize_ui_shot(shot)
                asset_rows.append({"shot_id": shot["shotId"], "provider": "deterministic-ui", "path": "", "sha256": "", "status": "APPROVED_FALLBACK", "reason": str(exc)[:500], "ui_spec": shot.get("uiSpec")})
                telemetry.emit(provider="deterministic-ui", scene=shot["shotId"], query_or_prompt=json.dumps(shot.get("uiSpec") or {}, ensure_ascii=False, sort_keys=True), result="selected", rejection_reason=str(exc), estimated_cost_usd=0, metadata={"source": "route_plan_fallback", "evidence_beat_id": shot.get("evidenceBeatId")})
                print("[longform] %s usa UI determinista tras fallar provider: %s" % (shot["shotId"], str(exc)[:140]))
                checkpoint(shot["shotId"])
                continue
            if deterministic_route == "motion-card":
                shot.update({"visualKind": "motion-card", "source": "", "mediaType": "card", "sourceInMs": 0, "sourceOutMs": 0, "provider": "remotion-fallback"})
                asset_rows.append({"shot_id": shot["shotId"], "provider": "remotion-fallback", "path": "", "sha256": "", "status": "APPROVED_FALLBACK", "reason": str(exc)[:500]})
                telemetry.emit(provider="remotion-fallback", scene=shot["shotId"], query_or_prompt=str(shot.get("screenCopy") or shot.get("visualProof") or ""), result="selected", rejection_reason=str(exc), estimated_cost_usd=0, metadata={"template": "motion-card", "source": "route_plan_fallback", "evidence_beat_id": shot.get("evidenceBeatId")})
                print("[longform] %s usa motion-card tras fallar provider: %s" % (shot["shotId"], str(exc)[:140]))
                checkpoint(shot["shotId"])
                continue
            if shot.get("proofKind") in {"real_event", "third_party_commentary", "cultural_reference"}:
                raise RuntimeError("%s requiere evidencia real; reescribe el beat o entrega una fuente: %s" % (shot["shotId"], str(exc)))
            if shot.get("beatRole") == "proof":
                raise RuntimeError("%s quedo sin requiredEvidence; no se permite tarjeta generica: %s" % (shot["shotId"], str(exc)))
            if still_image_forbidden(shot):
                raise RuntimeError("%s requiere movimiento real y la escalera de video fallo: %s" % (shot["shotId"], str(exc)))
            shot.update({"visualKind": "motion-card", "source": "", "mediaType": "card", "sourceInMs": 0, "sourceOutMs": 0, "provider": "remotion-fallback"})
            asset_rows.append({"shot_id": shot["shotId"], "provider": "remotion-fallback", "path": "", "sha256": "", "status": "APPROVED_FALLBACK", "reason": str(exc)[:500]})
            telemetry.emit(provider="remotion-fallback", scene=shot["shotId"], query_or_prompt=str(shot.get("screenCopy") or shot.get("visualProof") or ""), result="selected", rejection_reason=str(exc), estimated_cost_usd=0, metadata={"template": "motion-card", "evidence_beat_id": shot.get("evidenceBeatId")})
            print("[longform] %s usa motion-card final: %s" % (shot["shotId"], str(exc)[:160]))
            checkpoint(shot["shotId"])
            continue
        if shot.get("hybridTemplate"):
            materialize_hybrid_shot(shot, rel, media_type, used_route)
            asset_rows.append({"shot_id": shot["shotId"], "provider": shot["provider"], "source_provider": used_route, "path": str(path), "sha256": sha256(path), "status": "APPROVED_HYBRID"})
        else:
            shot.update({"visualKind": "broll" if media_type == "video" else "image", "source": rel, "mediaType": media_type, "sourceInMs": 0, "sourceOutMs": duration_ms if media_type == "video" else 0, "provider": used_route})
            asset_rows.append({"shot_id": shot["shotId"], "provider": used_route, "original_provider": shot.get("libraryOriginalProvider"), "source_url": shot.get("librarySourceUrl"), "license": shot.get("libraryLicense"), "path": str(path), "sha256": sha256(path), "status": "APPROVED"})
        checkpoint(shot["shotId"])
    # Recompute from the resolved plan. Incremental counters can be stale when
    # a checkpointed presenter fallback is invalidated and rematerialized by a
    # directed repair through a non-avatar route.
    avatar_count = sum(1 for shot in plan["shots"] if shot.get("visualKind") == "avatar-full")
    avatar_fallback_count = sum(1 for shot in plan["shots"] if shot.get("avatarFallback") is True)
    if avatar_count + avatar_fallback_count != 2:
        raise RuntimeError("se resolvieron %d anclas de presentador; deben ser 2" % (avatar_count + avatar_fallback_count))
    normalize_plan_visual_composition(plan)
    apply_motion_choreography(plan)
    resolved_qa = validate_resolved_plan(plan)
    if resolved_qa["status"] != "PASS":
        raise RuntimeError("assets produjeron timeline invalido: %s" % resolved_qa["errors"])
    set_qa = validate_evidence_set(plan)
    set_qa["retention"] = validate_retention(plan)
    if set_qa["retention"]["status"] != "PASS":
        set_qa["errors"].extend(set_qa["retention"]["errors"])
        set_qa["status"] = "FAIL"
    set_qa["contact_sheet"] = str(evidence_contact_sheet(plan, pathlib.Path(REMOTION_DIR) / "public", paths["work"] / "reviews" / "evidence_set_contact_sheet.jpg"))
    write_json(paths["work"] / "04_evidence_set_qa.json", set_qa)
    if set_qa["status"] != "PASS":
        raise RuntimeError("QA global del conjunto fallo antes de finalize: %s" % set_qa["errors"][:8])
    telemetry_summary = telemetry.summary()
    write_json(paths["work"] / "04_provider_summary.json", telemetry_summary)
    provider_events = telemetry.read()
    degraded_by_shot = {item["shot_id"]: item for item in set_qa.get("degraded_scenes") or []}
    scene_decisions = []
    for shot in plan.get("shots") or []:
        sid = str(shot.get("shotId") or "")
        events = [event for event in provider_events if str(event.get("scene") or "").split("_")[0] == sid]
        scene_decisions.append({
            "shot_id": sid,
            "proof_kind": shot.get("proofKind"),
            "required_evidence": shot.get("requiredEvidence"),
            "temporal_evidence_mode": shot.get("temporalEvidenceMode"),
            "requires_observed_transition": bool(shot.get("requiresObservedTransition")),
            "detail_salience": shot.get("detailSalience"),
            "motion_spec": shot.get("motionSpec") or {},
            "stop_motion": shot.get("stopMotion") or {},
            "preferred_medium": shot.get("preferredMedium"),
            "planned_providers": shot.get("routePlan") or [],
            "attempted_providers": list(dict.fromkeys(str(event.get("provider") or "") for event in events if event.get("provider"))),
            "winner": shot.get("provider"),
            "quality": (shot.get("candidateSelection") or {}).get("quality") or {},
            "rejections": [{"provider": event.get("provider"), "reason": event.get("rejection_reason")} for event in events if event.get("result") in {"failed", "rejected"}],
            "degraded": degraded_by_shot.get(sid),
        })
    write_json(paths["work"] / "04_scene_decisions.json", {"run_id": data["run_id"], "scenes": scene_decisions})
    avatar_status = "REAL" if avatar_count == 2 else ("FALLBACK" if avatar_fallback_count == 2 else "PARTIAL")
    provider_manager_path = paths["work"] / "provider_manager.json"
    provider_manager_state = read_json(provider_manager_path) if provider_manager_path.is_file() else {"providers": {}}
    manifest = {"status": "ASSETS_READY", "run_id": data["run_id"], "assets": asset_rows, "shot_signatures": shot_signatures, "unique_hashes": len(used_hashes), "user_clips_used": len(used_user_clips), "avatar_status": avatar_status, "avatar_real_count": avatar_count, "avatar_fallback_count": avatar_fallback_count, "avatar_failures": avatar_failures, "evidence_set_qa": set_qa, "provider_summary": telemetry_summary, "provider_manager": provider_manager_state, "scene_decisions": scene_decisions, "cta": plan.get("cta") or {}, "shots": plan["shots"]}
    write_json(paths["work"] / "04_assets_manifest.json", manifest)
    write_json(paths["work"] / "05_resolved_plan.json", plan)
    partial_path.unlink(missing_ok=True)
    record_state(paths, "assets", True, "%d unique assets" % len(used_hashes))
    return plan


def captions_from_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    captions = []
    for index in range(0, len(words), 6):
        group = words[index:index + 6]
        if not group:
            continue
        captions.append({"text": " ".join(str(item["word"]) for item in group), "startMs": int(group[0]["start_ms"]), "endMs": int(group[-1]["end_ms"])})
    return captions


def prepare_cta_thumbnail(cta: dict[str, Any], paths: dict[str, pathlib.Path]) -> str:
    """Download only the thumbnail associated with the already verified CTA target."""
    if cta.get("verified") is not True:
        return ""
    video_id = str(cta.get("target_video_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return ""
    url = str(cta.get("thumbnail_url") or "https://i.ytimg.com/vi/%s/hqdefault.jpg" % video_id)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"i.ytimg.com", "img.youtube.com"}:
        return ""
    target = paths["public"] / "assets" / "cta-next-video.jpg"
    temporary = target.with_suffix(".download")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "longform-verified-cta/1.0"})
        with urllib.request.urlopen(request, timeout=25) as response, temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        with Image.open(temporary) as image:
            image.load()
            if image.width < 320 or image.height < 180:
                raise RuntimeError("thumbnail CTA demasiado pequeno")
            converted = ImageOps.exif_transpose(image).convert("RGB")
            converted.save(target, format="JPEG", quality=92, optimize=True)
        return "runs/%s/assets/%s" % (str(paths["public"].name), target.name)
    except Exception as exc:
        print("[longform] thumbnail CTA no disponible; se conserva fallback tipografico: %s" % str(exc)[:180])
        return ""
    finally:
        temporary.unlink(missing_ok=True)


def validate_resolved_plan(plan: dict[str, Any]) -> dict[str, Any]:
    errors = []
    shots = plan.get("shots") or []
    avatar = 0
    avatar_fallback = 0
    cards = 0
    sources = set()
    expected = 0
    if shots:
        promise = str(plan.get("thumbnailPromise") or "").strip()
        if promise and str(shots[0].get("screenCopy") or "").strip() != promise:
            errors.append("hook screenCopy debe coincidir exactamente con thumbnailPromise")
    consecutive_text_cards = 0
    max_consecutive_text_cards = 0
    consecutive_graphics = 0
    max_consecutive_graphics = 0
    moving_shots = 0
    video_shots = 0
    for shot in shots:
        length = int(shot["endMs"]) - int(shot["startMs"])
        if abs(int(shot["startMs"]) - expected) > 180:
            errors.append("%s gap/overlap" % shot["shotId"])
        expected = int(shot["endMs"])
        if length <= 0 or length > MAX_SHOT_MS + 150:
            errors.append("%s duracion invalida %dms" % (shot["shotId"], length))
        if shot.get("visualKind") == "avatar-full":
            avatar += 1
            ratio = int(shot.get("sourceWidth") or 0) / max(1, int(shot.get("sourceHeight") or 0))
            if not (1.74 <= ratio <= 1.80):
                errors.append("%s avatar no 16:9" % shot["shotId"])
        if shot.get("avatarFallback") is True:
            avatar_fallback += 1
            if shot.get("visualKind") not in {"broll", "image", "motion-card", "ui-card"}:
                errors.append("%s fallback de avatar no es un visual materializado" % shot["shotId"])
        motion_changes = int((shot.get("motionSpec") or {}).get("meaningfulChanges") or 0)
        explanatory_ui = shot.get("visualKind") == "ui-card" and motion_changes >= 2
        if shot.get("visualKind") in {"motion-card", "ui-card"}:
            cards += 1
        if shot.get("visualKind") in {"motion-card", "ui-card"} and not explanatory_ui:
            consecutive_graphics += 1
            if len(str(shot.get("screenCopy") or "").strip()) < 4:
                errors.append("%s card sin mensaje explicativo" % shot["shotId"])
        else:
            consecutive_graphics = 0
        if shot.get("visualKind") == "motion-card":
            consecutive_text_cards += 1
        else:
            consecutive_text_cards = 0
        max_consecutive_text_cards = max(max_consecutive_text_cards, consecutive_text_cards)
        max_consecutive_graphics = max(max_consecutive_graphics, consecutive_graphics)
        if shot.get("mediaType") == "video" or shot.get("visualKind") == "avatar-full" or motion_changes >= 1:
            moving_shots += 1
        if shot.get("mediaType") == "video":
            video_shots += 1
        for key in ("source", "secondarySource"):
            source = str(shot.get(key) or "")
            if source:
                if source in sources:
                    errors.append("%s reutiliza %s" % (shot["shotId"], source))
                sources.add(source)
        if shot.get("mediaType") == "video" and int(shot.get("sourceOutMs") or 0) - int(shot.get("sourceInMs") or 0) + 60 < length:
            errors.append("%s ventana fuente corta" % shot["shotId"])
        for field in ("screenCopy", "subcopy"):
            if has_mojibake(shot.get(field)):
                errors.append("%s %s contiene texto corrupto" % (shot["shotId"], field))
        copy = str(shot.get("screenCopy") or "").strip()
        if copy and (len(copy) > 32 or len(copy.split()) > 4):
            errors.append("%s screenCopy supera 4 palabras/32 caracteres" % shot["shotId"])
    if str(plan.get("schemaVersion") or "2.0") in {"3.0", "3.1", "3.2"}:
        errors.extend(validate_plan_media_contract(plan))
        errors.extend(validate_plan_visual_composition(plan, resolved=True))
        errors.extend(validate_motion_choreography(plan))
    if abs(expected - int(plan.get("durationMs") or 0)) > 180:
        errors.append("timeline no cubre durationMs")
    card_share = cards / max(1, len(shots))
    moving_share = moving_shots / max(1, len(shots))
    video_share = video_shots / max(1, len(shots))
    if max_consecutive_text_cards > 2:
        errors.append("hay %d tarjetas de texto consecutivas; deben alternarse" % max_consecutive_text_cards)
    cta = plan.get("cta") or {}
    if cta and not 8 <= float(cta.get("end_screen_hold_seconds") or 0) <= 10:
        errors.append("CTA necesita pantalla final de 8-10 segundos")
    if cta and (cta.get("verified") is not True or not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(cta.get("target_video_id") or ""))):
        errors.append("CTA no tiene identidad verificada")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "metrics": {"shots": len(shots), "avatar_count": avatar, "avatar_fallback_count": avatar_fallback, "presenter_anchor_count": avatar + avatar_fallback, "motion_card_share": round(card_share, 4), "meaningful_motion_share": round(moving_share, 4), "video_share": round(video_share, 4), "max_consecutive_cards": max_consecutive_text_cards, "max_consecutive_graphics": max_consecutive_graphics, "unique_sources": len(sources), "duration_ms": plan.get("durationMs")}}


def build_sfx_events(plan: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    previous_chapter = ""
    cue_files = {
        "line-draw": "sfx/ui-line-draw.wav",
        "reveal": "sfx/ui-card-pop.wav",
        "confirmation": "sfx/ui-check-tick.wav",
        "impact": "sfx/ui-impact-soft.wav",
        "warning": "sfx/ui-filter-reject.wav",
        "comparison-switch": "sfx/ui-page-swipe.wav",
        "meter": "sfx/ui-meter-fill.wav",
        "callout": "sfx/ui-callout-ping.wav",
    }
    last_at = -10_000
    for shot in plan.get("shots") or []:
        at = int(shot["startMs"])
        duration = max(1, int(shot.get("endMs") or at + 1) - at)
        if shot.get("chapterId") != previous_chapter:
            if at - last_at >= 500:
                events.append({"src": "sfx/ui-page-swipe.wav", "startMs": at, "volume": 0.12, "semantic": "chapter-transition", "shotId": shot.get("shotId")})
                last_at = at
            previous_chapter = str(shot.get("chapterId") or "")
        cues = list(((shot.get("motionSpec") or {}).get("sfxCues") or []))
        if not cues and shot.get("visualKind") == "avatar-full":
            cues = [{"at": 0.05, "kind": "impact", "volume": 0.08}]
        for cue in cues[:2]:
            kind = str(cue.get("kind") or "reveal")
            event_at = at + round(max(0.0, min(1.0, float(cue.get("at") or 0))) * duration)
            if event_at - last_at < 650:
                continue
            events.append({
                "src": cue_files.get(kind, "sfx/ui-soft-click.wav"),
                "startMs": event_at,
                "volume": max(0.04, min(0.14, float(cue.get("volume") or 0.08))),
                "semantic": kind,
                "shotId": shot.get("shotId"),
            })
            last_at = event_at
    return events


def prepare_music_beds(data: dict[str, Any], voice: dict[str, Any], paths: dict[str, pathlib.Path]) -> list[dict[str, Any]]:
    manifest_path = paths["work"] / "music_manifest.json"
    manifest_missing = not manifest_path.is_file()
    if production_mode() and manifest_path.is_file():
        manifest_missing = str(read_json(manifest_path).get("provider") or "").lower() != "suno"
    if manifest_missing:
        if production_mode():
            candidates = asset_library.search(
                "musica instrumental longform salud bienestar calida creible analitica sin voz",
                kinds=("music",), run_id=data["run_id"], used_hashes=set(), limit=6,
            )
            reusable = next((item for item in candidates if str(item.get("provider") or "").lower() == "suno" and item.get("source_url") and item.get("license")), None)
            if reusable:
                write_json(manifest_path, {
                    "provider": "suno",
                    "source_url": reusable["source_url"],
                    "job_id": reusable.get("job_id") or "",
                    "prompt": reusable.get("prompt_query") or reusable.get("description") or "Suno instrumental reutilizado",
                    "license": reusable["license"],
                    "reused_from_library": True,
                    "tracks": [{"path": reusable["path"], "mood": reusable.get("mood") or "calido y explicativo", "volume": 0.075}],
                })
            else:
                request = build_suno_request(
                    mood="warm, credible, modern organic electronic",
                    bpm=int(os.environ.get("SUNO_BPM", "92")),
                    duration_seconds=round(float(data.get("target_minutes") or 3) * 60),
                    chapter_titles=[str(chapter.get("title") or "") for chapter in voice.get("chapters") or []],
                )
                write_json(paths["work"] / "suno_request.json", request)
                raise RuntimeError("falta musica Suno aprobada: no existe pista reutilizable en la biblioteca ni music_manifest.json descargado desde Chrome")
        else:
            source = paths["work"] / "voice" / "mock_music.wav"
            get_providers(WIDTH, HEIGHT, FPS).ambient_bed(voice["duration_ms"] / 1000, str(source))
            write_json(manifest_path, {"provider": "mock", "source_url": "", "prompt": "mock ambient bed", "license": "test only", "tracks": [{"path": str(source), "mood": "calm analytical"}]})
    manifest = read_json(manifest_path)
    if production_mode():
        from providers.suno_browser import validate_manifest
        manifest = validate_manifest(manifest_path)
    tracks = manifest.get("tracks") or []
    if not tracks:
        raise RuntimeError("music_manifest.json no contiene tracks")
    beds = []
    for index, chapter in enumerate(voice["chapters"]):
        track = tracks[min(index, len(tracks) - 1)]
        source = pathlib.Path(str(track.get("path") or ""))
        if not source.is_absolute():
            source = (manifest_path.parent / source).resolve()
        if not source.is_file():
            raise RuntimeError("pista de musica no existe: %s" % source)
        public_track = paths["public"] / "audio" / ("music_%02d%s" % (index + 1, source.suffix.lower()))
        if not public_track.exists() or sha256(public_track) != sha256(source):
            shutil.copy2(source, public_track)
        library_id = asset_library.register(source, kind="music", description="Suno instrumental %s" % str(track.get("mood") or ""), provider=str(manifest.get("provider") or ""), tags=["instrumental", "longform", str(track.get("mood") or "")], mood=str(track.get("mood") or ""), source_url=str(manifest.get("source_url") or ""), job_id=str(manifest.get("job_id") or ""), prompt_query=str(manifest.get("prompt") or ""), duration_ms=ffprobe(source)["duration_ms"], license_name=str(manifest.get("license") or ""))
        asset_library.mark_used(library_id, data["run_id"], chapter["id"] + "_music")
        beds.append({"src": "runs/%s/audio/%s" % (data["run_id"], public_track.name), "startMs": chapter["start_ms"], "endMs": chapter["end_ms"], "volume": float(track.get("volume") or 0.075), "mood": str(track.get("mood") or "calm analytical")})
    return beds


def stage_props(data: dict[str, Any], voice: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    paths = run_paths(data)
    assert_provider_mode(plan, "props")
    qa = validate_resolved_plan(plan)
    write_json(paths["work"] / "06_plan_qa.json", qa)
    if qa["status"] != "PASS":
        raise RuntimeError("resolved plan QA fallo: %s" % qa["errors"])
    captions = captions_from_words(voice["words"])
    sfx = build_sfx_events(plan)
    if not sfx:
        raise RuntimeError("audio design sin SFX")
    music_beds = prepare_music_beds(data, voice, paths)
    cta = data.get("cta") or {}
    hold_ms = round(float(cta.get("end_screen_hold_seconds") or 8) * 1000)
    end_screen_start = max(0, int(voice["duration_ms"]) - hold_ms)
    thumbnail_src = prepare_cta_thumbnail(cta, paths)
    end_screen = {"startMs": end_screen_start, "durationMs": min(hold_ms, int(voice["duration_ms"]) - end_screen_start), "targetVideoTitle": str(cta.get("target_video_title") or ""), "targetVideoId": str(cta.get("target_video_id") or ""), "targetChannelId": str(cta.get("target_channel_id") or ""), "targetUrl": str(cta.get("target_url") or ""), "visibility": str(cta.get("visibility") or ""), "verifiedAt": str(cta.get("verified_at") or ""), "screenCopy": str(cta.get("screen_copy") or ""), "thumbnailSrc": thumbnail_src}
    theme = plan.get("designTheme") or remotion_theme(plan.get("designProfile") or data.get("_design_profile") or {})
    brand = {
        "ink": theme["text"], "cream": theme["background"], "teal": theme["accent"],
        "gold": theme["highlight"], "red": theme["danger"],
        "fontDisplay": theme.get("fontDisplay") or "Inter",
        "fontBody": theme.get("fontBody") or theme.get("fontDisplay") or "Inter",
    }
    props = {"runId": data["run_id"], "durationMs": voice["duration_ms"], "audioSrc": voice["audio_src"], "sfx": sfx, "musicBeds": music_beds, "endScreen": end_screen, "showCaptions": False, "showProgress": False, "brand": brand, "theme": theme, "designProfile": plan.get("designProfile") or {}, "shots": plan["shots"], "captions": captions}
    write_json(paths["work"] / "longform-props.json", props)
    chapter_props = []
    for chapter in voice["chapters"]:
        start, end = chapter["start_ms"], chapter["end_ms"]
        local_shots = []
        for shot in plan["shots"]:
            if shot["chapterId"] != chapter["id"]:
                continue
            item = dict(shot)
            item["startMs"] -= start
            item["endMs"] -= start
            local_shots.append(item)
        local_captions = [{**caption, "startMs": caption["startMs"] - start, "endMs": caption["endMs"] - start} for caption in captions if caption["startMs"] >= start and caption["startMs"] < end]
        local_sfx = [{**event, "startMs": event["startMs"] - start} for event in sfx if start <= event["startMs"] < end]
        local_music = [{**bed, "startMs": max(0, bed["startMs"] - start), "endMs": min(chapter["duration_ms"], bed["endMs"] - start)} for bed in music_beds if bed["startMs"] < end and bed["endMs"] > start]
        local_end_screen = None
        if end_screen["startMs"] < end and end_screen["startMs"] >= start:
            local_end_screen = {**end_screen, "startMs": end_screen["startMs"] - start}
        cp = {"runId": data["run_id"] + "-" + chapter["id"], "durationMs": chapter["duration_ms"], "audioSrc": chapter["audio_src"], "sfx": local_sfx, "musicBeds": local_music, "endScreen": local_end_screen, "showCaptions": False, "showProgress": False, "brand": brand, "theme": theme, "designProfile": plan.get("designProfile") or {}, "shots": local_shots, "captions": local_captions}
        cp_path = paths["work"] / "plans" / (chapter["id"] + "_props.json")
        write_json(cp_path, cp)
        chapter_props.append({"id": chapter["id"], "path": str(cp_path), "duration_ms": chapter["duration_ms"]})
    write_json(paths["work"] / "07_chapter_props.json", chapter_props)
    record_state(paths, "props", True, "%d chapter props" % len(chapter_props))
    return props


def remotion_render_signature(props: dict[str, Any]) -> str:
    signature = hashlib.sha256(json.dumps(props, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    sources = [props.get("audioSrc")]
    sources.append((props.get("endScreen") or {}).get("thumbnailSrc"))
    sources.extend(item.get("src") for item in props.get("musicBeds") or [])
    sources.extend(item.get("src") for item in props.get("sfx") or [])
    sources.extend(shot.get(key) for shot in props.get("shots") or [] for key in ("source", "secondarySource", "backgroundSource"))
    for source in sources:
        if not source:
            continue
        asset = pathlib.Path(REMOTION_DIR) / "public" / str(source)
        if asset.is_file():
            signature.update(sha256(asset).encode("ascii"))
    src_root = pathlib.Path(REMOTION_DIR) / "src"
    for source_file in sorted(path for path in src_root.rglob("*") if path.is_file() and path.suffix.lower() in {".ts", ".tsx", ".css"}):
        signature.update(str(source_file.relative_to(src_root)).encode("utf-8"))
        signature.update(source_file.read_bytes())
    return signature.hexdigest()


def prepare_remotion_public(run_id: str, paths: dict[str, pathlib.Path]) -> pathlib.Path:
    """Expose only this run and the shared SFX bank to Remotion.

    Remotion copies its public directory into every bundle. Keeping historical
    runs there made a one-frame render copy almost a gigabyte. Hardlinks retain
    staticFile() semantics while making staging fast and run-isolated.
    """
    source_root = pathlib.Path(REMOTION_DIR) / "public"
    source_run = source_root / "runs" / run_id
    if not source_run.is_dir():
        raise RuntimeError("public assets del run no existen: %s" % source_run)
    target = paths["work"] / "render_public"
    if target.exists():
        shutil.rmtree(target)

    def hardlink_or_copy(source: str, destination: str) -> str:
        try:
            os.link(source, destination)
            return destination
        except OSError:
            return shutil.copy2(source, destination)

    shutil.copytree(source_run, target / "runs" / run_id, copy_function=hardlink_or_copy)
    sfx = source_root / "sfx"
    if sfx.is_dir():
        shutil.copytree(sfx, target / "sfx", copy_function=hardlink_or_copy)
    write_json(paths["work"] / "render_public_manifest.json", {
        "run_id": run_id,
        "source": str(source_run),
        "target": str(target),
        "files": sum(1 for item in target.rglob("*") if item.is_file()),
        "bytes": sum(item.stat().st_size for item in target.rglob("*") if item.is_file()),
        "strategy": "hardlink-or-copy",
    })
    return target


def stage_render(data: dict[str, Any]) -> pathlib.Path:
    paths = run_paths(data)
    assert_provider_mode(read_json(paths["work"] / "05_resolved_plan.json"), "render")
    full_props_path = paths["work"] / "longform-props.json"
    full_props = read_json(full_props_path)
    render_public = prepare_remotion_public(data["run_id"], paths)
    render_env = subprocess_env()
    render_env["REMOTION_PUBLIC_DIR"] = str(render_public)
    draft = paths["out"] / "draft-960x540.mp4"
    draft_signature = remotion_render_signature(full_props)
    draft_sidecar = pathlib.Path(str(draft) + ".render.json")
    if not (draft.is_file() and draft_sidecar.is_file() and read_json(draft_sidecar).get("signature") == draft_signature):
        command = ["npx", "remotion", "render", "src/index.ts", "Longform", str(draft), "--props", str(full_props_path), "--codec", "h264", "--pixel-format", "yuv420p", "--crf", "28", "--scale", "0.5", "--concurrency", "4"]
        result = subprocess.run(command, cwd=REMOTION_DIR, capture_output=True, text=True, shell=(os.name == "nt"), env=render_env)
        if result.returncode:
            raise RuntimeError("render draft fallo: %s" % (result.stderr or result.stdout)[-900:])
        write_json(draft_sidecar, {"signature": draft_signature, "props": str(full_props_path)})
    draft_meta = ffprobe(draft)
    draft_errors = []
    if (draft_meta["width"], draft_meta["height"]) != (960, 540):
        draft_errors.append("draft no es 960x540")
    if not draft_meta["has_audio"]:
        draft_errors.append("draft sin mezcla de audio")
    plan = read_json(paths["work"] / "05_resolved_plan.json")
    draft_samples = sample_plan_video(draft, paths["work"] / "reviews" / "draft_shot_frames", plan)
    composition = validate_composed_frames(draft_samples, plan)
    rendered_motion = measure_rendered_motion(draft, plan)
    viewer = viewer_video_qa(data, draft, draft_samples, plan) if production_mode() else {"ok": True, "score": 100, "blockers": [], "improvements": ["mock mode"]}
    art_direction = review_art_direction(plan, viewer)
    draft_report = {"status": "PASS" if not draft_errors and composition["status"] == "PASS" and rendered_motion["status"] == "PASS" and viewer.get("ok") else "FAIL", "mechanical_errors": draft_errors, "composition": composition, "rendered_motion": rendered_motion, "viewer": viewer, "art_direction": art_direction, "path": str(draft)}
    write_json(paths["work"] / "07b_draft_avatar_review.json", draft_report)
    if draft_report["status"] != "PASS":
        raise DraftReviewFailed(draft_report)
    chapter_props = read_json(paths["work"] / "07_chapter_props.json")
    outputs = []
    for chapter in chapter_props:
        output = paths["out"] / "chapters" / (chapter["id"] + ".mp4")
        props = read_json(pathlib.Path(chapter["path"]))
        render_hash = remotion_render_signature(props)
        sidecar = pathlib.Path(str(output) + ".render.json")
        if output.is_file() and sidecar.is_file() and read_json(sidecar).get("signature") == render_hash:
            outputs.append(output)
            print("[longform] render cache hit %s" % chapter["id"])
            continue
        command = ["npx", "remotion", "render", "src/index.ts", "Longform", str(output), "--props", chapter["path"], "--codec", "h264", "--pixel-format", "yuv420p", "--crf", "20", "--concurrency", "4"]
        result = subprocess.run(command, cwd=REMOTION_DIR, capture_output=True, text=True, shell=(os.name == "nt"), env=render_env)
        if result.returncode:
            raise RuntimeError("render %s fallo: %s" % (chapter["id"], (result.stderr or result.stdout)[-900:]))
        write_json(sidecar, {"signature": render_hash, "props": chapter["path"]})
        outputs.append(output)
    concat = paths["out"] / "chapters" / "concat.txt"
    concat.write_text("\n".join("file '%s'" % str(path).replace("'", "''") for path in outputs) + "\n", encoding="utf-8")
    master = paths["out"] / "master.mp4"
    command = [media_tools.find_binary("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(master)]
    result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
    if result.returncode:
        raise RuntimeError("concat master fallo: %s" % result.stderr[-700:])
    record_state(paths, "render", True, str(master))
    return master


def sample_video(master: pathlib.Path, output_dir: pathlib.Path, duration_ms: int, count: int = 18) -> list[pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    regular = [(duration_ms / 1000) * (index + 0.5) / count for index in range(count)]
    times = []
    for at in [1.0, 3.0] + regular:
        if at < duration_ms / 1000 and all(abs(at - known) > 0.35 for known in times):
            times.append(at)
    for index, at in enumerate(times):
        output = output_dir / ("frame_%02d.jpg" % index)
        command = [media_tools.find_binary("ffmpeg"), "-y", "-ss", "%.3f" % at, "-i", str(master), "-frames:v", "1", "-update", "1", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
        if result.returncode == 0 and output.exists():
            frames.append(output)
    return frames


def sample_plan_video(master: pathlib.Path, output_dir: pathlib.Path, plan: dict[str, Any]) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    shots = plan.get("shots") or []
    opening_shot = next((shot for shot in shots if int(shot.get("startMs") or 0) <= 1000 < int(shot.get("endMs") or 0)), {})
    points = [(1000, "HOOK-1S", opening_shot), (3000, "HOOK-3S", opening_shot)]
    for shot in shots:
        if shot is opening_shot:
            # The opening shot is already sampled twice to validate progression in the first three seconds.
            continue
        start_ms = int(shot["startMs"])
        end_ms = int(shot["endMs"])
        # Deterministic UI is judged after its reveal has resolved. Sampling at
        # the midpoint can hide the final checklist state while it is animating.
        ratio = 0.72 if str(shot.get("route") or "") == "ui" else 0.50
        points.append((int(start_ms + (end_ms - start_ms) * ratio), shot["shotId"], shot))
    samples = []
    seen = set()
    for index, (at_ms, label, shot) in enumerate(points):
        bucket = round(at_ms / 250)
        if bucket in seen or at_ms >= int(plan.get("durationMs") or 0):
            continue
        seen.add(bucket)
        output = output_dir / ("shot_%02d_%s.jpg" % (index, label.replace("-", "_")))
        command = [media_tools.find_binary("ffmpeg"), "-y", "-v", "error", "-ss", "%.3f" % (at_ms / 1000), "-i", str(master), "-frames:v", "1", "-update", "1", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
        if result.returncode == 0 and output.exists():
            samples.append({"path": output, "at_ms": at_ms, "label": label, "shot": shot or {}})
    return samples


def mechanical_video_qa(master: pathlib.Path, expected_duration_ms: int) -> dict[str, Any]:
    meta = ffprobe(master)
    errors = []
    if (meta["width"], meta["height"]) != (WIDTH, HEIGHT):
        errors.append("master debe ser %dx%d" % (WIDTH, HEIGHT))
    if abs(meta["fps"] - FPS) > 0.1:
        errors.append("fps %.3f != %d" % (meta["fps"], FPS))
    if not meta["has_audio"]:
        errors.append("master sin audio")
    if abs(meta["duration_ms"] - expected_duration_ms) > 1200:
        errors.append("duracion master %dms difiere de plan %dms" % (meta["duration_ms"], expected_duration_ms))
    command = [media_tools.find_binary("ffmpeg"), "-i", str(master), "-af", "volumedetect", "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
    volume = result.stderr or ""
    mean_match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", volume)
    max_match = re.search(r"max_volume:\s*(-?[\d.]+) dB", volume)
    mean = float(mean_match.group(1)) if mean_match else None
    peak = float(max_match.group(1)) if max_match else None
    if mean is None or not (-25 <= mean <= -12):
        errors.append("mean volume fuera de rango: %s" % mean)
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "metrics": {**meta, "mean_volume_db": mean, "max_volume_db": peak}}


def speech_audio_qa(data: dict[str, Any], master: pathlib.Path, voice: dict[str, Any]) -> dict[str, Any]:
    errors = []
    forbidden = forbidden_spoken_terms(" ".join(str(item.get("word") or "") for item in voice.get("words") or []))
    if forbidden:
        errors.append("TTS contiene metadata de produccion: %s" % forbidden)
    script_words = re.findall(r"\b\w+\b", full_script(data), re.UNICODE)
    duration_minutes = max(0.01, ffprobe(master)["duration_ms"] / 60000)
    wpm = len(script_words) / duration_minutes
    if not 105 <= wpm <= 175:
        errors.append("ritmo de voz %.1f WPM fuera de 105-175" % wpm)
    aligned = voice.get("words") or []
    coverage = len(aligned) / max(1, len(script_words))
    if not 0.97 <= coverage <= 1.03:
        errors.append("alineacion cubre %.1f%% de palabras" % (coverage * 100))
    command = [media_tools.find_binary("ffmpeg"), "-v", "info", "-i", str(master), "-af", "silencedetect=noise=-45dB:d=1.5", "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
    silences = [float(value) for value in re.findall(r"silence_duration:\s*([\d.]+)", result.stderr or "")]
    longest = max(silences or [0.0])
    if longest > 2.5:
        errors.append("silencio largo %.2fs" % longest)
    gemma_report = {
        "status": "RETIRED",
        "reason": "El watchthrough Gemini de video completo ya evalua imagen y audio en una sola pasada; no se inicia detector local redundante.",
    }
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "metrics": {"words": len(script_words), "aligned_words": len(aligned), "alignment_coverage": round(coverage, 4), "wpm": round(wpm, 1), "longest_silence_s": round(longest, 2), "tts_speed": voice.get("tts_speed"), "forbidden_speech_terms": forbidden, "gemma_audio": gemma_report}}


def audio_design_qa(data: dict[str, Any], paths: dict[str, pathlib.Path]) -> dict[str, Any]:
    props = read_json(paths["work"] / "longform-props.json")
    errors = []
    if not props.get("sfx"):
        errors.append("no hay SFX programados")
    if not props.get("musicBeds"):
        errors.append("no hay musica programada")
    for event in props.get("sfx") or []:
        if float(event.get("volume") or 0) > 0.20:
            errors.append("SFX demasiado alto en %sms" % event.get("startMs"))
        source = pathlib.Path(REMOTION_DIR) / "public" / str(event.get("src") or "")
        if not source.is_file() or source.stat().st_size <= 0:
            errors.append("SFX inexistente: %s" % event.get("src"))
    for bed in props.get("musicBeds") or []:
        if float(bed.get("volume") or 0) > 0.12:
            errors.append("musica demasiado alta: %s" % bed.get("mood"))
        source = pathlib.Path(REMOTION_DIR) / "public" / str(bed.get("src") or "")
        if not source.is_file() or source.stat().st_size <= 0:
            errors.append("musica inexistente: %s" % bed.get("src"))
    end_screen = props.get("endScreen") or {}
    cta = data.get("cta") or {}
    if str(end_screen.get("targetVideoTitle") or "") != str(cta.get("target_video_title") or ""):
        errors.append("pantalla final no apunta al video nombrado por CTA")
    if str(end_screen.get("targetVideoId") or "") != str(cta.get("target_video_id") or "") or cta.get("verified") is not True:
        errors.append("pantalla final no conserva el ID verificado del CTA")
    if not 8000 <= int(end_screen.get("durationMs") or 0) <= 10000:
        errors.append("pantalla final no dura 8-10 segundos")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "metrics": {"sfx_count": len(props.get("sfx") or []), "music_beds": len(props.get("musicBeds") or []), "end_screen_ms": end_screen.get("durationMs")}}


def viewer_video_qa(data: dict[str, Any], master: pathlib.Path, samples: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    from engine import qa
    system = """Eres QA senior de video longform de YouTube. Evalúa únicamente lo que se ve en cada frame y el contrato temporal adjunto; no favorezcas ni castigues un proveedor por su nombre.
Comprueba: promesa visible en HOOK-1S/HOOK-3S; correspondencia literal entre narración y evidencia; claridad semántica; composición profesional; jerarquía, legibilidad y ausencia de colisiones; repetición; watermarks, logos o interfaces ajenas; credibilidad; avatar horizontal centrado; y CTA final con el título real del siguiente video. El ID de catálogo es metadato y nunca debe verse.
Una imagen puede implicar acción. Exige trayectoria visible solo cuando requires_observed_transition=true; initial_final admite dos estados consistentes. Evalúa etiquetas pequeñas por saliencia humana a velocidad normal. Motion graphics y UI solo pasan cuando hacen visible la relación, estado o dato exigido y no tapan la evidencia. Una tarjeta de texto no sustituye prueba visual.
Devuelve SOLO JSON: {\"ok\":true,\"score\":0,\"blockers\":[],\"improvements\":[],\"timeline_notes\":[]}. ok exige score>=82 y cero blockers. Cada blocker debe usar uno de los labels incluidos en el lote y describir una observación verificable."""
    def normalize_review(raw: dict[str, Any], labels: list[str], batch: list[dict[str, Any]]) -> dict[str, Any]:
        raw_blockers = list(raw.get("blockers") or [])
        allowed = {label.upper() for label in labels}
        shot_by_label = {str(item.get("label") or "").upper(): item.get("shot") or {} for item in batch}
        blockers = []
        invalid_blockers = []
        for blocker in raw_blockers:
            label, reason = _draft_blocker_text(blocker)
            shot = shot_by_label.get(label.upper()) or {}
            if label.upper() not in allowed:
                invalid_blockers.append(blocker)
            else:
                blockers.append(blocker)
        score = int(raw.get("score") or 0)
        return {"ok": score >= 82 and not blockers, "score": score, "blockers": blockers, "invalid_blockers": invalid_blockers, "improvements": raw.get("improvements") or [], "timeline_notes": raw.get("timeline_notes") or [], "labels": labels}

    reports = []
    for start in range(0, len(samples), 4):
        batch = samples[start:start + 4]
        labels = [{
            "image": index + 1,
            "label": item["label"],
            "at_s": round(item["at_ms"] / 1000, 2),
            "tts": str(item["shot"].get("tts") or "")[:220],
            "required_evidence": str(((item["shot"].get("companionContract") or {}).get("requiredEvidence") if item["shot"].get("avatarFallback") else "") or item["shot"].get("requiredEvidence") or item["shot"].get("visualProof") or "")[:260],
            "screen_copy": item["shot"].get("screenCopy", ""),
            "visual_kind": item["shot"].get("visualKind", ""),
            "provider": item["shot"].get("provider", ""),
            "proof_kind": ((item["shot"].get("companionContract") or {}).get("proofKind") if item["shot"].get("avatarFallback") else "") or item["shot"].get("proofKind", ""),
            "evidence_mode": item["shot"].get("evidenceMode", ""),
            "avatar_fallback": bool(item["shot"].get("avatarFallback")),
            "asset_source": item["shot"].get("source", ""),
            "background_source": item["shot"].get("backgroundSource", ""),
            "hybrid_template": item["shot"].get("hybridTemplate", ""),
        } for index, item in enumerate(batch)]
        user = "Title: %s\nThumbnail promise: %s\nDuration: %.1fs\nBatch frames:\n%s" % (data["title"], data["thumbnail_promise"], plan["durationMs"] / 1000, json.dumps(labels, ensure_ascii=False))
        label_names = [item["label"] for item in batch]
        review = normalize_review(qa.call_ai_json(system, user, images=[str(item["path"]) for item in batch], vision_required=True), label_names, batch)
        reports.append({**review, "review_count": 1})
    blockers = [item for report in reports for item in report["blockers"]]
    improvements = [item for report in reports for item in report["improvements"]]
    notes = [item for report in reports for item in report["timeline_notes"]]
    score = min([report["score"] for report in reports] or [0])
    return {"ok": bool(reports) and all(report["ok"] for report in reports) and score >= 82 and not blockers, "score": score, "blockers": blockers, "improvements": improvements, "timeline_notes": notes, "batches": reports, "policy": "single-neutral-composition-review-v2"}


def normalize_degraded_watchthrough(raw: dict[str, Any], gate_reports: list[dict[str, Any]], provider_failure: str, audio: pathlib.Path, spectrogram: pathlib.Path) -> dict[str, Any]:
    raw_blockers = list(raw.get("blockers") or [])
    allowed_labels = {"PROGRAM", "AUDIO", "CTA"}
    blockers = [blocker for blocker in raw_blockers if isinstance(blocker, dict) and str(blocker.get("label") or "").upper() in allowed_labels]
    invalid_blockers = [blocker for blocker in raw_blockers if blocker not in blockers]
    score = int(raw.get("score") or 0)
    gates_ok = all(str(report.get("status") or "") == "PASS" or report.get("ok") is True for report in gate_reports)
    return {
        "ok": False,
        "score": score,
        "blockers": blockers,
        "invalid_blockers": invalid_blockers,
        "dropoff_moments": raw.get("dropoff_moments") or [],
        "improvements": raw.get("improvements") or [],
        "audio_notes": raw.get("audio_notes") or [],
        "audio_path": str(audio),
        "spectrogram_path": str(spectrogram),
        "mode": "spectrogram+metrics-advisory",
        "degraded_audio_review": True,
        "provider_failure": provider_failure[:500],
        "deterministic_audio_gates_passed": gates_ok,
        "publication_blocked": True,
    }


def audiovisual_watchthrough_qa(data: dict[str, Any], master: pathlib.Path, samples: list[dict[str, Any]], plan: dict[str, Any], paths: dict[str, pathlib.Path], gate_reports: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One complete audiovisual pass over the full program, without QA voting loops."""
    from engine import qa
    audio = paths["work"] / "reviews" / "watchthrough_audio.mp3"
    command = [media_tools.find_binary("ffmpeg"), "-y", "-v", "error", "-i", str(master), "-vn", "-ac", "1", "-ar", "24000", "-b:a", "64k", str(audio)]
    result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
    if result.returncode or not audio.is_file():
        return {"ok": False, "score": 0, "blockers": ["no se pudo extraer audio para watchthrough"], "improvements": []}
    gate_reports = gate_reports or []
    timeline = [{
        "shot_id": shot.get("shotId"), "start_s": round(int(shot.get("startMs") or 0) / 1000, 2),
        "end_s": round(int(shot.get("endMs") or 0) / 1000, 2), "tts": str(shot.get("tts") or "")[:360],
        "required_evidence": shot.get("requiredEvidence"), "provider": shot.get("provider"),
        "proof_kind": shot.get("proofKind"), "temporal_evidence_mode": shot.get("temporalEvidenceMode"),
        "requires_observed_transition": bool(shot.get("requiresObservedTransition")),
        "detail_salience": shot.get("detailSalience"), "motion": shot.get("motionSpec"),
    } for shot in plan.get("shots") or []]
    contact = paths["work"] / "reviews" / "watchthrough_contact.jpg"
    contact_command = [media_tools.find_binary("ffmpeg"), "-y", "-v", "error", "-i", str(master), "-vf", "fps=1/8,scale=480:-1,tile=4x4:padding=4:margin=4", "-frames:v", "1", str(contact)]
    subprocess.run(contact_command, capture_output=True, text=True, env=subprocess_env())
    proxy = paths["work"] / "reviews" / "watchthrough_full_proxy.mp4"
    proxy_command = [
        media_tools.find_binary("ffmpeg"), "-y", "-v", "error", "-i", str(master),
        "-vf", "scale=640:-2:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-maxrate", "650k", "-bufsize", "1300k",
        "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", str(proxy),
    ]
    proxy_result = subprocess.run(proxy_command, capture_output=True, text=True, env=subprocess_env())
    if proxy_result.returncode or not proxy.is_file():
        return {"ok": False, "score": 0, "blockers": ["no se pudo crear proxy audiovisual completo"], "improvements": [], "mode": "proxy-failed"}
    system = """Eres una espectadora hispana adulta 45+ y QA senior de video longform. Mira y escucha EL VIDEO COMPLETO como una experiencia continua, no como una colección de frames. Evalua: promesa visual/verbal en 0-3 s; claridad y naturalidad del TTS; música audible pero subordinada; SFX semánticos; sincronía entre cada frase y la evidencia visible; ritmo y posibles abandonos; repetición; credibilidad; avatar 16:9; y CTA a un video real. No exijas captions: longform no los usa. No hagas pixel-peeping: un detalle incidental imperceptible a velocidad normal no bloquea. Una imagen puede implicar acción; solo exige video cuando requires_observed_transition=true. Stop motion solo es válido cuando su intención narrativa se entiende y mejora el beat. Motion graphics son válidos si explican relaciones o datos y no tapan evidencia. Devuelve SOLO JSON {\"ok\":true,\"score\":0,\"blockers\":[],\"dropoff_moments\":[],\"improvements\":[],\"audio_notes\":[]}. Cada blocker debe incluir shot_id o rango temporal y una observación verificable. ok exige score>=82 y cero blockers."""
    user = "Title: %s\nPromise: %s\nAudience profile: %s\nDesign profile: %s\nVerified CTA: %s\nFull timeline contract:\n%s" % (data["title"], data["thumbnail_promise"], data.get("audience_profile") or "", str(plan.get("designProfileId") or ""), json.dumps(plan.get("cta") or {}, ensure_ascii=False), json.dumps(timeline, ensure_ascii=False))
    provider_failure = ""
    raw: dict[str, Any] | None = None
    failures: list[str] = []
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        failures.append("Gemini no configurado")
    else:
        for attempt in range(2):
            try:
                raw = qa._gemini_ai_json(system, user, files=[str(proxy)])
                break
            except Exception as exc:
                failures.append("intento %d: %s" % (attempt + 1, str(exc)))
                if attempt == 0:
                    time.sleep(2)
    if raw is None:
        provider_failure = " | ".join(failures)
        spectrogram = paths["work"] / "reviews" / "watchthrough_spectrogram.png"
        spectrum_command = [media_tools.find_binary("ffmpeg"), "-y", "-v", "error", "-i", str(master), "-lavfi", "showspectrumpic=s=1600x600:legend=1:color=channel", "-frames:v", "1", str(spectrogram)]
        subprocess.run(spectrum_command, capture_output=True, text=True, env=subprocess_env())
        metrics = {"mechanical": gate_reports[0] if len(gate_reports) > 0 else {}, "speech_audio": gate_reports[1] if len(gate_reports) > 1 else {}, "audio_design": gate_reports[2] if len(gate_reports) > 2 else {}, "full_viewer_gate": gate_reports[3] if len(gate_reports) > 3 else {}}
        fallback_system = """Eres QA senior de continuidad audiovisual longform. El proveedor que escucha audio no está disponible: no afirmes que escuchaste la voz ni juzgues naturalidad sonora. El QA visual completo ya evaluó cada escena; no vuelvas a bloquear evidencia de escenas ausentes en este muestreo y no inventes una promesa distinta a required_evidence. Usa contacto y frames solo para macro-ritmo, continuidad, repetición global y CTA. Evalúa presencia técnica de voz, música y SFX únicamente mediante métricas y espectrograma; esos gates son autoritativos. Un blocker debe ser un objeto con label PROGRAM, AUDIO o CTA y reason. Cualquier otro label es inválido. Devuelve SOLO JSON {\"ok\":true,\"score\":0,\"blockers\":[],\"dropoff_moments\":[],\"improvements\":[],\"audio_notes\":[]}. ok exige score>=82 y cero blockers válidos."""
        fallback_user = "%s\nDeterministic metrics:\n%s\nFull approved narration:\n%s" % (user, json.dumps(metrics, ensure_ascii=False), full_script(data))
        key_samples = [samples[index] for index in sorted(set([0, 1, min(6, len(samples) - 1), min(10, len(samples) - 1), min(13, len(samples) - 1), len(samples) - 1])) if samples]
        fallback_images = ([str(contact)] if contact.is_file() else []) + ([str(spectrogram)] if spectrogram.is_file() else []) + [str(item["path"]) for item in key_samples]
        try:
            fallback_raw = qa.call_ai_json(fallback_system, fallback_user, images=fallback_images, vision_required=True)
        except Exception as fallback_exc:
            return {"ok": False, "score": 0, "blockers": ["watchthrough fallback fallo: %s" % str(fallback_exc)[:220]], "improvements": [], "mode": "fallback-failed", "provider_failure": provider_failure[:500]}
        result = normalize_degraded_watchthrough(fallback_raw, gate_reports, provider_failure, audio, spectrogram)
        write_json(paths["work"] / "08_av_watchthrough.json", result)
        return result
    assert raw is not None
    blockers = raw.get("blockers") or []
    score = int(raw.get("score") or 0)
    result = {"ok": bool(raw.get("ok")) and score >= 82 and not blockers, "score": score, "blockers": blockers, "dropoff_moments": raw.get("dropoff_moments") or [], "improvements": raw.get("improvements") or [], "audio_notes": raw.get("audio_notes") or [], "audio_path": str(audio), "video_proxy_path": str(proxy), "mode": "gemini-full-video", "degraded_audio_review": False, "passes": 1, "provider_attempts": max(1, len(failures) + 1)}
    write_json(paths["work"] / "08_av_watchthrough.json", result)
    return result


def stage_qa(data: dict[str, Any], plan: dict[str, Any], master: pathlib.Path) -> dict[str, Any]:
    paths = run_paths(data)
    assert_provider_mode(plan, "qa")
    if production_mode() and str(data.get("schema_version") or "") == "1.2":
        from engine.cta_resolver import verify_cta

        cta = data.get("cta") or {}
        verified = verify_cta(cta)
        if verified.get("verified") is not True or verified.get("target_video_id") != cta.get("target_video_id"):
            raise RuntimeError("CTA dejo de estar disponible antes de QA/publicacion")
    mechanical = mechanical_video_qa(master, plan["durationMs"])
    voice = read_json(paths["work"] / "02_voice_alignment.json")
    audio = speech_audio_qa(data, master, voice)
    audio_design = audio_design_qa(data, paths)
    samples = sample_plan_video(master, paths["work"] / "reviews" / "final_shot_frames", plan)
    composition = validate_composed_frames(samples, plan)
    rendered_motion = measure_rendered_motion(master, plan)
    viewer = viewer_video_qa(data, master, samples, plan) if production_mode() else {"ok": True, "score": 100, "blockers": [], "improvements": ["mock mode"]}
    watchthrough = audiovisual_watchthrough_qa(data, master, samples, plan, paths, [mechanical, audio, audio_design, viewer]) if production_mode() else {"ok": True, "score": 100, "blockers": [], "improvements": ["mock mode"]}
    art_direction = review_art_direction(plan, viewer)
    report = {"status": "PASS" if mechanical["status"] == "PASS" and audio["status"] == "PASS" and audio_design["status"] == "PASS" and composition["status"] == "PASS" and rendered_motion["status"] == "PASS" and viewer["ok"] and watchthrough["ok"] else "FAIL", "mechanical": mechanical, "audio": audio, "audio_design": audio_design, "composition": composition, "rendered_motion": rendered_motion, "viewer": viewer, "art_direction": art_direction, "audiovisual_watchthrough": watchthrough, "sampled_frames": [{"path": str(item["path"]), "label": item["label"], "at_ms": item["at_ms"]} for item in samples]}
    learning = record_learning_run(data["run_id"], plan, report)
    report["learning"] = {"path": str(pathlib.Path(ROOT) / "work" / "channel_learning.json"), "last_run": learning.get("last_run"), "learned_rules": learning.get("learned_rules") or []}
    write_json(paths["work"] / "08_master_qa.json", report)
    if report["status"] != "PASS":
        record_state(paths, "qa", False, json.dumps(report, ensure_ascii=False)[:500])
        raise RuntimeError("master QA fallo: %s" % json.dumps(report, ensure_ascii=False)[:600])
    record_state(paths, "qa", True, "master approved score=%s" % viewer["score"])
    return report


def load_stage_artifacts(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = run_paths(data)
    return read_json(paths["work"] / "02_voice_alignment.json"), read_json(paths["work"] / "05_resolved_plan.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-script longform production engine")
    parser.add_argument("stage", choices=["validate", "voice", "plan", "assets", "props", "render", "qa", "full", "status"])
    parser.add_argument("approved_script")
    args = parser.parse_args()
    input_path = pathlib.Path(args.approved_script).resolve()
    preview = load_approved_script(input_path)
    paths = run_paths(preview)
    if args.stage == "status":
        print((paths["work"] / "pipeline_state.json").read_text(encoding="utf-8") if (paths["work"] / "pipeline_state.json").exists() else "{}")
        return 0
    try:
        with run_lock(paths, args.stage):
            data = stage_validate(input_path)
            if args.stage == "validate":
                print(json.dumps({"status": "PASS", "run_id": data["run_id"]}))
                return 0
            stage_provider_preflight(data)
            voice = stage_voice(data) if args.stage in {"voice", "full"} else read_json(paths["work"] / "02_voice_alignment.json")
            if args.stage == "voice": return 0
            plan = stage_plan(data, voice) if args.stage in {"plan", "full"} else read_json(paths["work"] / ("05_resolved_plan.json" if args.stage in {"props", "render", "qa"} else "03_visual_plan.json"))
            if args.stage == "plan": return 0
            if args.stage in {"assets", "full"}:
                prior_review_path = paths["work"] / "07b_draft_avatar_review.json"
                repair_path = paths["work"] / "07c_draft_repair_plan.json"
                repair_is_current = repair_path.is_file() and str((read_json(repair_path).get("policy") or "")) == DRAFT_REPAIR_POLICY_VERSION
                if prior_review_path.is_file() and not repair_is_current:
                    prior_review = read_json(prior_review_path)
                    if prior_review.get("status") == "FAIL":
                        previous_resolved = read_json(paths["work"] / "05_resolved_plan.json") if (paths["work"] / "05_resolved_plan.json").is_file() else plan
                        try:
                            plan = build_draft_repair_plan(data, previous_resolved, prior_review, paths)
                            write_json(paths["work"] / "03_visual_plan.json", plan)
                            print("[longform] review fallido previo convertido en reparacion antes de assets")
                        except GlobalVisualReplanRequired as exc:
                            reset_visual_plan_for_global_replan(paths, str(exc))
                            plan = stage_plan(data, voice)
                            print("[longform] plan visual recompilado globalmente antes de assets")
                plan = stage_assets(data, voice, plan)
            if args.stage == "assets": return 0
            if args.stage in {"props", "full"}:
                stage_props(data, voice, plan)
            if args.stage == "props": return 0
            if args.stage in {"render", "full"}:
                global_replan_used = False
                for draft_attempt in range(4):
                    try:
                        master = stage_render(data)
                        break
                    except DraftReviewFailed as exc:
                        if draft_attempt >= 3:
                            raise RuntimeError("draft no supero QA despues de dos reparaciones dirigidas") from exc
                        current_plan = read_json(paths["work"] / "05_resolved_plan.json")
                        try:
                            plan = build_draft_repair_plan(data, current_plan, exc.report, paths)
                        except GlobalVisualReplanRequired as replan_exc:
                            if global_replan_used:
                                raise RuntimeError("recompilacion global no resolvio los blockers visuales") from replan_exc
                            global_replan_used = True
                            reset_visual_plan_for_global_replan(paths, str(replan_exc))
                            plan = stage_plan(data, voice)
                            print("[longform] QA amplio descarto parches y recompilo el plan visual")
                        write_json(paths["work"] / "03_visual_plan.json", plan)
                        print("[longform] QA de borrador genero reparacion dirigida %d" % (draft_attempt + 1))
                        plan = stage_assets(data, voice, plan)
                        stage_props(data, voice, plan)
            else:
                master = paths["out"] / "master.mp4"
            if args.stage == "render": return 0
            report = stage_qa(data, plan, master)
            print(json.dumps({"status": report["status"], "master": str(master), "qa": str(paths["work"] / "08_master_qa.json")}, ensure_ascii=False))
            return 0
    except Exception as exc:
        record_state(paths, args.stage, False, str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
