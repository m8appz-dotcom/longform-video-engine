from __future__ import annotations

import json
import os
import re
from typing import Any

from engine.motion_spec import apply_motion_contract, infer_temporal_evidence, stop_motion_decision, validate_motion_contract


PROOF_KINDS = {
    "human_action",
    "real_event",
    "third_party_commentary",
    "cultural_reference",
    "product_inspection",
    "physiological_mechanism",
    "comparison",
    "exact_ui_state",
    "presenter",
    "abstract_concept",
}
# Kept as a compatibility export for older runs and callers. New plans always
# write one of PROOF_KINDS to proofKind and mediaNeedKind.
MEDIA_NEED_KINDS = PROOF_KINDS
EVIDENCE_MODES = {"illustrative", "demonstrative", "documentary", "data_exact"}
TEMPORAL_ACTIONS = {"single", "multi_step"}
PROVIDER_ROUTES = {"clip_extractor", "pexels", "image", "image_pair", "cutout_motion", "omni", "ui", "motion-card", "avatar"}
PEOPLE_POLICIES = {"forbidden", "contextual", "required"}


LEGACY_KIND_MAP = {
    "label_or_ingredient": "product_inspection",
    "measurement_protocol": "human_action",
    "timeline_or_progression": "abstract_concept",
}


def cutout_enabled() -> bool:
    return os.environ.get("CUTOUT_PROVIDER_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values).lower()


def infer_media_need(shot: dict[str, Any], direction: dict[str, Any] | None = None) -> str:
    direction = direction or {}
    explicit = str(
        direction.get("proof_kind")
        or direction.get("proofKind")
        or direction.get("media_need_kind")
        or shot.get("proofKind")
        or shot.get("mediaNeedKind")
        or ""
    ).strip().lower()
    explicit = LEGACY_KIND_MAP.get(explicit, explicit)
    locked = bool(
        direction.get("proof_kind_locked")
        or direction.get("proofKindLocked")
        or shot.get("proofKindLocked")
    )
    if locked and explicit in PROOF_KINDS:
        return explicit
    proof_text = _text(shot.get("tts"), direction.get("visual_proof"), direction.get("prompt"), direction.get("query"))
    # Concrete proof cues outrank an incompatible LLM label. In particular, a
    # split-screen/same-subject comparison is not product inspection merely
    # because the narration also mentions a cream or package.
    if re.search(r"\b(split[- ]screen|same (?:person|subject).+different angles?|misma persona.+(?:dos|diferentes?) [aá]ngulos?|otro [aá]ngulo.+(?:aparente|diferencia|fabricar))\b", proof_text):
        return "comparison"
    if re.search(r"\b(?:person|woman|mujer|patient|paciente|hand|mano)\b.*\b(?:appl(?:y|ies|ying)|aplica|consult(?:s|ing)?|consulta|reads?|revisa|tests?|prueba|checks?|inspecciona|shops?|compra)\b", proof_text) or re.search(r"\bconsulta a un profesional\b", proof_text):
        return "human_action"
    if re.search(r"\b(etiqueta|label)\b", proof_text) or (
        re.search(r"\b(envase|empaque|frasco|tarro|botella|tubo|package)\b", proof_text)
        and re.search(r"\b(promete|promesa|afirma|dice|absolut[oa]s?|eliminar grasa|cura|contenido)\b", proof_text)
    ):
        return "product_inspection"
    if explicit in PROOF_KINDS:
        return explicit
    text = proof_text
    if re.search(r"\b(studio|dashboard|interfaz|pantalla|app|software|spreadsheet|hoja de c[aá]lculo|celda|bot[oó]n|menu|men[uú])\b", text):
        return "exact_ui_state"
    if re.search(r"\b(etiqueta|ingrediente|porci[oó]n|prote[ií]na|fibra|az[uú]car|retinol|cafe[ií]na|aminofilina|nutrition|label)\b", text):
        return "product_inspection"
    if re.search(r"\b(mecanismo|c[eé]lula|tejido|dermis|epidermis|grasa subcut[aá]nea|circulaci[oó]n|inflamaci[oó]n|metabolismo)\b", text):
        return "physiological_mechanism"
    if re.search(r"\b(misma luz|misma distancia|misma postura|mide|medir|protocolo|prueba una zona|fotograf[ií]a|seguimiento)\b", text):
        return "human_action"
    if re.search(r"\b(compara|comparaci[oó]n|versus|frente a|antes y despu[eé]s|lado a lado|diferencia entre)\b", text):
        return "comparison"
    if re.search(r"\b(semanas|meses|progresi[oó]n|a lo largo|primero.+luego|timeline|cronolog[ií]a)\b", text):
        return "abstract_concept"
    if re.search(r"\b(envase|frasco|tarro|botella|tubo|producto|crema|empaque|package|jar|bottle)\b", text):
        return "product_inspection"
    if re.search(r"\b(comentario|reacci[oó]n|otro video|youtube dice|creador dice|entrevista ajena)\b", text):
        return "third_party_commentary"
    if re.search(r"\b(pel[ií]cula|serie|video musical|videoclip|escena famosa|referencia cultural)\b", text):
        return "cultural_reference"
    if re.search(r"\b(noticia|evento real|archivo|documental|grabaci[oó]n real|caso real|declaraci[oó]n p[uú]blica|anuncio real)\b", text):
        return "real_event"
    if re.search(r"\b(aplica|abre|cierra|masajea|frota|señala|senala|camina|lee|sostiene|gira|toma|coloca|persona|mujer|hombre|mano)\b", text):
        return "human_action"
    return "abstract_concept"


def infer_temporal_action(shot: dict[str, Any], direction: dict[str, Any] | None = None) -> str:
    direction = direction or {}
    explicit = str(direction.get("temporal_action") or direction.get("temporalAction") or "").strip().lower()
    text = _text(shot.get("tts"), direction.get("visual_proof"))
    transitions = len(re.findall(r"\b(primero|segundo|tercero|luego|despu[eé]s|finalmente|antes.+despu[eé]s)\b", text))
    action_verbs = len(re.findall(r"\b(usa|utiliza|aplica|abre|gira|lee|compara|mide|toma|espera|observa|coloca|cambia|marca|fotograf[ií]a)\b", text))
    inferred = "multi_step" if transitions >= 1 or action_verbs >= 2 else "single"
    if explicit in TEMPORAL_ACTIONS and not (explicit == "single" and inferred == "multi_step"):
        return explicit
    return inferred


def infer_readable_data(kind: str, shot: dict[str, Any], direction: dict[str, Any] | None = None) -> bool:
    direction = direction or {}
    if "requires_readable_data" in direction or "requiresReadableData" in direction:
        return bool(direction.get("requires_readable_data") if "requires_readable_data" in direction else direction.get("requiresReadableData"))
    text = _text(shot.get("tts"), direction.get("visual_proof"), direction.get("prompt"))
    if kind == "exact_ui_state":
        return True
    return kind == "product_inspection" and bool(re.search(r"\b(lee|mira|revisa|busca|dice|promete|promesa|afirma|absolut[oa]s?|cantidad|porcentaje|0[.,]3|mg|ml|gramos?)\b", text))


def infer_state_continuity(kind: str, temporal_action: str, direction: dict[str, Any] | None = None) -> bool:
    direction = direction or {}
    if "requires_state_continuity" in direction or "requiresStateContinuity" in direction:
        return bool(direction.get("requires_state_continuity") if "requires_state_continuity" in direction else direction.get("requiresStateContinuity"))
    return temporal_action == "multi_step" or kind in {"exact_ui_state", "comparison"}


def route_order(kind: str, *, readable: bool, continuity: bool, temporal_action: str,
                temporal_evidence_mode: str = "implied") -> list[str]:
    routes = {
        # Clip Extractor is source retrieval, not a generic stock provider.
        "human_action": ["pexels", "image", "omni"],
        "real_event": ["clip_extractor"],
        "third_party_commentary": ["clip_extractor"],
        "cultural_reference": ["clip_extractor"],
        "exact_ui_state": ["ui"],
        "abstract_concept": ["image", "ui", "omni", "motion-card"],
        "presenter": ["avatar", "pexels", "image"],
        "product_inspection": ["pexels", "image", "ui", "omni"],
        "physiological_mechanism": ["image", "ui", "omni"],
        "comparison": ["image_pair", "ui", "omni"],
    }[kind]
    if readable and kind == "product_inspection":
        # A readable packaging claim needs both a real-looking package and
        # deterministic legibility. The image becomes evidence; Remotion adds
        # the exact claim as a magnifier/overlay instead of drawing a fake jar.
        routes = ["image", "omni", "ui"]
    elif readable:
        routes = ["ui"] + [route for route in routes if route not in {"ui", "pexels", "omni"}]
    if temporal_evidence_mode == "initial_final" and kind != "exact_ui_state":
        routes = ["image_pair"] + [route for route in routes if route not in {"image_pair", "image"}]
        if kind == "human_action" and "ui" not in routes:
            routes.append("ui")
    if temporal_evidence_mode == "continuous" and kind != "exact_ui_state":
        routes = [route for route in routes if route not in {"image", "image_pair"}]
        if kind == "human_action" and "ui" not in routes:
            # A deterministic Remotion process is an honest explanation of a
            # multi-step action when no suitable filmed demonstration exists.
            routes.append("ui")
    if continuity and kind == "exact_ui_state":
        routes = ["ui"] + [route for route in routes if route != "ui"]
    return list(dict.fromkeys(routes))


def infer_people_policy(kind: str, shot: dict[str, Any], direction: dict[str, Any]) -> str:
    explicit = str(direction.get("people_policy") or direction.get("peoplePolicy") or shot.get("peoplePolicy") or "").lower()
    # A comparison may or may not contain people. Contextual accepts either,
    # while the area cap still rejects a face that becomes the presenter.
    if kind == "comparison":
        return "contextual"
    if explicit in PEOPLE_POLICIES:
        # `required` means a presenter-sized face to the technical prefilter.
        # Hands, legs or a body performing an action are contextual evidence
        # and are verified semantically instead of requiring a visible face.
        if explicit == "required" and kind != "presenter":
            return "contextual"
        return explicit
    if kind == "presenter":
        return "required"
    if kind in {"human_action", "third_party_commentary", "cultural_reference", "real_event", "comparison"}:
        return "contextual"
    return "forbidden"


def required_evidence_for(kind: str, shot: dict[str, Any], direction: dict[str, Any]) -> str:
    explicit = str(direction.get("required_evidence") or direction.get("requiredEvidence") or shot.get("requiredEvidence") or "").strip()
    return explicit or str(direction.get("visual_proof") or shot.get("visualProof") or shot.get("tts") or "").strip()[:360]


def preferred_medium_for(kind: str, routes: list[str], direction: dict[str, Any]) -> str:
    explicit = str(direction.get("preferred_medium") or direction.get("preferredMedium") or "").strip().lower()
    return explicit if explicit in routes else routes[0]


def forbidden_substitutions_for(kind: str, direction: dict[str, Any]) -> list[str]:
    explicit = direction.get("forbidden_substitutions") or direction.get("forbiddenSubstitutions") or []
    if isinstance(explicit, str):
        explicit = [explicit]
    defaults = {
        "human_action": ["clip_extractor", "motion-card-as-evidence"],
        "real_event": ["pexels", "image", "omni", "ui", "motion-card", "synthetic-reenactment"],
        "third_party_commentary": ["pexels", "image", "omni", "ui", "motion-card", "synthetic-reenactment"],
        "cultural_reference": ["pexels", "image", "omni", "ui", "motion-card", "synthetic-reenactment"],
        "physiological_mechanism": ["generic-stock-as-proof"],
        "comparison": ["single-unrelated-still"],
        "exact_ui_state": ["fake-ui", "generic-stock-as-proof"],
    }
    return list(dict.fromkeys([str(value) for value in explicit] + defaults.get(kind, [])))


def normalize_media_contract(shot: dict[str, Any], direction: dict[str, Any] | None = None) -> dict[str, Any]:
    direction = direction or {}
    kind = infer_media_need(shot, direction)
    temporal = infer_temporal_action(shot, direction)
    readable = infer_readable_data(kind, shot, direction)
    continuity = infer_state_continuity(kind, temporal, direction)
    evidence_mode = str(direction.get("evidence_mode") or "").strip().lower()
    if evidence_mode not in EVIDENCE_MODES:
        evidence_mode = "data_exact" if readable else "documentary" if kind in {"real_event", "third_party_commentary", "cultural_reference"} else "demonstrative" if kind in {"human_action", "comparison", "product_inspection"} else "illustrative"
    probe = dict(shot)
    probe.update({"proofKind": kind, "mediaNeedKind": kind, "temporalAction": temporal, "evidenceMode": evidence_mode})
    temporal_evidence_mode, requires_observed_transition, state_count = infer_temporal_evidence(probe, direction)
    routes = route_order(
        kind,
        readable=readable,
        continuity=continuity,
        temporal_action=temporal,
        temporal_evidence_mode=temporal_evidence_mode,
    )
    stop_motion = stop_motion_decision(probe, direction)
    if cutout_enabled() and stop_motion.get("eligible"):
        routes = ["cutout_motion"] + [route for route in routes if route != "cutout_motion"]
    proof_text = _text(shot.get("tts"), direction.get("visual_proof"), shot.get("visualProof"))
    complex_comparison = kind == "comparison" and (
        len(re.findall(r"\b(?:versus|vs\.?|frente a)\b", proof_text)) >= 2
        or (" ni " in " %s " % proof_text and len(re.findall(r"\bcon\b", proof_text)) >= 2)
    )
    if complex_comparison:
        # The literal body/anatomy evidence is an editorial image. Remotion may
        # label it, but it must not invent anatomy from rectangles and circles.
        routes = ["image", "omni"] + [route for route in routes if route not in {"image", "omni", "ui"}]
        shot["uiTemplate"] = "body-distinction"
        shot["hybridTemplate"] = "body-distinction"
        shot["uiItems"] = ["HINCHAZÓN ≠ GRASA", "PIEL LUMINOSA ≠ MENOS GRASA"]
    controlled_comparison = kind == "comparison" and bool(
        re.search(r"\b(?:[aá]ngulo|otro [aá]ngulo|diferente [aá]ngulo)\b", proof_text)
    ) and not complex_comparison
    if controlled_comparison:
        routes = ["image_pair"] + [route for route in routes if route != "image_pair"]
    protocol_comparison_setup = kind == "comparison" and bool(
        re.search(r"\b(?:misma luz|misma distancia|misma postura)\b", proof_text)
    ) and not controlled_comparison and not complex_comparison
    if protocol_comparison_setup:
        # A physical camera/body setup cannot be represented by a wireframe.
        # Generate or retrieve the literal scene and reserve UI for callouts.
        routes = ["image", "omni"] + [route for route in routes if route not in {"image", "omni", "ui"}]
        shot["uiTemplate"] = "process-steps"
        shot["hybridTemplate"] = "process-steps"
        shot["uiVariant"] = "protocol-diagram"
        shot["uiItems"] = ["MISMA LUZ", "MISMA DISTANCIA", "MISMA POSTURA"]
    if evidence_mode in {"documentary", "data_exact"}:
        routes = [route for route in routes if route != "cutout_motion"]
    preferred = str(direction.get("route") or shot.get("route") or "").strip().lower()
    # Director preference is advisory. Exact UI data keeps deterministic UI
    # first; readable packaging is the exception because it is compiled as a
    # product image plus deterministic Remotion overlay.
    if preferred in routes and (
        not readable
        or (kind != "product_inspection" and preferred == "ui")
        or (kind == "product_inspection" and preferred in {"image", "omni"})
    ):
        routes = [preferred] + [route for route in routes if route != preferred]
    people_policy = infer_people_policy(kind, shot, direction)
    required_evidence = required_evidence_for(kind, shot, direction)
    preferred_medium = preferred_medium_for(kind, routes, direction)
    forbidden = forbidden_substitutions_for(kind, direction)
    novelty_key = str(direction.get("novelty_key") or direction.get("noveltyKey") or shot.get("noveltyKey") or "%s:%s" % (kind, re.sub(r"\W+", "-", required_evidence.lower())[:48])).strip("-:")
    beat_role = str(direction.get("beat_role") or direction.get("beatRole") or shot.get("beatRole") or ("proof" if evidence_mode in {"documentary", "data_exact", "demonstrative"} else "explanation"))
    shot.update({
        "proofKind": kind,
        "mediaNeedKind": kind,
        "beatRole": beat_role,
        "requiredEvidence": required_evidence,
        "preferredMedium": preferred_medium,
        "forbiddenSubstitutions": forbidden,
        "evidenceMode": evidence_mode,
        "requiresReadableData": readable,
        "detailSalience": "focal" if readable else "required" if kind == "product_inspection" else "incidental",
        "requiresContinuity": continuity,
        "requiresStateContinuity": continuity,
        "temporalAction": temporal,
        "temporalEvidenceMode": temporal_evidence_mode,
        "requiresObservedTransition": requires_observed_transition,
        "stateCount": state_count,
        "peoplePolicy": people_policy,
        "presenterAllowed": people_policy == "required",
        "maxFaceAreaRatio": 0.42 if people_policy == "required" else 0.20 if people_policy == "contextual" else 0.0,
        "evidenceMustRemainDominant": people_policy != "required",
        "noveltyKey": novelty_key,
        "routePlan": routes,
        "route": routes[0],
        "fallbackStrategy": "deterministic-ui" if "ui" in routes else "bounded-provider-search",
        "complexComparison": complex_comparison,
        "controlledComparison": controlled_comparison,
        "protocolComparisonSetup": protocol_comparison_setup,
    })
    if kind == "product_inspection" and readable:
        shot["route"] = routes[0]
        shot["preferredMedium"] = routes[0]
        shot["hybridTemplate"] = str(shot.get("hybridTemplate") or "product-inspection")
        shot["uiTemplate"] = str(shot.get("uiTemplate") or "product-inspection")
    literal_hybrid = (
        str(shot.get("hybridTemplate") or "") in {"anatomy-explainer", "body-distinction", "process-steps"}
        and (
            str(shot.get("uiTemplate") or "") in {"anatomy-explainer", "body-distinction"}
            or str(shot.get("uiVariant") or "") == "protocol-diagram"
            or complex_comparison
            or protocol_comparison_setup
        )
    )
    if complex_comparison or protocol_comparison_setup or literal_hybrid:
        routes = [route for route in list(shot.get("routePlan") or routes) if route not in {"ui", "motion-card"}]
        if not routes:
            routes = ["image", "omni"]
        shot["routePlan"] = routes
        shot["route"] = routes[0]
        shot["preferredMedium"] = routes[0]
        shot["fallbackStrategy"] = "bounded-provider-search"
        shot["evidenceMustRemainDominant"] = True
        forbidden_now = list(shot.get("forbiddenSubstitutions") or [])
        shot["forbiddenSubstitutions"] = list(dict.fromkeys(forbidden_now + ["ui", "motion-card", "text-only-ui", "wireframe-diagram"]))
    apply_motion_contract(shot, direction)
    return shot


def assign_evidence_beats(shots: list[dict[str, Any]]) -> None:
    counter = 0
    previous_key: tuple[str, str, bool] | None = None
    for shot in shots:
        key = (str(shot.get("chapterId") or ""), str(shot.get("proofKind") or shot.get("mediaNeedKind") or ""), bool(shot.get("requiresStateContinuity")))
        if key != previous_key or not shot.get("requiresStateContinuity"):
            counter += 1
        shot["evidenceBeatId"] = "B%03d" % counter
        if shot.get("requiresStateContinuity"):
            shot["continuityGroup"] = str(shot.get("continuityGroup") or "%s-%s" % (key[0].lower(), key[1].replace("_", "-")))
        else:
            shot["continuityGroup"] = str(shot.get("continuityGroup") or "")
        previous_key = key


def balance_graphic_routes(shots: list[dict[str, Any]], max_consecutive: int = 2) -> None:
    """Prevent card walls while respecting hard evidence constraints."""
    consecutive = 0
    graphic_routes = {"ui", "motion-card"}
    for shot in shots:
        route = str(shot.get("route") or "")
        if route not in graphic_routes:
            consecutive = 0
            continue
        consecutive += 1
        if consecutive <= max_consecutive:
            continue
        alternatives = [candidate for candidate in (shot.get("routePlan") or []) if candidate not in graphic_routes]
        if shot.get("requiresObservedTransition"):
            alternatives = [candidate for candidate in alternatives if candidate not in {"image", "image_pair"}]
        elif shot.get("temporalEvidenceMode") == "initial_final":
            alternatives = [candidate for candidate in alternatives if candidate != "image"]
        if shot.get("requiresReadableData"):
            alternatives = []
        proof_kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
        if proof_kind not in {"real_event", "third_party_commentary", "cultural_reference"}:
            alternatives = [candidate for candidate in alternatives if candidate != "clip_extractor"]
        if alternatives:
            selected = alternatives[0]
            shot["route"] = selected
            remaining = [candidate for candidate in shot.get("routePlan") or [] if candidate != selected]
            if proof_kind not in {"real_event", "third_party_commentary", "cultural_reference"}:
                remaining = [candidate for candidate in remaining if candidate != "clip_extractor"]
            shot["routePlan"] = [selected] + list(dict.fromkeys(remaining))
            shot["routingAdjustment"] = "alternate_after_%d_graphics" % max_consecutive
            consecutive = 0


def validate_media_contract(shot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    label = str(shot.get("shotId") or "shot")
    kind = str(shot.get("mediaNeedKind") or "")
    route = str(shot.get("route") or "")
    routes = list(shot.get("routePlan") or [])
    temporal = str(shot.get("temporalAction") or "")
    prompt = _text(shot.get("prompt"), shot.get("clipQuery"), shot.get("pexelsQuery"))
    if kind not in PROOF_KINDS:
        errors.append("%s proofKind invalido" % label)
    if route not in PROVIDER_ROUTES or not routes or route != routes[0] or any(item not in PROVIDER_ROUTES for item in routes):
        errors.append("%s route/routePlan invalido" % label)
    readable_product_hybrid = (
        kind == "product_inspection"
        and route in {"image", "omni"}
        and str(shot.get("hybridTemplate") or "") == "product-inspection"
    )
    if shot.get("requiresReadableData") and route != "ui" and not readable_product_hybrid:
        errors.append("%s requiere datos legibles y debe usar ui determinista" % label)
    if kind == "human_action" and "clip_extractor" in routes:
        errors.append("%s Clip Extractor no puede usarse como stock para human_action" % label)
    if kind in {"real_event", "third_party_commentary", "cultural_reference"} and routes != ["clip_extractor"]:
        errors.append("%s evidencia real no admite sustituto sintetico" % label)
    if shot.get("requiresObservedTransition") and route in {"image", "image_pair"}:
        errors.append("%s requiere observar la transicion completa y no admite still" % label)
    if shot.get("temporalEvidenceMode") == "initial_final" and route == "image":
        errors.append("%s requiere estado inicial/final y debe usar image_pair" % label)
    if shot.get("requiresReadableData") and re.search(r"\b(no text|without text|sin texto|hide all data|ocultar todos los datos)\b", prompt):
        errors.append("%s prompt contradice requiresReadableData" % label)
    if re.search(r"\b(before and after|antes y despu[eé]s)\b", prompt) and route == "image" and shot.get("temporalEvidenceMode") == "initial_final":
        errors.append("%s antes/despues requiere dos imagenes separadas" % label)
    if shot.get("requiresStateContinuity") and not str(shot.get("continuityGroup") or ""):
        errors.append("%s requiere continuityGroup" % label)
    if str(shot.get("peoplePolicy") or "") not in PEOPLE_POLICIES:
        errors.append("%s peoplePolicy invalido" % label)
    if not str(shot.get("requiredEvidence") or "").strip():
        errors.append("%s requiredEvidence vacio" % label)
    forbidden = set(shot.get("forbiddenSubstitutions") or [])
    if route in forbidden:
        errors.append("%s route %s esta prohibida por forbiddenSubstitutions" % (label, route))
    copy = str(shot.get("screenCopy") or "").strip()
    if copy and (len(copy) > 32 or len(copy.split()) > 4):
        errors.append("%s screenCopy supera 4 palabras/32 caracteres" % label)
    query_variants = shot.get("queryVariants")
    if isinstance(query_variants, dict):
        abstract_patterns = (r"combine task fragments", r"one thread", r"idea clave", r"visual support", r"generic concept")
        for provider in [item for item in routes if item in {"clip_extractor", "pexels", "image", "image_pair", "cutout_motion", "omni"}]:
            # Resolved/checkpoint plans may retain only the selected provider's
            # compiled query. Fresh plans are compiled with every route key.
            if provider not in query_variants:
                continue
            values = [str(value or "").strip() for value in (query_variants.get(provider) or [])]
            if not values or len(values) > 3:
                errors.append("%s %s requiere 1-3 consultas compiladas" % (label, provider))
                continue
            if any(not value or any(re.search(pattern, value, re.I) for pattern in abstract_patterns) for value in values):
                errors.append("%s %s contiene consulta abstracta" % (label, provider))
            if provider == "pexels" and any(len(value.split()) > 10 for value in values):
                errors.append("%s Pexels debe usar sujeto+accion+entorno conciso" % label)
            if provider == "image" and any("16:9" not in value and "landscape" not in value.lower() for value in values):
                errors.append("%s image no declara composicion 16:9" % label)
            if provider == "image_pair":
                for value in values:
                    try:
                        pair = json.loads(value)
                    except Exception:
                        pair = {}
                    if not isinstance(pair, dict) or not pair.get("left") or not pair.get("right"):
                        errors.append("%s image_pair requiere prompts left/right" % label)
            if provider == "cutout_motion" and any(not re.search(r"(?:Background|Fondo):.+(?:Props|Objetos):", value, re.I | re.S) for value in values):
                errors.append("%s Cutout requiere cues Background y Props" % label)
            if provider == "omni" and any(not all(token in value.lower() for token in ("start state", "action progression", "end state")) for value in values):
                errors.append("%s Omni no declara secuencia temporal completa" % label)
    errors.extend(validate_motion_contract(shot))
    return list(dict.fromkeys(errors))


def validate_plan_media_contract(plan: dict[str, Any]) -> list[str]:
    shots = list(plan.get("shots") or [])
    errors = [error for shot in shots for error in validate_media_contract(shot)]
    previous_index = -10
    previous_start = -100_000
    previous_intent = ""
    for index, shot in enumerate(shots):
        stop = shot.get("stopMotion") or {}
        if str(shot.get("route") or "") != "cutout_motion" and stop.get("eligible") is not True:
            continue
        label = str(shot.get("shotId") or "shot")
        intent = str(stop.get("intent") or "")
        start = int(shot.get("startMs") or 0)
        if index == previous_index + 1:
            errors.append("%s stop motion no puede repetirse en beats adyacentes" % label)
        if intent and intent == previous_intent and start - previous_start < 35_000:
            errors.append("%s repite la misma intencion stop motion antes de 35s" % label)
        previous_index, previous_start, previous_intent = index, start, intent
    return list(dict.fromkeys(errors))
