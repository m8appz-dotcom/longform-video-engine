// GENERADO por scripts/codegen.py desde shared/core.json. NO editar a mano.

export const CANVAS = {"width": 1080, "height": 1920, "fps": 24} as const;
export const CAPTION_PILL_H = 150;
export const CAPTION_PAD_BOTTOM: Record<string, number> = {"center_low": 420, "bottom": 320};
export const CAPTION_PAD_TOP_WHEN_TOP = 240;
export const PANEL = {"top_margin": 214, "min_height": 640, "content_padding": 300} as const;
export const OVERLAY_ROW_PX: Record<string, number> = {"StepList": 126, "CausalMeter": 156, "ChapterDots": 92};
export const COMPONENTS = ["StatRing", "CountUp", "StepList", "CausalMeter", "StoryArcChart", "KeywordPop", "LowerThird", "ChapterDots", "ObjectCallout", "Annotation", "FocusPunch", "SplitCompare", "BigWordSequence"] as const;
export const COMPONENT_ALIASES: Record<string, string> = {"CountUp": "StatRing", "Annotation": "ObjectCallout"};
export const STRONG_OVERLAYS = new Set<string>(["KeywordPop", "StepList", "CausalMeter", "StatRing", "CountUp", "StoryArcChart", "SplitCompare", "BigWordSequence"]);
export const EXPRESSIVE_TRANSITIONS = new Set<string>(["punch_in", "whip"]);
export const MEDIA_BACKED_MIN_RATIO = 0.6;
export const MAX_CONSECUTIVE_TEXT_SCENES = 2;
export const KINETIC_TEXT_HITS_MAX = 4;
export const AVATAR_COMPANION_H = 960;
export const AVATAR_CAPTION_BAND_H = 352;
export const AVATAR_H = 608;
export const AVATAR_APPEARANCES = 2;
export const SFX_MAX_GAIN: Record<string, number> = {"sub-drop": 1.1, "impact": 1.1, "riser": 1.0, "whoosh": 1.1, "swoosh-up": 1.1, "click": 0.95, "pop": 1.0, "ui-soft-click": 0.85, "ui-card-pop": 1.2, "ui-check-tick": 1.0, "ui-line-draw": 1.2, "ui-meter-fill": 1.25, "ui-filter-pass": 1.15, "ui-filter-reject": 1.05, "ui-callout-ping": 0.95, "ui-page-swipe": 1.1, "ui-impact-soft": 1.25};

// Reserva inferior (px) que los overlays dejan libre para el caption.
export const captionLaneReservePx = (pos?: string): number => {
  if (pos === "top") return 0;
  const pad = CAPTION_PAD_BOTTOM[pos || "center_low"] ?? CAPTION_PAD_BOTTOM["center_low"];
  return pad + CAPTION_PILL_H;
};

export const captionLaneReserveTopPx = (pos?: string): number =>
  pos === "top" ? CAPTION_PAD_TOP_WHEN_TOP + CAPTION_PILL_H : 0;
