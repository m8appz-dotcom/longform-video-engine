#!/usr/bin/env python3
"""QA visual basico para reels renderizados.

Detecta frames demasiado oscuros/vacios y huecos en plates.
No reemplaza revision humana. Los checks estructurales de media/captions/SFX
viven en validate_props.py y qa_report.py los incluye en el bundle versionado.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

from engine.config import ROOT, REMOTION_DIR as _REM, WORK_DIR as _WORK  # V2PORT

from engine import media_tools
DEFAULT_MP4 = os.path.join(ROOT, "remotion", "out", "reel.mp4")
DEFAULT_PROPS = os.path.join(ROOT, "remotion", "props.json")


def run(args):
    return media_tools.run(args, capture_output=True)


def load_props(props_path):
    try:
        return json.load(open(props_path, encoding="utf-8"))
    except Exception:
        return {}


def load_theme(props_path):
    props = load_props(props_path)
    return ((props.get("style") or {}).get("base_theme") or "unknown").lower()


def sample_frames(mp4, fps=2, w=64, h=114):
    with tempfile.TemporaryDirectory(prefix="reel-visual-qa-") as td:
        pattern = os.path.join(td, "frame_%04d.ppm")
        rr = run([
            "ffmpeg",
            "-v",
            "error",
            "-i",
            mp4,
            "-vf",
            "fps=%s,scale=%d:%d" % (fps, w, h),
            "-pix_fmt",
            "rgb24",
            pattern,
        ])
        if rr.returncode != 0:
            raise RuntimeError((rr.stderr or b"ffmpeg fallo").decode("utf-8", "replace")[-500:])
        chunks = []
        for name in sorted(os.listdir(td)):
            if name.endswith(".ppm"):
                chunks.append(read_ppm_rgb(os.path.join(td, name), w, h))
    frame_size = w * h * 3
    frames = []
    for chunk in chunks:
        if len(chunk) != frame_size:
            continue
        lum = []
        for i in range(0, len(chunk), 3):
            r, g, b = chunk[i], chunk[i + 1], chunk[i + 2]
            lum.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
        mean = sum(lum) / len(lum)
        var = sum((x - mean) ** 2 for x in lum) / len(lum)
        frames.append({"index": len(frames), "at_ms": round(len(frames) * (1000 / fps)), "mean_luma": mean, "luma_var": var, "luma_std": math.sqrt(var)})
    return frames


def read_ppm_rgb(path, expected_w, expected_h):
    data = open(path, "rb").read()
    tokens = []
    pos = 0
    while len(tokens) < 4:
        while pos < len(data) and data[pos] in b" \t\r\n":
            pos += 1
        if pos < len(data) and data[pos] == ord("#"):
            while pos < len(data) and data[pos] not in b"\r\n":
                pos += 1
            continue
        start = pos
        while pos < len(data) and data[pos] not in b" \t\r\n":
            pos += 1
        tokens.append(data[start:pos])
    magic, width, height, maxval = tokens
    while pos < len(data) and data[pos] in b" \t\r\n":
        pos += 1
    if magic != b"P6" or int(width) != expected_w or int(height) != expected_h or int(maxval) != 255:
        raise RuntimeError("PPM inesperado en %s" % path)
    return data[pos:]


def scene_at(props, at_ms):
    for sc in props.get("scenes", []):
        if int(sc.get("fromMs", 0)) <= at_ms < int(sc.get("toMs", 0)):
            return sc
    return None


INFORMATIVE_OVERLAYS = {
    "KeywordPop", "StepList", "StatRing", "CountUp",
    "StoryArcChart", "LowerThird", "Annotation",
    "ChapterDots", "CausalMeter", "ObjectCallout",
    # v2: SplitCompare/BigWordSequence cuentan como cobertura -- un plate
    # cubierto solo por ellos figuraba como 'hueco' y empujaba a apilar MAS texto.
    "SplitCompare", "BigWordSequence",
}


def media_balance_errors(props):
    """v2 (SEMANTICA SOBRE PRECISION): simetria del QA determinista. Todos los
    checks historicos protegian a los plates de quedarse sin TEXTO; ninguno
    protegia al reel de quedarse sin MEDIA/accion -- el motor que optimiza
    'pasar QA' convergia a plates llenos de overlays. Numeros de shared/core.json."""
    try:
        from engine._generated import MEDIA_BACKED_MIN_RATIO as _RATIO, MAX_CONSECUTIVE_TEXT_SCENES as _MAXTXT
    except Exception:
        _RATIO, _MAXTXT = 0.6, 2
    scenes = props.get("scenes", []) or []
    errors = []

    def _m(sc):
        return bool(sc.get("media")) or sc.get("role") == "avatar"

    body = [sc for sc in scenes if sc.get("role") != "hook" and sc.get("layout") != "cta"]
    if body:
        with_media = [sc for sc in body if _m(sc)]
        ratio = len(with_media) / float(len(body))
        if ratio + 1e-9 < _RATIO:
            errors.append("solo %d/%d escenas body con media (%.0f%% < %.0f%%); la base del reel es gente/accion, el texto va encima" % (
                len(with_media), len(body), 100 * ratio, 100 * _RATIO))
    run = 0
    for i, sc in enumerate(scenes):
        if _m(sc):
            run = 0
        else:
            run += 1
            if run == _MAXTXT + 1:
                errors.append("%d+ escenas sin media consecutivas terminando en scene %d (max %d)" % (run, i, _MAXTXT))
    return errors


def active_informative_overlay(props, at_ms):
    for o in props.get("overlays", []) or []:
        if o.get("component") not in INFORMATIVE_OVERLAYS:
            continue
        start = int(o.get("startMs", 0))
        end = start + int(o.get("durMs", 0))
        if start <= at_ms < end:
            return True
    return False


def plate_coverage_errors(props, max_gap_ms=300):
    # max_gap 300 (antes 700): los huecos cortos entre overlays los cierra ahora el
    # hold de render (Reel.tsx OverlayLayer extiende la Sequence hasta abutar el
    # siguiente overlay <=700ms); un hueco que sobrevive al hold es un plate vacio real.
    overlays = props.get("overlays", []) or []
    errors = []
    for idx, sc in enumerate(props.get("scenes", []) or []):
        if sc.get("role") != "plate" or sc.get("media") or sc.get("layout") == "cta" or sc.get("coverage_required") is False:
            continue
        start, end = int(sc.get("fromMs", 0)), int(sc.get("toMs", 0))
        if end - start <= 300:
            continue
        spans = []
        for o in overlays:
            if o.get("component") not in INFORMATIVE_OVERLAYS:
                continue
            a = int(o.get("startMs", 0))
            b = a + int(o.get("durMs", 0))
            if b <= start or a >= end:
                continue
            spans.append((max(start, a), min(end, b)))
        spans.sort()
        cursor = start
        gaps = []
        for a, b in spans:
            if b - a < 250:
                continue
            if a - cursor > max_gap_ms:
                gaps.append((cursor - start, a - start))
            cursor = max(cursor, b)
        if end - cursor > max_gap_ms:
            gaps.append((cursor - start, end - start))
        if gaps:
            errors.append("plate scene %d gaps=%s" % (idx, gaps[:3]))
    return errors


def chapter_structure_errors(props):
    overlays = props.get("overlays", []) or []
    errors = []
    for idx, sc in enumerate(props.get("scenes", []) or []):
        if sc.get("role") != "plate" or sc.get("media") or sc.get("plate_purpose") != "chapter":
            continue
        start, end = int(sc.get("fromMs", 0)), int(sc.get("toMs", 0))
        comps = {
            o.get("component")
            for o in overlays
            if int(o.get("startMs", 0)) < end
            and int(o.get("startMs", 0)) + int(o.get("durMs", 0)) > start
        }
        if comps == {"KeywordPop"} or (comps and not (comps & {"ChapterDots", "LowerThird"})):
            errors.append("chapter scene %d usa solo %s; necesita ChapterDots/LowerThird o corte directo" % (idx, ",".join(sorted(str(x) for x in comps))))
    return errors


def main():
    mp4 = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MP4
    props = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PROPS
    if not os.path.exists(mp4):
        print("VISUAL QA FAIL: no existe %s" % mp4)
        return 2
    props_data = load_props(props)
    theme = ((props_data.get("style") or {}).get("base_theme") or "unknown").lower()
    frames = sample_frames(mp4)
    if not frames:
        print("VISUAL QA FAIL: no pude muestrear frames")
        return 1
    # Frames de escenas CON media quedan exentos de low/very_low salvo negro
    # casi absoluto: video de accion real (interiores oscuros, fade-in, ropa
    # negra) disparaba falsos 'frames casi negros' -- ceguera que castigaba
    # precisamente la media que el mandato v2 pide.
    def _scene_has_media(f):
        sc = scene_at(props_data, f["at_ms"])
        return bool(sc and (sc.get("media") or sc.get("role") == "avatar"))
    low = [f for f in frames if f["mean_luma"] < 28 and f["luma_var"] < 950 and not _scene_has_media(f)]
    very_low = [f for f in frames if f["mean_luma"] < (8 if _scene_has_media(f) else 18)]
    bright_empty = []
    if theme == "light":
        for f in frames:
            sc = scene_at(props_data, f["at_ms"])
            if sc and sc.get("role") == "plate" and not sc.get("media") and sc.get("layout") != "cta":
                scene_age = f["at_ms"] - int(sc.get("fromMs", 0))
                # luma_std<6 (antes 9) acompana la reduccion del glow del plate en
                # remotion/src/layers/surfaces.tsx (0.42->0.10): con 9, bajar el glow
                # reactivaba bright_empty y la remediacion volvia a subirlo (oscilacion).
                if scene_age >= 450 and not active_informative_overlay(props_data, f["at_ms"]) and f["mean_luma"] > 232 and f["luma_std"] < 6:
                    bright_empty.append(f)
    coverage = plate_coverage_errors(props_data)
    chapter_structure = chapter_structure_errors(props_data)
    media_balance = media_balance_errors(props_data)
    errors = []
    if media_balance:
        errors.append("balance de medio: " + "; ".join(media_balance[:4]))
    if theme == "light" and low:
        errors.append("tema claro con %d frames demasiado oscuros/casi vacios" % len(low))
    if very_low:
        errors.append("%d frames casi negros" % len(very_low))
    if bright_empty:
        errors.append("tema claro con %d frames plate demasiado vacios/planos" % len(bright_empty))
    if coverage:
        errors.append("huecos temporales en plates: " + "; ".join(coverage[:4]))
    if chapter_structure:
        errors.append("chapters casi vacios: " + "; ".join(chapter_structure[:4]))
    if errors:
        print("VISUAL QA FAIL: " + "; ".join(errors))
        bad = low or very_low or bright_empty
        print("  primeros frames malos:", [f["index"] for f in bad[:8]])
        return 1
    means = [f["mean_luma"] for f in frames]
    print("VISUAL QA OK: %d frames, luma %.1f-%.1f, theme=%s" % (len(frames), min(means), max(means), theme))
    return 0


if __name__ == "__main__":
    sys.exit(main())
