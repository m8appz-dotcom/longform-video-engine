from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
from typing import Any

import cv2
import numpy as np


WATERMARK_TERMS = {"shutterstock", "microstock", "alamy", "getty", "istock", "dreamstime", "depositphotos"}
WRONG_SOFTWARE_TERMS = {"blender", "deepseek", "premiere pro", "after effects", "photoshop"}


def _sample_frames(path: pathlib.Path, media_type: str) -> list[Any]:
    if media_type == "image":
        frame = cv2.imread(str(path))
        return [frame] if frame is not None else []
    cap = cv2.VideoCapture(str(path))
    frames: list[Any] = []
    try:
        count = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1))
        for fraction in (0.18, 0.50, 0.82):
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(count - 1, max(0, int(count * fraction))))
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
    finally:
        cap.release()
    return frames


def _sample_frame(path: pathlib.Path, media_type: str):
    frames = _sample_frames(path, media_type)
    return frames[len(frames) // 2] if frames else None


def _probe(path: pathlib.Path) -> dict[str, Any]:
    binary = shutil.which("ffprobe")
    if not binary:
        return {}
    result = subprocess.run(
        [binary, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,bit_rate,r_frame_rate,avg_frame_rate:format=duration,bit_rate,size", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    if result.returncode:
        return {}
    try:
        payload = json.loads(result.stdout)
        stream = (payload.get("streams") or [{}])[0]
        fmt = payload.get("format") or {}
        duration = float(fmt.get("duration") or 0)
        size = int(fmt.get("size") or path.stat().st_size)
        bitrate = int(stream.get("bit_rate") or fmt.get("bit_rate") or (size * 8 / duration if duration else 0))
        rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
        numerator, denominator = (rate.split("/", 1) + ["1"])[:2]
        fps = float(numerator) / max(1.0, float(denominator))
        return {"bitrate_bps": bitrate, "duration_seconds": duration, "fps": fps, "file_size": size}
    except Exception:
        return {}


def _ocr(frame) -> tuple[str, bool]:
    binary = shutil.which("tesseract")
    if not binary or frame is None:
        return "", False
    with tempfile.TemporaryDirectory(prefix="longform-ocr-") as directory:
        image = pathlib.Path(directory) / "frame.png"
        cv2.imwrite(str(image), frame)
        result = subprocess.run([binary, str(image), "stdout", "-l", "eng+spa"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        return re.sub(r"\s+", " ", result.stdout or "").strip(), result.returncode == 0


def _face_metrics(frame) -> tuple[int, float]:
    if frame is None:
        return 0, 0.0
    cascade_path = pathlib.Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    boxes = detector.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(60, 60))
    area = float(frame.shape[0] * frame.shape[1])
    return len(boxes), max((float(w * h) / area for _, _, w, h in boxes), default=0.0)


def _sharpness(frame) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _blockiness(frame) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    normal_h = float(np.mean(np.abs(np.diff(gray, axis=1)))) + 1e-6
    normal_v = float(np.mean(np.abs(np.diff(gray, axis=0)))) + 1e-6
    right = gray[:, 8::8]
    left = gray[:, 7:-1:8]
    bottom = gray[8::8, :]
    top = gray[7:-1:8, :]
    columns = min(right.shape[1], left.shape[1])
    rows = min(bottom.shape[0], top.shape[0])
    boundary_h = float(np.mean(np.abs(right[:, :columns] - left[:, :columns]))) if columns else normal_h
    boundary_v = float(np.mean(np.abs(bottom[:rows, :] - top[:rows, :]))) if rows else normal_v
    excess = max(0.0, ((boundary_h / normal_h) + (boundary_v / normal_v)) / 2.0 - 1.0)
    return min(1.0, excess / 2.0)


def _motion(frames: list[Any]) -> float:
    if len(frames) < 2:
        return 0.0
    grays = [cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (320, 180)) for frame in frames]
    return float(np.mean([np.mean(cv2.absdiff(grays[index - 1], grays[index])) for index in range(1, len(grays))]))


def _people_errors(frames: list[Any], characteristics: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    observations = [_face_metrics(frame) for frame in frames]
    face_count = max((item[0] for item in observations), default=0)
    face_ratio = max((item[1] for item in observations), default=0.0)
    policy = str(characteristics.get("peoplePolicy") or characteristics.get("people_policy") or "contextual")
    presenter_allowed = bool(characteristics.get("presenterAllowed") or characteristics.get("presenter_allowed"))
    requires_visible_face = bool(characteristics.get("requiresVisibleFace") or characteristics.get("requires_visible_face"))
    max_ratio = float(characteristics.get("maxFaceAreaRatio") or characteristics.get("max_face_area_ratio") or (0.45 if policy == "required" else 0.20))
    errors: list[str] = []
    if requires_visible_face and face_count == 0:
        errors.append("rostro esperado como evidencia pero no visible")
    elif policy == "required" and face_count == 0:
        errors.append("presentador requerido pero no visible")
    elif policy == "forbidden" and face_ratio >= 0.025:
        errors.append("persona prohibida domina evidencia")
    elif policy == "contextual" and face_ratio > max_ratio and not presenter_allowed:
        errors.append("presentador accidental domina la evidencia")
    return errors, {"faces": face_count, "max_face_area_ratio": round(face_ratio, 4), "people_policy": policy, "requires_visible_face": requires_visible_face}


def prefilter_search_thumbnail(path: pathlib.Path, characteristics: dict[str, Any] | None = None) -> dict[str, Any]:
    characteristics = characteristics or {}
    frames = _sample_frames(path, "image")
    if not frames:
        return {"status": "REJECT", "errors": ["thumbnail no decodificable"], "ocr_text": "", "metrics": {}}
    frame = frames[0]
    ocr_text, ocr_available = _ocr(frame)
    haystack = (path.name + " " + ocr_text).lower()
    errors: list[str] = []
    watermark_hits = sorted(term for term in WATERMARK_TERMS if term in haystack)
    if watermark_hits:
        errors.append("watermark/stock logo: %s" % ", ".join(watermark_hits))
    kind = str(characteristics.get("proofKind") or characteristics.get("media_need_kind") or "")
    wrong_software = sorted(term for term in WRONG_SOFTWARE_TERMS if term in haystack)
    if wrong_software and kind != "exact_ui_state":
        errors.append("software/tutorial inesperado: %s" % ", ".join(wrong_software))
    word_count = len(re.findall(r"\b\w+\b", ocr_text))
    if word_count > 28 and not characteristics.get("requires_readable_data"):
        errors.append("texto denso ajeno al beat")
    people_errors, people = _people_errors(frames, characteristics)
    errors.extend(people_errors)
    height, width = frame.shape[:2]
    return {"status": "REJECT" if errors else "PASS", "errors": errors, "ocr_text": ocr_text, "metrics": {"width": width, "height": height, "ocr_words": word_count, "ocr_available": ocr_available, **people}}


def prefilter(path: pathlib.Path, media_type: str, shot: dict[str, Any], route: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file() or path.stat().st_size <= 0:
        return {"status": "REJECT", "errors": ["archivo inexistente o vacio"], "warnings": [], "ocr_text": "", "metrics": {}}
    frames = _sample_frames(path, media_type)
    if not frames:
        return {"status": "REJECT", "errors": ["no se pudo decodificar media"], "warnings": [], "ocr_text": "", "metrics": {}}
    frame = frames[len(frames) // 2]
    height, width = frame.shape[:2]
    if width <= height:
        errors.append("orientacion no horizontal")
    if width < 1280 or height < 720:
        errors.append("resolucion menor que 1280x720")
    probe = _probe(path) if media_type == "video" else {}
    sharpness = float(np.mean([_sharpness(item) for item in frames]))
    blockiness = float(np.mean([_blockiness(item) for item in frames]))
    motion = _motion(frames)
    bitrate = int(probe.get("bitrate_bps") or 0)
    megapixels = width * height / 1_000_000
    resolution_score = min(25.0, 8.0 + megapixels * 5.0)
    bitrate_target = 8_000_000 if width >= 3000 else 2_500_000
    bitrate_score = 20.0 if media_type != "video" else min(20.0, 20.0 * bitrate / max(1, bitrate_target))
    sharpness_score = min(25.0, sharpness / 5.0)
    block_score = max(0.0, 15.0 * (1.0 - blockiness))
    motion_score = 10.0 if media_type != "video" else min(10.0, motion / 2.0)
    quality_score = round(min(100.0, resolution_score + bitrate_score + sharpness_score + block_score + motion_score + 5.0), 1)
    compressed_hd = media_type == "video" and width >= 1920 and bitrate and bitrate < 1_200_000 and (sharpness < 55 or blockiness > 0.12)
    upscale_suspected = width >= 1920 and sharpness < 35 and blockiness > 0.08
    if compressed_hd:
        errors.append("1080p comprimido sin detalle util")
    if upscale_suspected:
        errors.append("reescalado aparente: resolucion nominal sin nitidez")
    ocr_text, ocr_available = _ocr(frame)
    haystack = (path.name + " " + ocr_text).lower()
    watermark_hits = sorted(term for term in WATERMARK_TERMS if term in haystack)
    if watermark_hits:
        errors.append("watermark/stock logo: %s" % ", ".join(watermark_hits))
    expected_ui = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "") == "exact_ui_state"
    wrong_software = sorted(term for term in WRONG_SOFTWARE_TERMS if term in haystack)
    if wrong_software and not expected_ui:
        errors.append("software/tutorial inesperado: %s" % ", ".join(wrong_software))
    word_count = len(re.findall(r"\b\w+\b", ocr_text))
    if word_count > 28 and not shot.get("requiresReadableData"):
        errors.append("texto denso ajeno al beat")
    people_errors, people = _people_errors(frames, shot)
    errors.extend(people_errors)
    if shot.get("requiresReadableData") and route != "ui":
        expected = {token.lower() for token in re.findall(r"\b[\wáéíóúüñ]{4,}\b", str(shot.get("tts") or ""))}
        observed = {token.lower() for token in re.findall(r"\b[\wáéíóúüñ]{4,}\b", ocr_text)}
        if ocr_available and expected and not (expected & observed):
            errors.append("datos legibles no coinciden con narracion bloqueada")
        elif not ocr_available:
            warnings.append("OCR no disponible; requiere UI determinista o QA visual")
    source_meta: dict[str, Any] = {}
    for suffix in (".pexels.json", ".clip_extractor.json"):
        sidecar = pathlib.Path(str(path) + suffix)
        if sidecar.is_file():
            try:
                source_meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                source_meta = {}
            break
    source_width = int(source_meta.get("source_width") or source_meta.get("width") or 0)
    source_height = int(source_meta.get("source_height") or source_meta.get("height") or 0)
    metrics = {
        "width": width, "height": height, "frames_sampled": len(frames), "bitrate_bps": bitrate,
        "fps": round(float(probe.get("fps") or 0), 3), "sharpness": round(sharpness, 2),
        "blockiness": round(blockiness, 4), "motion_score": round(motion, 2),
        "quality_score": quality_score, "upscale_suspected": upscale_suspected,
        "source_width": source_width, "source_height": source_height,
        "source_resolution_verified": bool(source_width and source_height),
        "ocr_words": word_count, "ocr_available": ocr_available, **people,
    }
    return {"status": "REJECT" if errors else "PASS", "errors": errors, "warnings": warnings, "ocr_text": ocr_text, "metrics": metrics}
