#!/usr/bin/env python3
"""Genera engine/_generated.py y remotion/src/generated.ts desde shared/core.json.

La geometria del caption/panel y el registro de componentes viven en UN solo
archivo (shared/core.json). Renderer y validadores importan lo generado: es
imposible que diverjan. Correr tras cualquier edicion de core.json.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = json.load(open(os.path.join(ROOT, "shared", "core.json"), encoding="utf-8"))

HEADER = "GENERADO por scripts/codegen.py desde shared/core.json. NO editar a mano."


def gen_python():
    lines = [
        '"""%s"""' % HEADER,
        "",
        "CANVAS = %r" % (CORE["canvas"],),
        "CAPTION_PILL_H = %d" % CORE["caption"]["pill_height"],
        "CAPTION_PAD_BOTTOM = %r" % (CORE["caption"]["pad_bottom"],),
        "CAPTION_PAD_TOP_WHEN_TOP = %d" % CORE["caption"]["pad_top_when_top"],
        "PANEL = %r" % (CORE["panel"],),
        "OVERLAY_ROW_PX = %r" % (CORE["overlay_row_px"],),
        "COMPONENTS = %r" % (set(CORE["components"]),),
        "COMPONENT_ALIASES = %r" % (CORE["component_aliases"],),
        "STRONG_OVERLAYS = %r" % (set(CORE["strong_overlays"]),),
        "EXPRESSIVE_TRANSITIONS = %r" % (set(CORE["expressive_transitions"]["kinds"]),),
        "EXPRESSIVE_MAX_PER_REEL = %d" % CORE["expressive_transitions"]["max_per_reel"],
        "MEDIA_BACKED_MIN_RATIO = %r" % CORE["media_base"]["media_backed_min_ratio"],
        "MAX_CONSECUTIVE_TEXT_SCENES = %d" % CORE["media_base"]["max_consecutive_text_scenes"],
        "KINETIC_TEXT_HITS_MAX = %d" % CORE["media_base"]["kinetic_text_hits_max"],
        "AVATAR_COMPANION_H = %d" % CORE["avatar_split"]["companion_h"],
        "AVATAR_CAPTION_BAND_H = %d" % CORE["avatar_split"]["caption_band_h"],
        "AVATAR_H = %d" % CORE["avatar_split"]["avatar_h"],
        "AVATAR_APPEARANCES = %d" % CORE["avatar_split"]["appearances"],
        "AVATAR_MAX_APPEARANCE_MS = %d" % CORE["avatar_split"].get("max_appearance_ms", 0),
        "VIEWER_MIN_SCORE = %d" % CORE["viewer_gate"]["min_score"],
        "VIEWER_RUNS = %d" % CORE["viewer_gate"]["runs"],
        "SFX_MAX_GAIN = %r" % (CORE["sfx_max_gain"],),
        "",
        "",
        "def caption_lane_reserve_px(pos):",
        '    """Reserva inferior (px) que los overlays dejan libre para el caption."""',
        '    if pos == "top":',
        "        return 0",
        '    return CAPTION_PAD_BOTTOM.get(pos or "center_low", CAPTION_PAD_BOTTOM["center_low"]) + CAPTION_PILL_H',
        "",
        "",
        "def caption_lane_reserve_top_px(pos):",
        '    return (CAPTION_PAD_TOP_WHEN_TOP + CAPTION_PILL_H) if pos == "top" else 0',
        "",
    ]
    path = os.path.join(ROOT, "engine", "_generated.py")
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    return path


def gen_ts():
    lines = [
        "// %s" % HEADER,
        "",
        "export const CANVAS = %s as const;" % json.dumps(CORE["canvas"]),
        "export const CAPTION_PILL_H = %d;" % CORE["caption"]["pill_height"],
        "export const CAPTION_PAD_BOTTOM: Record<string, number> = %s;" % json.dumps(CORE["caption"]["pad_bottom"]),
        "export const CAPTION_PAD_TOP_WHEN_TOP = %d;" % CORE["caption"]["pad_top_when_top"],
        "export const PANEL = %s as const;" % json.dumps(CORE["panel"]),
        "export const OVERLAY_ROW_PX: Record<string, number> = %s;" % json.dumps(CORE["overlay_row_px"]),
        "export const COMPONENTS = %s as const;" % json.dumps(CORE["components"]),
        "export const COMPONENT_ALIASES: Record<string, string> = %s;" % json.dumps(CORE["component_aliases"]),
        "export const STRONG_OVERLAYS = new Set<string>(%s);" % json.dumps(CORE["strong_overlays"]),
        "export const EXPRESSIVE_TRANSITIONS = new Set<string>(%s);" % json.dumps(CORE["expressive_transitions"]["kinds"]),
        "export const MEDIA_BACKED_MIN_RATIO = %s;" % json.dumps(CORE["media_base"]["media_backed_min_ratio"]),
        "export const MAX_CONSECUTIVE_TEXT_SCENES = %d;" % CORE["media_base"]["max_consecutive_text_scenes"],
        "export const KINETIC_TEXT_HITS_MAX = %d;" % CORE["media_base"]["kinetic_text_hits_max"],
        "export const AVATAR_COMPANION_H = %d;" % CORE["avatar_split"]["companion_h"],
        "export const AVATAR_CAPTION_BAND_H = %d;" % CORE["avatar_split"]["caption_band_h"],
        "export const AVATAR_H = %d;" % CORE["avatar_split"]["avatar_h"],
        "export const AVATAR_APPEARANCES = %d;" % CORE["avatar_split"]["appearances"],
        "export const SFX_MAX_GAIN: Record<string, number> = %s;" % json.dumps(CORE["sfx_max_gain"]),
        "",
        "// Reserva inferior (px) que los overlays dejan libre para el caption.",
        "export const captionLaneReservePx = (pos?: string): number => {",
        '  if (pos === "top") return 0;',
        '  const pad = CAPTION_PAD_BOTTOM[pos || "center_low"] ?? CAPTION_PAD_BOTTOM["center_low"];',
        "  return pad + CAPTION_PILL_H;",
        "};",
        "",
        "export const captionLaneReserveTopPx = (pos?: string): number =>",
        '  pos === "top" ? CAPTION_PAD_TOP_WHEN_TOP + CAPTION_PILL_H : 0;',
        "",
    ]
    path = os.path.join(ROOT, "remotion", "src", "generated.ts")
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    return path


if __name__ == "__main__":
    print("OK:", gen_python())
    print("OK:", gen_ts())
