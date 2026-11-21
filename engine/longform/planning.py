"""Visual planning rules and direction, separate from stage orchestration.

Imported by longform_pipeline to preserve its public helper API. Provider calls
remain behind production_mode(); this module never starts a run at import time.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from engine.config import ROOT, production_mode
from engine.media_router import infer_media_need, route_order

def compact_pexels_query(value: str, shot: dict[str, Any] | None = None) -> str:
    """Pexels works best with broad stock concepts, not narrated sentences."""
    raw = str(value or "").strip().lower()
    if raw and len(re.findall(r"[a-z]+", raw)) <= 8:
        return raw
    context = " ".join([
        raw,
        str((shot or {}).get("visualProof") or ""),
        str((shot or {}).get("prompt") or ""),
        str((shot or {}).get("tts") or ""),
    ]).lower()
    families = [
        (("label", "etiqueta", "ingredient", "ingrediente", "envase", "package"), "body lotion label"),
        (("cream", "crema", "skincare", "retinol", "cafeína", "caffeine"), "body cream skincare"),
        (("calendar", "month", "meses", "semanas"), "calendar months passing"),
        (("photo", "foto", "camera", "cámara", "postura", "distance", "distancia"), "woman taking progress photo"),
        (("irritation", "irritación", "patch", "reacción", "reaction"), "skin patch test"),
        (("asthma", "asma", "inhaler"), "woman using inhaler"),
        (("shopping", "compra", "store", "tienda"), "woman comparing skincare products"),
        (("skin", "piel", "cellulite", "celulitis", "fat", "grasa"), "body skincare application"),
    ]
    for terms, query in families:
        if any(term in context for term in terms):
            return query
    return "skincare product routine"


def parse_json_response(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except Exception:
        match = re.search(r"\{.*\}", clean, re.S)
        if not match:
            raise RuntimeError("director visual no devolvio JSON")
        return json.loads(match.group(0))


def fallback_direction(shot: dict[str, Any]) -> dict[str, Any]:
    text = shot["tts"].lower()
    exact = any(term in text for term in ("aplica", "masaje", "etiqueta", "ingrediente", "mide", "compara", "piel", "crema"))
    mechanism = any(term in text for term in ("porque", "mecanismo", "agua", "grasa", "circulación", "temporal", "evidencia"))
    route = "pexels" if exact else ("image" if mechanism else "pexels")
    query = "woman applying body cream" if "crema" in text else "woman reading skincare label" if "etiqueta" in text else "mature woman skincare"
    words = [w.strip(".,:;!?\"") for w in shot["tts"].split() if len(w.strip(".,:;!?\"")) > 3]
    selected = []
    for word in words[:4]:
        if len(" ".join(selected + [word])) > 32:
            break
        selected.append(word)
    screen = " ".join(selected).upper() or "IDEA CLAVE"
    moving = any(term in text for term in ("aplica", "abre", "compara", "mide", "masaje", "camina", "lee", "muestra"))
    return {"shot_id": shot["shotId"], "route": route, "clip_query": "", "pexels_query": compact_pexels_query(query, shot), "query": query, "prompt": "Landscape 16:9 editorial health visual. Packaging must look commercially plausible when visible; never use blank packaging or real trademarks. " + shot["tts"], "screen_copy": screen, "subcopy": "", "visual_proof": shot["tts"][:180], "moving_visual_required": moving}


def product_context(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("product_context") or {}
    return {
        "brand": str(raw.get("fictional_brand") or "MARCA FICTICIA").strip().upper(),
        "name": str(raw.get("product_name") or "PRODUCTO").strip().upper(),
        "size": str(raw.get("product_size") or "").strip().upper(),
        "language": str(raw.get("label_language") or data.get("language") or "es").strip(),
    }


def visual_directions(data: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from providers import codex_oauth

    instructions = (pathlib.Path(ROOT) / "prompts" / "longform_visual_director.md").read_text(encoding="utf-8")
    compact = [{"shot_id": item["shotId"], "chapter": item["chapterTitle"], "start_ms": item["startMs"], "end_ms": item["endMs"], "narration": item["tts"]} for item in shots]
    user = "Title: %s\nThumbnail promise: %s\nAudience: %s\nDesign profile:\n%s\nTimed chunks:\n%s" % (data["title"], data["thumbnail_promise"], data["audience_profile"], json.dumps(data.get("_design_profile") or {}, ensure_ascii=False), json.dumps(compact, ensure_ascii=False))
    if not production_mode():
        return {shot["shotId"]: fallback_direction(shot) for shot in shots}
    try:
        text = codex_oauth.responses([{"role": "user", "content": [{"type": "input_text", "text": user}]}], instructions=instructions)
        payload = parse_json_response(text)
        rows = payload.get("shots") or []
        result = {str(row.get("shot_id")): row for row in rows if row.get("shot_id")}
    except Exception as exc:
        print("[longform] director visual LLM fallo, fallback deterministico: %s" % str(exc)[:180])
        result = {}
    for shot in shots:
        result.setdefault(shot["shotId"], fallback_direction(shot))
    return result


def concise_display_copy(value: str) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip(" .,:;!?")
    return clean if clean and len(clean) <= 32 and len(clean.split()) <= 4 else ""


def select_avatar_targets(shots: list[dict[str, Any]]) -> set[int]:
    """Pick two trust beats without displacing exact data or multi-step proof."""
    if len(shots) < 4:
        return {0, max(0, len(shots) - 1)}
    eligible = [
        index for index, shot in enumerate(shots)
        if not shot.get("requiresReadableData")
        and shot.get("temporalAction") != "multi_step"
        and shot.get("beatRole") not in {"proof", "demonstration", "comparison"}
        and shot.get("mediaNeedKind") not in {"exact_ui_state", "comparison", "measurement_protocol", "label_or_ingredient"}
    ]
    if len(eligible) < 2:
        eligible = list(range(len(shots)))
    targets = []
    for fraction, low, high in ((0.20, 0.08, 0.38), (0.68, 0.52, 0.86)):
        pool = [index for index in eligible if low <= index / max(1, len(shots) - 1) <= high and index not in targets]
        pool = pool or [index for index in eligible if index not in targets]
        targets.append(min(pool, key=lambda index: abs(index / max(1, len(shots) - 1) - fraction)))
    return set(targets)


FILMABLE_OVERRIDES = (
    (r"\b(se vea m[aá]s lisa|superficie m[aá]s lisa)\b", "woman applies body lotion to her arm during a skincare routine close up", "woman applying body lotion", "A woman visibly applies body lotion to her upper-body skin in a close skincare shot.", False),
    (r"\b(prueba una (?:pequeña|pequena) zona|patch test|revisa si aparece)\b", "how to apply a skincare patch test to the forearm", "applying cream forearm", "A small amount of skincare cream is visibly applied to one clearly defined test area on the forearm.", True),
    (r"\b(consulta a un profesional|health professional|dermatologist|dermat[oó]log)\b", "mature woman consults a health professional and listens to practical guidance", "mature woman doctor consultation", "A mature woman visibly consults a health professional and listens to practical guidance.", False),
)


def apply_purchase_evidence_routes(shots: list[dict[str, Any]], product: dict[str, str] | None = None) -> None:
    """Render purchase criteria as readable evidence instead of generic stock."""
    product = product or {"brand": "MARCA FICTICIA", "name": "PRODUCTO", "size": ""}
    for shot in shots:
        text = " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof")).lower()
        if not re.search(r"\bregla de compra\b", text, re.I):
            continue
        shot.update({
            "proofKind": "exact_ui_state",
            "mediaNeedKind": "exact_ui_state",
            "proofKindLocked": True,
            "evidenceMode": "demonstrative",
            "requiresReadableData": True,
            "requiresStateContinuity": False,
            "temporalAction": "multi_step",
            "route": "ui",
            "routePlan": ["ui"],
            "fallbackStrategy": "deterministic-ui",
            "movingVisualRequired": True,
            "visualProof": "A product label checklist visibly highlights promise, ingredients, expected time and tolerance.",
            "requiredEvidence": "A deterministic purchase checklist visibly separates promise, identifiable ingredients, realistic timing and skin tolerance without inventing a formula.",
            "screenCopy": "REGLA DE COMPRA",
            "subcopy": "PROMESA, TIEMPO Y TOLERANCIA",
            "uiTemplate": "product-label",
            "uiItems": ["PROMESA", "INGREDIENTES", "TIEMPO", "TOLERANCIA"],
            "uiValues": ["¿QUÉ CAMBIA?", "LISTA LEGIBLE", "PLAZO REALISTA", "PRUEBA EN ZONA"],
            "productBrand": product["brand"],
            "productName": product["name"],
            "productSize": product["size"],
            "filmableOverride": False,
        })
        for key in ("evidenceOverlayHeadline", "evidenceOverlayItems", "evidenceOverlayProductBrand", "evidenceOverlayProduct"):
            shot.pop(key, None)
        # This is a complete deterministic checklist, not a hybrid requiring
        # a generated package behind it. Remove stale director metadata.
        for key in ("hybridTemplate", "backgroundSource", "backgroundMediaType", "backgroundObjectPosition"):
            shot.pop(key, None)


def align_observable_evidence_contracts(shots: list[dict[str, Any]]) -> None:
    """Describe what the selected visual can truthfully demonstrate, without impossible cues."""
    for shot in shots:
        text = " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof")).lower()
        if str(shot.get("proofKind") or shot.get("mediaNeedKind") or "") in {"human_action", "physiological_mechanism"} and any(
            term in text for term in ("calor", "cosquilleo", "sudor", "warming", "tingling")
        ):
            shot.update({
                "proofKind": "physiological_mechanism",
                "mediaNeedKind": "physiological_mechanism",
                "proofKindLocked": True,
                "evidenceMode": "demonstrative",
                "requiresReadableData": False,
                "requiresStateContinuity": False,
                "temporalAction": "single",
                "temporalEvidenceMode": "implied",
                "requiresObservedTransition": False,
                "route": "ui",
                "routePlan": ["ui", "image", "omni"],
                "preferredMedium": "ui",
                "fallbackStrategy": "deterministic-ui",
                "movingVisualRequired": True,
                "visualProof": "An animated surface-versus-composition diagram separates heat, tingling or sweat from any change in body fat.",
                "requiredEvidence": "A deterministic animated diagram shows that heat, tingling and sweat are surface sensations, not proof of reduced body fat.",
                "screenCopy": "SENSACIÓN ≠ GRASA",
                "subcopy": "ACTÚA EN LA SUPERFICIE",
                "uiTemplate": "mechanism",
                "uiItems": ["CALOR", "COSQUILLEO", "SUDOR", "GRASA SIN CAMBIO"],
                "uiValues": ["SUPERFICIE", "SUPERFICIE", "SUPERFICIE", "NO DEMOSTRADO"],
                "filmableOverride": False,
            })
            shot.pop("hybridTemplate", None)


def apply_early_context_broll(data: dict[str, Any], shots: list[dict[str, Any]]) -> None:
    """Anchor an abstract opening claim with one truthful topical-cream action."""
    if len(shots) < 2 or "crema" not in str(data.get("title") or "").lower():
        return
    shot = shots[1]
    if shot.get("requiresReadableData"):
        return
    pexels_query = "woman applying body lotion leg"
    shot.update({
        "proofKind": "human_action",
        "mediaNeedKind": "human_action",
        "proofKindLocked": True,
        "evidenceMode": "illustrative",
        "requiresReadableData": False,
        "requiresStateContinuity": False,
        "temporalAction": "single",
        "route": "pexels",
        "routePlan": ["pexels", "image", "omni"],
        "fallbackStrategy": "bounded-provider-search",
        "movingVisualRequired": True,
        "visualProof": "A woman visibly applies body lotion to the skin of her leg; this illustrates topical use without implying fat loss.",
        "query": pexels_query,
        "clipQuery": "",
        "clipBaseQuery": "",
        "pexelsQuery": pexels_query,
        "pexelsBaseQuery": pexels_query,
        "hookRequirement": "Debe verse crema o locion aplicada sobre piel real. No debe implicar que la grasa desaparece y ningun envase blanco sin etiqueta puede ser el protagonista.",
        "filmableOverride": True,
    })


def apply_closing_distinction_route(shots: list[dict[str, Any]]) -> None:
    """Reset stale shopping routes when the narration needs a body-state distinction."""
    for shot in shots:
        text = str(shot.get("tts") or "").lower()
        if "ahora mira" in text or not ("disting" in text and "piel" in text and "grasa" in text):
            continue
        shot.update({
            "proofKind": "physiological_mechanism",
            "mediaNeedKind": "physiological_mechanism",
            "proofKindLocked": True,
            "evidenceMode": "demonstrative",
            "requiresReadableData": False,
            "requiresStateContinuity": True,
            "temporalAction": "multi_step",
            "route": "image",
            "routePlan": ["image", "ui", "omni"],
            "fallbackStrategy": "bounded-provider-search",
            "movingVisualRequired": True,
            "visualProof": "An animated three-part abdomen diagram clearly distinguishes skin surface, temporary bloating and deeper fat.",
            "screenCopy": "DISTINGUE ANTES DE COMPRAR",
            "subcopy": "PIEL, HINCHAZON Y GRASA",
            "uiTemplate": "anatomy-explainer",
            "hybridTemplate": "anatomy-explainer",
            "uiItems": ["PIEL", "HINCHAZON", "GRASA"],
            "uiValues": ["SUPERFICIE", "TEMPORAL", "SUBCUTANEA"],
            "hookRequirement": "Debe distinguir visualmente superficie de piel, hinchazon temporal y grasa subcutanea con un diagrama animado, sin transformaciones corporales exageradas.",
            "query": "",
            "clipQuery": "",
            "clipBaseQuery": "",
            "pexelsQuery": "",
            "pexelsBaseQuery": "",
            "prompt": "",
            "imageBasePrompt": "",
            "filmableOverride": False,
            "continuityGroup": "skin-bloating-fat-anatomy",
            "preferredMedium": "image",
            "forbiddenSubstitutions": ["generic-stock-as-proof", "text-card-as-proof"],
        })


def apply_cta_end_screen_route(data: dict[str, Any], shots: list[dict[str, Any]]) -> None:
    """Mark one spoken CTA anchor; the global end-screen owns its rendering."""
    cta = data.get("cta") or {}
    target = str(cta.get("target_video_title") or "").strip()
    if cta and cta.get("verified") is not True:
        raise RuntimeError("CTA no verificado: no se puede fabricar una recomendacion de pantalla final")
    anchor_set = False
    for shot in shots:
        was_embedded_cta = bool(shot.pop("verifiedCtaEndScreen", None)) or str(shot.get("uiTemplate") or "") == "verified-next-video"
        shot.pop("ctaAnchor", None)
        if was_embedded_cta:
            for key in ("uiTemplate", "uiVariant", "uiItems", "uiValues", "uiSpec", "proofKindLocked"):
                shot.pop(key, None)
            inferred = infer_media_need(shot, {"visual_proof": shot.get("visualProof") or shot.get("tts")})
            if inferred == "exact_ui_state":
                inferred = "abstract_concept"
            routes = route_order(
                inferred,
                readable=False,
                continuity=bool(shot.get("requiresStateContinuity")),
                temporal_action=str(shot.get("temporalAction") or "single"),
            )
            shot.update({
                "proofKind": inferred,
                "mediaNeedKind": inferred,
                "route": routes[0],
                "routePlan": routes,
                "preferredMedium": routes[0],
                "requiresReadableData": False,
                "screenCopy": concise_display_copy(shot.get("tts") or target or "SIGUIENTE VIDEO"),
            })
        text = str(shot.get("tts") or "")
        if not anchor_set and ("ahora mira" in text.lower() or (target and target.lower() in text.lower())):
            shot["ctaAnchor"] = True
            anchor_set = True


def apply_filmable_overrides(shots: list[dict[str, Any]], product: dict[str, str] | None = None) -> None:
    """Prefer observable human action when it truthfully supports the narration."""
    product = product or {"brand": "MARCA FICTICIA", "name": "PRODUCTO", "size": ""}
    for shot in shots:
        if shot.get("proofKindLocked"):
            continue
        text = " ".join(str(shot.get(key) or "") for key in ("tts", "visualProof")).lower()
        for pattern, clip_query, pexels_query, visual_proof, movement_required in FILMABLE_OVERRIDES:
            if not re.search(pattern, text, re.I):
                continue
            shot.update({
                "proofKind": "human_action",
                "mediaNeedKind": "human_action",
                "proofKindLocked": True,
                "evidenceMode": "demonstrative" if movement_required else "illustrative",
                "requiresReadableData": False,
                "requiresStateContinuity": movement_required,
                "temporalAction": "single",
                "route": "pexels",
                "routePlan": ["pexels", "omni", "ui"] if movement_required else ["pexels", "image", "omni"],
                "fallbackStrategy": "deterministic-ui" if movement_required else "bounded-provider-search",
                "movingVisualRequired": movement_required,
                "visualProof": visual_proof,
                "requiredEvidence": visual_proof,
                "query": pexels_query,
                "clipQuery": "",
                "clipBaseQuery": "",
                "pexelsQuery": pexels_query,
                "pexelsBaseQuery": pexels_query,
                "filmableOverride": True,
            })
            stale_hook = str(shot.get("hookRequirement") or "")
            if product["brand"] in stale_hook or "etiqueta comercial ficticia" in stale_hook.lower() or re.search(r"\b(etiqueta|envase|packaging|marca)\b", stale_hook, re.I):
                shot["hookRequirement"] = "Debe verse una accion humana real con un producto de cuidado personal reconocible. La etiqueta no necesita ser legible en este plano ilustrativo, pero no puede haber watermarks, logos de stock ni un envase blanco usado como producto protagonista."
            if re.search(r"\b(consulta a un profesional|health professional|dermatologist|dermat[oó]log)\b", text, re.I):
                shot["hookRequirement"] = "Debe verse una mujer adulta en una consulta activa con un profesional de salud. El producto no necesita aparecer; rechaza planos de un profesional solo, una sala vacia o una conversacion no medica."
                shot["screenCopy"] = "CONSULTA A UN PROFESIONAL"
                shot["subcopy"] = "SI TIENES DUDAS"
                shot["headlinePosition"] = "bottom-left"
            if re.search(r"\b(regla de compra|antes de elegir)\b", text, re.I):
                shot["evidenceOverlayHeadline"] = "REGLA DE COMPRA"
                shot["evidenceOverlayItems"] = ["PROMESA", "INGREDIENTES", "TIEMPO", "TOLERANCIA"]
                shot["evidenceOverlayProductBrand"] = product["brand"]
                shot["evidenceOverlayProduct"] = product["name"]
            if movement_required:
                shot.update({
                    "continuityGroup": str(shot.get("continuityGroup") or "patch-test-protocol"),
                    "uiTemplate": "procedure",
                    "uiItems": ["APLICA POCO", "ESPERA", "REVISA"],
                    "uiValues": ["ZONA PEQUEÑA", "SIN INSISTIR", "TOLERANCIA"],
                })
            break
