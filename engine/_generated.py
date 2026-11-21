"""GENERADO por scripts/codegen.py desde shared/core.json. NO editar a mano."""

CANVAS = {'width': 1080, 'height': 1920, 'fps': 24}
CAPTION_PILL_H = 150
CAPTION_PAD_BOTTOM = {'center_low': 420, 'bottom': 320}
CAPTION_PAD_TOP_WHEN_TOP = 240
PANEL = {'top_margin': 214, 'min_height': 640, 'content_padding': 300}
OVERLAY_ROW_PX = {'StepList': 126, 'CausalMeter': 156, 'ChapterDots': 92}
COMPONENTS = {'ObjectCallout', 'FocusPunch', 'Annotation', 'StoryArcChart', 'KeywordPop', 'SplitCompare', 'BigWordSequence', 'ChapterDots', 'LowerThird', 'CausalMeter', 'StepList', 'StatRing', 'CountUp'}
COMPONENT_ALIASES = {'CountUp': 'StatRing', 'Annotation': 'ObjectCallout'}
STRONG_OVERLAYS = {'StoryArcChart', 'KeywordPop', 'SplitCompare', 'BigWordSequence', 'CausalMeter', 'StepList', 'StatRing', 'CountUp'}
EXPRESSIVE_TRANSITIONS = {'punch_in', 'whip'}
EXPRESSIVE_MAX_PER_REEL = 3
MEDIA_BACKED_MIN_RATIO = 0.6
MAX_CONSECUTIVE_TEXT_SCENES = 2
KINETIC_TEXT_HITS_MAX = 4
AVATAR_COMPANION_H = 960
AVATAR_CAPTION_BAND_H = 352
AVATAR_H = 608
AVATAR_APPEARANCES = 2
AVATAR_MAX_APPEARANCE_MS = 0
VIEWER_MIN_SCORE = 70
VIEWER_RUNS = 2
SFX_MAX_GAIN = {'sub-drop': 1.1, 'impact': 1.1, 'riser': 1.0, 'whoosh': 1.1, 'swoosh-up': 1.1, 'click': 0.95, 'pop': 1.0, 'ui-soft-click': 0.85, 'ui-card-pop': 1.2, 'ui-check-tick': 1.0, 'ui-line-draw': 1.2, 'ui-meter-fill': 1.25, 'ui-filter-pass': 1.15, 'ui-filter-reject': 1.05, 'ui-callout-ping': 0.95, 'ui-page-swipe': 1.1, 'ui-impact-soft': 1.25}


def caption_lane_reserve_px(pos):
    """Reserva inferior (px) que los overlays dejan libre para el caption."""
    if pos == "top":
        return 0
    return CAPTION_PAD_BOTTOM.get(pos or "center_low", CAPTION_PAD_BOTTOM["center_low"]) + CAPTION_PILL_H


def caption_lane_reserve_top_px(pos):
    return (CAPTION_PAD_TOP_WHEN_TOP + CAPTION_PILL_H) if pos == "top" else 0
