#!/usr/bin/env python3
"""Validate Remotion props before rendering.

This catches stale or unsafe props.json files that bypass the ReelPlan validator,
for example old overlays that still show visual numbers not present in captions.
"""
import json
import math
import os
import re
import sys
import wave
from array import array

from engine.config import ROOT, REMOTION_DIR as _REM, WORK_DIR as _WORK  # V2PORT
DEFAULT_PROPS = os.path.join(ROOT, "remotion", "props.json")

from engine import pacing as pacing_utils
from engine import _generated as GEN  # V2PORT: registro unico

VISUAL_NUMBER_RE = re.compile(
    r"\b(?P<num>\d+)\s*(?:(?P<slash>/\s*\d+)|(?P<unit>%|s\b|seg\b|sec\b|min\b|mins\b|minutos?\b|m\b|metros?\b|reps?\b|repeticiones?\b|rondas?\b))",
    re.I,
)
SKIP_KEYS = {"prompt", "asset", "src", "url", "poster", "audio", "media", "file", "id", "role", "model", "size"}
STRONG_OVERLAYS = {
    "KeywordPop", "StepList", "CausalMeter",
    "StatRing", "CountUp", "StoryArcChart",
}
DEFAULT_SUPPORTED_OVERLAYS = {
    "StoryArcChart", "CountUp", "StatRing", "StepList",
    "CausalMeter", "ObjectCallout", "KeywordPop",
    "LowerThird", "Annotation", "ChapterDots",
    "FocusPunch", "SplitCompare", "BigWordSequence",
}
SUPPORTED_OVERLAYS = set(GEN.COMPONENTS)
STRONG_OVERLAYS = {component for component in STRONG_OVERLAYS if component in SUPPORTED_OVERLAYS}
ANIMATED_OVERLAYS = {
    "StoryArcChart", "CountUp", "StatRing", "StepList",
    "CausalMeter", "ObjectCallout", "KeywordPop",
    "LowerThird", "Annotation", "ChapterDots",
    "FocusPunch", "SplitCompare", "BigWordSequence",
}
ANIMATED_OVERLAYS = {component for component in ANIMATED_OVERLAYS if component in SUPPORTED_OVERLAYS}
CHAPTER_COVER_OVERLAYS = {"ChapterDots", "LowerThird"}
DECLARED_RENDER_POLICIES = {"declared_only"}
SPANISH_NUMBERS = {
    1: ("uno", "una", "un"),
    2: ("dos",),
    3: ("tres",),
    4: ("cuatro",),
    5: ("cinco",),
    6: ("seis",),
    7: ("siete",),
    8: ("ocho",),
    9: ("nueve",),
    10: ("diez",),
    11: ("once",),
    12: ("doce",),
    13: ("trece",),
    14: ("catorce",),
    15: ("quince",),
    16: ("dieciseis", "dieciséis"),
    17: ("diecisiete",),
    18: ("dieciocho",),
    19: ("diecinueve",),
    20: ("veinte",),
}
UNIT_WORDS = {
    "min": ("min", "mins", "minuto", "minutos"),
    "s": ("s", "seg", "segundo", "segundos"),
    "m": ("m", "metro", "metros"),
    "%": ("%", "por ciento"),
    "rep": ("rep", "reps", "repeticion", "repeticiones"),
    "ronda": ("ronda", "rondas"),
}
# Espejo de scripts/validate_plan.py: caps de gain del banco de SFX. Aqui se aplican
# a la MEZCLA FINAL (director + auto) para cerrar el hueco C8 (las auto no pasaban por cap).
SFX_MAX_GAIN = {
    "sub-drop": 1.10, "impact": 1.10, "riser": 1.00, "whoosh": 1.10, "swoosh-up": 1.10,
    "click": 0.95, "pop": 1.00, "ui-soft-click": 0.85, "ui-card-pop": 1.20,
    "ui-check-tick": 1.00, "ui-line-draw": 1.20, "ui-meter-fill": 1.25,
    "ui-filter-pass": 1.15, "ui-filter-reject": 1.05, "ui-callout-ping": 0.95,
    "ui-page-swipe": 1.10, "ui-impact-soft": 1.25,
}


def has_list(value, min_len=1):
    return isinstance(value, list) and len(value) >= min_len


def has_text(value):
    return value is not None and str(value).strip() != ""


def has_declared_overlay_content(component, params):
    params = params or {}
    # params.allow_renderer_defaults ya NO cortocircuita este check (Fuga C10).
    if component == "StoryArcChart":
        return has_list(params.get("points"), 2)
    if component in ("StatRing", "CountUp"):
        return has_text(params.get("value"))
    if component == "StepList":
        return has_list(params.get("items"))
    if component == "CausalMeter":
        return has_list(params.get("items"))
    if component in ("ObjectCallout", "Annotation"):
        return has_text(params.get("label"))
    if component == "KeywordPop":
        return has_list(params.get("words"))
    if component == "LowerThird":
        return has_text(params.get("text"))
    if component == "ChapterDots":
        return has_list(params.get("labels"))
    if component == "FocusPunch":
        return has_text(params.get("target_x")) and has_text(params.get("target_y"))
    if component == "SplitCompare":
        return has_text(params.get("left_label")) and has_text(params.get("right_label"))
    if component == "BigWordSequence":
        return has_list(params.get("words"), 2)
    return True


from engine._generated import (
    OVERLAY_ROW_PX as LIST_ROW_PX,
    CAPTION_PILL_H,
    caption_lane_reserve_px as _gen_lane_px,
)


def scene_caption_pos(props, at_ms):
    """Posicion efectiva del caption en un instante: override por escena > style global.
    Espejo de Reel.tsx sceneCaptionPos."""
    for s in props.get("scenes") or []:
        if int(s.get("fromMs", 0)) <= at_ms < int(s.get("toMs", 0)):
            pos = s.get("caption_position")
            if pos:
                return pos
            break
    return ((props.get("style") or {}).get("caption_position")) or "center_low"


def caption_lane_reserve_px(style, pos=None):
    """Reserva de caption lane desde shared/core.json (via _generated): la misma
    matematica que usa el renderer, generada de la misma fuente."""
    style = style or {}
    return _gen_lane_px(pos or style.get("caption_position") or "center_low")


def list_overlay_fit(component, params, style, pos=None):
    """Estima si una lista cabe en la zona segura sobre el caption.
    Devuelve (content_px, available_px, fits) o None si no aplica."""
    if component not in LIST_ROW_PX:
        return None
    items = params.get("items") or params.get("labels") or params.get("criteria") or []
    n = len(items) if isinstance(items, list) else 0
    if not n:
        return None
    content_h = n * LIST_ROW_PX[component]
    available = 1920 - caption_lane_reserve_px(style, pos) - 214  # 214 = margen superior del panel
    return content_h, available, content_h <= available


def compact(text):
    t = str(text).lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def unit_key(unit):
    u = compact(unit)
    if u in ("min", "mins", "minuto", "minutos"):
        return "min"
    if u in ("s", "seg", "sec", "segundo", "segundos"):
        return "s"
    if u in ("m", "metro", "metros"):
        return "m"
    if u in ("rep", "reps", "repeticion", "repeticiones"):
        return "rep"
    if u in ("ronda", "rondas"):
        return "ronda"
    if u == "%":
        return "%"
    return u


def token_allowed(token, num, unit, caption_text):
    if "/" in token:
        m = re.match(r"\s*(\d+)\s*/\s*(\d+)\s*", token)
        if not m:
            return False
        a, b = int(m.group(1)), int(m.group(2))
        if compact(token) in caption_text:
            return True
        return any(
            compact("%s de %s" % (x, y)) in caption_text
            for x in SPANISH_NUMBERS.get(a, ())
            for y in SPANISH_NUMBERS.get(b, ())
        )
    n = int(num)
    u = unit_key(unit)
    forms = [str(n)]
    if u:
        forms += ["%s %s" % (n, x) for x in UNIT_WORDS.get(u, (u,))]
        forms += ["%s%s" % (n, x) for x in UNIT_WORDS.get(u, (u,))]
    if any(compact(x) in caption_text for x in forms):
        return True
    if u:
        return any(
            compact("%s %s" % (nw, uw)) in caption_text
            for nw in SPANISH_NUMBERS.get(n, ())
            for uw in UNIT_WORDS.get(u, (u,))
        )
    return any(compact(w) in caption_text for w in SPANISH_NUMBERS.get(n, ()))


def walk(value, path="props"):
    if isinstance(value, dict):
        if value.get("visual_scale") is True or value.get("allow_visual_number_scale") is True:
            return
        for k, v in value.items():
            if str(k) in SKIP_KEYS:
                continue
            yield from walk(v, "%s.%s" % (path, k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, "%s[%d]" % (path, i))
    elif isinstance(value, str):
        for m in VISUAL_NUMBER_RE.finditer(value):
            yield path, m.group(0), m.group("num"), m.group("unit") or m.group("slash") or ""


def overlap_ms(a, b):
    a0 = int(a.get("startMs", 0))
    a1 = a0 + int(a.get("durMs", 0))
    b0 = int(b.get("startMs", 0))
    b1 = b0 + int(b.get("durMs", 0))
    return max(0, min(a1, b1) - max(a0, b0))


def placement_group(o):
    p = o.get("placement") or o.get("safe_zone") or ""
    c = o.get("component")
    if p in ("safe_center", "full_context") or c in STRONG_OVERLAYS:
        return "center"
    if p in ("safe_top", "top"):
        return "top"
    if p in ("safe_lower", "bottom"):
        return "bottom"
    return p or "center"


def caption_hidden_stats(props):
    style = props.get("style") or {}
    if style.get("caption_style") == "none":
        return 0, 0
    hook_end = int((props.get("hook") or {}).get("hookEndMs") or 0)
    cta_ms = int((props.get("cta") or {}).get("fromMs") or props.get("totalMs") or 0)
    blocks = [
        (int(o.get("startMs", 0)), int(o.get("startMs", 0)) + int(o.get("durMs", 0)))
        for o in props.get("overlays", []) or []
        if o.get("blocks_captions") is True
    ]
    hidden = 0
    total = 0
    for c in props.get("captions", []) or []:
        at = int(c.get("startMs", 0))
        if at < hook_end or at >= cta_ms:
            continue
        total += 1
        if any(a <= at < b for a, b in blocks):
            hidden += 1
    return hidden, total


def sfx_in_window(sfx, start, end, ids=None):
    out = []
    for x in sfx:
        sid = x.get("id")
        if not sid or sid == "none":
            continue
        if ids and sid not in ids:
            continue
        at = int(x.get("atMs", 0))
        if start <= at <= end:
            out.append(x)
    return out


def media_public_path(media):
    if not isinstance(media, str) or not media.startswith("media/"):
        return None
    rel = media.replace("/", os.sep)
    return os.path.join(ROOT, "remotion", "public", rel)


def generated_media_needs_fingerprint(scene):
    media = scene.get("media") or ""
    if not media.startswith("media/"):
        return False
    name = os.path.basename(media)
    return name.startswith(("broll_", "image_", "gen_", "avatar_"))


def engine_generated_clip_extractor_media(scene, media_path=None):
    media = str(scene.get("media") or "").lower().replace("\\", "/")
    if "broll_clip_extractor_" in media or "/clip_extractor" in media:
        return True
    if media_path and os.path.exists(media_path + ".clip_extractor.json"):
        return True
    meta_path = (media_path or "") + ".meta.json"
    if meta_path and os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, encoding="utf-8-sig"))
        except Exception:
            meta = {}
        marker = "%s %s" % (meta.get("kind", ""), meta.get("provider", ""))
        return "clip_extractor" in marker.lower()
    return False


def dbfs(value):
    value = float(value or 0)
    if value <= 1e-12:
        return -120.0
    return 20.0 * math.log10(value)


def wav_peak(path):
    try:
        with wave.open(path, "rb") as wf:
            if wf.getsampwidth() != 2:
                return None
            raw = wf.readframes(wf.getnframes())
        samples = array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
        if not samples:
            return 0.0
        return max(abs(x) for x in samples) / 32768.0
    except Exception:
        return None


ACCENTED_PUBLIC_WORDS = {
    "tecnica": "técnica",
    "despues": "después",
    "evaluacion": "evaluación",
    "operacion": "operación",
    "articulacion": "articulación",
    "repeticion": "repetición",
    "porcion": "porción",
}


def public_copy_issues(label, value):
    if not isinstance(value, str) or not value.strip():
        return []
    issues = []
    c = compact(value)
    for plain, accented in ACCENTED_PUBLIC_WORDS.items():
        if re.search(r"(^|\s)%s($|\s)" % re.escape(plain), c) and accented not in value.lower():
            issues.append("%s debe usar acento en %r" % (label, accented))
    return issues


def captions_for_overlay(props, overlay, tolerance_ms=800):
    start = int(overlay.get("startMs", 0)) - tolerance_ms
    end = int(overlay.get("startMs", 0)) + int(overlay.get("durMs", 0)) + tolerance_ms
    words = []
    for caption in props.get("captions", []) or []:
        c0 = int(caption.get("startMs", 0))
        c1 = int(caption.get("endMs", c0))
        if c1 >= start and c0 <= end:
            words.append(str(caption.get("word", "")))
    return compact(" ".join(words))


def main(path=None):
    path = path or (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROPS)
    props = json.load(open(path, encoding="utf-8"))
    errors = []
    policies = props.get("policies") or {}
    style = props.get("style") or {}
    render_policy = policies.get("render_policy") or style.get("render_policy") or "declared_only"
    declared_only = True
    if render_policy not in DECLARED_RENDER_POLICIES:
        errors.append("policies.render_policy debe ser declared_only; recibido %r" % render_policy)
    if declared_only and style.get("plate_layout") == "auto":
        errors.append("declared_only no permite style.plate_layout=auto; declara overlays/plate_purpose concretos")
    supported_sources = {"asset", "google", "pexels", "clip_extractor", "kreado", "image", "none", ""}
    overlays = props.get("overlays") or []
    for idx, scene in enumerate(props.get("scenes") or []):
        start = int(scene.get("fromMs", 0))
        end = int(scene.get("toMs", 0))
        dur = end - start
        if dur <= 0:
            errors.append("scene[%d]/%s dura %dms; no se permiten escenas de duracion cero" % (
                idx, scene.get("role"), dur))
        elif scene.get("layout") == "cta" and dur < 2500:
            errors.append("scene[%d]/cta dura %dms; minimo 2500ms" % (idx, dur))
        for field in ("editorial_point", "why_it_matters", "visual_proof"):
            if len(str(scene.get(field) or "").strip()) < 12:
                errors.append("scene[%d]/%s requiere %s para QA creativo" % (idx, scene.get("role"), field))
        source = scene.get("source") or ""
        if source not in supported_sources:
            errors.append("scene[%d] usa source no soportado en props: %r" % (idx, source))
        if scene.get("plate_purpose") == "comparison":
            errors.append("scene[%d]/%s usa plate_purpose='comparison' legacy; regenera desde plan valido" % (
                idx, scene.get("role")))
        if scene.get("visual_family") == "decision_compare":
            errors.append("scene[%d]/%s usa visual_family='decision_compare' legacy; regenera desde plan valido" % (
                idx, scene.get("role")))
        needs_media = (
            scene.get("role") in ("avatar", "broll")
            or (scene.get("role") == "hook" and source != "none")
            or source in ("asset", "google", "pexels", "clip_extractor", "kreado", "image")
        )
        if needs_media and not scene.get("media"):
            errors.append("scene[%d]/%s source=%s requiere media resuelto antes de render" % (
                idx, scene.get("role"), source or "<missing>"))
        media_path = media_public_path(scene.get("media"))
        if media_path and not os.path.exists(media_path):
            errors.append("scene[%d]/%s media no existe en public: %s" % (
                idx, scene.get("role"), scene.get("media")))
        if source == "asset" and engine_generated_clip_extractor_media(scene, media_path):
            errors.append("scene[%d]/%s es Clip Extractor camuflado como source=asset; conserva source='clip_extractor' en props" % (
                idx, scene.get("role")))
        if policies.get("media_fingerprints") is True and generated_media_needs_fingerprint(scene):
            meta_path = (media_path or "") + ".meta.json"
            if not media_path or not os.path.exists(meta_path):
                errors.append("scene[%d]/%s media generado no tiene fingerprint; regenera props/assets" % (
                    idx, scene.get("role")))
        if source in ("asset", "pexels", "clip_extractor", "image"):
            targets = [str(x).strip() for x in (scene.get("visual_targets") or []) if str(x).strip()]
            if not targets:
                errors.append("scene[%d]/%s source=%s requiere visual_targets concretos para QA semantico" % (
                    idx, scene.get("role"), source))
            if len(compact(scene.get("visual_proof") or "")) < 12:
                errors.append("scene[%d]/%s source=%s requiere visual_proof concreto para comparar contra el asset" % (
                    idx, scene.get("role"), source))
        if scene.get("role") == "plate" and source == "none" and scene.get("plate_purpose") == "chapter":
            overlapping = [
                o for o in overlays
                if int(o.get("startMs", 0)) < end
                and int(o.get("startMs", 0)) + int(o.get("durMs", 0)) > start
            ]
            comps = {o.get("component") for o in overlapping}
            if comps == {"KeywordPop"} or (comps and not (comps & CHAPTER_COVER_OVERLAYS)):
                errors.append("scene[%d]/chapter no puede depender solo de KeywordPop; usa ChapterDots, LowerThird o corta al B-roll" % idx)
        if declared_only and scene.get("role") in ("plate", "hook") and source == "none" and not scene.get("media") and scene.get("layout") != "cta":
            overlapping = [
                o for o in overlays
                if int(o.get("startMs", 0)) < end
                and int(o.get("startMs", 0)) + int(o.get("durMs", 0)) > start
            ]
            declared_plate = has_text(scene.get("plate_purpose")) and scene.get("plate_purpose") != "none"
            if not declared_plate and not overlapping:
                errors.append("scene[%d]/%s source=none no declara plate_purpose ni overlays; Remotion no debe inventar contenido" % (
                    idx, scene.get("role")))
            if declared_plate and scene.get("plate_purpose") in ("decision_card", "rule_checklist") and not has_list(scene.get("visual_targets")):
                errors.append("scene[%d]/%s plate_purpose=%s requiere visual_targets; Remotion no puede usar labels fallback" % (
                    idx, scene.get("role"), scene.get("plate_purpose")))
    pacing = pacing_utils.pacing_report(props)
    if not pacing.get("ok"):
        errors.extend(pacing.get("errors") or [])
    if pacing.get("cosmetic_count", 0):
        errors.append("props contiene %d pacingBeats cosmeticos/legacy; regenera props con visualBeats semanticos" % pacing.get("cosmetic_count", 0))
    avatar_policy = policies.get("avatar_policy", "required")
    avatar_scenes = [s for s in props.get("scenes", []) or [] if s.get("role") == "avatar"]
    if avatar_policy != "disabled" and not avatar_scenes:
        errors.append("props requieren avatar: no hay escenas role='avatar'")
    for idx, scene in enumerate(avatar_scenes):
        if not scene.get("media"):
            errors.append("avatar scene %d no tiene media/avatar_*.mp4 resuelto" % idx)
    media_policy = policies.get("media_policy", "production")
    media_min = int(policies.get("media_min_scenes", 2) or 0)
    media_scenes = [
        s for s in props.get("scenes", []) or []
        if s.get("role") != "hook"
        and s.get("layout") != "cta"
        and s.get("source") in ("asset", "pexels", "clip_extractor", "image")
        and s.get("media")
    ]
    if media_policy == "production" and len(media_scenes) < media_min:
        errors.append("props media_policy=production requiere %d escenas pexels/clip_extractor/image con media; recibidas %d" % (
            media_min, len(media_scenes)))
    # v2 (SEMANTICA SOBRE PRECISION): espejo del balance de medio del plan. El
    # piso fijo de 2 dejo pasar el reel 3/9 media; y una remediacion en props
    # podia degradar por debajo de lo que el plan prometio sin que nadie lo viera.
    try:
        from engine._generated import MEDIA_BACKED_MIN_RATIO as _MB_RATIO, MAX_CONSECUTIVE_TEXT_SCENES as _MB_MAXTXT
    except Exception:
        _MB_RATIO, _MB_MAXTXT = 0.6, 2
    _mb_body = [s for s in props.get("scenes", []) or [] if s.get("role") != "hook" and s.get("layout") != "cta"]
    if media_policy == "production" and _mb_body:
        try:
            _mb_min_ratio = float(policies.get("media_min_ratio", _MB_RATIO))
        except Exception:
            _mb_min_ratio = _MB_RATIO
        _mb_backed = [s for s in _mb_body if s.get("media") or s.get("role") == "avatar"]
        _mb_ratio = len(_mb_backed) / float(len(_mb_body))
        if _mb_ratio + 1e-9 < _mb_min_ratio:
            errors.append("balance de medio en props: %d/%d escenas body con media resuelta (%.0f%% < %.0f%%)" % (
                len(_mb_backed), len(_mb_body), 100 * _mb_ratio, 100 * _mb_min_ratio))
        _mb_run = 0
        for _mb_i, s in enumerate(props.get("scenes", []) or []):
            if s.get("media") or s.get("role") == "avatar":
                _mb_run = 0
                continue
            _mb_run += 1
            if _mb_run == _MB_MAXTXT + 1:
                errors.append("balance de medio en props: %d+ escenas sin media consecutivas terminando en scene %d (max %d)" % (
                    _mb_run, _mb_i, _MB_MAXTXT))
    hidden, total_captions = caption_hidden_stats(props)
    if total_captions and hidden / total_captions > 0.15:
        errors.append("captions palabra-por-palabra ocultas por overlays: %d/%d palabras" % (hidden, total_captions))
    caption_style = style.get("caption_style")
    readability = style.get("caption_readability_mode")
    readable_modes = {"adaptive_boxed", "high_contrast_boxed"}
    if caption_style != "none" and readability not in readable_modes:
        errors.append("meta.style.caption_readability_mode debe ser adaptive_boxed/high_contrast_boxed para captions legibles sobre media")
    full_bleed_media = [
        s for s in props.get("scenes", []) or []
        if s.get("media")
        and s.get("layout") in ("full_bleed", "full_frame")
        and s.get("source") in ("asset", "google", "pexels", "clip_extractor", "image")
    ]
    if full_bleed_media and caption_style == "word_pop" and readability not in readable_modes:
        errors.append("caption_style=word_pop sobre media full-bleed requiere caption_readability_mode boxed/adaptive")
    cta = props.get("cta") or {}
    if cta.get("visual_style"):
        errors.append("cta.visual_style no debe llegar a props publicos ni renderizarse")
    for label, value in (
        ("cta.text", cta.get("text")),
        ("cta.button", cta.get("button")),
        ("cta.resource_title", cta.get("resource_title")),
    ):
        errors.extend(public_copy_issues(label, value))
    for idx, point in enumerate(cta.get("resource_points") or []):
        errors.extend(public_copy_issues("cta.resource_points[%d]" % idx, point))
    for oidx, overlay in enumerate(props.get("overlays") or []):
        component = overlay.get("component")
        params = overlay.get("params") or {}
        if (overlay.get("semantic_kind") == "comparison" or overlay.get("type") == "compare") and component != "SplitCompare":
            errors.append("overlay/%s usa comparativo legacy; para contrastes A/B explicitos usa SplitCompare" % component)
        if component not in SUPPORTED_OVERLAYS:
            errors.append("overlay/%s no esta incluido en el process map activo" % component)
        if declared_only and not has_declared_overlay_content(component, params):
            errors.append("overlay/%s no declara contenido suficiente; Remotion no puede usar defaults hardcoded" % component)
        if declared_only and params.get("allow_renderer_defaults"):
            errors.append("overlay/%s usa params.allow_renderer_defaults; prohibido bajo declared_only (deja que Remotion invente valores/labels). Declara el contenido real." % component)
        _mnc = overlay.get("must_not_cover") or []
        _side = str(params.get("side") or "").lower()
        if "caption" in _mnc and (overlay.get("placement") == "safe_lower" or _side == "bottom"):
            errors.append("overlay/%s declara must_not_cover=caption pero cae en la lane inferior (placement=safe_lower/side=bottom); reposiciona a safe_top/safe_center" % component)
        _pos = scene_caption_pos(props, int(overlay.get("startMs", 0)) + 1)
        _fit = list_overlay_fit(component, params, style, _pos)
        if _fit and not _fit[2]:
            _n = len(params.get("items") or params.get("labels") or params.get("criteria") or [])
            _hint = "reduce items o divide la escena" if _pos in ("bottom", "top") else \
                "reduce items, divide la escena, o declara caption_position:\"bottom\" en la escena para liberar ~100px"
            errors.append(
                "overlay/%s: %d items (~%dpx) no caben en la zona segura sobre el caption "
                "(~%dpx disponibles con caption_position=%s); %s"
                % (component, _n, _fit[0], _fit[1], _pos, _hint))
        caption_text = captions_for_overlay(props, overlay)
        if component == "CausalMeter" and str(params.get("visual_asset_strategy", "")).lower() == "diagram":
            if params.get("image_slots"):
                errors.append("CausalMeter diagram no debe traer image_slots compactos")
        if component == "StepList":
            item_count = len(params.get("items") or [])
            dur = int(overlay.get("durMs", 0) or 0)
            has_item_ms = bool(overlay.get("itemMs"))
            compact_short = params.get("variant") == "compact" and dur >= 900
            if item_count >= 3 and not has_item_ms and dur < 1800 and not compact_short:
                errors.append("StepList con %d items dura %dms sin itemMs; divide la escena o usa modo compacto/show-all" % (
                    item_count, dur))
        for value_path, token, num, unit in walk(overlay.get("params") or {}, "overlays[%d].params" % oidx):
            if not token_allowed(token, num, unit, caption_text):
                errors.append("%s/%s contiene numero visual %r que no aparece cerca del overlay (%sms-%sms)" % (
                    component,
                    value_path,
                    token,
                    overlay.get("startMs", 0),
                    int(overlay.get("startMs", 0)) + int(overlay.get("durMs", 0)),
                ))
    for i, left in enumerate(overlays):
        for right in overlays[i + 1:]:
            ov = overlap_ms(left, right)
            if ov <= 120:
                continue
            if left.get("component") in STRONG_OVERLAYS and right.get("component") in STRONG_OVERLAYS:
                if placement_group(left) == placement_group(right):
                    errors.append("overlays fuertes %s/%s se solapan %dms en %s" % (
                        left.get("component"), right.get("component"), ov, placement_group(left)))
    avatar_media = {}
    avatar_clip_policy_declared = "avatar_clip_reuse" in policies
    avatar_clip_reuse_allowed = bool(policies.get("avatar_clip_reuse"))
    for i, scene in enumerate(props.get("scenes") or []):
        if scene.get("role") != "avatar":
            continue
        key = scene.get("avatar_key") or "default"
        media = scene.get("media") or ""
        if avatar_clip_policy_declared and not avatar_clip_reuse_allowed and media in avatar_media:
            errors.append("avatar media %r se reutiliza en escenas %s y %s; identidad igual no debe reutilizar el mismo clip hablado" % (
                media, avatar_media[media], i))
        avatar_media.setdefault(media, i)
    sfx = [s for s in props.get("sfx", []) if s.get("id") and s.get("id") != "none" and float(s.get("gain", 0) or 0) > 0]
    sorted_sfx = sorted(sfx, key=lambda x: int(x.get("atMs", 0) or 0))
    for prev, curr in zip(sorted_sfx, sorted_sfx[1:]):
        gap = int(curr.get("atMs", 0) or 0) - int(prev.get("atMs", 0) or 0)
        if gap < 180 and not prev.get("allow_stack") and not curr.get("allow_stack"):
            errors.append("sfx/%s y sfx/%s estan separados por %dms; minimo 180ms para no apilar golpes" % (
                prev.get("id"), curr.get("id"), gap))
    for s in sfx:
        wav = os.path.join(ROOT, "remotion", "public", "sfx", "%s.wav" % s.get("id"))
        if not os.path.exists(wav):
            errors.append("sfx/%s no existe en remotion/public/sfx" % s.get("id"))
            continue
        peak = wav_peak(wav)
        gain = float(s.get("gain", 0) or 0)
        cap = SFX_MAX_GAIN.get(s.get("id"), 1.25)
        if gain > cap + 1e-6:
            errors.append("sfx/%s gain %.2f excede el maximo %.2f del banco en la mezcla final%s" % (
                s.get("id"), gain, cap, " (auto)" if s.get("auto") else ""))
        if peak is None:
            errors.append("sfx/%s no se pudo medir para audibilidad" % s.get("id"))
            continue
        predicted_peak = dbfs(peak * gain)
        if predicted_peak < -20.0:
            errors.append("sfx/%s queda demasiado bajo: peak estimado %.1fdBFS con gain %.2f; minimo -20dBFS" % (
                s.get("id"), predicted_peak, gain))
    for overlay in overlays:
        component = overlay.get("component")
        if component not in ANIMATED_OVERLAYS:
            continue
        start = int(overlay.get("startMs", 0))
        end = start + int(overlay.get("durMs", 0))
        nearby = sfx_in_window(sfx, start - 160, end + 160)
        if not nearby:
            errors.append("overlay/%s no tiene SFX audible durante su animacion" % component)
            continue
        if component in ("StepList", "CausalMeter"):
            params = overlay.get("params") or {}
            item_count = len(params.get("items") or params.get("criteria") or [])
            event_ids = {"ui-check-tick", "ui-line-draw", "ui-meter-fill", "ui-filter-pass", "ui-filter-reject"}
            item_events = sfx_in_window(sfx, start - 160, end + 160, event_ids)
            if item_count >= 2 and len(item_events) < min(item_count, 2):
                errors.append("overlay/%s tiene %d items pero solo %d SFX internos" % (
                    component, item_count, len(item_events)))
    visual_beats = pacing_utils.derive_visual_beats(
        props.get("scenes") or [],
        props.get("overlays") or [],
        int(props.get("totalMs", 0) or 0),
    )
    for beat in visual_beats:
        at = int(beat.get("atMs", 0) or 0)
        if not sfx_in_window(sfx, at - 220, at + 260):
            errors.append("visualBeat/%s en %dms no tiene SFX audible cercano" % (
                beat.get("action") or beat.get("kind") or "beat", at))
    # C8 inverso: cada SFX del DIRECTOR (no auto) debe caer sobre algo VISIBLE
    # (overlay animado, visual_beat o corte de escena). Las auto:true ya estan
    # atadas a sub-animaciones por construccion en plan_to_props.derive_*_sfx.
    director_sfx = [s for s in sfx if not s.get("auto")]
    if director_sfx:
        overlay_windows = [
            (int(o.get("startMs", 0)), int(o.get("startMs", 0)) + int(o.get("durMs", 0)))
            for o in overlays if o.get("component") in ANIMATED_OVERLAYS
        ]
        beat_times = [int(b.get("atMs", 0) or 0) for b in visual_beats]
        cut_times = [int(sc.get("fromMs", 0) or 0) for sc in (props.get("scenes") or [])]
        cta_ms = int(props.get("ctaStartMs", 0) or 0)
        for s in director_sfx:
            at = int(s.get("atMs", 0) or 0)
            near = (
                any(a - 200 <= at <= b + 200 for a, b in overlay_windows)
                or any(abs(at - t) <= 300 for t in beat_times)
                or any(abs(at - t) <= 300 for t in cut_times)
                or (cta_ms and abs(at - cta_ms) <= 400)
            )
            if not near:
                errors.append("sfx/%s (director) en %dms no coincide con ninguna animacion/overlay/beat/corte visible; anclalo a un evento visible o quitalo" % (
                    s.get("id"), at))
    if errors:
        print("PROPS INVALIDO (%d):" % len(errors))
        for e in errors:
            print("  -", e)
        return 1
    print("PROPS OK: %d scenes, %d overlays, %d sfx" % (
        len(props.get("scenes", [])), len(props.get("overlays", [])), len(sfx)
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
