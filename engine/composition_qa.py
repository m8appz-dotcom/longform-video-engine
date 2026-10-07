from __future__ import annotations

import pathlib
import re
from typing import Any

import cv2
import numpy as np

from engine.media_prefilter import _ocr
from engine.visual_contract import internal_id_visible


def _frame_at(cap: cv2.VideoCapture, at_ms: int):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0, at_ms))
    ok, frame = cap.read()
    return frame if ok and frame is not None else None


def _motion_score(frames: list[Any]) -> float:
    if len(frames) < 2:
        return 0.0
    grays = [cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (320, 180)) for frame in frames]
    scores = [float(np.mean(cv2.absdiff(grays[index - 1], grays[index]))) for index in range(1, len(grays))]
    return round(float(np.mean(scores)), 4)


def measure_rendered_motion(master: pathlib.Path, plan: dict[str, Any]) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(master))
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    moving = 0
    required = 0
    try:
        for shot in plan.get("shots") or []:
            start = int(shot.get("startMs") or 0)
            end = int(shot.get("endMs") or start + 1)
            duration = max(1, end - start)
            frames = [_frame_at(cap, start + round(duration * ratio)) for ratio in (0.14, 0.50, 0.84)]
            frames = [frame for frame in frames if frame is not None]
            score = _motion_score(frames)
            expects_motion = bool(shot.get("requiresObservedTransition")) or (
                shot.get("visualKind") in {"ui-card", "motion-card"}
                and int((shot.get("motionSpec") or {}).get("meaningfulChanges") or 0) >= 2
            )
            if expects_motion:
                required += 1
                if score < 0.45:
                    errors.append("%s declara cambio temporal pero el render es practicamente estatico (%.3f)" % (shot.get("shotId"), score))
            if score >= 0.45:
                moving += 1
            rows.append({
                "shot_id": shot.get("shotId"),
                "motion_score": score,
                "motion_required": expects_motion,
                "visual_kind": shot.get("visualKind"),
                "provider": shot.get("provider"),
            })
    finally:
        cap.release()
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "metrics": {
            "shots_measured": len(rows),
            "moving_shots": moving,
            "motion_required_shots": required,
            "actual_motion_share": round(moving / max(1, len(rows)), 4),
        },
        "shots": rows,
    }


def validate_composed_frames(samples: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    target_id = str((plan.get("cta") or {}).get("target_video_id") or "")
    for sample in samples:
        path = pathlib.Path(sample["path"])
        frame = cv2.imread(str(path))
        text, available = _ocr(frame)
        words = re.findall(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ]+\b", text, re.UNICODE)
        shot = sample.get("shot") or {}
        sid = str(sample.get("label") or shot.get("shotId") or "frame")
        if available and internal_id_visible(text, target_id):
            errors.append("%s muestra el ID interno del video recomendado" % sid)
        if available and str(shot.get("visualStrategy") or "") == "hybrid":
            maximum = int(shot.get("maxBackgroundWords") or 0)
            if str(shot.get("backgroundTextPolicy") or "") == "forbidden" and len(words) > maximum + 12:
                errors.append("%s contiene texto de fondo excesivo debajo del overlay (%d palabras)" % (sid, len(words)))
        rows.append({"label": sid, "ocr_available": available, "ocr_words": len(words), "ocr_text": text[:500]})
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "frames": rows,
        "metrics": {"frames": len(rows), "ocr_frames": sum(1 for row in rows if row["ocr_available"])},
    }
