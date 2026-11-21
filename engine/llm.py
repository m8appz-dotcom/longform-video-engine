#!/usr/bin/env python3
"""LLM del Reel Engine.

MockLLM (guion fijo), CodexOAuthLLM, OpenAI o endpoints OpenAI-compatible
como vLLM/LiteLLM. Los secretos se leen solo desde entorno.
"""
import os, json, re, unicodedata, urllib.request, urllib.error
from providers import codex_oauth

class MockLLM:
    mode = "mock"
    def script(self, topic, language="es"):
        return None  # el engine usa su HOOK/BODY fijos

DEFAULT_SCRIPT_WORDS = "120 a 155"
DEFAULT_SCRIPT_DURATION = "45 a 60 segundos"

ANGLE_SCORE_FIELDS = ("tension", "novedad", "proof", "visualidad", "especificidad", "utilidad", "riesgo")
DISSONANCE_ANGLE_TYPES = ("contraintuitivo", "mito_incompleto", "mecanismo_oculto")
CASE_HOOK_TERMS = (
    "directo", "cuando", "si ",
    " por que ", "por qué", "error de", " vs ", "versus", "truco", "detalle",
)
BELIEF_RE = r"\b(todo el mundo|te dicen|siempre te han dicho|la recomendacion|los expertos|se supone|la logica|la mayoria|mucha gente|nos ensenan|lo normal|el consejo)\b"
REFUTE_RE = r"\b(pero|sin embargo|eso es cierto|falta|el dato|lo que casi nadie|la variable|el detalle|el problema|no basta|incomplet|fracasa|cambia la ecuacion)\b"
CTA_RE = r"\b(prueba|sirve|comenta|guarda|haz|mira|cambia|empieza|usa|elige|separa|cierra|mide|manda|escribe|revisa|quita|pon|baja|sube|reduce|observa|anota|compara|evalua|descansa|ajusta|sigue|compart|lee)\b"
BELIEF_REASON_RE = r"\b(porque|por que|ya que|tiene|tienen|ayuda|recomiendan|sirve|funciona|beneficio|bueno|mejor|logico|parece|energia)\b"
OVERCLAIM_RE = r"\b(cura|curar|garantiza|garantizado|100%|sin esfuerzo|sin excepcion|milagro|milagros|instant[aá]neo|nunca falla|siempre funciona)\b"
BANNED_INTRO_RE = r"\b(hoy te voy|hoy vamos|sabias que|sab[ií]as que|muchas personas|en este video|te explico|vamos a hablar)\b"
MODERN_PEAK_RE = r"\b(pero|detalle|raro|cambia|cambio|contrario|contraste|golpe|pico|problema|no es|no fue|no siempre|nadie|nunca|error|riesgo|trampa|consecuencia|advertencia|ah[ií]|en realidad|lo que casi nadie|ese segundo dato|lo importante)\b"
RELEASE_RE = r"\b(porque|parece|todo el mundo|la gente|lo normal|se supone|tiene sentido|creen|crees|la recomendacion|el consejo|contexto|eso explica)\b"
WEIRD_ABSTRACT_RE = r"\b(la|el|tu|tus|mi|mis)\s+(regla|guerra|cuerpo|algoritmo|cerebro|mente|sistema|proceso)\s+(obedece|entiende|sabe|quiere|decide|recuerda|premia|castiga)\b"
GENERIC_SCRIPT_RE = r"\bZZZ_DOMAIN_MOLD_DISABLED_ZZZ\b"
# v2: incluye el vocabulario causal ORAL (porque, funciona, hace que...) --
# antes solo contaban sustantivos analiticos (criterio, variable, comparacion),
# asi que el guion abstracto cosechaba 'mecanismo' y el guion hablado de accion
# quedaba penalizado por explicar la causa con palabras simples.
MECHANISM_RE = r"\b(señal|senal|cerebro|conducta|contexto|respuesta|mecanismo|detalle|variable|observacion|evidencia|prueba|patron|decisi[oó]n|comparaci[oó]n|criterio|consecuencia|porque|funciona|hace que|provoca|efecto|causa|sistema|proceso|flujo|automatiza|plantilla|metodo|método|paso|estructura|algoritmo|embudo|formula|fórmula)\b"
# VISUALIZABLE_RE (ES) traia solo vocabulario de la genesis skincare del motor
# (frota/masajea/frasco/envase/etiqueta/piel): un guion de otro dominio
# (tech/negocios/digital) no lo cumplia por tema, no por ser poco visual. Se
# agregan verbos/objetos digitales igual de mostrables en camara (escribe,
# toca, desliza, telefono, pantalla de chat...) sin quitar los de skincare
# (retrocompat con guiones ya tuneados contra esta lista).
VISUALIZABLE_RE = r"\b(objeto|producto|pantalla|clip|imagen|mano|mesa|escena|cara|persona|documento|lista|filtro|curva|mapa|grafico|antes|despues|se ve|mira|aplica|frota|masajea|masaje|gira|sostiene|abre|corta|vierte|senala|señala|gesto|frasco|envase|etiqueta|piel|telefono|teléfono|laptop|computadora|aplicacion|aplicación|chat|mensaje|escribe|teclea|toca|desliza|publica|sube|construye|crea|graba)\b"
OVERCLAIM_RE_ES = OVERCLAIM_RE
CTA_RE_ES = CTA_RE
BANNED_INTRO_RE_ES = BANNED_INTRO_RE
MODERN_PEAK_RE_ES = MODERN_PEAK_RE
RELEASE_RE_ES = RELEASE_RE
WEIRD_ABSTRACT_RE_ES = WEIRD_ABSTRACT_RE
MECHANISM_RE_ES = MECHANISM_RE
VISUALIZABLE_RE_ES = VISUALIZABLE_RE

# ---------------------------------------------------------------------------
# Variantes EN: mismo rol semantico que las de arriba, portadas al ingles.
# Todo el motor de audicion/validacion de guion (BANNED_INTRO, MODERN_PEAK,
# RELEASE, WEIRD_ABSTRACT, MECHANISM, VISUALIZABLE, OVERCLAIM, CTA) es
# language-specific por regex de palabra: sin esta capa, un guion en ingles
# pasaria por estos checks matcheando CERO (no por ser bueno, sino porque las
# palabras clave son espanolas), inflando o hundiendo el score sin relacion
# con la calidad real. _lang_patterns(language) resuelve el set correcto.
# ---------------------------------------------------------------------------
BANNED_INTRO_RE_EN = r"\b(today i'?m going to|today we'?re going to|did you know|a lot of people|in this video|let me explain|we'?re going to talk about)\b"
# Amplio a proposito (parida con la cobertura de MODERN_PEAK_RE en espanol,
# ~19 marcadores): un primer intento con solo 8 palabras clave le hizo fallar
# GENUINAMENTE buenos guiones en ingles ('the trap', 'the gap', 'the
# difference' son giros reales que la version angosta no reconocia) -- 2
# writers agotaron sus 4 reintentos cada uno en la corrida real de prueba.
MODERN_PEAK_RE_EN = r"\b(but|detail|weird|changes|change|contrary|contrast|twist|turn|peak|problem|isn'?t|aren'?t|don'?t|doesn'?t|wasn'?t|not always|nobody|never|mistake|error|risk|trap|catch|trick|gap|shift|flip|difference|instead|turns out|in fact|reality is|consequence|warning|actually|in reality|what almost nobody|that second|the important part|the thing is|the real reason|the real issue)\b"
RELEASE_RE_EN = r"\b(because|seems|everyone|people|the norm|supposedly|makes sense|believe|think|the advice|the recommendation|context|that explains)\b"
WEIRD_ABSTRACT_RE_EN = r"\b(the|your|my)\s+(rule|war|body|algorithm|brain|mind|system|process)\s+(obeys|understands|knows|wants|decides|remembers|rewards|punishes)\b"
MECHANISM_RE_EN = r"\b(signal|brain|behavior|context|response|mechanism|detail|variable|observation|evidence|proof|pattern|decision|comparison|criteria|criterion|consequence|because|works|makes it|causes|effect|cause|system|process|workflow|automate|automation|pipeline|template|method|step|framework|structure|algorithm|funnel|formula)\b"
# VISUALIZABLE_RE_EN: mismo fix que la version ES -- se agregan objetos/verbos
# digitales genericos (telefono, app, escribe, toca, desliza...) igual de
# mostrables en camara que los fisicos, sin quitar los de skincare heredados.
VISUALIZABLE_RE_EN = r"\b(object|product|screen|clip|image|hand|table|scene|face|person|document|list|filter|curve|map|chart|before|after|you see|look|apply|rub|massage|spin|turn|holds|opens|cuts|pours|points|gesture|jar|bottle|label|skin|phone|laptop|computer|app|chat|message|type|typing|tap|swipe|post|upload|build|create|record|keyboard|click)\b"
OVERCLAIM_RE_EN = r"\b(cure|cures|guarantee|guaranteed|100%|effortless|no exceptions|miracle|miracles|instant|instantly|never fails|always works)\b"
CTA_RE_EN = r"\b(save|comment|share|try|use|watch|change|start|choose|follow|close|measure|drop|write|check|remove|set|lower|raise|reduce|observe|note|compare|evaluate|rest|adjust|keep|read|tag|swipe|tap|grab)\b"


def _lang_patterns(language):
    """Resuelve el set de regex language-specific para el guion. 'es' (default)
    devuelve las constantes historicas sin cambiar de nombre (compat)."""
    lang = (language or "es").strip().lower()
    if lang == "en":
        return {
            "BANNED_INTRO_RE": BANNED_INTRO_RE_EN, "MODERN_PEAK_RE": MODERN_PEAK_RE_EN,
            "RELEASE_RE": RELEASE_RE_EN, "WEIRD_ABSTRACT_RE": WEIRD_ABSTRACT_RE_EN,
            "MECHANISM_RE": MECHANISM_RE_EN, "VISUALIZABLE_RE": VISUALIZABLE_RE_EN,
            "OVERCLAIM_RE": OVERCLAIM_RE_EN, "CTA_RE": CTA_RE_EN,
        }
    return {
        "BANNED_INTRO_RE": BANNED_INTRO_RE_ES, "MODERN_PEAK_RE": MODERN_PEAK_RE_ES,
        "RELEASE_RE": RELEASE_RE_ES, "WEIRD_ABSTRACT_RE": WEIRD_ABSTRACT_RE_ES,
        "MECHANISM_RE": MECHANISM_RE_ES, "VISUALIZABLE_RE": VISUALIZABLE_RE_ES,
        "OVERCLAIM_RE": OVERCLAIM_RE_ES, "CTA_RE": CTA_RE_ES,
    }

class ScriptFormatError(RuntimeError):
    def __init__(self, provider_name, issues):
        self.issues = issues
        super().__init__("guion no cumple la estructura narrativa %s: %s" % (provider_name, "; ".join(issues)))

def _norm(text):
    text = str(text or "")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return text.lower()

def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if s.strip()]

def _angle_prompt(topic):
    sys_p = (
        "Eres estratega editorial de reels verticales en espanol neutro natural. "
        "Antes de escribir guion, debes escoger el mejor angulo para el Modelo de Disonancia Cognitiva. "
        "Genera 4 a 6 angulos candidatos y rankealos con una matriz. "
        "Usa strings cortos; cada campo textual debe ser una frase breve. "
        "Cada candidato debe tener angle_type, angle_sentence, hook_claim, common_belief, ignored_variable, specific_case y cta_action. "
        "hook_claim es la ruptura inmediata: una afirmacion directa, contraintuitiva y amplia. No debe incluir el caso especifico, ni 'directo del paquete', ni 'si/cuando', ni 'por que'. "
        "hook_claim tampoco debe prometer causalidad falsa o exagerada (curas, garantias absolutas, resultados milagrosos); usa formulaciones fuertes pero sostenibles como 'te frena', 'no siempre funciona' o 'no es lo que crees'. "
        "common_belief es el consenso que la gente ya cree y por que parece logico. "
        "ignored_variable es la informacion poco discutida que complementa o refuta esa creencia. "
        "specific_case es donde se aterriza el problema despues del giro, no en el hook. "
        "cta_action es una accion concreta y corta que el espectador puede hacer. "
        "Tipos sugeridos: contraintuitivo, mito_incompleto, mecanismo_oculto, error_comun, prueba_practica, riesgo_evitable, objecion. "
        "Puntua cada criterio de 1 a 5: "
        "tension = contradice o complica algo que la audiencia ya cree; "
        "novedad = no es el consejo tipico; "
        "proof = se puede explicar con observacion simple, no con humo; "
        "visualidad = se puede mostrar en video en 1 a 3 segundos; "
        "especificidad = aplica a una conducta concreta; "
        "utilidad = termina en una accion que la persona puede probar; "
        "riesgo = 5 significa bajo riesgo/no promete algo falso medico o exagerado, 1 significa alto riesgo. "
        "No selecciones un angulo con riesgo menor a 4 o proof menor a 3 aunque tenga tension alta. "
        "Para este formato, tension y novedad pesan mas que especificidad en el hook; la especificidad debe vivir en specific_case. "
        "El ganador debe maximizar tension + novedad + proof + visualidad + especificidad + utilidad + riesgo sin sacrificar hook_claim amplio. "
        "Devuelve SOLO JSON valido con esta forma exacta: "
        "{\"candidates\":[{\"angle_type\":\"...\",\"angle_sentence\":\"...\",\"hook_claim\":\"...\",\"common_belief\":\"...\",\"ignored_variable\":\"...\",\"specific_case\":\"...\",\"cta_action\":\"...\",\"tension\":1,\"novedad\":1,\"proof\":1,\"visualidad\":1,\"especificidad\":1,\"utilidad\":1,\"riesgo\":1,\"score\":7,\"reason\":\"...\"}],"
        "\"selected\":{\"angle_type\":\"...\",\"angle_sentence\":\"...\",\"score\":7,\"why\":\"...\"}}"
    )
    usr_p = "Tema del reel: %s" % topic
    return sys_p, usr_p

def _score_value(v):
    try:
        n = int(v)
    except Exception:
        return 1
    return max(1, min(5, n))

def _normalize_angle_candidate(c):
    out = {
        "angle_type": str(c.get("angle_type") or c.get("type") or "otro").strip()[:40],
        "angle_sentence": str(c.get("angle_sentence") or c.get("sentence") or "").strip(),
        "hook_claim": str(c.get("hook_claim") or c.get("hook") or "").strip(),
        "common_belief": str(c.get("common_belief") or c.get("belief") or "").strip(),
        "ignored_variable": str(c.get("ignored_variable") or c.get("hidden_variable") or c.get("variable") or "").strip(),
        "specific_case": str(c.get("specific_case") or c.get("case") or "").strip(),
        "cta_action": str(c.get("cta_action") or c.get("cta") or "").strip(),
        "reason": str(c.get("reason") or c.get("why") or "").strip()[:240],
    }
    for field in ANGLE_SCORE_FIELDS:
        out[field] = _score_value(c.get(field))
    out["score"] = sum(out[field] for field in ANGLE_SCORE_FIELDS)
    if c.get("score") is not None:
        try:
            out["model_score"] = int(c.get("score"))
        except Exception:
            pass
    return out

def _hook_claim_is_broad(text):
    n = " " + _norm(text) + " "
    if not str(text or "").strip():
        return False
    if len(re.findall(r"\w+", n)) > 8:
        return False
    if re.search(OVERCLAIM_RE, n):
        return False
    return not any(term in n for term in CASE_HOOK_TERMS)

def _dissonance_rank(c):
    type_bonus = 0
    if c["angle_type"] == "contraintuitivo":
        type_bonus = 10
    elif c["angle_type"] in DISSONANCE_ANGLE_TYPES:
        type_bonus = 6
    elif c["angle_type"] == "error_comun":
        type_bonus = -4
    hook_bonus = 7 if _hook_claim_is_broad(c.get("hook_claim")) else -8
    return (
        c["tension"] * 2.3
        + c["novedad"] * 2.0
        + c["proof"] * 1.4
        + c["visualidad"] * 1.1
        + c["especificidad"] * 0.7
        + c["utilidad"] * 1.1
        + c["riesgo"] * 1.4
        + type_bonus
        + hook_bonus
    )

def _validate_angle_payload(d, provider_name):
    candidates = d.get("candidates") or d.get("angles") or []
    if not isinstance(candidates, list):
        candidates = []
    normalized = []
    for c in candidates[:6]:
        if not isinstance(c, dict):
            continue
        item = _normalize_angle_candidate(c)
        if item["angle_sentence"]:
            normalized.append(item)
    if len(normalized) < 4:
        raise RuntimeError("%s no genero 4 angulos validos: %s" % (provider_name, d))

    selected_raw = d.get("selected") or {}
    selected_sentence = ""
    selected_type = ""
    if isinstance(selected_raw, dict):
        selected_sentence = str(selected_raw.get("angle_sentence") or selected_raw.get("sentence") or "").strip()
        selected_type = str(selected_raw.get("angle_type") or selected_raw.get("type") or "").strip()
    elif isinstance(selected_raw, str):
        selected_sentence = selected_raw.strip()

    safe_candidates = [c for c in normalized if c["riesgo"] >= 4 and c["proof"] >= 3]
    ranked = sorted(safe_candidates or normalized, key=_dissonance_rank, reverse=True)
    selected = ranked[0]
    for c in normalized:
        same_sentence = selected_sentence and c["angle_sentence"].lower() == selected_sentence.lower()
        same_type = selected_type and c["angle_type"].lower() == selected_type.lower()
        if same_sentence or (same_type and selected_sentence.lower() in c["angle_sentence"].lower()):
            if c["riesgo"] >= 4 and c["proof"] >= 3 and _dissonance_rank(c) >= _dissonance_rank(selected):
                selected = c
            break
    return {"candidates": normalized, "selected": selected}

def _use_legacy_angle_selection():
    return os.environ.get("LLM_USE_ANGLE_SELECTION", "0").lower() in ("1", "true", "yes", "on")

class CodexOAuthLLM:
    mode = "real"
    def __init__(self):
        self.last_angle_report = None

    def _json_response(self, sys_p, usr_p, label):
        msg = [{"role": "user", "content": [{"type": "input_text", "text": usr_p}]}]
        out = codex_oauth.responses(msg, instructions=sys_p)
        return _json_from_text(out, label)

    def script(self, topic, language="es"):
        n = os.environ.get("SCRIPT_WORDS", DEFAULT_SCRIPT_WORDS)
        self.last_angle_report = None
        if _use_legacy_angle_selection():
            angle_sys, angle_usr = _angle_prompt(topic)
            last_angle_error = None
            for _ in range(int(os.environ.get("LLM_ANGLE_RETRIES", "3"))):
                try:
                    angle_payload = self._json_response(angle_sys, angle_usr, "codex-angle")
                    self.last_angle_report = _validate_angle_payload(angle_payload, "codex-angle")
                    break
                except Exception as e:
                    last_angle_error = e
            else:
                raise last_angle_error
        feedback = None
        last_error = None
        for _ in range(int(os.environ.get("LLM_SCRIPT_RETRIES", "4"))):
            sys_p, usr_p = _script_prompt(topic, n, None, feedback, language=language)
            d = self._json_response(sys_p, usr_p, "codex-script")
            try:
                return _validate_script_payload(d, "codex", language=language)
            except ScriptFormatError as e:
                feedback = e.issues
                last_error = e
        raise last_error

def _angle_context(angle_report):
    if not angle_report:
        return ""
    selected = angle_report.get("selected") or {}
    return (
        "Angulo seleccionado obligatorio: angle_type=%s; angle_sentence=%s. "
        "hook_claim obligatorio=%s. common_belief=%s. ignored_variable=%s. specific_case=%s. cta_action=%s. "
        "El hook debe salir de hook_claim, no del caso especifico. "
        "El caso especifico debe entrar despues del consenso y del dato ignorado. "
        "No cambies de angulo salvo que detectes un riesgo medico/factual claro. "
        % (
            selected.get("angle_type", "otro"),
            selected.get("angle_sentence", ""),
            selected.get("hook_claim") or selected.get("angle_sentence", ""),
            selected.get("common_belief", ""),
            selected.get("ignored_variable", ""),
            selected.get("specific_case", ""),
            selected.get("cta_action", ""),
        )
    )

def _render_template(template, values):
    out = str(template or "")
    for key, value in values.items():
        out = out.replace("{{%s}}" % key, str(value))
    return out


def _parse_hook_guion(text):
    """Acepta el formato HOOK:/GUION: como alternativa al JSON."""
    cleaned = str(text or "").strip()
    m = re.search(r"HOOK\s*:\s*(.*?)\s+GUION\s*:\s*(.*)", cleaned, re.I | re.S)
    if not m:
        return None
    hook = m.group(1).strip().strip("[]")
    body = m.group(2).strip().strip("[]")
    if not hook or not body:
        return None
    return {"hook": hook, "body": body}


_LANG_DEFAULTS = {
    "es": {
        "audience": "audiencia de Reels", "objective": "retener y explicar una idea clara",
        "duration": DEFAULT_SCRIPT_DURATION, "cta": "guardar, comentar o seguir segun el tema",
        "feedback_prefix": "Corrige estos problemas del intento anterior: %s.",
        "topic_label": "Tema del reel: %s",
    },
    "en": {
        "audience": "Reels audience", "objective": "retain attention and explain one clear idea",
        "duration": "45 to 60 seconds", "cta": "save, comment, or follow depending on the topic",
        "feedback_prefix": "Fix these problems from the previous attempt: %s.",
        "topic_label": "Reel topic: %s",
    },
}


def _script_prompt(topic, words_hint, angle_report=None, feedback=None, structure="arc", language="es"):
    """Prompt de guion desde prompts/ — la UNICA fuente. structure: arc|case|countdown.
    language: 'es' (default, prompts/*.md sin sufijo) | 'en' (prompts/*_en.md)."""
    from engine.config import prompt_text
    lang = (language or "es").strip().lower()
    L = _LANG_DEFAULTS.get(lang, _LANG_DEFAULTS["es"])
    feedback_text = (L["feedback_prefix"] % "; ".join(feedback)) if feedback else ""
    if structure not in ("arc", "case", "countdown"):
        structure = "arc"
    sys_p = _render_template(prompt_text("script", lang), {
        "TOPIC": topic,
        "AUDIENCE": os.environ.get("SCRIPT_AUDIENCE", L["audience"]),
        "OBJECTIVE": os.environ.get("SCRIPT_OBJECTIVE", L["objective"]),
        "DURATION_SECONDS": os.environ.get("SCRIPT_DURATION_SECONDS", L["duration"]),
        "CTA": os.environ.get("SCRIPT_CTA", L["cta"]),
        "SCRIPT_WORDS": words_hint,
        "STRUCTURE_BLOCK": prompt_text("structure_%s" % structure, lang).strip(),
    })
    if feedback_text:
        sys_p = sys_p.rstrip() + "\n\n" + feedback_text
    return sys_p, L["topic_label"] % topic

def _json_from_text(text, provider_name):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    hook_guion = _parse_hook_guion(cleaned)
    if hook_guion:
        return hook_guion
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    m = re.search(r"\{.*\}", cleaned, re.S)
    if not m:
        raise RuntimeError("%s no devolvio JSON utilizable: %s" % (provider_name, cleaned[:240]))
    try:
        return json.loads(m.group(0))
    except Exception as e:
        raise RuntimeError("%s devolvio JSON invalido: %s | %s" % (provider_name, e, cleaned[:300]))

def _modern_story_format_issues(hook, body, language="es"):
    P = _lang_patterns(language)
    en = (language or "es").strip().lower() == "en"
    issues = []
    hook_n = " " + _norm(hook) + " "
    hook_words = re.findall(r"\w+", hook_n)
    body_words = re.findall(r"\w+", _norm(body))
    # default 85 (antes 105): alineado con el piso 1.8 w/s de script_audit (v2).
    min_words = int(os.environ.get("SCRIPT_MIN_WORDS", "85"))
    max_words = int(os.environ.get("SCRIPT_MAX_WORDS", "175"))
    if len(hook_words) > 12:
        issues.append("hook must be a short sentence" if en else "hook debe ser una frase corta")
    if not hook.strip():
        issues.append("empty hook" if en else "hook vacio")
    if len(body_words) < min_words:
        issues.append(("script too short for 45-60s: %d words, minimum %d" if en else
                        "guion demasiado corto para 45-60s: %d palabras, minimo %d") % (len(body_words), min_words))
    if len(body_words) > max_words:
        issues.append(("script too long for 45-60s: %d words, maximum %d" if en else
                        "guion demasiado largo para 45-60s: %d palabras, maximo %d") % (len(body_words), max_words))
    body_sentences = _sentences(body)
    if len(body_sentences) < 7:
        issues.append("body needs enough sentences for hook, peak, release, mini-peaks and CTA" if en else
                       "body debe tener suficientes frases para hook, pico, release, mini-picos y CTA")
        return issues

    body_n = _norm(body)
    first_sentence = _norm(body_sentences[0])
    first_two = _norm(" ".join(body_sentences[:2]))
    if re.search(P["BANNED_INTRO_RE"], first_sentence):
        issues.append("slow/introductory opening; start in tension" if en else "arranque lento o introductorio; empieza en tension")
    stop_es = {"te", "da", "dan", "mas", "más", "no", "el", "la", "los", "las", "un", "una", "de", "del", "al"}
    stop_en = {"the", "a", "an", "to", "you", "your", "is", "it", "of", "and", "not", "no"}
    hook_core = set(re.findall(r"\w+", hook_n)) - (stop_en if en else stop_es)
    body_start_words = set(re.findall(r"\w+", first_sentence))
    if hook_core and len(hook_core & body_start_words) < max(1, min(2, len(hook_core))):
        issues.append("the script must open with the same idea as the hook" if en else
                       "el guion debe empezar con la misma idea del hook")
    if not re.search(P["MODERN_PEAK_RE"], first_two):
        issues.append("missing a first peak or contrast in the opening seconds" if en else
                       "falta primer pico o contraste en los primeros segundos")
    if not re.search(P["RELEASE_RE"], _norm(" ".join(body_sentences[1:6]))):
        issues.append("missing a release with minimal context after the first peak" if en else
                       "falta release con contexto minimo despues del primer pico")
    peak_markers = len(re.findall(P["MODERN_PEAK_RE"], body_n))
    if len(re.findall(r"\w+", body_n)) >= 95 and peak_markers < 3:
        issues.append("missing mini-peaks; must re-hook every 10-15 seconds" if en else
                       "faltan mini-picos; debe reenganchar cada 10-15 segundos")
    if re.search(P["OVERCLAIM_RE"], _norm(hook + " " + body)):
        issues.append("claim too technical or absolute; use an observable variable and plain language" if en else
                       "claim demasiado tecnico o absoluto; usa variable observable y lenguaje facil")

    last_two = _norm(" ".join(body_sentences[-2:]))
    if not re.search(P["CTA_RE"], last_two):
        issues.append("missing a direct CTA at the end" if en else "falta CTA directo al final")
    metadata_re = r"\b(save-worthy line|line to remember|line to share)\b" if en else r"\b(frase guardable|frase para recordar|frase para compartir)\b"
    if re.search(metadata_re, body_n):
        issues.append("closing sounds like metadata, not spoken voice" if en else "cierre suena a metadata, no a voz hablada")
    return issues

def _validate_script_payload(d, provider_name, enforce_modern_arc=True, language="es"):
    hook = (d.get("hook") or "").strip()
    txt = (d.get("body") or "").strip()
    words = [w for w in re.split(r"\s+", txt) if w]
    if not hook or len(words) < 12:
        raise RuntimeError("guion incompleto del LLM %s: %s" % (provider_name, d))
    if enforce_modern_arc:
        issues = _modern_story_format_issues(hook, txt, language)
        if issues:
            raise ScriptFormatError(provider_name, issues)
    return hook, words

def _word_count(text):
    return len(re.findall(r"\w+", _norm(text)))

def score_script_candidate(hook, body, language="es"):
    """Director-style blind rubric. It scores the script text, not the model."""
    P = _lang_patterns(language)
    en = (language or "es").strip().lower() == "en"
    hook = str(hook or "").strip()
    body = str(body or "").strip()
    text = "%s\n%s" % (hook, body)
    text_n = _norm(text)
    sentences = _sentences(body)
    issues = _modern_story_format_issues(hook, body, language)
    hard_rejects = []
    if not hook or not body:
        hard_rejects.append("empty hook/body" if en else "hook/body vacio")
    if re.search(P["BANNED_INTRO_RE"], _norm(sentences[0] if sentences else "")):
        hard_rejects.append("opens with preamble" if en else "arranque con preambulo")
    if re.search(P["WEIRD_ABSTRACT_RE"], text_n):
        hard_rejects.append("odd personification/idiom" if en else "modismo/personificacion rara")
    explain_re = r"\b(because|so that|means)\b" if en else r"\b(porque|para que|significa|quiere decir)\b"
    if _word_count(hook) > 12 or re.search(explain_re, _norm(hook)):
        hard_rejects.append("hook explains too soon" if en else "hook explica demasiado pronto")
    if len(sentences) < 6:
        hard_rejects.append("script lacks enough arc" if en else "guion sin arco suficiente")
    if re.search(P["OVERCLAIM_RE"], text_n):
        hard_rejects.append("exaggerated medical/physiological claim" if en else "claim medico/fisiologico exagerado")

    wc = _word_count(body)
    peak_count = len(re.findall(P["MODERN_PEAK_RE"], text_n))
    release_count = len(re.findall(P["RELEASE_RE"], text_n))
    mechanism_count = len(re.findall(P["MECHANISM_RE"], text_n))
    visual_count = len(re.findall(P["VISUALIZABLE_RE"], text_n))
    generic_hits = len(re.findall(GENERIC_SCRIPT_RE, text_n))
    repeated_sentence_roots = 0
    seen = set()
    for sentence in sentences:
        words = [w for w in re.findall(r"\w+", _norm(sentence)) if len(w) > 4]
        root = " ".join(words[:4])
        if root and root in seen:
            repeated_sentence_roots += 1
        if root:
            seen.add(root)

    score = 100
    score -= len(issues) * 8
    score -= len(hard_rejects) * 18
    # piso 85 (antes 105): alineado con el piso 1.8 w/s de script_audit -- el
    # guion media-led deja respirar la accion sin voz encima (mandato v2).
    if wc < 85:
        score -= min(22, (85 - wc) // 3)
    if wc > 175:
        score -= min(22, (wc - 175) // 3)
    if peak_count < 3:
        score -= (3 - peak_count) * 9
    if release_count < 2:
        score -= (2 - release_count) * 7
    if mechanism_count < 2:
        score -= (2 - mechanism_count) * 10
    # v2: filmabilidad pesa igual que mecanismo (antes -6 vs -10: la audicion
    # ciega premiaba al retorico y el ganador solo cabia en plates).
    if visual_count < 3:
        score -= (3 - visual_count) * 10
    if generic_hits >= 3:
        score -= 12
        hard_rejects.append("relies on a repeated generic mold" if en else "depende de un molde generico repetido")
    score -= repeated_sentence_roots * 7
    score = max(0, min(100, int(score)))

    hook_explains_early = ("hook explains too soon" if en else "hook explica demasiado pronto") in hard_rejects
    dimensions = {
        "hook_tension": max(0, min(10, 10 - (4 if hook_explains_early else 0) - (3 if _word_count(hook) > 9 else 0))),
        "primer_pico": max(0, min(10, 4 + min(6, peak_count * 2))),
        "release": max(0, min(10, 3 + min(7, release_count * 3))),
        "mecanismo_evidencia": max(0, min(10, 2 + min(8, mechanism_count * 3))),
        "espanol_natural": 0 if re.search(P["WEIRD_ABSTRACT_RE"], text_n) else 8,
        "no_repetitivo": max(0, min(10, 10 - repeated_sentence_roots * 2 - (4 if generic_hits >= 3 else 0))),
        "visualizable": max(0, min(10, min(10, visual_count * 3))),
        "cta": 8 if sentences and re.search(P["CTA_RE"], _norm(" ".join(sentences[-2:]))) else 2,
    }
    return {
        "score": score,
        "hard_rejects": hard_rejects,
        "issues": issues,
        "word_count": wc,
        "peak_count": peak_count,
        "release_count": release_count,
        "mechanism_count": mechanism_count,
        "visual_count": visual_count,
        "dimensions": dimensions,
        "eligible": not hard_rejects and score >= int(os.environ.get("SCRIPT_AUDITION_MIN_SCORE", "62")),
    }

def get_script_audition_writers():
    """Return distinct writer providers. No OpenAI and no same-model prompt variants."""
    writers = []
    enabled = {x.strip().lower() for x in os.environ.get("SCRIPT_AUDITION_WRITERS", "codex,gemma").split(",") if x.strip()}
    if "codex" in enabled:
        writers.append({
            "id": "codex-oauth",
            "provider": "codex",
            "model": "codex-oauth",
            "client": CodexOAuthLLM(),
        })
    if "gemma" in enabled or "spark" in enabled or "vllm" in enabled:
        writers.append({
            "id": "gemma-local",
            "provider": "gemma",
            "model": os.environ.get("VLLM_MODEL") or os.environ.get("LLM_MODEL") or "gemma-local",
            "client": OpenAICompatLLM(
                "gemma",
                os.environ.get("VLLM_BASE_URL") or os.environ.get("LLM_BASE_URL") or "http://spark:18100/v1",
                os.environ.get("VLLM_MODEL") or os.environ.get("LLM_MODEL") or "gemma-local",
                os.environ.get("VLLM_API_KEY") or os.environ.get("LLM_API_KEY") or "",
            ),
        })
    return writers

class OpenAICompatLLM:
    mode = "real"
    def __init__(self, provider_name, base_url, model, api_key=""):
        self.provider_name = provider_name
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key or ""
        self.last_angle_report = None
        if not self.base_url:
            raise RuntimeError("falta LLM_BASE_URL/VLLM_BASE_URL para LLM_PROVIDER=%s" % provider_name)
        if not self.model:
            raise RuntimeError("falta LLM_MODEL/VLLM_MODEL para LLM_PROVIDER=%s" % provider_name)

    def _chat_json(self, sys_p, usr_p, label, max_tokens):
        body = {
            "model": self.model,
            "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.35")),
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": sys_p},
                {"role": "user", "content": usr_p},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        url = self.base_url + "/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=int(os.environ.get("LLM_TIMEOUT", "120"))) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read()[:400]
            raise RuntimeError("%s chat %s: %s" % (self.provider_name, e.code, detail))
        content = resp["choices"][0]["message"]["content"]
        return _json_from_text(content, label)

    def script(self, topic, language="es"):
        n = os.environ.get("SCRIPT_WORDS", DEFAULT_SCRIPT_WORDS)
        self.last_angle_report = None
        if _use_legacy_angle_selection():
            angle_sys, angle_usr = _angle_prompt(topic)
            last_angle_error = None
            for _ in range(int(os.environ.get("LLM_ANGLE_RETRIES", "3"))):
                try:
                    angle_payload = self._chat_json(
                        angle_sys,
                        angle_usr,
                        "%s-angle" % self.provider_name,
                        int(os.environ.get("LLM_ANGLE_MAX_TOKENS", "1600")),
                    )
                    self.last_angle_report = _validate_angle_payload(angle_payload, "%s-angle" % self.provider_name)
                    break
                except Exception as e:
                    last_angle_error = e
            else:
                raise last_angle_error
        feedback = None
        last_error = None
        for _ in range(int(os.environ.get("LLM_SCRIPT_RETRIES", "4"))):
            sys_p, usr_p = _script_prompt(topic, n, None, feedback, language=language)
            d = self._chat_json(
                sys_p,
                usr_p,
                self.provider_name,
                int(os.environ.get("LLM_MAX_TOKENS", "900")),
            )
            try:
                return _validate_script_payload(d, self.provider_name, language=language)
            except ScriptFormatError as e:
                feedback = e.issues
                last_error = e
        raise last_error

class OpenAILLM:
    mode = "real"
    def __init__(self):
        self.last_angle_report = None

    def _chat_json(self, sys_p, usr_p, label, max_tokens):
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("falta la variable de entorno OPENAI_API_KEY (LLM_PROVIDER=openai)")
        model = os.environ.get("OPENAI_SCRIPT_MODEL", "gpt-4o-mini")
        body = {"model": model, "temperature": 0.8,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": sys_p},
                             {"role": "user", "content": usr_p}]}
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions",
              data=json.dumps(body).encode(), method="POST",
              headers={"Authorization": "Bearer %s" % key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError("OpenAI chat %s: %s" % (e.code, e.read()[:200]))
        return _json_from_text(resp["choices"][0]["message"]["content"], label)

    def script(self, topic, language="es"):
        n = os.environ.get("SCRIPT_WORDS", DEFAULT_SCRIPT_WORDS)
        self.last_angle_report = None
        if _use_legacy_angle_selection():
            angle_sys, angle_usr = _angle_prompt(topic)
            last_angle_error = None
            for _ in range(int(os.environ.get("LLM_ANGLE_RETRIES", "3"))):
                try:
                    angle_payload = self._chat_json(
                        angle_sys,
                        angle_usr,
                        "openai-angle",
                        int(os.environ.get("LLM_ANGLE_MAX_TOKENS", "1600")),
                    )
                    self.last_angle_report = _validate_angle_payload(angle_payload, "openai-angle")
                    break
                except Exception as e:
                    last_angle_error = e
            else:
                raise last_angle_error
        feedback = None
        last_error = None
        for _ in range(int(os.environ.get("LLM_SCRIPT_RETRIES", "4"))):
            sys_p, usr_p = _script_prompt(topic, n, None, feedback, language=language)
            d = self._chat_json(sys_p, usr_p, "openai", int(os.environ.get("LLM_MAX_TOKENS", "900")))
            try:
                return _validate_script_payload(d, "openai", language=language)
            except ScriptFormatError as e:
                feedback = e.issues
                last_error = e
        raise last_error

def get_llm():
    p = os.environ.get("LLM_PROVIDER", "mock").lower()
    if p == "openai":
        return OpenAILLM()
    if p in ("vllm", "spark", "gemma"):
        return OpenAICompatLLM(
            p,
            os.environ.get("VLLM_BASE_URL") or os.environ.get("LLM_BASE_URL") or "http://spark:18100/v1",
            os.environ.get("VLLM_MODEL") or os.environ.get("LLM_MODEL") or "gemma-local",
            os.environ.get("VLLM_API_KEY") or os.environ.get("LLM_API_KEY") or "",
        )
    if p in ("litellm", "openai-compatible", "openai_compat", "compat"):
        return OpenAICompatLLM(
            p,
            os.environ.get("LITELLM_BASE_URL") or os.environ.get("LLM_BASE_URL") or "http://spark:4000/v1",
            os.environ.get("LITELLM_MODEL") or os.environ.get("LLM_MODEL") or "",
            os.environ.get("LITELLM_API_KEY") or os.environ.get("LLM_API_KEY") or "",
        )
    if p in ("codex", "real"):
        return CodexOAuthLLM()
    return MockLLM()
