from __future__ import annotations

import collections
import pathlib
from typing import Any

import cv2
from PIL import Image, ImageDraw, ImageFont


def _provider_class(provider: str, original_provider: str = "") -> str:
    if provider == "library" and original_provider:
        return _provider_class(original_provider)
    base = provider.split("+", 1)[0]
    if base in {"user", "library", "clip_extractor", "pexels"}:
        return "real"
    if base in {"deterministic-ui", "deterministic-ui-avatar-fallback", "deterministic-composite", "remotion", "remotion-fallback", "remotion-avatar-fallback"}:
        return "deterministic"
    if base in {"image", "image_pair", "cutout_motion", "omni"}:
        return "generated"
    if base == "avatar":
        return "presenter"
    return provider or "unknown"


def _shot_provider_class(shot: dict[str, Any]) -> str:
    return _provider_class(str(shot.get("provider") or ""), str(shot.get("libraryOriginalProvider") or ""))


def validate_set(plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    shots = list(plan.get("shots") or [])
    providers = collections.Counter(str(shot.get("provider") or "") for shot in shots)
    classes = collections.Counter(_shot_provider_class(shot) for shot in shots)
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    degraded: list[dict[str, str]] = []
    for shot in shots:
        sid = str(shot.get("shotId") or "shot")
        kind = str(shot.get("visualKind") or "")
        provider = str(shot.get("provider") or "")
        if kind not in {"motion-card", "ui-card"} and not str(shot.get("source") or ""):
            errors.append("%s sin evidencia visual materializada" % sid)
        if shot.get("requiresReadableData") and kind != "ui-card":
            errors.append("%s datos exactos fuera de UI determinista" % sid)
        if shot.get("requiresObservedTransition") and kind == "image":
            errors.append("%s transicion observable resuelta como still" % sid)
        original_provider = str(shot.get("libraryOriginalProvider") or "") if provider == "library" else provider
        is_materialized_pair = original_provider.split("+", 1)[0] == "image_pair"
        if shot.get("temporalEvidenceMode") == "initial_final" and kind == "image" and not str(shot.get("secondarySource") or "") and not is_materialized_pair:
            errors.append("%s estado inicial/final requiere dos imagenes" % sid)
        proof_kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
        evidence_text = " ".join(str(shot.get(key) or "") for key in ("requiredEvidence", "tts", "visualProof")).lower()
        background = str(shot.get("backgroundSource") or "")
        if shot.get("hybridTemplate") and not background:
            errors.append("%s hibrido Remotion sin evidencia visual de fondo" % sid)
        if proof_kind == "product_inspection" and any(term in evidence_text for term in ("envase", "etiqueta", "packaging")) and not (str(shot.get("source") or "") or background):
            errors.append("%s inspeccion de envase sin envase visual" % sid)
        if proof_kind == "human_action" and shot.get("requiresObservedTransition") and kind == "ui-card" and not background:
            errors.append("%s tecnica humana continua resuelta como lista sin demostracion" % sid)
        if proof_kind == "human_action" and provider == "clip_extractor":
            errors.append("%s usa Clip Extractor como stock generico" % sid)
        if proof_kind in {"real_event", "third_party_commentary", "cultural_reference"} and provider != "clip_extractor":
            errors.append("%s sustituyo evidencia real con %s" % (sid, provider or "sin provider"))
        if shot.get("beatRole") == "proof" and kind == "motion-card":
            errors.append("%s motion-card reemplaza evidencia requerida" % sid)
        preferred = str(shot.get("preferredMedium") or "")
        provider_base = provider.split("+", 1)[0]
        if provider == "library" and shot.get("libraryOriginalProvider"):
            provider_base = str(shot.get("libraryOriginalProvider"))
        used_medium = "ui" if provider_base.startswith("deterministic-ui") else "motion-card" if provider_base.startswith("remotion") else provider_base
        if preferred and used_medium and preferred != used_medium:
            degraded.append({"shot_id": sid, "required": preferred, "used": used_medium})
        group = str(shot.get("continuityGroup") or "")
        if group:
            groups[group].append(shot)
    for group, members in groups.items():
        state_members = [member for member in members if member.get("requiresStateContinuity")]
        if not state_members:
            continue
        # Illustrative cutaways may alternate inside the same chapter without
        # taking part in the locked before/after state sequence.
        group_classes = {_shot_provider_class(member) for member in state_members}
        if len(group_classes) > 1 and "presenter" not in group_classes:
            errors.append("continuityGroup %s mezcla medios incompatibles: %s" % (group, sorted(group_classes)))
        generated = [member for member in state_members if _shot_provider_class(member) == "generated"]
        if len(generated) > 1 and not all(str(member.get("continuityLock") or "") for member in generated):
            errors.append("continuityGroup %s usa generacion independiente sin continuityLock" % group)
    switches = 0
    previous = None
    for shot in shots:
        current = _shot_provider_class(shot)
        if previous is not None and current != previous:
            switches += 1
        previous = current
    if shots and switches / max(1, len(shots) - 1) > 0.75:
        warnings.append("cambios de familia visual muy frecuentes")
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "metrics": {"shots": len(shots), "providers": dict(providers), "media_classes": dict(classes), "style_switches": switches, "continuity_groups": len(groups), "degraded_scenes": len(degraded)},
        "degraded_scenes": degraded,
    }


def _frame_for(path: pathlib.Path, media_type: str):
    if media_type == "image":
        frame = cv2.imread(str(path))
    else:
        cap = cv2.VideoCapture(str(path))
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1) // 2))
            ok, frame = cap.read()
            if not ok:
                frame = None
        finally:
            cap.release()
    if frame is None:
        return None
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def contact_sheet(plan: dict[str, Any], public_root: pathlib.Path, output: pathlib.Path) -> pathlib.Path:
    shots = list(plan.get("shots") or [])
    tile_w, tile_h = 480, 310
    columns = 4
    rows = max(1, (len(shots) + columns - 1) // columns)
    canvas = Image.new("RGB", (tile_w * columns, tile_h * rows), "#F0EDE6")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
    for index, shot in enumerate(shots):
        x = (index % columns) * tile_w
        y = (index // columns) * tile_h
        source = str(shot.get("source") or shot.get("backgroundSource") or "")
        media_type = str(shot.get("mediaType") or "video") if shot.get("source") else str(shot.get("backgroundMediaType") or "image")
        image = _frame_for(public_root / source, media_type) if source else None
        if image is None:
            image = Image.new("RGB", (tile_w, 245), "#0D0D0D")
            local = ImageDraw.Draw(image)
            local.text((24, 90), str((shot.get("uiSpec") or {}).get("headline") or shot.get("screenCopy") or shot.get("visualKind") or "VISUAL"), fill="#F0EDE6", font=font)
        image.thumbnail((tile_w, 245), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (tile_w, 245), "#111315")
        frame.paste(image, ((tile_w - image.width) // 2, (245 - image.height) // 2))
        canvas.paste(frame, (x, y))
        label = "%s | %s | %s" % (shot.get("shotId"), shot.get("provider"), shot.get("evidenceBeatId"))
        draw.text((x + 10, y + 254), label[:44], fill="#0D0D0D", font=font)
        draw.text((x + 10, y + 282), str(shot.get("mediaNeedKind") or "")[:44], fill="#2D8C74", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=90)
    return output
