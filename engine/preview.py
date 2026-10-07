#!/usr/bin/env python3
"""Contact sheet BARATA de un ReelPlan ANTES de generar media cara.

Resuelve anchors con una alineacion sintetica (~320ms por palabra), construye
props de preview SIN media (broll/hook muestran el fondo de marca con la
etiqueta de sus visual_targets), renderiza 1 still por escena con Remotion y
compone una contact sheet. CERO llamadas a proveedores (TTS, Omni, imagenes,
Kreado): el objetivo es revisar composicion, jerarquia, caption lane y densidad
de overlays cuando corregir el plan todavia es gratis.

Uso:
    python scripts/preview_plan.py contracts/mi_plan.json
    -> work/preview/contact_sheet.png + stills individuales
"""
import json
import math
import os
import re
import subprocess
import sys

from engine.config import ROOT, REMOTION_DIR as _REM, WORK_DIR as _WORK  # V2PORT

from engine import resolve as plan_resolve

REM = os.path.join(ROOT, "remotion")
OUT = os.path.join(ROOT, "work", "preview")

SCENE_PASSTHROUGH = (
    "intent", "visual_targets", "max_duration_ms", "layout", "plate_purpose",
    "visual_mode", "visual_family", "why_this_visual_not_other", "editorial_point",
    "why_it_matters", "visual_proof", "coverage_required", "caption_position",
    "avatar_layout", "visualBeats", "pacingBeats",
)
OVERLAY_PASSTHROUGH = (
    "semantic_kind", "placement", "must_not_cover", "safe_zone",
    "max_duration_ms", "blocks_captions", "rationale",
)


def rough_alignment(script):
    """Espejo de validate_plan.rough_alignment: timing sintetico por palabra."""
    words = []
    for i, m in enumerate(re.finditer(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ/]+", script)):
        start = i * 320
        words.append({"word": m.group(0), "start_ms": start, "end_ms": start + 230})
    return {"duration_ms": max(1000, len(words) * 320 + 500), "words": words}


def hx(c):
    c = str(c or "")
    return c if c.startswith("#") else "#" + c


def build_preview_props(plan):
    al = rough_alignment(plan["script"])
    r = plan_resolve.resolve(plan, al)
    brand = plan["meta"]["brand"]
    style = dict(plan.get("meta", {}).get("style", {}) or {})
    style.setdefault("caption_granularity", "word")
    style.setdefault("caption_decoration", "none")
    style.setdefault("caption_emphasis_policy", "smart_stopwords")
    style.setdefault("caption_readability_mode", "adaptive_boxed")
    style.setdefault("render_policy", "declared_only")

    caps = []
    for i, w in enumerate(al["words"]):
        nxt = al["words"][i + 1]["start_ms"] if i + 1 < len(al["words"]) else w["end_ms"]
        caps.append({"word": w["word"], "startMs": int(w["start_ms"]), "endMs": max(int(w["end_ms"]), int(nxt))})

    scenes = []
    for s in r["scenes"]:
        sp = {
            "role": s["role"],
            "source": "none",   # preview: nunca media real
            "media": None,
            "fromMs": s["fromMs"],
            "toMs": s["toMs"],
            "motion": "static",
            "transition_in": s.get("transition_in", "cut"),
        }
        for k in SCENE_PASSTHROUGH:
            if k in s:
                sp[k] = s[k]
        if s.get("clip", {}).get("treatment"):
            sp["treatment"] = s["clip"]["treatment"]
        scenes.append(sp)

    overlays = []
    plan_overlays = plan.get("overlays", [])
    for i, o in enumerate(r["overlays"]):
        op = dict(o)
        if i < len(plan_overlays):
            for k in OVERLAY_PASSTHROUGH:
                if k in plan_overlays[i]:
                    op[k] = plan_overlays[i][k]
        overlays.append(op)

    cta = plan.get("cta", {}) or {}
    hook = plan.get("hook", {}) or {}
    fps = int(plan.get("meta", {}).get("fps", 24))
    props = {
        "width": 1080, "height": 1920, "fps": fps,
        "totalMs": r["totalMs"],
        "providerMode": "preview",
        "brand": {"bg": hx(brand["bg"]), "fg": hx(brand["fg"]), "accent": hx(brand["accent"])},
        "style": style,
        "hook": {"headline": hook.get("headline", ""), "hookEndMs": min(2400, r["durationMs"])},
        "captions": caps,
        "scenes": scenes,
        "overlays": overlays,
        "sfx": [],
        "cta": {
            "text": cta.get("text", ""), "button": cta.get("button", ""),
            "fromMs": r["ctaStartMs"],
            "resource_title": cta.get("resource_title"),
            "resource_points": cta.get("resource_points"),
            "mockup_type": cta.get("mockup_type"),
        },
    }
    return props, r


def render_stills(props, r, fps):
    os.makedirs(OUT, exist_ok=True)
    props_path = os.path.join(OUT, "props_preview.json")
    with open(props_path, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False)
    frames = []
    for i, s in enumerate(props["scenes"]):
        # El momento representativo de la escena es el centro de su overlay
        # (si tiene): un still en escena "vacia" post-overlay enganaria la revision.
        mid = (s["fromMs"] + s["toMs"]) // 2
        for o in props["overlays"]:
            if s["fromMs"] <= o["startMs"] < s["toMs"]:
                mid = min(s["toMs"] - 1, o["startMs"] + o["durMs"] // 2)
                break
        frames.append(("scene%02d_%s" % (i, s["role"]), int(mid / 1000 * fps)))
    cta_mid = (r["ctaStartMs"] + r["totalMs"]) // 2
    frames.append(("cta", int(cta_mid / 1000 * fps)))
    stills = []
    for idx, (name, frame) in enumerate(frames):
        dst = os.path.join(OUT, "prev_%02d_%s.png" % (idx, name))
        cmd = ["npx", "remotion", "still", "Reel", dst,
               "--props=%s" % props_path, "--frame=%d" % frame]
        from engine.config import subprocess_env
        res = subprocess.run(cmd, cwd=REM, capture_output=True, text=True, shell=(os.name == "nt"), env=subprocess_env())
        if res.returncode != 0:
            raise SystemExit("preview still fallo (%s frame %d):\n%s" % (name, frame, res.stderr[-800:]))
        stills.append(dst)
        print("  still %s (frame %d)" % (name, frame))
    return stills


def contact_sheet(stills):
    cols = 4
    rows = math.ceil(len(stills) / cols)
    # ffmpeg tile exige un numero exacto de inputs: duplica el ultimo para rellenar
    padded = stills + [stills[-1]] * (cols * rows - len(stills))
    seq_dir = os.path.join(OUT, "_seq")
    os.makedirs(seq_dir, exist_ok=True)
    import shutil
    for i, src in enumerate(padded):
        dst = os.path.join(seq_dir, "s%03d.png" % i)
        shutil.copy(src, dst)
    sheet = os.path.join(OUT, "contact_sheet.png")
    cmd = ["ffmpeg", "-y", "-i", os.path.join(seq_dir, "s%03d.png"),
           "-filter_complex", "scale=300:-1,tile=%dx%d:padding=6:color=0x111111" % (cols, rows),
           "-frames:v", "1", sheet]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit("contact sheet fallo:\n%s" % res.stderr[-800:])
    return sheet


def main():
    if len(sys.argv) < 2:
        raise SystemExit("uso: python scripts/preview_plan.py contracts/<plan>.json")
    plan = json.load(open(sys.argv[1], encoding="utf-8"))
    props, r = build_preview_props(plan)
    fps = props["fps"]
    print("PREVIEW: %d escenas, %d overlays, %.1fs (alineacion sintetica)" % (
        len(props["scenes"]), len(props["overlays"]), r["totalMs"] / 1000.0))
    stills = render_stills(props, r, fps)
    sheet = contact_sheet(stills)
    print("PREVIEW OK: %s" % sheet)
    print("Revisa composicion/jerarquia/caption-lane ANTES de generar media cara.")


if __name__ == "__main__":
    main()


def main_for(plan_path):
    """Adapter programatico: contact sheet para un plan dado."""
    import sys as _sys
    argv = _sys.argv
    _sys.argv = ["preview", str(plan_path)]
    try:
        return main()
    finally:
        _sys.argv = argv
