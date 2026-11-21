#!/usr/bin/env python3
"""Valida un ReelPlan que emite el DIRECTOR antes de mandarlo al motor.
Uso: python3 scripts/validate_plan.py contracts/reel_plan.example.json
Chequea: (1) JSON Schema, (2) hook.spoken es prefijo literal de script,
(3) cada anchor.phrase (escenas, overlays, item_anchors, sfx) existe literal en el script
    -> garantiza que el motor podra resolverlo a milisegundos tras el alignment.
Sale 0 si todo OK; 1 si hay errores (lista cada problema)."""
import json, os, re, sys

from engine.config import ROOT  # V2PORT
SCHEMA = os.path.join(ROOT, "contracts", "reel_plan.schema.json")

from engine import pacing as pacing_utils
from engine import _generated as GEN  # V2PORT: registro unico

DEFAULT_SUPPORTED_OVERLAYS = {
    "StoryArcChart", "CountUp", "StatRing", "StepList",
    "CausalMeter", "ObjectCallout", "KeywordPop",
    "LowerThird", "Annotation", "ChapterDots",
    "FocusPunch", "SplitCompare", "BigWordSequence",
}
SUPPORTED_OVERLAYS = set(GEN.COMPONENTS)

PLATE_PURPOSE_COMPONENTS = {
    "diagnosis_card": {"CausalMeter", "StepList", "StatRing", "CountUp", "Annotation"},
    "stat_card": {"StatRing", "CountUp"},
    "rule_checklist": {"StepList", "ChapterDots"},
    "quantity_diagram": {"CausalMeter", "Annotation", "StepList"},
    "decision_card": {"CausalMeter", "StepList", "StatRing", "CountUp", "KeywordPop"},
    "cta_resource": {"LowerThird", "StepList", "KeywordPop"},
    "chapter": {"ChapterDots", "LowerThird"},
}
PLATE_PURPOSE_COMPONENTS = {
    key: {component for component in components if component in SUPPORTED_OVERLAYS}
    for key, components in PLATE_PURPOSE_COMPONENTS.items()
}
INFORMATIVE_OVERLAYS = set(SUPPORTED_OVERLAYS)
STRONG_OVERLAYS = {
    component for component in (
        "KeywordPop", "StepList", "CausalMeter",
        "StatRing", "CountUp", "StoryArcChart",
        "SplitCompare", "BigWordSequence",
    )
    if component in SUPPORTED_OVERLAYS
}
SFX_MAX_GAIN = {
    "sub-drop": 1.10,
    "impact": 1.10,
    "riser": 1.00,
    "whoosh": 1.10,
    "swoosh-up": 1.10,
    "click": 0.95,
    "pop": 1.00,
    "ui-soft-click": 0.85,
    "ui-card-pop": 1.20,
    "ui-check-tick": 1.00,
    "ui-line-draw": 1.20,
    "ui-meter-fill": 1.25,
    "ui-filter-pass": 1.15,
    "ui-filter-reject": 1.05,
    "ui-callout-ping": 0.95,
    "ui-page-swipe": 1.10,
    "ui-impact-soft": 1.25,
}
SFX_MIN_GAIN = {
    "ui-soft-click": 0.40,
    "click": 0.40,
    "ui-check-tick": 0.80,
    "ui-callout-ping": 0.55,
    "pop": 0.55,
    "ui-card-pop": 0.65,
    "ui-line-draw": 0.65,
    "ui-meter-fill": 0.75,
    "ui-filter-pass": 0.65,
    "ui-filter-reject": 0.60,
    "ui-page-swipe": 0.65,
    "ui-impact-soft": 0.75,
    "whoosh": 0.55,
    "swoosh-up": 0.55,
    "impact": 0.60,
    "sub-drop": 0.60,
    "riser": 0.45,
}
VISUAL_FAMILIES = {
    "hook_spectacle", "diagnostic_flow", "criteria_gate", "rule_cards",
    "concrete_proof", "action_proof", "quantity_control",
    "cta_document", "avatar_human", "chapter",
}
VISIBLE_MEDIA_TERMS = {
    "objeto fisico", "objeto real", "producto fisico", "persona real",
    "gesto fisico", "accion fisica", "lugar real",
    "herramienta", "dispositivo", "maquina", "vehiculo", "edificio",
}
# Muletillas plantilla del molde de guion: se repiten identicas entre videos y
# delatan copy AI. El pico debe escribirse con palabras propias del tema.
SCRIPT_TEMPLATE_PHRASES = (
    "lo raro es",
    "pero el detalle es",
    "ahi cambia todo",
    "lo que casi nadie nota",
    "ese segundo dato cambia la lectura",
)
# visual_proof que describe un concepto en vez de algo visible en pantalla.
ABSTRACT_PROOF_RE = re.compile(
    r"\b(concepto|idea abstracta|metafora|representacion|simboliza|simbolico|abstracto|abstracta|sensacion de|la idea de)\b"
)
HOOK_SEQUENCE_TERMS = {
    "luego", "then", "after that",
}
HOOK_CAMERA_TERMS = {
    "macro", "close-up", "close up", "primer plano", "plano", "camara",
    "cámara", "camera", "dolly", "zoom", "crash zoom", "rack focus",
    "whip", "orbit", "top-down", "45 grados", "45 degrees", "lente",
    "lens", "wide", "tele", "handheld",
}
HOOK_CONTEXT_STYLE_TERMS = {
    "mesa", "table", "estudio", "studio", "piso", "floor", "calle", "street",
    "fondo", "background", "luz", "light", "lighting", "iluminacion",
    "iluminación", "fotoreal", "photoreal", "cinematografico",
    "cinematic", "editorial", "natural",
}
HOOK_ACTION_TERMS = {
    "empuja", "coloca", "sirve", "abre", "rompe", "corta", "levanta",
    "revela", "desliza", "cae", "entra", "sale", "separa", "junta",
    "muestra", "pesa", "llena", "vacía", "vacia", "gira", "transforma",
    "detiene", "frena", "pushes", "places", "slides", "reveals", "opens",
    "breaks", "cuts", "fills", "becomes", "spins", "stops", "splits",
    "separates", "collapses",
}
HOOK_RESULT_TERMS = {
    "vacio", "vacío", "incompleto", "completo", "faltante", "falta",
    "corrige", "corregido", "contraste", "versus", "vs", "antes",
    "despues", "después", "riesgo", "cambio", "missing", "incomplete",
    "complete", "corrected", "contrast",
}
SPANISH_NUMBERS = {
    0: ("cero",),
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
VISUAL_NUMBER_RE = re.compile(
    r"\b(?P<num>\d+)\s*(?:(?P<slash>/\s*\d+)|(?P<unit>%|s\b|seg\b|sec\b|min\b|mins\b|minutos?\b|m\b|metros?\b|reps?\b|repeticiones?\b|rondas?\b))",
    re.I,
)
SKIP_NUMBER_KEYS = {"prompt", "asset", "src", "url", "notes", "model", "size", "id", "role", "image_provider"}

def rough_alignment(script):
    words = []
    for i, m in enumerate(re.finditer(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ/]+", script)):
        start = i * 320
        words.append({"word": m.group(0), "start_ms": start, "end_ms": start + 230})
    return {"duration_ms": max(1000, len(words) * 320 + 500), "words": words}

def norm(s):
    return " ".join(strip_accents(str(s).lower()).split())

def query_tokens(s):
    return [t for t in re.findall(r"[a-z0-9áéíóúñü]+", s.lower()) if len(t) > 1]

def hex_to_rgb(c):
    if not isinstance(c, str):
        return None
    c = c.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", c):
        return None
    return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))

def luma(c):
    rgb = hex_to_rgb(c)
    if not rgb:
        return 1.0
    r, g, b = [x / 255.0 for x in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def is_dark(c):
    return luma(c) < 0.36

def _lin_channel(v):
    v = v / 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

def rel_luminance(c):
    rgb = hex_to_rgb(c)
    if not rgb:
        return None
    r, g, b = rgb
    return 0.2126 * _lin_channel(r) + 0.7152 * _lin_channel(g) + 0.0722 * _lin_channel(b)

def wcag_contrast(a, b):
    la, lb = rel_luminance(a), rel_luminance(b)
    if la is None or lb is None:
        return None
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def phrase_text(anchor):
    return anchor.get("phrase") or anchor.get("at") or ""

def strip_accents(s):
    return (
        s.replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ü", "u")
        .replace("Á", "a").replace("É", "e").replace("Í", "i")
        .replace("Ó", "o").replace("Ú", "u").replace("Ü", "u")
    )

def compact_text(s):
    return re.sub(r"\s+", " ", strip_accents(str(s).lower())).strip()

CLIP_EXTRACTOR_QUERY_NOISE_PATTERNS = [
    r"\b(?:no|without)\s+(?:subtitles?|captions?|text(?:\s+overlays?)?|overlays?|logos?|watermarks?|social\s+ui|ui)\b",
    r"\bsin\s+(?:subtitulos|captions?|texto|overlays?|logos?|marcas?\s+de\s+agua|interfaz|ui)\b",
    r"\b(?:football\s+reels?|raw\s+broadcast|full\s+match\s+broadcast|full\s+match)\b",
    r"\b(?:vertical|portrait|9:16|reels?|shorts?|tiktok|instagram|documentary|cinematic|editorial|audience|language|tone|format)\b",
]
CLIP_EXTRACTOR_QUERY_MAX_TOKENS = 6
CLIP_EXTRACTOR_QUERY_MAX_CHARS = 72
CLIP_EXTRACTOR_QUERY_DROP_TOKENS = {
    "official", "real", "clip", "video", "scene", "shot", "moment",
    "momento", "escena", "footage", "highlight", "highlights",
}
ENGINE_GENERATED_ASSET_PATTERNS = [
    r"(^|/)broll_clip_extractor_\d+\.mp4$",
    r"(^|/)clip_extractor",
    r"(^|/)work/clips/",
    r"\.clip_extractor\.json$",
]

def clip_extractor_query_noise(q):
    text = compact_text(q)
    return [pat for pat in CLIP_EXTRACTOR_QUERY_NOISE_PATTERNS if re.search(pat, text, flags=re.I)]

def clip_extractor_meaningful_query_tokens(q):
    return [t for t in query_tokens(q) if t not in CLIP_EXTRACTOR_QUERY_DROP_TOKENS]

def engine_generated_asset_path(asset):
    text = str(asset or "").strip().lower().replace("\\", "/")
    return any(re.search(pat, text, flags=re.I) for pat in ENGINE_GENERATED_ASSET_PATTERNS)

def contains_unnegated_term(text, term):
    haystack = compact_text(text)
    needle = compact_text(term)
    if not needle:
        return False
    word_chars = r"a-z0-9ñ/"
    pattern = r"(?<![%s])%s(?![%s])" % (word_chars, re.escape(needle), word_chars)
    for match in re.finditer(pattern, haystack):
        prefix = haystack[max(0, match.start() - 24):match.start()]
        if re.search(r"(sin|no|without)\s+$", prefix):
            continue
        return True
    return False

def count_unnegated_terms(text, terms):
    return sum(1 for term in terms if contains_unnegated_term(text, term))

ACCENTED_PUBLIC_WORDS = {
    "tecnica": "técnica",
    "despues": "después",
    "evaluacion": "evaluación",
    "operacion": "operación",
    "articulacion": "articulación",
    "repeticion": "repetición",
    "porcion": "porción",
}
CTA_METADATA_TERMS = (
    "cream", "verde oscuro", "azul", "premium", "mockup",
    "paleta", "tipografia", "fondo", "canvas", "visual style",
    "documento", "color", "acento",
)

def public_copy_issues(label, value):
    issues = []
    if not isinstance(value, str) or not value.strip():
        return issues
    raw = value
    compacted = compact_text(raw)
    for plain, accented in ACCENTED_PUBLIC_WORDS.items():
        if re.search(r"(^|\s)%s($|\s)" % re.escape(plain), compacted):
            if accented not in raw.lower():
                issues.append("%s debe usar acento en %r" % (label, accented))
    for term in CTA_METADATA_TERMS:
        if term in compacted:
            issues.append("%s contiene metadata/estilo interno: %r" % (label, term))
    return issues

def scene_semantic_text(sc):
    clip = sc.get("clip", {}) or {}
    parts = [
        phrase_text(sc.get("anchor", {})),
        sc.get("intent", ""),
        sc.get("why_this_visual_not_other", ""),
        clip.get("query", ""),
        clip.get("prompt", ""),
    ]
    parts.extend(sc.get("visual_targets", []) or [])
    return compact_text(" ".join(str(x) for x in parts if x))

def has_visible_media_need(sc):
    if sc.get("layout") == "cta":
        return False
    if sc.get("plate_purpose") == "chapter":
        return False
    text = scene_semantic_text(sc)
    if not text:
        return False
    for term in VISIBLE_MEDIA_TERMS:
        if " " in term or "-" in term:
            if term in text:
                return True
        elif re.search(r"(^|\s)%s($|\s)" % re.escape(term), text):
            return True
    return False

def canonical_unit(unit):
    u = compact_text(unit)
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

def visual_number_allowed(num, unit, script_norm):
    n = int(num)
    cu = canonical_unit(unit)
    digit_forms = [str(n)]
    if cu:
        digit_forms += ["%s %s" % (n, u) for u in UNIT_WORDS.get(cu, (cu,))]
        digit_forms += ["%s%s" % (n, u) for u in UNIT_WORDS.get(cu, (cu,))]
    if any(compact_text(x) in script_norm for x in digit_forms):
        return True
    word_forms = SPANISH_NUMBERS.get(n, ())
    if not word_forms:
        return False
    if cu:
        for nw in word_forms:
            for uw in UNIT_WORDS.get(cu, (cu,)):
                if compact_text("%s %s" % (nw, uw)) in script_norm:
                    return True
    return any(compact_text(w) in script_norm for w in word_forms)

def slash_number_allowed(token, script_norm):
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)\s*", token)
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    if compact_text(token) in script_norm:
        return True
    aw, bw = SPANISH_NUMBERS.get(a, ()), SPANISH_NUMBERS.get(b, ())
    return any(compact_text("%s de %s" % (x, y)) in script_norm for x in aw for y in bw)

def walk_visual_number_strings(value, path="params"):
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k) in SKIP_NUMBER_KEYS:
                continue
            yield from walk_visual_number_strings(v, "%s.%s" % (path, k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk_visual_number_strings(v, "%s[%d]" % (path, i))
    elif isinstance(value, str):
        for m in VISUAL_NUMBER_RE.finditer(value):
            token = m.group(0)
            yield path, token, m.group("num"), m.group("unit") or m.group("slash") or ""

def merged_gaps(scene, overlays, max_gap_ms=700):
    start, end = int(scene.get("fromMs", 0)), int(scene.get("toMs", 0))
    if end - start <= 300:
        return []
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
    gaps = []
    cursor = start
    for a, b in spans:
        if b - a < 250:
            continue
        if a - cursor > max_gap_ms:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if end - cursor > max_gap_ms:
        gaps.append((cursor, end))
    return gaps

def overlap_ms(a, b):
    a0, a1 = int(a.get("startMs", 0)), int(a.get("startMs", 0)) + int(a.get("durMs", 0))
    b0, b1 = int(b.get("startMs", 0)), int(b.get("startMs", 0)) + int(b.get("durMs", 0))
    return max(0, min(a1, b1) - max(a0, b0))

def placement_group(o):
    p = o.get("placement") or o.get("safe_zone") or ""
    c = o.get("component")
    if p in ("safe_center", "full_context") or c in ("StatRing", "CountUp", "KeywordPop", "StepList", "CausalMeter", "SplitCompare", "BigWordSequence"):
        return "center"
    if p in ("safe_top", "top"):
        return "top"
    if p in ("safe_lower", "bottom"):
        return "bottom"
    return p or "center"

def overlap_allowed(a, b):
    pa = a.get("params", {}) or {}
    pb = b.get("params", {}) or {}
    if pa.get("allow_overlap") is True or pb.get("allow_overlap") is True:
        return True
    allowed = {"badge", "fade_under", "intentional"}
    return pa.get("handoff") in allowed or pb.get("handoff") in allowed


def has_list(value, min_len=1):
    return isinstance(value, list) and len(value) >= min_len


def has_text(value):
    return value is not None and str(value).strip() != ""


def has_declared_overlay_content(component, params):
    params = params or {}
    # Nota: params.allow_renderer_defaults ya NO cortocircuita este check.
    # Bajo declared_only ese flag esta prohibido (se rechaza en main()).
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


def main(path):
    schema = json.load(open(SCHEMA, encoding="utf-8"))
    plan = json.load(open(path, encoding="utf-8"))
    errors = []

    try:
        import jsonschema
        jsonschema.validate(plan, schema)
    except ImportError:
        errors.append("schema: falta la dependencia 'jsonschema' (instala jsonschema; no se permite saltar el contrato)")
    except Exception as e:
        errors.append("schema: %s" % str(e).split("\n")[0])

    spoken = plan.get("hook", {}).get("spoken", "")
    script = plan.get("script", "")
    if not norm(script).startswith(norm(spoken)):
        errors.append("hook.spoken no es el prefijo literal de script")
    # Transiciones expresivas: presupuesto duro + razon declarada.
    _expressive = [(i, s) for i, s in enumerate(plan.get("scenes") or [])
                   if s.get("transition_in") in ("punch_in", "whip")]
    if len(_expressive) > 3:
        errors.append("maximo 3 transiciones expresivas (punch_in/whip) por reel; hay %d" % len(_expressive))
    for _i, _s in _expressive:
        if len(str(_s.get("transition_reason") or "").strip()) < 12:
            errors.append(
                "scene[%d] usa transition_in=%s sin transition_reason concreto: declara por que este "
                "cambio merece una transicion expresiva o vuelve a cut" % (_i, _s.get("transition_in")))
    _script_c = compact_text(script)
    for _m in SCRIPT_TEMPLATE_PHRASES:
        if _m in _script_c:
            errors.append(
                "script usa la muletilla plantilla %r: escribe el giro con palabras propias del tema "
                "(las frases conectoras del molde se repiten entre videos y suenan a AI)" % _m)
    cta_button = plan.get("cta", {}).get("button", "")
    if cta_button and norm(cta_button) not in norm(script):
        errors.append("cta.button debe aparecer literal en script para que el CTA visual no quede mudo")
    cta = plan.get("cta", {}) or {}
    cta_intent = norm("%s %s" % (cta.get("text", ""), cta.get("button", "")))
    if any(w in cta_intent for w in ("lista", "guia", "mapa", "documento", "recurso")):
        if not cta.get("resource_title") or not cta.get("resource_points"):
            errors.append("cta de recurso/lista requiere resource_title y resource_points para renderizar un mockup concreto")
    for label, value in (
        ("cta.text", cta.get("text")),
        ("cta.button", cta.get("button")),
        ("cta.resource_title", cta.get("resource_title")),
        ("cta.visual_style", cta.get("visual_style")),
    ):
        errors.extend(public_copy_issues(label, value))
    for idx, point in enumerate(cta.get("resource_points") or []):
        errors.extend(public_copy_issues("cta.resource_points[%d]" % idx, point))

    hv = plan.get("hook", {}).get("visual", {}) or {}
    scenes = plan.get("scenes", [])
    first_src = ((scenes[0].get("clip") or {}).get("source") if scenes else None)
    hook_providers = ("asset", "clip_extractor", "pexels", "image", "motion", "none", "google")
    if hv.get("provider") not in hook_providers:
        errors.append("hook.visual.provider debe ser uno de: %s" % ", ".join(hook_providers))
    if scenes and scenes[0].get("role") == "hook":
        expected_provider = first_src
        provider = hv.get("provider")
        if first_src == "none":
            if provider and provider not in ("none", "motion"):
                errors.append("hook.visual.provider=%r debe coincidir con scene[0].clip.source='none' (usa none o motion)" % provider)
        elif provider and expected_provider and provider != expected_provider:
            errors.append("hook.visual.provider=%r debe coincidir con scene[0].clip.source=%r" % (
                provider, first_src))
    hook_uses_google = bool(scenes and scenes[0].get("role") == "hook" and first_src == "google")
    if hook_uses_google:
        if not str(hv.get("prompt") or (scenes[0].get("clip") or {}).get("prompt") or "").strip():
            errors.append("hook google requiere prompt en hook.visual.prompt o scene[0].clip.prompt")
        for field in ("generative_reason", "why_real_media_failed"):
            value = (scenes[0].get("clip") or {}).get(field) or hv.get(field)
            if len(str(value or "").strip()) < 20:
                errors.append("hook google requiere %s: Google/Omni es ultimo recurso, no default" % field)
    style = plan.get("meta", {}).get("style", {}) or {}
    meta = plan.get("meta", {}) or {}
    render_policy = style.get("render_policy") or "declared_only"
    declared_only = True
    if render_policy != "declared_only":
        errors.append("meta.style.render_policy debe ser declared_only; legacy_auto no se permite en produccion")
    if declared_only and style.get("plate_layout") == "auto":
        errors.append("meta.style.plate_layout=auto no se permite; usa declared_only + overlays/plate_purpose declarados")
    style_source = style.get("style_source") or {}
    palette = style.get("palette") or {}
    brand = plan.get("meta", {}).get("brand", {}) or {}
    # C6: contraste real texto/fondo (WCAG). Captions/labels son texto grande y bold,
    # asi que el piso duro es 3.0:1 (AA large text). Fondo efectivo = palette.bg o brand.bg.
    eff_bg = palette.get("bg") or brand.get("bg")
    for _clabel, _ccolor in (("fg", palette.get("fg") or brand.get("fg")),
                             ("accent", palette.get("accent") or brand.get("accent"))):
        if _ccolor and eff_bg:
            _ratio = wcag_contrast(_ccolor, eff_bg)
            if _ratio is not None and _ratio < 3.0:
                errors.append("contraste %s/bg %.2f:1 es ilegible en movil; minimo 3.0:1 (WCAG AA texto grande). Ajusta la paleta." % (
                    _clabel, _ratio))
    if style_source:
        if not style.get("base_theme"):
            errors.append("meta.style con style_source requiere base_theme extraido de la fuente visual")
        if not style.get("background_role"):
            errors.append("meta.style con style_source requiere background_role extraido de la fuente visual")
    if style.get("base_theme") == "light":
        if is_dark(brand.get("bg")):
            errors.append("base_theme=light no puede usar meta.brand.bg oscuro como fondo global")
        for role in ("bg", "panel"):
            if palette.get(role) and is_dark(palette.get(role)):
                errors.append("base_theme=light no puede usar palette.%s oscuro como fondo global" % role)
        if style.get("background_role") == "dark":
            errors.append("base_theme=light contradice background_role=dark")
    if style.get("caption_style") == "karaoke":
        errors.append("meta.style.caption_style='karaoke' no se permite: los captions deben ser palabra por palabra")
    if style.get("caption_decoration") == "underline":
        errors.append("meta.style.caption_decoration='underline' no se permite por defecto; usa 'none' salvo indicacion explicita del usuario")
    if style.get("caption_style") != "none" and not style.get("caption_emphasis_policy"):
        errors.append("meta.style requiere caption_emphasis_policy para evitar captions gigantes en conectores/stopwords")
    if plan.get("hook", {}).get("headline") and hook_uses_google:
        hook_prompt = " ".join([
            str((plan.get("hook", {}).get("visual") or {}).get("prompt") or ""),
            str(((scenes[0].get("clip") or {}) if scenes else {}).get("prompt") or ""),
        ])
        # v3 (2026-07-05): quitadas las reglas anti-texto/anti-marca del hook
        # generativo (superficies con texto tipo pantalla/cartel, 'sin texto
        # legible', 'sin logos'). Misma politica que la imagen: una etiqueta o
        # marca legible es valida; el texto REALMENTE garabateado lo caza el
        # juez de render mirando pixeles, no un veto por palabra clave en el
        # prompt (que bloqueaba prompts legitimos por las palabras que usaban).
        for term in sorted(HOOK_SEQUENCE_TERMS, key=len, reverse=True):
            if contains_unnegated_term(hook_prompt, term):
                errors.append("hook Google debe pedir una sola accion legible desde el primer frame; evita secuencias con %r" % term)
                break
        if count_unnegated_terms(hook_prompt, HOOK_CAMERA_TERMS) < 1:
            errors.append("hook Google/Omni debe declarar camara o framing concreto (macro, close-up, 45 grados, dolly-in, crash zoom, etc.)")
        if count_unnegated_terms(hook_prompt, HOOK_CONTEXT_STYLE_TERMS) < 2:
            errors.append("hook Google/Omni debe declarar contexto/escena y estilo/luz concretos; evita fondos genericos")
        # (quitadas en v3 las exigencias de 'sin texto legible' y 'sin logos')
        # v2: HOOK_ACTION_TERMS estaba definido y nunca cableado. El hook debe
        # MOSTRAR una accion (la creencia del gancho ocurriendo), no un bodegon.
        if count_unnegated_terms(hook_prompt, HOOK_ACTION_TERMS) < 1:
            errors.append("hook generativo debe declarar la ACCION visible que ocurre (empuja, gira, revela, aplica, muestra...): el hook dramatiza la creencia, no un bodegon estatico")

    if scenes:
        first = scenes[0]
        first_source = (first.get("clip") or {}).get("source")
        hook_sources = ("asset", "clip_extractor", "pexels", "image", "none", "google")
        if first.get("role") != "hook" or first_source not in hook_sources:
            errors.append("la primera escena debe ser role='hook' con clip.source en: %s" % ", ".join(hook_sources))
    for sc in scenes:
        src = (sc.get("clip") or {}).get("source")
        if src in ("omni", "seedance"):
            errors.append("scene/%s no puede usar alias clip.source=%r; usa google/pexels/clip_extractor/image/none" % (sc.get("role"), src))
    avatar_scenes = [sc for sc in scenes if sc.get("role") == "avatar"]
    try:
        from engine._generated import AVATAR_APPEARANCES as _AV_N
    except Exception:
        _AV_N = 2
    try:
        _av_want = int(meta.get("avatar_appearances", _AV_N))
    except Exception:
        _av_want = _AV_N
    if len(avatar_scenes) > _AV_N:
        errors.append("avatar: maximo %d escenas role='avatar' por reel" % _AV_N)
    avatar_policy = meta.get("avatar_policy", "required")
    if avatar_policy == "disabled":
        if len(str(meta.get("avatar_disabled_reason") or "").strip()) < 20:
            errors.append("meta.avatar_policy=disabled requiere avatar_disabled_reason concreto")
    elif len(avatar_scenes) != _av_want:
        # Mandato del dueño: cuando el avatar esta habilitado, sale EXACTAMENTE
        # avatar_appearances veces (default 2). Override explicito con
        # meta.avatar_appearances; disabled con razon lo apaga por completo.
        errors.append("avatar habilitado requiere EXACTAMENTE %d escenas role='avatar' (hay %d); usa meta.avatar_appearances para otro numero o meta.avatar_policy='disabled' con razon" % (_av_want, len(avatar_scenes)))
    media_policy = meta.get("media_policy", "production")
    body_media = [
        sc for sc in scenes
        if sc.get("role") != "hook" and sc.get("layout") != "cta"
    ]
    media_scenes = [
        sc for sc in body_media
        if (sc.get("clip") or {}).get("source") in ("asset", "pexels", "clip_extractor", "image")
    ]
    # GENRE-AWARE (antes: piso fijo de 2, genre-blind, que false-rechazaba un
    # explainer analitico y false-aceptaba stock irrelevante). Ahora el piso lo
    # decide el MISMO clasificador que usan los jueces (medium_policy, fuente
    # unica): exige media SOLO para las escenas cuyo claim es DEMOSTRABLE. Un reel
    # de claims textuales tiene piso 0; uno demostrable exige la media que si ayuda.
    # meta.media_min_scenes sigue disponible como override manual explicito.
    try:
        from engine import medium_policy as _mp
        # SOLO alta confianza (match duro de VISIBLE_MEDIA_TERMS, 0.9): el piso
        # DETERMINISTA solo se impone en casos inequivocos, igual que enforce. Los
        # hints debiles (0.6) son "quiza demostrable" y los resuelve el juez AI,
        # no un piso ciego (evita over-rechazar por mencionar 'frasco'/'etiqueta').
        def _hard_demo(sc):
            v = _mp.classify_scene(sc)
            return v.get("kind") == "demostrable" and v.get("confidence", 0) >= 0.9
        demonstrable_body = [sc for sc in body_media if _hard_demo(sc)]
        media_min = int(meta["media_min_scenes"]) if "media_min_scenes" in meta else len(demonstrable_body)
    except Exception:
        # sin el clasificador, cae al comportamiento anterior (piso 2) como backstop
        media_min = int(meta.get("media_min_scenes", 2) or 0)
    if media_policy == "production" and len(media_scenes) < media_min:
        errors.append("media_policy=production requiere media para las %d escena(s) con claim demostrable; con media: %d (declara meta.media_min_scenes para override)" % (
            media_min, len(media_scenes)))

    # MANDATO v2 (SEMANTICA SOBRE PRECISION): checks ABSOLUTOS de balance de
    # medio, independientes del clasificador -- el piso genre-aware de arriba
    # puede ser 0 y legalizo un reel 6/9-plates ('PowerPoint con voz en off',
    # veredicto humano). Numeros unicos en shared/core.json (media_base) via
    # codegen; los jueces (qa.py) predican los mismos umbrales.
    try:
        from engine._generated import (
            MEDIA_BACKED_MIN_RATIO as _MB_RATIO,
            MAX_CONSECUTIVE_TEXT_SCENES as _MB_MAXTXT,
        )
    except Exception:
        _MB_RATIO, _MB_MAXTXT = 0.6, 2
    _MB_SOURCES = ("asset", "pexels", "clip_extractor", "image", "google", "kreado")
    if media_policy == "production" and body_media:
        try:
            _mb_min_ratio = float(meta.get("media_min_ratio", _MB_RATIO))
        except Exception:
            _mb_min_ratio = _MB_RATIO
        _mb_backed = [
            sc for sc in body_media
            if ((sc.get("clip") or {}).get("source")) in _MB_SOURCES or sc.get("role") == "avatar"
        ]
        _mb_ratio = len(_mb_backed) / float(len(body_media))
        if _mb_ratio + 1e-9 < _mb_min_ratio:
            errors.append(
                "balance de medio: %d/%d escenas body con media (%.0f%% < %.0f%%). La base del reel son "
                "personas/accion; la precision va en overlays declarados SOBRE la media, no en plates "
                "(meta.media_min_ratio para override)" % (
                    len(_mb_backed), len(body_media), 100 * _mb_ratio, 100 * _mb_min_ratio))
        # Racha: nunca mas de N escenas 100%-texto seguidas. cta/chapter CUENTAN
        # como texto (una racha chapter+2 plates era exactamente la zona de
        # abandono 14-26s del reel fallido).
        _mb_run, _mb_start = 0, 0
        for _mb_i, sc in enumerate(scenes):
            _mb_src = (sc.get("clip") or {}).get("source")
            if _mb_src in _MB_SOURCES or sc.get("role") == "avatar":
                _mb_run = 0
                continue
            if _mb_run == 0:
                _mb_start = _mb_i
            _mb_run += 1
            if _mb_run == _MB_MAXTXT + 1:
                errors.append(
                    "balance de medio: %d+ escenas 100%%-texto consecutivas desde la escena %d (max %d); "
                    "convierte al menos una a media con el texto como overlay declarado" % (
                        _mb_run, _mb_start, _MB_MAXTXT))
        # Hook: debe MOSTRAR la creencia/accion del gancho. Un hook 100%-texto
        # solo con override deliberado (meta.hook_plate_reason >= 20 chars).
        if scenes:
            _mb_first_src = (scenes[0].get("clip") or {}).get("source")
            if _mb_first_src in (None, "none", "motion") and len(str(meta.get("hook_plate_reason") or "").strip()) < 20:
                errors.append(
                    "hook 100%-texto en media_policy=production: el hook debe MOSTRAR la creencia/accion "
                    "del gancho con media; declara meta.hook_plate_reason (>=20 chars) solo si el pico "
                    "tipografico es deliberado")

    s = norm(script)
    script_num_text = compact_text(script)
    def chk(phrase, where):
        if norm(phrase) not in s:
            errors.append("anchor sin resolver en %s: %r" % (where, phrase))

    seen_queries = {}
    generic = set("vertical close up person background generic abstract high quality footage stock".split())
    prev_plate_family = None
    for sc in scenes:
        a = sc.get("anchor", {})
        clip = sc.get("clip", {}) or {}
        layout = sc.get("layout")
        src = clip.get("source")
        role = sc.get("role")
        family = sc.get("visual_family")
        if sc.get("plate_purpose") == "comparison":
            errors.append("scene/%s usa plate_purpose='comparison' legacy; usa decision_card, rule_checklist, quantity_diagram o B-roll real" % role)
        if family == "decision_compare":
            errors.append("scene/%s usa visual_family='decision_compare' legacy; usa criteria_gate, rule_cards, concrete_proof o media real por escena" % role)
        why = str(sc.get("why_this_visual_not_other") or "").strip()
        editorial_point = str(sc.get("editorial_point") or "").strip()
        why_it_matters = str(sc.get("why_it_matters") or "").strip()
        visual_proof = str(sc.get("visual_proof") or "").strip()
        if family not in VISUAL_FAMILIES:
            errors.append("scene/%s requiere visual_family valido: %s" % (role, ", ".join(sorted(VISUAL_FAMILIES))))
        if len(why) < 20:
            errors.append("scene/%s requiere why_this_visual_not_other concreto (minimo 20 caracteres)" % role)
        if len(editorial_point) < 12:
            errors.append("scene/%s requiere editorial_point: tesis concreta del beat" % role)
        if len(why_it_matters) < 12:
            errors.append("scene/%s requiere why_it_matters: por que importa para el espectador" % role)
        if len(visual_proof) < 12:
            errors.append("scene/%s requiere visual_proof: prueba visual concreta" % role)
        elif src in (None, "none", "motion") and ABSTRACT_PROOF_RE.search(compact_text(visual_proof)):
            # v2: el veto a 'metafora/concepto' queda SOLO para plates. Una metafora
            # ENCARNADA en media (personas/objetos concretos) es dramatizacion valida
            # -- exactamente lo que el mandato pone por encima del plate probatorio.
            errors.append(
                "scene/%s visual_proof abstracto (%r): nombra el objeto, accion, persona, documento o dato "
                "concreto que se VE en pantalla, no un concepto/metafora" % (role, visual_proof[:60]))
        if media_policy == "production" and role == "plate" and src in (None, "none") \
                and layout != "cta" and sc.get("plate_purpose") not in ("chapter", "cta_resource") \
                and len(str(sc.get("plate_last_resort_reason") or "").strip()) < 20:
            # v2: peaje simetrico. Antes solo la media pagaba justificaciones
            # (google 2 campos, clip_extractor targets+proof) y el plate entraba
            # gratis -- el camino de menor friccion burocratica era el texto.
            errors.append(
                "scene/plate (%s) requiere plate_last_resort_reason (>=20 chars): plate es ultimo recurso; "
                "explica por que NINGUNA media puede dramatizar este beat" % (sc.get("plate_purpose") or "sin proposito"))
        if role == "avatar":
            avatar_text = norm(compact_text(" ".join([sc.get("intent",""), editorial_point, why_it_matters, visual_proof])))
            # Bilingue: los campos editoriales siguen el idioma del guion
            # (meta.language), no siempre espanol. Mismo patron que
            # script_audit/llm/qa -- un set monolingue aqui haria fallar
            # SIEMPRE una escena de avatar en un reel en ingles.
            _AVATAR_TERMS_BY_LANG = {
                "es": ("autoridad", "confianza", "humano", "humana", "presentador", "ancla", "criterio", "advertencia", "pivote"),
                "en": ("authority", "confidence", "credibility", "human", "presenter", "anchor", "criteria", "criterion", "warning", "pivot"),
            }
            avatar_terms = _AVATAR_TERMS_BY_LANG.get(str(meta.get("language", "es")).strip().lower(), _AVATAR_TERMS_BY_LANG["es"])
            if not any(t in avatar_text for t in avatar_terms):
                errors.append("scene/avatar requiere proposito editorial claro: %s" % ", ".join(avatar_terms[:5]))
        if not layout:
            errors.append("scene/%s requiere layout explicito (full_bleed/full_frame/diagram/split/card/cta)" % role)
        if role == "hook" and src not in ("asset", "clip_extractor", "pexels", "image", "none", "google"):
            errors.append("scene/hook debe usar clip.source asset/clip_extractor/pexels/image/none/google; no %r" % src)
        if role == "hook" and layout not in ("full_bleed", "full_frame", "diagram", "card"):
            errors.append("scene/hook debe usar layout full_bleed/full_frame o diagram/card si es motion/plate")
        if role == "avatar" and layout not in ("full_bleed", "full_frame"):
            errors.append("scene/avatar debe usar layout full_bleed o full_frame; Remotion compone broll/motion en la mitad superior, la franja de captions en el medio y el avatar 16:9 EXACTO abajo (sin recortar la cara)")
        if role == "avatar" and src not in ("google", "kreado"):
            errors.append("scene/avatar debe usar clip.source='kreado' (produccion) o 'google' (legacy); no %r" % src)
        companion = (clip.get("companion") or {}) if isinstance(clip.get("companion"), dict) else {}
        if companion and role != "avatar":
            errors.append("clip.companion solo se permite en escenas role='avatar'")
        if role == "avatar":
            csrc = companion.get("source")
            if csrc == "asset" and not companion.get("asset"):
                errors.append("avatar companion source=asset requiere companion.asset con clip de usuario")
            if csrc == "clip_extractor":
                q = companion.get("query", "")
                toks = query_tokens(q)
                meaningful = [t for t in clip_extractor_meaningful_query_tokens(q) if t not in generic]
                if len(toks) < 3 or len(set(meaningful)) < 3:
                    errors.append("avatar companion clip_extractor requiere query especifico, no generico: %r" % q)
                if len(clip_extractor_meaningful_query_tokens(q)) > CLIP_EXTRACTOR_QUERY_MAX_TOKENS or len(q) > CLIP_EXTRACTOR_QUERY_MAX_CHARS:
                    errors.append("avatar companion clip_extractor query demasiado largo: %r. Usa busqueda por beat, no formato/tono/negativos." % q)
                if clip_extractor_query_noise(q):
                    errors.append("avatar companion clip_extractor query mezcla busqueda con filtros editoriales/QA: %r" % q)
            if csrc == "pexels" or (companion.get("query") and csrc in (None, "pexels")):
                q = companion.get("query", "")
                toks = query_tokens(q)
                meaningful = [t for t in toks if t not in generic]
                if len(toks) < 3 or len(set(meaningful)) < 2:
                    errors.append("avatar companion pexels requiere query especifico, no generico: %r" % q)
            if csrc == "image":
                if not companion.get("prompt"):
                    errors.append("avatar companion source=image requiere prompt; imagen es fallback despues de asset/clip_extractor/pexels")
                if companion.get("image_provider") and companion.get("image_provider") != "codex-oauth":
                    errors.append("avatar companion image_provider debe ser codex-oauth")
                if companion.get("model") and companion.get("model") != "gpt-image-2":
                    errors.append("avatar companion image model debe ser gpt-image-2")
                if companion.get("motion", "kenburns-in") not in ("kenburns-in", "kenburns-out", "pan-left", "pan-right"):
                    errors.append("avatar companion source=image debe usar Ken Burns/pan; no motion=%r" % companion.get("motion"))
            if csrc == "motion" and companion.get("asset"):
                errors.append("avatar companion source=motion no debe declarar asset")
        if role == "broll" and src in ("asset", "pexels", "clip_extractor", "image", "google") and layout not in ("full_bleed", "full_frame"):
            errors.append("scene/broll con visual real/generado debe usar layout full_bleed o full_frame")
        if role == "broll" and src not in ("asset", "pexels", "clip_extractor", "image", "google"):
            errors.append("scene/broll debe usar clip.source='asset', 'pexels', 'clip_extractor', 'image' o 'google'; no %r" % src)
        # v2: google (Omni Flash) es el ULTIMO peldaño de la escalera y se permite
        # en body b-roll SIEMPRE que el director lo justifique (generative_reason +
        # why_real_media_failed): 'ultimo recurso' de verdad, no un fallback
        # automatico silencioso (author_real_clip nunca lo autora: se queda en image).
        if src == "google":
            for field in ("generative_reason", "why_real_media_failed"):
                value = clip.get(field) or (hv.get(field) if role == "hook" else "")
                if len(str(value or "").strip()) < 20:
                    errors.append("scene/%s source=google requiere %s: video generativo es ultimo recurso, declaralo" % (role, field))
        if src == "kreado" and role != "avatar":
            errors.append("clip.source='kreado' solo se permite para role='avatar'")
        if src == "asset" and not clip.get("asset"):
            errors.append("scene/%s source=asset requiere clip.asset" % role)
        if src == "asset" and engine_generated_asset_path(clip.get("asset")):
            errors.append("scene/%s usa asset generado por Clip Extractor como source=asset; conserva provenance con clip.source='clip_extractor' y clip.query por escena" % role)
        if src == "image" and not clip.get("asset") and not clip.get("prompt"):
            errors.append("scene/%s source=image requiere clip.prompt o clip.asset" % role)
        if src == "pexels":
            q = clip.get("query", "")
            toks = query_tokens(q)
            meaningful = [t for t in toks if t not in generic]
            if len(toks) < 3 or len(set(meaningful)) < 2:
                errors.append("scene/%s pexels requiere query especifico, no generico: %r" % (role, q))
        if src == "none" and layout not in ("diagram", "card", "cta", "full_bleed", "full_frame"):
            errors.append("scene con clip.source=none debe ser diagram/card/cta, no layout=%r" % layout)
        if role == "plate" or src == "none":
            if prev_plate_family == family:
                errors.append("scene/plate repite visual_family consecutiva (%s); cambia componente/layout o usa B-roll/imagen si aporta" % family)
            prev_plate_family = family
            purpose = sc.get("plate_purpose")
            if not purpose or purpose == "none":
                errors.append("scene/plate con clip.source=none requiere plate_purpose concreto (diagnosis_card/stat_card/rule_checklist/etc.)")
            if declared_only and purpose in ("decision_card", "rule_checklist") and not has_list(sc.get("visual_targets")):
                errors.append("scene/plate plate_purpose=%s requiere visual_targets en render_policy declared_only; Remotion no puede usar labels fallback" % purpose)
            if not sc.get("visual_mode"):
                errors.append("scene/plate con clip.source=none requiere visual_mode para que Remotion no use una placa generica")
            if src == "none" and layout == "diagram" and purpose == "cta_resource":
                errors.append("scene/plate cta_resource debe usar layout='cta' o card, no diagram")
            if role == "plate" and src == "none" and has_visible_media_need(sc):
                errors.append("scene/plate %r describe algo visible; usa role='broll' con clip.source='pexels', 'clip_extractor' o 'image'" % (
                    phrase_text(sc.get("anchor", {}))))
        if "phrase" in a:
            chk(a["phrase"], "scene/%s" % sc.get("role"))
        if sc.get("pacing_beats"):
            errors.append("scene/%s usa pacing_beats legado; usa visual_beats con action/semantic_delta/target o divide la escena" % role)
        beat_sigs = []
        prev_beat_label = None
        for bi, beat in enumerate(sc.get("visual_beats") or []):
            ba = beat.get("anchor", {}) or {}
            if "phrase" in ba:
                chk(ba["phrase"], "visual_beat/%s[%d]" % (sc.get("role"), bi))
            if beat.get("action") in ("accent_wipe", "reframe"):
                errors.append("visual_beat/%s[%d] no puede ser cosmetico; usa crop_reframe, component_state, layout_swap, callout_target, insert_card o new_media" % (
                    sc.get("role"), bi))
            if len(str(beat.get("semantic_delta") or "").strip()) < 12:
                errors.append("visual_beat/%s[%d] requiere semantic_delta concreto" % (sc.get("role"), bi))
            if len(str(beat.get("target") or "").strip()) < 2:
                errors.append("visual_beat/%s[%d] requiere target visual concreto" % (sc.get("role"), bi))
            # C3: dos beats no pueden inflar la cadencia repitiendo el mismo pico.
            blabel = norm(str(beat.get("label") or "").strip())
            btarget = norm(str(beat.get("target") or "").strip())
            bdelta = norm(str(beat.get("semantic_delta") or "").strip())
            sig = (blabel, btarget, bdelta)
            if blabel and sig in beat_sigs:
                errors.append("visual_beat/%s[%d] es duplicado exacto (label/target/semantic_delta repetidos); cada pico debe aportar informacion nueva" % (
                    sc.get("role"), bi))
            beat_sigs.append(sig)
            if blabel and blabel == prev_beat_label:
                errors.append("visual_beat/%s[%d] repite el label del beat anterior (%r); dos picos seguidos con el mismo texto no dan giro narrativo nuevo" % (
                    sc.get("role"), bi, beat.get("label")))
            prev_beat_label = blabel
        if sc.get("clip", {}).get("source") == "pexels":
            q = sc.get("clip", {}).get("query", "")
            if not q:
                errors.append("pexels en scene/%s requiere query especifico" % sc.get("role"))
            else:
                toks = query_tokens(q)
                meaningful = [t for t in toks if t not in generic]
                if len(toks) < 4 or len(set(meaningful)) < 2:
                    errors.append("pexels query demasiado generico en scene/%s: %r" % (sc.get("role"), q))
                nq = norm(q)
                if nq in seen_queries:
                    errors.append("pexels query repetido: %r en escenas %s y %s" % (q, seen_queries[nq], sc.get("anchor", {})))
                seen_queries[nq] = sc.get("anchor", {})
            if not sc.get("intent"):
                errors.append("scene/broll requiere intent: explica que objeto, accion o prueba aporta")
        if sc.get("clip", {}).get("source") == "clip_extractor":
            q = sc.get("clip", {}).get("query", "")
            if role not in ("hook", "broll"):
                errors.append("clip_extractor solo se permite en scene role='hook' o 'broll'")
            if not q:
                errors.append("clip_extractor en scene/%s requiere query especifico" % sc.get("role"))
            else:
                toks = query_tokens(q)
                meaningful = [t for t in clip_extractor_meaningful_query_tokens(q) if t not in generic]
                if len(toks) < 3 or len(set(meaningful)) < 3:
                    errors.append("clip_extractor query demasiado generico en scene/%s: %r" % (sc.get("role"), q))
                if len(clip_extractor_meaningful_query_tokens(q)) > CLIP_EXTRACTOR_QUERY_MAX_TOKENS or len(q) > CLIP_EXTRACTOR_QUERY_MAX_CHARS:
                    errors.append("clip_extractor query demasiado largo en scene/%s: %r. Usa una busqueda por clip/beat, maximo %d terminos utiles y %d caracteres." % (
                        sc.get("role"), q, CLIP_EXTRACTOR_QUERY_MAX_TOKENS, CLIP_EXTRACTOR_QUERY_MAX_CHARS))
                if clip_extractor_query_noise(q):
                    errors.append("clip_extractor query mezcla busqueda con filtros editoriales/QA en scene/%s: %r. Deja solo persona/evento/objeto/lugar/fecha/accion; no uses formato, tono, audiencia, idioma ni negativos como sin subtitulos/no text." % (sc.get("role"), q))
                nq = norm(q)
                if nq in seen_queries:
                    errors.append("clip_extractor query repetido: %r en escenas %s y %s" % (q, seen_queries[nq], sc.get("anchor", {})))
                seen_queries[nq] = sc.get("anchor", {})
            if len(sc.get("visual_targets") or []) < 2:
                errors.append("clip_extractor requiere al menos 2 visual_targets concretos")
            if len(visual_proof) < 20:
                errors.append("clip_extractor requiere visual_proof concreto para auditar que el clip prueba el beat")
            if not sc.get("intent"):
                errors.append("scene/clip_extractor requiere intent: explica que objeto, accion o prueba aporta")
        if sc.get("clip", {}).get("source") == "image":
            clip = sc.get("clip", {})
            if not clip.get("asset") and not clip.get("prompt"):
                errors.append("image en scene/%s requiere prompt o asset" % sc.get("role"))
            if clip.get("image_provider") and clip.get("image_provider") != "codex-oauth":
                errors.append("image_provider debe ser codex-oauth; no uses API key para imagenes generadas")
            if clip.get("model") and clip.get("model") != "gpt-image-2":
                errors.append("source=image debe usar model gpt-image-2 si se especifica model")
            if not clip.get("asset") and sc.get("motion", "kenburns-in") not in ("kenburns-in", "kenburns-out", "pan-left", "pan-right"):
                errors.append("source=image generado debe usar Ken Burns/pan, no motion=%r" % sc.get("motion"))
            if not sc.get("intent"):
                errors.append("scene/image requiere intent: explica por que una imagen generada aporta mas que Pexels o plate")
        if not (role == "plate" or src == "none"):
            prev_plate_family = None
    story_charts = []
    for o in plan.get("overlays", []):
        a = o.get("anchor", {})
        if "phrase" in a:
            chk(a["phrase"], "overlay/%s" % o.get("component"))
        component = o.get("component")
        params = o.get("params", {}) or {}
        semantic = o.get("semantic_kind")
        if (semantic == "comparison" or o.get("type") == "compare") and component != "SplitCompare":
            errors.append("overlay/%s usa comparativo legacy; para contrastes A/B explicitos del guion usa SplitCompare" % component)
        if component not in SUPPORTED_OVERLAYS:
            errors.append(
                "overlay/%s no esta incluido en el process map activo; usa uno de: %s"
                % (component, ", ".join(sorted(SUPPORTED_OVERLAYS)))
            )
        if not params.get("visual_scale") and not params.get("allow_visual_number_scale"):
            for value_path, token, num, unit in walk_visual_number_strings(params):
                allowed = slash_number_allowed(token, script_num_text) if "/" in token else visual_number_allowed(num, unit, script_num_text)
                if not allowed:
                    errors.append("overlay/%s %s contiene numero visual %r que no aparece en el guion ni esta marcado como escala visual" % (
                        component, value_path, token))
        if not semantic:
            errors.append("overlay/%s requiere semantic_kind para evitar graficas decorativas" % component)
        if not o.get("placement"):
            errors.append("overlay/%s requiere placement para que Remotion no adivine posicion" % component)
        if declared_only and not has_declared_overlay_content(component, params):
            errors.append("overlay/%s no declara contenido suficiente para render_policy declared_only; no dependas de defaults de Remotion" % component)
        if declared_only and params.get("allow_renderer_defaults"):
            errors.append("overlay/%s usa params.allow_renderer_defaults; prohibido bajo declared_only (Remotion inventaria valores/labels). Declara points/value/items/labels/words/text reales." % component)
        # C6: must_not_cover geometrico. Si el overlay promete no tapar captions pero
        # se posiciona en la lane inferior, es contradictorio (varios componentes ignoran
        # must_not_cover en runtime). Bloquea el plan en vez de confiar en el z-order.
        _mnc = o.get("must_not_cover") or []
        _side = str(params.get("side") or "").lower()
        if "caption" in _mnc and (o.get("placement") == "safe_lower" or _side == "bottom"):
            errors.append("overlay/%s declara must_not_cover=caption pero se posiciona en la lane inferior (placement=safe_lower o side=bottom); usa safe_top/safe_center o quita el conflicto" % component)
        if component == "StoryArcChart":
            story_charts.append(o)
            if int(o.get("duration_ms") or 0) > 3200:
                errors.append("StoryArcChart dura demasiado (%sms); maximo 3200ms para no tapar el visual" % o.get("duration_ms"))
            if semantic != "process":
                errors.append("StoryArcChart solo se permite con semantic_kind=process")
            semantic_text = norm(" ".join([
                phrase_text(o.get("anchor", {})),
                str(params.get("title", "")),
                str(o.get("rationale", "")),
                str(params.get("xLabel", "")),
                str(params.get("yLabel", "")),
            ]))
            process_terms = ("tiempo", "minuto", "curva", "proceso", "ciclo", "progreso", "secuencia", "evolucion", "trayectoria", "sube", "baja")
            if not any(t in semantic_text for t in process_terms):
                errors.append("StoryArcChart requiere una relacion temporal/proceso explicita; si no, usa B-roll, Annotation, StatRing o StepList")
            if style.get("base_theme") == "light" and (params.get("variant") == "traditional"):
                errors.append("StoryArcChart variant=traditional no se permite en tema claro salvo rediseño neutral; usa StatRing, Annotation o B-roll")
        if o.get("max_duration_ms") and o.get("duration_ms") and int(o["duration_ms"]) > int(o["max_duration_ms"]):
            errors.append("overlay/%s excede max_duration_ms (%sms > %sms)" % (component, o["duration_ms"], o["max_duration_ms"]))
        if component in ("StoryArcChart", "StatRing", "StepList") and not o.get("rationale"):
            errors.append("overlay/%s requiere rationale semantico" % component)
        if component == "KeywordPop" and int(o.get("duration_ms") or 0) > 1200:
            errors.append("KeywordPop no debe convertirse en pantalla de texto; maximo 1200ms")
        if component == "BigWordSequence" and int(o.get("duration_ms") or 0) > 2500:
            # v2: mismo agujero que ya se tapo para KeywordPop, sin tapar aqui --
            # BigWordSequence sostenido fue la zona de abandono 14-26s del reel fallido.
            errors.append("BigWordSequence no debe convertirse en escena de texto sostenida; maximo 2500ms (es un pico, no una escena)")
        if component == "KeywordPop" and o.get("placement") == "safe_lower" and "caption" in (o.get("must_not_cover") or []):
            errors.append("KeywordPop con must_not_cover=caption no puede usar placement=safe_lower")
        if component == "StepList" and len(o.get("params", {}).get("items", [])) > 4:
            errors.append("StepList no debe cubrir enumeraciones largas (>4 items); divide en B-roll por objeto o compacta la lista")
        if component == "StepList":
            variant = str(params.get("variant", "")).strip()
            allowed_variants = {"diagnosis", "rule", "criteria", "checklist", "compact"}
            if variant not in allowed_variants:
                errors.append("StepList requiere params.variant en %s para que Remotion no repita siempre la misma lista" % sorted(allowed_variants))
            if variant in ("rule", "criteria", "diagnosis") and params.get("future_reveal") == "ghost_text":
                errors.append("StepList variant=%s no debe usar future_reveal=ghost_text; adelanta texto futuro y mata la tension. Usa skeleton_only u omite future_reveal" % variant)
        if component == "CausalMeter":
            items = params.get("items", [])
            anchors = params.get("item_anchors", [])
            tokens = params.get("tokens", [])
            meter_values = params.get("meter_values", [])
            if semantic not in ("list", "process"):
                errors.append("CausalMeter requiere semantic_kind=list o process")
            if o.get("placement") != "full_context":
                errors.append("CausalMeter debe usar placement=full_context para reservar diagrama, filas y caption lane")
            if not isinstance(items, list) or not (2 <= len(items) <= 4):
                errors.append("CausalMeter requiere params.items con 2 a 4 causas")
            if len(anchors) != len(items):
                errors.append("CausalMeter requiere item_anchors del mismo largo que items")
            if len(tokens) != len(items):
                errors.append("CausalMeter requiere tokens del mismo largo que items")
            if meter_values and len(meter_values) != len(items):
                errors.append("CausalMeter.meter_values debe tener el mismo largo que items")
            if params.get("future_reveal") != "skeleton_only":
                errors.append("CausalMeter requiere future_reveal='skeleton_only' para no mostrar texto futuro")
            image_slots = params.get("image_slots", [])
            visual_strategy = str(params.get("visual_asset_strategy", "diagram"))
            if image_slots:
                if visual_strategy not in ("generated_image", "hybrid", "diagram"):
                    errors.append("CausalMeter.params.visual_asset_strategy debe ser diagram, generated_image o hybrid")
                if not isinstance(image_slots, list):
                    errors.append("CausalMeter.params.image_slots debe ser una lista")
                else:
                    source_slots = [
                        slot for slot in image_slots
                        if isinstance(slot, dict) and str(slot.get("role") or slot.get("id") or "").lower() in ("source_card", "source", "snack_package", "package_card")
                    ]
                    if visual_strategy in ("generated_image", "hybrid") and not source_slots:
                        errors.append("CausalMeter hybrid/generated_image requiere image_slots con role='source_card' para no dejar el primer card vacio")
                    for idx, slot in enumerate(image_slots):
                        if not isinstance(slot, dict):
                            errors.append("CausalMeter.image_slots[%d] debe ser objeto" % idx)
                            continue
                        if not (slot.get("prompt") or slot.get("asset") or slot.get("src")):
                            errors.append("CausalMeter.image_slots[%d] requiere prompt, asset o src" % idx)
                        if slot.get("model") and slot.get("model") != "gpt-image-2":
                            errors.append("CausalMeter.image_slots[%d].model debe ser gpt-image-2" % idx)
            if "caption" not in (o.get("must_not_cover") or []):
                errors.append("CausalMeter debe declarar must_not_cover con caption")
            if o.get("blocks_captions", False) is not False:
                errors.append("CausalMeter debe usar blocks_captions=false porque reserva caption lane")
        if component == "LowerThird" and params.get("sub") and params.get("sub_source") not in ("narrated", "user"):
            errors.append("LowerThird.params.sub requiere sub_source='narrated' o 'user'; no renderices reglas internas como copy")
        if component in ("StatRing", "CountUp"):
            if params.get("value") is None:
                errors.append("overlay/%s requiere params.value numerico" % component)
            display = "%s%s" % (params.get("value", ""), params.get("suffix", ""))
            if len(str(display).strip()) >= 4 and params.get("fit_mode") not in ("responsive", "compact", "single_line"):
                errors.append("overlay/%s con valor ancho (%r) requiere params.fit_mode responsive/compact/single_line" % (component, display))
        for ia in o.get("params", {}).get("item_anchors", []):
            chk(ia, "item_anchor/%s" % o.get("component"))
    if len(story_charts) > 1:
        errors.append("StoryArcChart: maximo 1 por reel; usa StepList, StatRing, Annotation o B-roll cuando corresponda")
    # v2: presupuesto GLOBAL de golpes tipograficos (todo lo escaso tenia tope
    # -- transiciones 3, avatar 2, reescritura 1 -- excepto el texto en pantalla,
    # que era ilimitado y absorbia todo bajo presion).
    try:
        from engine._generated import KINETIC_TEXT_HITS_MAX as _KIN_MAX
    except Exception:
        _KIN_MAX = 4
    _kinetic = [o for o in plan.get("overlays", []) if str(o.get("component")) in ("BigWordSequence", "KeywordPop")]
    if len(_kinetic) > _KIN_MAX:
        errors.append(
            "golpes tipograficos: %d overlays BigWordSequence/KeywordPop (max %d por reel). Son picos, no "
            "relleno: mueve el resto a overlays compuestos sobre media o eliminalos" % (len(_kinetic), _KIN_MAX))
    for x in plan.get("sfx", []):
        a = x.get("anchor", {})
        if "phrase" in a:
            chk(a["phrase"], "sfx/%s" % x.get("id"))
        sid = x.get("id")
        if sid == "none":
            continue
        gain = float(x.get("gain", 0.5))
        cap = SFX_MAX_GAIN.get(sid, 0.20)
        floor = SFX_MIN_GAIN.get(sid, 0.40)
        if gain > cap:
            errors.append("sfx/%s gain %.2f excede maximo %.2f; mezcla bajo la voz y evita ruido agresivo" % (sid, gain, cap))
        if gain < floor:
            errors.append("sfx/%s gain %.2f queda inaudible; minimo %.2f para el banco local actual" % (sid, gain, floor))

    try:
        from engine import resolve as plan_resolve
        resolved = plan_resolve.resolve(plan, rough_alignment(script))
        resolved_overlays = resolved.get("overlays", [])
        body_scenes = [
            sc for sc in resolved.get("scenes", [])
            if sc.get("role") != "hook" and sc.get("layout") != "cta"
        ]
        body_ms = sum(max(0, int(sc.get("toMs", 0)) - int(sc.get("fromMs", 0))) for sc in body_scenes)
        # GENRE-AWARE: solo cuenta como plate "de mas" el tiempo de plates cuyo
        # claim es DEMOSTRABLE (esos SI deberian ser media). El tiempo de plates
        # que sirven claims textuales es correcto y no infla este cap -- antes un
        # explainer analitico se pasaba del 70% siendo legitimamente grafico. La
        # monotonia visual real (aun con genero correcto) la juzga el render judge
        # sobre frames, no este proxy de tiempo ciego.
        try:
            from engine import medium_policy as _mp2
            def _demo(sc):
                v = _mp2.classify_scene(sc)
                return v.get("kind") == "demostrable" and v.get("confidence", 0) >= 0.9
        except Exception:
            _demo = lambda sc: True  # backstop: sin clasificador, todo plate cuenta (comportamiento viejo)
        plate_ms = sum(
            max(0, int(sc.get("toMs", 0)) - int(sc.get("fromMs", 0)))
            for sc in body_scenes
            if sc.get("role") == "plate" and (sc.get("clip") or {}).get("source") == "none" and _demo(sc)
        )
        if media_policy == "production" and body_ms > 0 and plate_ms / body_ms > 0.70:
            errors.append("media_policy=production deja %.0f%% del cuerpo como plate para claims DEMOSTRABLES (deberian ser media)" % (
                100 * plate_ms / body_ms))
        # v2: segundo cap CIEGO al genero. El cap de arriba excluia plates
        # 'textuales' -> tiempo de texto ILIMITADO (un reel podia ser 100% texto
        # si el clasificador decia textual, que es lo que paso). El texto total,
        # del genero que sea, no puede dominar el cuerpo del reel.
        plate_ms_total = sum(
            max(0, int(sc.get("toMs", 0)) - int(sc.get("fromMs", 0)))
            for sc in body_scenes
            if (sc.get("clip") or {}).get("source") in (None, "none", "motion") and sc.get("role") != "avatar"
        )
        if media_policy == "production" and body_ms > 0 and plate_ms_total / body_ms > 0.40:
            errors.append(
                "balance de medio: %.0f%% del tiempo del cuerpo es 100%%-texto (max 40%%); la base del reel "
                "es media de personas/accion" % (100 * plate_ms_total / body_ms))
        for sc in resolved.get("scenes", []):
            dur_ms = int(sc.get("toMs", 0)) - int(sc.get("fromMs", 0))
            if dur_ms <= 0:
                errors.append("timeline: scene/%s en %r dura %dms; no se permiten escenas de duracion cero" % (
                    sc.get("role"), phrase_text(sc.get("anchor", {})), dur_ms))
            elif sc.get("layout") == "cta" and dur_ms < 2500:
                errors.append("timeline: CTA visual dura %dms; minimo 2500ms" % dur_ms)
            elif sc.get("layout") != "cta" and dur_ms < 500:
                errors.append("timeline: scene/%s en %r dura %dms; minimo 500ms" % (
                    sc.get("role"), phrase_text(sc.get("anchor", {})), dur_ms))
            src = (sc.get("clip") or {}).get("source")
            if sc.get("role") != "plate" and src != "none":
                continue
            if sc.get("layout") == "cta" or sc.get("coverage_required") is False:
                continue
            purpose = sc.get("plate_purpose")
            overlapping = [
                o for o in resolved_overlays
                if int(o.get("startMs", 0)) < int(sc.get("toMs", 0))
                and int(o.get("startMs", 0)) + int(o.get("durMs", 0)) > int(sc.get("fromMs", 0))
            ]
            # plate_purpose ya NO acopla purpose->componente. El motor no impone la
            # forma: el director elige el elemento por lo que dice el beat, y la
            # cobertura real se valida por contenido (merged_gaps, abajo).
            if purpose == "chapter":
                comps = {o.get("component") for o in overlapping}
                if comps == {"KeywordPop"} or (comps and not (comps & {"ChapterDots", "LowerThird"})):
                    errors.append("scene/plate chapter %s no puede depender solo de KeywordPop; usa ChapterDots, LowerThird o corta al siguiente B-roll" % (
                        phrase_text(sc.get("anchor", {}))))
            gaps = merged_gaps(sc, resolved_overlays)
            if gaps:
                human = ", ".join("%d-%dms" % (a - sc["fromMs"], b - sc["fromMs"]) for a, b in gaps[:3])
                errors.append("scene/plate %s tiene huecos visuales sin overlay informativo: %s" % (
                    phrase_text(sc.get("anchor", {})), human))
        for i, left in enumerate(resolved_overlays):
            for right in resolved_overlays[i + 1:]:
                ov = overlap_ms(left, right)
                if ov <= 250 or overlap_allowed(left, right):
                    continue
                lc, rc = left.get("component"), right.get("component")
                pair = {lc, rc}
                if pair == {"StatRing", "KeywordPop"} or pair == {"CountUp", "KeywordPop"}:
                    errors.append("timeline: %s y %s se solapan %dms en el centro; acorta el stat o retrasa el KeywordPop" % (lc, rc, ov))
                    continue
                same_zone = placement_group(left) == placement_group(right)
                if same_zone and lc in STRONG_OVERLAYS and rc in STRONG_OVERLAYS:
                    errors.append("timeline: overlays fuertes %s/%s se solapan %dms en %s; usa handoff, otra zona o menos duracion" % (
                        lc, rc, ov, placement_group(left)))
        resolved_sfx = sorted(
            [x for x in resolved.get("sfx", []) if x.get("id") != "none"],
            key=lambda x: int(x.get("atMs", 0)),
        )
        for prev, curr in zip(resolved_sfx, resolved_sfx[1:]):
            delta = int(curr.get("atMs", 0)) - int(prev.get("atMs", 0))
            if delta < 2500:
                errors.append("timeline: sfx/%s y sfx/%s estan separados por %dms; minimo 2500ms para no ensuciar la voz" % (
                    prev.get("id"), curr.get("id"), delta))
        if int(resolved.get("totalMs", 0)) - int(resolved.get("ctaStartMs", 0)) < 2500:
            errors.append("timeline: CTA final visible menos de 2500ms; aumenta CTA_MIN_VISIBLE_MS o mueve el anchor")
        visual_beats = pacing_utils.derive_visual_beats(
            resolved.get("scenes", []),
            resolved_overlays,
            int(resolved.get("totalMs", 0)),
        )
        pacing = pacing_utils.pacing_report({
            "totalMs": resolved.get("totalMs", 0),
            "scenes": resolved.get("scenes", []),
            "overlays": resolved_overlays,
            "visualBeats": visual_beats,
            "pacingBeats": [],
        })
        if not pacing.get("ok"):
            errors.extend(pacing.get("errors") or [])
    except Exception as e:
        errors.append("timeline: no se pudo resolver anchors para QA de cobertura: %s" % str(e).split("\n")[0])

    if errors:
        print("PLAN INVALIDO (%d):" % len(errors))
        for e in errors:
            print("  -", e)
        return 1
    print("PLAN OK: %d escenas, %d overlays, %d sfx" % (
        len(plan.get("scenes", [])), len(plan.get("overlays", [])), len(plan.get("sfx", []))))
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("uso: python3 scripts/validate_plan.py <plan.json>"); sys.exit(2)
    sys.exit(main(sys.argv[1]))
