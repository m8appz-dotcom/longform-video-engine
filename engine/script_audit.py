#!/usr/bin/env python3
"""Audit ReelPlan voiceover scripts for generic/repetitive short-form writing.

This is an editorial gate, separate from validate_plan.py. It does not call
providers and is safe to run before render.
"""
import argparse
import json
import re
import sys
from pathlib import Path


WORD_RE = re.compile(r"[0-9A-Za-z\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1/-]+")
# Rango de palabras derivado de meta.target_seconds. Piso 1.8 w/s (antes 2.2):
# el piso alto presuponia narracion pared-a-pared y castigaba guiones que dejan
# respirar la accion sin voz encima (mandato v2 media-led). El techo 3.3 se
# conserva: sobre-escritura si es un problema real.
def words_range(target_seconds):
    ts = max(15, int(target_seconds or 45))
    return int(ts * 1.8), int(ts * 3.3)

# ---------------------------------------------------------------------------
# Patrones LANGUAGE-AWARE. Cada set (stopwords, frases genericas, throat-
# clearing, tension, mini-picos, CTA, claim abstracto, hook blando) es un
# diccionario de palabra clave: un guion en ingles evaluado con los patrones
# de espanol no falla con error, simplemente matchea CERO -- un gate que
# aprueba en silencio sin revisar nada real. LANG resuelve el set correcto por
# idioma; analyze()/message_clarity_report()/narrative_peak_gaps() leen
# meta.language del propio plan (default "es", compat con planes existentes).
# ---------------------------------------------------------------------------
LANG = {
    "es": {
        "stopwords": {
            "a", "al", "algo", "ante", "antes", "asi", "aunque", "cada", "como",
            "con", "cuando", "de", "del", "despues", "dos", "el", "ella", "en",
            "entre", "es", "esa", "ese", "eso", "esta", "este", "esto", "hacer",
            "hay", "la", "las", "le", "les", "lo", "los", "mas", "me", "menos",
            "mi", "mis", "muy", "ni", "no", "o", "para", "pero", "por", "porque",
            "que", "se", "si", "sin", "son", "su", "sus", "te", "tu", "tus",
            "un", "una", "unos", "unas", "va", "vas", "y", "ya",
        },
        "generic_phrases": {
            "desbloquea tu potencial", "transforma tu vida", "maximiza resultados",
            "maximiza tus resultados", "la guia definitiva", "esto cambia las reglas",
            "lo que nadie te dice", "eleva tu", "optimiza tu", "potencial", "secreto",
            "breakthrough", "game-changing", "holistico", "integral", "robusto",
            "sin complicaciones",
        },
        "throat_clearing": {
            "hola", "en este video", "hoy vamos a", "es importante", "la verdad es",
            "aqui esta la cosa", "al final del dia",
        },
        "tension_patterns": [
            r"\bno es\b", r"\bno porque\b", r"\bno significa\b", r"\bmal\b",
            r"\berror\b", r"\bproblema\b", r"\briesgo\b", r"\bfalla\b",
            r"\bincomplet", r"\basume\b", r"\bse queda cort",
            r"\bpero\b", r"\baunque\b", r"\bsino\b", r"\ben realidad\b",
            r"\bjusto cuando\b", r"\bsin que\b", r"\bdemasiado tarde\b",
        ],
        "mini_peak_patterns": [
            r"\bproblema\b", r"\berror\b", r"\briesgo\b", r"\bregla\b", r"\bpero\b",
            r"\bcambia\b", r"\bcambio\b", r"\bcontraste\b", r"\bno es\b", r"\bno fue\b",
            r"\bno siempre\b", r"\bnunca\b", r"\ben realidad\b", r"\bsi\b",
            r"\bantes de\b", r"\bjusto cuando\b", r"\basume\b", r"\bsube\b", r"\bse queda\b",
        ],
        "cta_patterns": [
            r"\bguarda\b", r"\bcomenta\b", r"\bcomparte\b", r"\bprueba\b", r"\busa\b",
            r"\bajusta\b", r"\bajustalo\b", r"\bpaso\b", r"\bsirve\b", r"\bmide\b",
            r"\bcierra\b", r"\bpon\b", r"\bsepara\b",
        ],
        "abstract_claim_patterns": [
            ("aforismo vago", r"\b\w+\s+manda\s+mas\s+que\s+\w+"),
            ("promesa abstracta", r"\bla\s+promesa\b"),
        ],
        "hook_bad_patterns": [
            ("hook blando", r"\bte\s+puede\b|\bpodria\s+ayudar\b|\bquizas\b"),
        ],
        "action_verbs": (
            r"\b(haz|hazlo|usa|prueba|mide|cambia|evita|guarda|empiez|deja|elig|ajusta|revisa|"
            r"compara|calcula|escrib|aplica|pon|quita|suma|resta|activa|desactiva|configura|anota|"
            r"marca|separa|cierra|abre|comparte|comenta|instala|reemplaza|prioriza|define|reduce|aumenta)\w*\b"
        ),
        "stem_suffixes": (
            "aciones", "iciones", "ciones", "cion", "mente", "ando", "iendo",
            "ados", "adas", "ado", "ada", "icos", "icas", "ico", "ica", "es", "s",
        ),
    },
    "en": {
        "stopwords": {
            "a", "an", "and", "are", "as", "at", "be", "been", "because", "before",
            "but", "by", "can", "do", "does", "each", "for", "from", "had", "has",
            "have", "he", "her", "him", "his", "how", "if", "in", "into", "is",
            "it", "its", "just", "less", "like", "more", "most", "my", "no", "not",
            "of", "on", "or", "she", "so", "some", "than", "that", "the", "their",
            "them", "then", "there", "these", "they", "this", "those", "to", "too",
            "very", "was", "we", "were", "when", "while", "who", "will", "with",
            "you", "your",
        },
        "generic_phrases": {
            "unlock your potential", "transform your life", "maximize results",
            "maximize your results", "the ultimate guide", "this changes everything",
            "what nobody tells you", "elevate your", "optimize your", "potential",
            "secret", "breakthrough", "game-changing", "holistic", "seamless",
            "robust", "hassle-free",
        },
        "throat_clearing": {
            "hey guys", "in this video", "today i'm going to", "it's important to",
            "here's the thing", "at the end of the day", "let's dive in",
        },
        "tension_patterns": [
            # aren't/don't/doesn't agregados (gap del port: ES cubre toda la
            # familia de negacion 'no es/no fue/no siempre'; el EN inicial solo
            # tenia isn't/wasn't y el pivote "aren't writing prompts" de un
            # guion real conto como CERO tension).
            r"\bit'?s not\b", r"\bisn'?t\b", r"\baren'?t\b", r"\bdon'?t\b",
            r"\bdoesn'?t\b", r"\bnot because\b", r"\bdoesn'?t mean\b",
            r"\bwrong\b", r"\bmistake\b", r"\berror\b", r"\bproblem\b", r"\brisk\b",
            r"\bfails?\b", r"\bincomplete\b", r"\bassumes\b", r"\bfalls short\b",
            r"\bbut\b", r"\balthough\b", r"\beven though\b", r"\binstead\b",
            r"\bin reality\b", r"\bactually\b", r"\bright when\b", r"\bwithout\b",
            r"\btoo late\b",
        ],
        "mini_peak_patterns": [
            r"\bproblem\b", r"\bmistake\b", r"\berror\b", r"\brisk\b", r"\brule\b",
            r"\bbut\b", r"\bchanges\b", r"\bchange\b", r"\bcontrast\b", r"\bisn'?t\b",
            r"\baren'?t\b", r"\bdon'?t\b",
            r"\bwasn'?t\b", r"\bnot always\b", r"\bnever\b", r"\bactually\b",
            r"\bif\b", r"\bbefore\b", r"\bright when\b", r"\bassumes\b",
            r"\brises?\b", r"\bfalls short\b", r"\btrap\b", r"\bcatch\b", r"\btrick\b",
            r"\bgap\b", r"\bshift\b", r"\bflip\b", r"\bdifference\b", r"\binstead\b",
            r"\bturns out\b", r"\bin fact\b", r"\bthe thing is\b", r"\breal reason\b",
        ],
        "cta_patterns": [
            r"\bsave\b", r"\bcomment\b", r"\bshare\b", r"\btry\b", r"\buse\b",
            r"\badjust\b", r"\bstep\b", r"\bfollow\b", r"\bmeasure\b", r"\bclose\b",
            r"\bset\b", r"\bseparate\b", r"\bwatch\b", r"\bswipe\b", r"\btap\b", r"\bgrab\b",
        ],
        "abstract_claim_patterns": [
            ("vague aphorism", r"\b\w+\s+matters\s+more\s+than\s+\w+"),
            ("abstract promise", r"\bthe\s+promise\b"),
        ],
        "hook_bad_patterns": [
            ("weak hook", r"\bcan\s+help\s+you\b|\bmight\s+help\b|\bmaybe\b|\bperhaps\b"),
        ],
        "action_verbs": (
            r"\b(do|make|use|try|measure|change|avoid|save|start|stop|choose|adjust|check|"
            r"compare|calculate|write|apply|put|remove|add|subtract|activate|deactivate|"
            r"configure|note|mark|separate|close|open|share|comment|install|replace|"
            r"prioritize|define|reduce|increase|swipe|tap|watch|follow|grab|drop|set|"
            r"track|test|build|fix|cut|skip)\w*\b"
        ),
        "stem_suffixes": (
            "ations", "ization", "edly", "ing", "tion", "sion", "ness", "ment",
            "ers", "ed", "ly", "er", "es", "s",
        ),
    },
}


def _lang(language):
    l = (language or "es").strip().lower()
    return LANG.get(l, LANG["es"])


# Compat: nombres historicos siguen apuntando al set 'es' por defecto para
# cualquier caller externo que los importe directo (ninguno en este repo,
# pero evita romper silenciosamente).
STOPWORDS = LANG["es"]["stopwords"]
GENERIC_PHRASES = LANG["es"]["generic_phrases"]
THROAT_CLEARING = LANG["es"]["throat_clearing"]
TENSION_PATTERNS = LANG["es"]["tension_patterns"]
MINI_PEAK_PATTERNS = LANG["es"]["mini_peak_patterns"]
CTA_PATTERNS = LANG["es"]["cta_patterns"]
ABSTRACT_CLAIM_PATTERNS = LANG["es"]["abstract_claim_patterns"]
HOOK_BAD_PATTERNS = LANG["es"]["hook_bad_patterns"]


def strip_accents(text):
    table = str.maketrans(
        "\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1",
        "aeiouunAEIOUUN",
    )
    return text.translate(table)


def norm(text):
    return strip_accents(str(text or "")).lower()


def words(text):
    return WORD_RE.findall(str(text or ""))


def sentences(text):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if x.strip()]


def stemish(word, language="es"):
    w = norm(word).strip(".,;:!??()[]")
    for suffix in _lang(language)["stem_suffixes"]:
        if len(w) > len(suffix) + 4 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def count_patterns(text, patterns):
    n = norm(text)
    return sum(len(re.findall(p, n)) for p in patterns)


def match_labeled_patterns(text, patterns):
    n = norm(text)
    return sorted({label for label, pattern in patterns if re.search(pattern, n)})


def message_clarity_report(script, language="es"):
    """Claridad de mensaje AGNOSTICA de dominio: hook debil, claim vago y ausencia
    de accion concreta. Sin vocabulario de ninguna industria (la concrecion
    especifica de un dominio la aporta su plugin)."""
    L = _lang(language)
    sentence_list = sentences(script)
    hook = sentence_list[0] if sentence_list else ""
    abstract_hits = match_labeled_patterns(script, L["abstract_claim_patterns"])
    hook_hits = match_labeled_patterns(hook, L["hook_bad_patterns"])
    has_action = bool(re.search(L["action_verbs"], norm(script)))
    severe = bool(hook_hits) or len(abstract_hits) >= 2
    warning = not severe and (bool(abstract_hits) or not has_action)
    return {
        "severe": severe,
        "warning": warning,
        "abstract_hits": abstract_hits,
        "hook_hits": hook_hits,
        "has_action": has_action,
    }


def narrative_peak_gaps(script, words_per_second=2.6, language="es"):
    """Aproxima la distribucion TEMPORAL de picos narrativos (C3).

    Mapea cada marcador de MINI_PEAK_PATTERNS a un indice de palabra, lo pasa a
    segundos con un wpm tipico de reel, y devuelve el hueco maximo entre picos
    (incluyendo inicio->primer pico y ultimo pico->fin). Un hueco largo = tramo
    sin razon nueva para seguir viendo.
    """
    starts = [m.start() for m in WORD_RE.finditer(str(script or ""))]
    if not starts:
        return None
    n = norm(script)

    def char_to_widx(c):
        lo, hi = 0, len(starts)
        while lo < hi:
            mid = (lo + hi) // 2
            if starts[mid] <= c:
                lo = mid + 1
            else:
                hi = mid
        return max(0, lo - 1)

    peak_widx = set()
    for pattern in _lang(language)["mini_peak_patterns"]:
        for m in re.finditer(pattern, n):
            peak_widx.add(char_to_widx(m.start()))
    total_words = len(starts)
    total_s = total_words / words_per_second
    peaks_s = sorted(w / words_per_second for w in peak_widx)
    marks = [0.0] + peaks_s + [total_s]
    gaps = [b - a for a, b in zip(marks, marks[1:])]
    return {
        "total_s": round(total_s, 1),
        "peak_count": len(peak_widx),
        "max_gap_s": round(max(gaps), 1) if gaps else round(total_s, 1),
    }


def load_plan(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, "json: %s" % str(exc).splitlines()[0]
    if not isinstance(data, dict) or not data.get("script"):
        return None, "sin script"
    return data, None


def analyze(path):
    data, err = load_plan(path)
    if err:
        return {
            "file": str(path),
            "ok": False,
            "score": 0.0,
            "errors": [err],
            "notes": [],
        }

    language = (data.get("meta") or {}).get("language", "es")
    L = _lang(language)
    script = data.get("script") or ""
    sentence_list = sentences(script)
    word_list = words(script)
    lower = norm(script)
    hook = sentence_list[0] if sentence_list else ""

    generic_hits = sorted([p for p in L["generic_phrases"] if p in lower])
    throat_hits = sorted([p for p in L["throat_clearing"] if p in lower])
    sentence_lengths = [len(words(s)) for s in sentence_list]
    max_sentence = max(sentence_lengths or [0])
    avg_sentence = round(sum(sentence_lengths) / max(1, len(sentence_lengths)), 1)

    start_keys = []
    for sentence in sentence_list:
        start = [stemish(w, language) for w in words(sentence)[:2]]
        if start:
            start_keys.append(" ".join(start))
    repeated_starts = {
        key: start_keys.count(key)
        for key in sorted(set(start_keys))
        if start_keys.count(key) > 1
    }

    topic = (data.get("meta") or {}).get("topic", "")
    topic_words = set(stemish(w, language) for w in words(topic))
    hook_words = set(stemish(w, language) for w in words((data.get("hook") or {}).get("spoken", "")))
    unavoidable = topic_words | hook_words
    counts = {}
    for word in word_list:
        stem = stemish(word, language)
        if stem in L["stopwords"] or len(stem) < 3:
            continue
        counts[stem] = counts.get(stem, 0) + 1
    repeat_flags = [
        [word, count]
        for word, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= 4 and word not in unavoidable
    ][:6]

    mini_peaks = count_patterns(script, L["mini_peak_patterns"])
    tension = count_patterns(script, L["tension_patterns"])
    cta = count_patterns(script, L["cta_patterns"])
    message_clarity = message_clarity_report(script, language)

    notes = []
    score = 10.0
    if generic_hits:
        score -= 2.0
        notes.append("frases genericas/AI: %s" % ", ".join(generic_hits))
    if throat_hits:
        score -= 2.0
        notes.append("arranque o relleno lento: %s" % ", ".join(throat_hits))
    if repeated_starts:
        score -= 1.0
        notes.append("arranques repetidos: %s" % repeated_starts)
    if repeat_flags:
        score -= 1.5
        notes.append("palabras repetidas sin cambio claro: %s" % repeat_flags)
    if max_sentence > 24:
        score -= 1.0
        notes.append("frase mas larga de 24 palabras: %d" % max_sentence)
    if avg_sentence > 15:
        score -= 0.75
        notes.append("promedio de frase alto: %.1f palabras" % avg_sentence)
    if len(words(hook)) > 12:
        score -= 0.5
        notes.append("hook hablado largo: %d palabras" % len(words(hook)))
    _ts = (data.get("meta") or {}).get("target_seconds")
    _min_w, _max_w = words_range(_ts)
    length_ok = _min_w <= len(word_list) <= _max_w
    if len(word_list) < _min_w:
        score -= 2.0
        notes.append("guion corto para %ss: %d palabras (objetivo %d-%d)" % (
            _ts or 45, len(word_list), _min_w, _max_w))
    elif len(word_list) > _max_w:
        score -= 1.25
        notes.append("guion largo para %ss: %d palabras (objetivo %d-%d)" % (
            _ts or 45, len(word_list), _min_w, _max_w))
    if mini_peaks < 3:
        if len(word_list) >= _min_w:
            score -= 1.0
        notes.append("pocos mini-picos narrativos: %d" % mini_peaks)
    if tension < 2:
        if len(word_list) >= _min_w:
            score -= 0.5
        notes.append("baja tension narrativa: %d marcadores" % tension)
    peak_gaps = narrative_peak_gaps(script, language=language)
    if peak_gaps and len(word_list) >= _min_w:
        max_gap = peak_gaps["max_gap_s"]
        # Senal blanda: el gate por keyword es crudo (un buen reel puede tener ~24s
        # entre marcadores y sostener con visuales). Solo penaliza huecos egregios;
        # el giro fino cada 8-15s lo juzga el LLM (protegido por Fuga #1).
        if max_gap > 30:
            score -= 1.0
            notes.append("hueco narrativo largo: %.0fs sin pico/giro por keyword (recomendado <=15s; el juez LLM valida el detalle)" % max_gap)
        elif max_gap > 24:
            notes.append("advertencia: hueco narrativo de %.0fs; confirma que haya un giro cada 8-15s" % max_gap)
    if cta < 1:
        score -= 0.5
        notes.append("CTA debil o ausente")
    if message_clarity["severe"]:
        score -= 2.0
        details = []
        if message_clarity["hook_hits"]:
            details.append("hook debil: %s" % ", ".join(message_clarity["hook_hits"]))
        if message_clarity["abstract_hits"]:
            details.append("abstracto: %s" % ", ".join(message_clarity["abstract_hits"]))
        if not message_clarity["has_action"]:
            details.append("sin accion concreta")
        notes.append("mensaje poco claro: %s" % "; ".join(details))
    elif message_clarity["warning"]:
        notes.append(
            "advertencia claridad: %s"
            % (", ".join(message_clarity["abstract_hits"]) or "sin accion concreta")
        )

    score = max(0.0, round(score, 1))
    return {
        "file": str(path),
        "ok": score >= 8.0 and length_ok and not generic_hits and not throat_hits and not message_clarity["severe"],
        "score": score,
        "words": len(word_list),
        "sentences": len(sentence_list),
        "avg_sentence_words": avg_sentence,
        "max_sentence_words": max_sentence,
        "hook": hook,
        "generic_hits": generic_hits,
        "throat_hits": throat_hits,
        "repeat_flags": repeat_flags,
        "repeated_starts": repeated_starts,
        "mini_peak_markers": mini_peaks,
        "narrative_peak_gaps": peak_gaps,
        "tension_markers": tension,
        "cta_markers": cta,
        "message_clarity": message_clarity,
        "notes": notes or ["ok"],
    }


def collect_paths(args):
    if args.paths:
        raw = [Path(p) for p in args.paths]
    else:
        raw = sorted(Path("contracts").glob("*.json"))
    paths = []
    for item in raw:
        if item.is_dir():
            paths.extend(sorted(item.glob("*.json")))
        else:
            paths.append(item)
    return [
        p for p in paths
        if p.name != "reel_plan.schema.json" and "legacy" not in {part.lower() for part in p.parts}
    ]


def print_human(results):
    for result in results:
        status = "OK" if result["ok"] else "REVISAR"
        print("%-42s %s  score=%.1f  words=%s  hook=%s" % (
            Path(result["file"]).name,
            status,
            result["score"],
            result.get("words", "-"),
            result.get("hook", "")[:80],
        ))
        for note in result.get("notes", []):
            if note != "ok":
                print("  - %s" % note)


def main():
    parser = argparse.ArgumentParser(description="Audit ReelPlan script quality.")
    parser.add_argument("paths", nargs="*", help="Plan JSON files or directories. Defaults to contracts/*.json")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--fail-under", type=float, default=8.0, help="Exit 1 if any script scores below this value")
    args = parser.parse_args()

    paths = collect_paths(args)
    results = [analyze(path) for path in paths]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_human(results)

    failed = [r for r in results if r["score"] < args.fail_under or not r["ok"]]
    if failed:
        if not args.json:
            print("SCRIPT QUALITY: revisar %d/%d" % (len(failed), len(results)))
        return 1
    if not args.json:
        print("SCRIPT QUALITY OK: %d" % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())


def run_for(plan_path, fail_under=8.0):
    """Adapter programatico para un solo plan; devuelve rc (0 ok)."""
    import sys as _sys
    argv = _sys.argv
    _sys.argv = ["script_audit", str(plan_path), "--fail-under", str(fail_under)]
    try:
        return main()
    finally:
        _sys.argv = argv
