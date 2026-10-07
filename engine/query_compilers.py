from __future__ import annotations

import json
import re
from typing import Any


ABSTRACT_QUERY_PATTERNS = (
    r"combine task fragments",
    r"one thread",
    r"idea clave",
    r"visual support",
    r"generic concept",
)

TRANSLATIONS = {
    "crema": "body cream",
    "frasco": "cosmetic jar",
    "tarro": "cosmetic jar",
    "envase": "product package",
    "etiqueta": "product label",
    "ingrediente": "ingredient label",
    "mujer": "woman",
    "mano": "hand",
    "aplica": "applying",
    "masaje": "massage",
    "compara": "comparing",
    "pantalla": "screen",
    "celular": "phone",
    "computador": "laptop",
    "alimento": "food",
    "pan": "bread",
    "cuello": "neck",
}

CUTOUT_PROP_PATTERNS = (
    (r"\b(crema|frasco|tarro|tubo|envase)\b", "tubo de crema corporal"),
    (r"\b(calendario|semanas?|meses?|progresi[oó]n)\b", "calendario de seguimiento"),
    (r"\b(reloj|tiempo|horas?)\b", "reloj analógico"),
    (r"\b(cinta|medir|medici[oó]n|distancia)\b", "cinta métrica"),
    (r"\b(foto|fotograf[ií]a|c[aá]mara|misma luz|luz)\b", "cámara fotográfica"),
    (r"\b(piel|dermis|epidermis|tejido)\b", "corte transversal de piel"),
    (r"\b(grasa|adiposo|adiposa)\b", "célula de grasa ilustrada"),
    (r"\b(agua|hidrataci[oó]n|hidrata)\b", "gota de agua"),
    (r"\b(inflamaci[oó]n|inflamado|inflamada)\b", "tejido inflamado ilustrado"),
    (r"\b(metabolismo|energ[ií]a)\b", "medidor de energía"),
    (r"\b(compara|comparaci[oó]n|versus)\b", "balanza de comparación"),
    (r"\b(sue[nñ]o|dormir|descanso)\b", "almohada de descanso"),
)


def _clean_words(value: str, limit: int = 8) -> list[str]:
    stop = {"para", "como", "esta", "este", "esto", "porque", "pero", "desde", "hasta", "sobre", "that", "with", "from", "into", "visual", "concept"}
    words = []
    for raw in re.findall(r"[a-záéíóúüñ0-9]+", str(value or "").lower()):
        word = TRANSLATIONS.get(raw, raw)
        if raw in stop or word in words or len(raw) < 3:
            continue
        words.append(word)
        if len(words) >= limit:
            break
    return words


def abstract_query(value: str) -> bool:
    text = str(value or "").lower().strip()
    return not text or any(re.search(pattern, text) for pattern in ABSTRACT_QUERY_PATTERNS)


def _base_subject(shot: dict[str, Any]) -> str:
    words = _clean_words(" ".join(str(shot.get(key) or "") for key in ("visualProof", "tts", "query")), 6)
    return " ".join(words) or "health product"


def clip_base_query(shot: dict[str, Any]) -> str:
    base = str(shot.get("clipBaseQuery") or shot.get("clipQuery") or "").strip()
    base = re.split(r"\s+(?:close up b roll|screen recording tutorial)(?:\s|$)", base, maxsplit=1, flags=re.I)[0].strip()
    return base


def clip_extractor_allowed(shot: dict[str, Any]) -> bool:
    return str(shot.get("proofKind") or shot.get("mediaNeedKind") or "") in {
        "real_event", "third_party_commentary", "cultural_reference"
    }


def compile_clip_extractor(shot: dict[str, Any], constraints: list[str] | None = None) -> list[str]:
    if not clip_extractor_allowed(shot):
        raise ValueError("Clip Extractor solo admite sucesos reales, comentario de terceros o referencias culturales")
    base = clip_base_query(shot)
    source_title = str(shot.get("sourceTitle") or shot.get("source_title") or "").strip()
    source_channel = str(shot.get("sourceChannel") or shot.get("source_channel") or "").strip()
    if abstract_query(base):
        base = " ".join(value for value in (source_title, source_channel) if value).strip()
    if abstract_query(base) or len(base.split()) < 3:
        raise ValueError("Clip Extractor requiere una fuente, evento o titulo identificable; no acepta conceptos genericos")
    kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
    mode = {
        "real_event": "original footage",
        "third_party_commentary": "full interview or commentary video",
        "cultural_reference": "official scene or music video",
    }[kind]
    constraints_text = " ".join(constraints or [])
    variants = [
        "%s %s" % (base, mode),
        "%s %s source clip" % (source_title or base, source_channel),
        "%s %s" % (base, constraints_text),
    ]
    return list(dict.fromkeys(re.sub(r"\s+", " ", value).strip()[:180] for value in variants if value.strip()))[:3]


def compile_pexels(shot: dict[str, Any], constraints: list[str] | None = None) -> list[str]:
    base = str(shot.get("pexelsBaseQuery") or shot.get("pexelsQuery") or "").strip().lower()
    if abstract_query(base) or len(base.split()) > 7:
        base = _base_subject(shot)
    words = _clean_words(base, 7)
    if len(words) < 3:
        words += ["close", "home"]
    core = " ".join(words[:7])
    variants = [core, core + " close up", core + " hands"]
    return [re.sub(r"\s+", " ", value).strip()[:80] for value in variants]


def continuity_clause(shot: dict[str, Any]) -> str:
    group = str(shot.get("continuityGroup") or "").strip()
    if not group:
        return ""
    return " Continuity lock %s: preserve the same subject, product, camera axis, environment, palette and declared data across this group." % group


def design_clause(shot: dict[str, Any]) -> str:
    scope = re.sub(r"\s+", " ", str(shot.get("designStyleScope") or "")).strip()
    return " Visual language: %s" % scope if scope else ""


def image_base_prompt(shot: dict[str, Any]) -> str:
    base = str(shot.get("imageBasePrompt") or shot.get("prompt") or "").strip()
    # Older resumable plans may contain a previously compiled prompt. Strip the
    # generated suffix so compiling again is stable instead of appending it.
    markers = (" Continuity lock ", " No watermark,", " Rejection corrections:", " Eye-level editorial camera,", " Over-the-shoulder composition,", " Controlled close-up,")
    positions = [base.find(marker) for marker in markers if base.find(marker) >= 0]
    if positions:
        base = base[: min(positions)].rstrip()
    return base


def compile_image(shot: dict[str, Any], constraints: list[str] | None = None) -> list[str]:
    base = image_base_prompt(shot)
    if not base:
        base = "Landscape 16:9 premium editorial health visual showing %s." % _base_subject(shot)
    elif "16:9" not in base and "landscape" not in base.lower():
        base = "Landscape 16:9 composition. " + base
    identity = continuity_clause(shot) + design_clause(shot)
    if str(shot.get("mediaNeedKind") or shot.get("proofKind") or "") == "product_inspection" and shot.get("hybridTemplate"):
        identity += " Place the complete product package in the lower-left 42 percent, fully visible and unobstructed; reserve the top-left as headline safe space and the right 45 percent as clean negative space for a deterministic editorial overlay."
    negatives = " No watermark, no unrelated logo, no deformed text, no fake medical evidence."
    if constraints:
        negatives += " Rejection corrections: " + ", ".join(constraints) + "."
    variants = [
        base + identity + negatives + " Eye-level editorial camera, one clear focal subject.",
        base + identity + negatives + " Over-the-shoulder composition, natural light, realistic materials.",
        base + identity + negatives + " Controlled close-up, clean background, generous safe margins.",
    ]
    return [value[:1400] for value in variants]


def compile_image_pair(shot: dict[str, Any], constraints: list[str] | None = None) -> list[str]:
    """Compile two separate images; the provider must never fake both states in one generation."""
    subject = _base_subject(shot)
    proof = str(shot.get("requiredEvidence") or shot.get("visualProof") or shot.get("tts") or "").strip()
    continuity = str(shot.get("continuityGroup") or "comparison-pair")
    corrections = ", ".join(constraints or [])
    explicit = image_base_prompt(shot)
    left_explicit = ""
    right_explicit = ""
    if explicit:
        pair_match = re.search(r"\bLeft\s*:\s*(.+?)\s*\bRight\s*:\s*(.+)", explicit, re.I | re.S)
        if pair_match:
            left_explicit = re.sub(r"\s+", " ", pair_match.group(1)).strip()
            right_explicit = re.sub(r"\s+", " ", pair_match.group(2)).strip()
            explicit = re.sub(r"\bLeft\s*:\s*.+", "", explicit, flags=re.I | re.S).strip()
    # Each provider call creates one side of the comparison. Remove layout
    # language that would make the image model draw another nested diptych.
    explicit = re.sub(r"\bcontrolled\s+two[- ]panel\s+documentary\s+comparison\s+of\b", "controlled single-state documentary photograph of", explicit, flags=re.I)
    explicit = re.sub(r"\b(two[- ]panel|split[- ]screen|side[- ]by[- ]side|diptych)\b", "single-state", explicit, flags=re.I)
    explicit = re.sub(r"\b(in\s+)?each\s+panel\b", "in this single frame", explicit, flags=re.I)
    explicit = re.sub(r"\bboth\s+panels\b", "this single frame", explicit, flags=re.I)
    people_policy = str(shot.get("peoplePolicy") or "contextual")
    if shot.get("requiresVisibleFace") or shot.get("requires_visible_face"):
        people_clause = " The same person's face and the relevant body area must both be clearly visible in this single state; do not use an isolated skin crop or change identity."
    else:
        people_clause = {
            "forbidden": " No face, no head, no portrait, no identifiable person; frame only the exact body area or object required by the evidence.",
            "contextual": " Any person must remain contextual and secondary; hands or the relevant body area dominate the evidence.",
            "required": " Keep the same clearly visible person in both final states without changing identity.",
        }.get(people_policy, "")
    label_requested = bool(re.search(r"\b(label(?:ed)?|etiquet(?:a|ado|ada)|marca|brand)\b", " ".join((explicit, left_explicit, right_explicit, str(shot.get("hookRequirement") or ""))), re.I))
    text_clause = "No extra text; render only the explicitly requested fictional packaging label legibly" if label_requested else "No text"
    common = (
        "Landscape 16:9 editorial evidence panel. Preserve the same relevant body area, product, room, lens, camera height, lighting and color grade. "
        "Generate exactly ONE full-frame photographic state, never a collage or split layout. Continuity key %s. %s, no watermark, no unrelated logo, no medical transformation claim.%s Subject: %s. Evidence across the final pair: %s.%s"
    ) % (continuity, text_clause, people_clause, subject, proof, (" Composition: " + explicit + ".") if explicit else "")
    common += design_clause(shot)
    pairs = []
    variants = [
        ("State A only: controlled baseline or first declared viewpoint.", "State B only: comparison state or second declared viewpoint; preserve identity exactly."),
        ("State A only: neutral frontal evidence view.", "State B only: the alternate evidence view requested by the narration, with identical environment."),
        ("State A only: documented reference condition.", "State B only: documented comparison condition; no exaggerated physical change."),
    ]
    for variant_index, (left, right) in enumerate(variants):
        if left_explicit:
            left = "State A only: %s" % left_explicit
        if right_explicit:
            right = "State B only: %s" % right_explicit
        if variant_index == 1:
            left += " Continuity retry: preserve the exact same person, body landmarks, product shape and camera geometry."
            right += " Continuity retry: preserve the exact same person, body landmarks, product shape and camera geometry."
            if label_requested:
                left += " Keep the requested fictional label consistent and readable."
                right += " Keep the requested fictional label consistent and readable."
        elif variant_index == 2:
            left += " Use a slightly wider natural composition with all required evidence visible and no cropped object."
            right += " Use a slightly wider natural composition with all required evidence visible and no cropped object."
            if label_requested:
                left += " Keep the plausible fictional label secondary and small enough that minor lettering is not salient, but never blank."
                right += " Keep the plausible fictional label secondary and small enough that minor lettering is not salient, but never blank."
        if corrections:
            left += " Rejection corrections: %s." % corrections
            right += " Rejection corrections: %s." % corrections
        pairs.append(json.dumps({"left": common + " " + left, "right": common + " " + right}, ensure_ascii=False, sort_keys=True))
    return pairs


def compile_omni(shot: dict[str, Any], constraints: list[str] | None = None) -> list[str]:
    subject = _base_subject(shot)
    proof = str(shot.get("visualProof") or shot.get("tts") or "").strip()
    continuity = continuity_clause(shot)
    correction = " Avoid: %s." % ", ".join(constraints or []) if constraints else ""
    base = (
        "Landscape 16:9 temporal sequence. Start state: %s before the action. "
        "Action progression: %s. End state: the visible change is clear and continuous. "
        "Preserve identity, object placement, lighting and camera direction.%s%s"
    ) % (subject, proof, continuity, correction)
    base += design_clause(shot)
    return [base[:1400], (base + " Use one continuous camera move.")[:1400], (base + " Use two clearly connected stages without a jump cut.")[:1400]]


def _cutout_props(shot: dict[str, Any]) -> list[str]:
    explicit = shot.get("cutoutProps") or shot.get("cutout_props") or []
    if isinstance(explicit, str):
        explicit = explicit.split(",")
    props = [re.sub(r"\s+", " ", str(value or "")).strip(" .,;:") for value in explicit]
    props = [value for value in props if value][:3]
    if props:
        return list(dict.fromkeys(props))

    text = " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof", "prompt")).lower()
    for pattern, label in CUTOUT_PROP_PATTERNS:
        if re.search(pattern, text, re.I) and label not in props:
            props.append(label)
        if len(props) == 3:
            break
    if props:
        return props
    defaults = {
        "physiological_mechanism": ["corte transversal de piel", "gota de agua", "célula ilustrada"],
        "timeline_or_progression": ["calendario de seguimiento", "reloj analógico", "marcador de progreso"],
        "comparison": ["balanza de comparación", "tarjeta inicial", "tarjeta final"],
    }
    return defaults.get(str(shot.get("mediaNeedKind") or ""), ["flecha de proceso", "medidor visual"])


def compile_cutout(shot: dict[str, Any], constraints: list[str] | None = None) -> list[str]:
    kind = str(shot.get("mediaNeedKind") or "abstract_concept")
    background = re.sub(r"\s+", " ", str(shot.get("cutoutBackground") or shot.get("cutout_background") or "")).strip(" .,;:")
    if not background:
        background = {
            "physiological_mechanism": "mesa de laboratorio editorial en papel",
            "timeline_or_progression": "tablero editorial de seguimiento",
            "comparison": "tablero editorial dividido",
        }.get(kind, "estudio editorial limpio en papel")
    relation = str(shot.get("cutoutRelation") or shot.get("cutout_relation") or "").strip().lower()
    if relation not in {"comparar", "causa", "secuencia", "dentro", "encima", "separado"}:
        relation = {
            "physiological_mechanism": "causa",
            "timeline_or_progression": "secuencia",
            "comparison": "comparar",
        }.get(kind, "separado")
    props = _cutout_props(shot)
    stop = shot.get("stopMotion") or {}
    intent = str(stop.get("intent") or shot.get("stopMotionIntent") or "").strip()
    reason = re.sub(r"\s+", " ", str(stop.get("why") or shot.get("whyStopMotion") or "")).strip()
    motion = shot.get("motionSpec") or {}
    primitive = str(motion.get("visualPrimitive") or "editorial")
    if not stop.get("eligible") or not intent or len(reason) < 18:
        return []
    choreography = {
        "comparar": "Los props entran por separado, se alinean y terminan en una comparación clara sin texto.",
        "causa": "El primer prop activa una reacción visual del segundo; el estado final mantiene ambos elementos claramente separados.",
        "secuencia": "Los props aparecen uno por uno de izquierda a derecha y terminan ordenados como una secuencia legible.",
        "dentro": "El prop secundario entra dentro del principal y se detiene en una composición clara.",
        "encima": "El prop secundario desciende y queda colocado encima del principal.",
        "separado": "Los props cobran vida brevemente, se separan y terminan con suficiente espacio entre sí.",
    }[relation]
    visual_brief = "Intent: %s. Purpose: %s. Why: %s. Choreography: %s" % (intent, primitive, reason, choreography)
    script = "Background: %s. Props: %s. Relacion: %s.\n%s" % (background, ", ".join(props), relation, visual_brief)
    return [script[:1800]]


def _short_copy(value: str, fallback: str) -> str:
    clean = re.sub(r"\s+", " ", str(value or fallback or "")).strip(" .,:;!?")
    if clean and len(clean) <= 32 and len(clean.split()) <= 6:
        return clean.upper()
    # Display copy stays in the narration language. Provider-query
    # translations must never leak into on-screen UI. Prefer a complete short
    # clause; when none fits, build a compact phrase and remove dangling
    # articles/prepositions instead of exposing a syntactically cut sentence.
    clauses = [
        re.sub(r"\s+", " ", part).strip(" .,:;!?")
        for part in re.split(r"[.;:!?]|\b(?:pero|aunque|porque|mientras)\b", clean, flags=re.I)
    ]
    for clause in clauses:
        if clause and len(clause) <= 32 and len(clause.split()) <= 6:
            return clause.upper()
    words = re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", clean)
    selected: list[str] = []
    for word in words:
        candidate = " ".join(selected + [word]).upper()
        if len(candidate) > 32 or len(selected) >= 6:
            break
        selected.append(word)
    dangling = {"a", "al", "con", "de", "del", "el", "en", "la", "las", "los", "o", "para", "por", "que", "se", "sin", "su", "sus", "un", "una", "y"}
    while selected and selected[-1].casefold() in dangling:
        selected.pop()
    return (" ".join(selected) or "PUNTO CLAVE").upper()


def compile_ui_spec(shot: dict[str, Any]) -> dict[str, Any]:
    kind = str(shot.get("mediaNeedKind") or "abstract_concept")
    template = str(shot.get("uiTemplate") or "") or {
        "exact_ui_state": "state-change",
        "product_inspection": "product-inspection",
        "physiological_mechanism": "mechanism",
        "human_action": "process-steps",
        "comparison": "comparison",
        "abstract_concept": "concept",
    }.get(kind, "concept")
    if kind == "human_action" and str(shot.get("temporalAction") or "") == "multi_step":
        template = "process-steps"
    repaired_hybrid = bool(
        shot.get("draftRepair")
        and str(shot.get("route") or "") in {"image", "image_pair"}
        and str(shot.get("hybridTemplate") or "")
    )
    if kind == "comparison" and shot.get("complexComparison") and not repaired_hybrid:
        template = "body-distinction"
    text = str(shot.get("tts") or "")
    numbers = [str(value) for value in (shot.get("uiValues") or [])][:4] or re.findall(r"\b\d+(?:[.,]\d+)?(?:\s?(?:%|mg|ml|g|meses?|semanas?|horas?))?\b", text, re.I)[:4]
    items = [str(value) for value in (shot.get("uiItems") or [])][:4]
    if not items and kind == "comparison" and re.search(r"[aá]ngulo", text, re.I):
        items = ["MISMA PERSONA", "OTRO ÁNGULO"]
    if not items:
        for part in re.split(r"[,.;:]|\by\b", text, flags=re.I):
            label = _short_copy(part, "")
            if label and label not in items:
                items.append(label)
            if len(items) >= 4:
                break
    headline = _short_copy(shot.get("screenCopy"), shot.get("visualProof") or text or "PUNTO CLAVE")
    return {
        "template": template,
        "variant": str(shot.get("uiVariant") or ""),
        "state": "resolved",
        "headline": headline,
        "subcopy": _short_copy(shot.get("subcopy"), ""),
        "items": items,
        "values": numbers,
        "productBrand": str(shot.get("productBrand") or ""),
        "productName": str(shot.get("productName") or ""),
        "productSize": str(shot.get("productSize") or ""),
        "continuityGroup": str(shot.get("continuityGroup") or ""),
        "dataSource": "locked_narration",
    }


def compile_all(shot: dict[str, Any], feedback_constraints: list[str] | None = None) -> dict[str, Any]:
    shot["clipBaseQuery"] = clip_base_query(shot)
    shot["pexelsBaseQuery"] = str(shot.get("pexelsBaseQuery") or shot.get("pexelsQuery") or "").strip()
    shot["imageBasePrompt"] = image_base_prompt(shot)
    routes = set(shot.get("routePlan") or [])
    if not routes:
        routes = {"pexels", "image", "cutout_motion", "omni", "ui"}
        if clip_extractor_allowed(shot):
            routes.add("clip_extractor")
    compilers = {
        "pexels": compile_pexels,
        "image": compile_image,
        "image_pair": compile_image_pair,
        "cutout_motion": compile_cutout,
        "omni": compile_omni,
    }
    result: dict[str, Any] = {}
    if "clip_extractor" in routes:
        result["clip_extractor"] = compile_clip_extractor(shot, feedback_constraints)
    for provider, compiler in compilers.items():
        if provider in routes:
            result[provider] = compiler(shot, feedback_constraints)
    if "ui" in routes:
        result["ui"] = [compile_ui_spec(shot)]
    shot["queryVariants"] = result
    if result.get("clip_extractor"):
        shot["clipQuery"] = result["clip_extractor"][0]
    if result.get("pexels"):
        shot["pexelsQuery"] = result["pexels"][0]
    if result.get("image"):
        shot["prompt"] = result["image"][0]
    if result.get("image_pair"):
        shot["imagePairPrompt"] = result["image_pair"][0]
    if result.get("cutout_motion"):
        shot["cutoutPrompt"] = result["cutout_motion"][0]
    if result.get("omni"):
        shot["omniPrompt"] = result["omni"][0]
    if result.get("ui"):
        shot["uiSpec"] = result["ui"][0]
    return result


def rejection_feedback(reason: str) -> dict[str, list[str]]:
    text = str(reason or "").lower()
    codes: list[str] = []
    constraints: list[str] = []
    mapping = [
        (r"watermark|microstock|shutterstock|stock logo", "third_party_watermark", "no watermark no stock logo"),
        (r"logo|marca real|third.party brand", "third_party_logo", "no third party logo"),
        (r"wrong software|blender|excel|deepseek|editor ui", "wrong_software", "correct software state no tutorial editor"),
        (r"no state change|sin cambio|static", "no_state_change", "visible before and after state change"),
        (r"presenter|talking head|rostro", "unexpected_presenter", "no presenter no talking head"),
        (r"generic|gen[eé]ric", "generic_visual", "specific observable action"),
        (r"wrong product|supplement|pills|producto equivocado", "wrong_product", "correct topical product no pills"),
    ]
    for pattern, code, constraint in mapping:
        if re.search(pattern, text):
            codes.append(code)
            constraints.append(constraint)
    if not codes:
        codes.append("semantic_mismatch")
        constraints.append("match the visible action and object exactly")
    return {"rejected_because": codes, "next_query_constraints": constraints}
