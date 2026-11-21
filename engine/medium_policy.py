# -*- coding: utf-8 -*-
"""Fuente UNICA del criterio de medium (demostrable-vs-textual) y de la accion que
lo aplica. Antes el criterio vivia duplicado en prosa en qa.py (plan_qa/render_qa)
y la DECISION la tomaba un humano leyendo un blocker. Aqui el motor DECIDE y ACTUA:

- CLAIM_GENRE_CRITERION: el criterio en un solo lugar (lo importa qa.py).
- classify_scene: clasifica el claim de una escena (determinista-primero).
- author_real_clip: transforma un plate demostrable -> broll+image valido.
- strengthen_media_prompt: mejora el prompt de una escena que YA es media pero no
  muestra el referente demostrable.
- enforce: pasada deterministica sobre el plan que corrige los mismatches obvios
  ANTES del gate, para que el plan nazca correcto sin intervencion humana.

El humano nunca decide medium ni responde "esa es la solucion?": esto lo decide.
"""
import re

# Reusa el lexico/heuristica que ya existe en el validador (no re-implementa).
from engine.validate_plan import (
    VISIBLE_MEDIA_TERMS,
    has_visible_media_need,
    scene_semantic_text,
    query_tokens as _vp_query_tokens,
    clip_extractor_meaningful_query_tokens as _vp_ce_tokens,
    clip_extractor_query_noise as _vp_ce_noise,
    CLIP_EXTRACTOR_QUERY_MAX_TOKENS as _VP_CE_MAX_TOK,
    CLIP_EXTRACTOR_QUERY_MAX_CHARS as _VP_CE_MAX_CH,
)

import json
import os

# Palabras que NO aportan a un query de stock/extractor (conectores + genericos
# que validate_plan tambien descarta). El query de la escalera se arma con
# sustantivos concretos de visual_targets.
_QUERY_STOP = set((
    "el la los las un una unos unas de del al con para por en y o u que se su sus "
    "tu tus mi mis lo le les como pero mas mas muy sin sobre entre hacia desde "
    "vertical close person background generic abstract high quality footage stock"
).split())
_PEXELS_GENERIC = set("vertical close up person background generic abstract high quality footage stock".split())


def _escalera_prefers_clips():
    """El mandato del dueño: preferir clips reales. MEDIA_ESCALERA=image fuerza el
    comportamiento viejo (solo foto). El ladder de build degrada si el backend
    de clips esta caido, asi que preferir clips es seguro por default."""
    return (os.environ.get("MEDIA_ESCALERA", "clips") or "clips").strip().lower() != "image"


def _pexels_available():
    return bool(os.environ.get("PEXELS_API_KEY"))


def _stock_query(scene):
    """Query limpio de sustantivos concretos desde visual_targets (+ intent como
    respaldo). Es la materia prima de clip_extractor/pexels."""
    src = " ".join(str(x) for x in (scene.get("visual_targets") or [])).strip()
    if not src:
        src = str(scene.get("intent") or "")
    toks = []
    for w in re.findall(r"[0-9a-záéíóúüñ]{3,}", src.lower()):
        if w in _QUERY_STOP or w in toks:
            continue
        toks.append(w)
    return " ".join(toks[:6])


_STOCK_QUERY_SYSTEM = (
    "Eres un buscador profesional de material de video. Conviertes un beat editorial "
    "en busquedas que los proveedores REALES pueden responder. Dos destinos distintos:\n"
    "\n"
    "1. youtube_query (para Clip Extractor, que busca en YouTube): escribela como una "
    "BUSQUEDA DE YOUTUBE sobre titulos reales de videos, NO como prompt de imagen. "
    "Patrones probados: b-roll real -> '{emocion/accion} {sujeto} {lugar} stock footage' "
    "o '{sujeto} {accion} b roll'; pantalla/software -> '{software/tarea} screen recording' "
    "o '{tarea} software demo'; concepto abstracto/sintetico -> '{concepto} animation' o "
    "'{concepto} motion graphics'. Si el beat es un concepto de software no filmable "
    "(dashboards, workflows, apps conectandose), USA motion graphics/animation, no b-roll. "
    "PROHIBIDO: vertical/portrait/9:16, marcas, dos escenas en un query.\n"
    "2. pexels_query (para Pexels, banco de stock con tags): UNA escena fisica concreta "
    "y filmable, 4-7 palabras (sujeto + accion + objeto/lugar), sin 'stock footage'. "
    "PROHIBIDO jerga con doble sentido fisico sin desambiguar ('running dashboard' "
    "devuelve gente corriendo).\n"
    "\n"
    "Ademas, para Clip Extractor:\n"
    "- source_mode: b_roll | screen_recording | motion_graphics (elige el que calza).\n"
    "- must_have_visuals: 1-3 requisitos VISIBLES concretos que el segmento debe mostrar. "
    "COHERENTES con source_mode: si es motion_graphics/screen_recording, describe SOLO el "
    "contenido de la animacion/pantalla (nada de personas, actores ni expresiones -- una "
    "animacion no tiene gente parada al lado); las personas van solo con b_roll.\n"
    "- nice_to_have_visuals: 0-2 apoyos opcionales.\n"
    "- avoid: clases de resultado malas para este beat (ej: tutorial, how to, review, "
    "reaction, unboxing, gameplay, webcam, vlog).\n"
    "Todo en ingles, minusculas. Devuelve SOLO JSON valido:\n"
    "{\"youtube_query\": \"...\", \"pexels_query\": \"...\", \"source_mode\": \"...\", "
    "\"must_have_visuals\": [...], \"nice_to_have_visuals\": [...], \"avoid\": [...]}"
)


_SOURCE_MODES = ("b_roll", "screen_recording", "motion_graphics", "tutorial", "known_scene")
_DEFAULT_AVOID = ["tutorial", "how to", "review", "reaction", "unboxing", "gameplay", "webcam", "vlog"]


def _clean_terms(value, n=3):
    out = []
    for item in (value if isinstance(value, list) else []):
        t = str(item or "").strip().lower()
        if t and t not in out:
            out.append(t[:80])
        if len(out) >= n:
            break
    return out


def author_stock_search(scene, spoken=""):
    """Contrato de busqueda COMPLETO autorado por LLM (guia real del servicio,
    GET /api/search-guidelines, integrada 2026-07-09): el query de Clip Extractor
    se escribe como BUSQUEDA DE YOUTUBE sobre titulos reales (no como prompt de
    imagen -- esa fue la mitad del fracaso 7/7), y characteristics dirige el
    ranking y la validacion de Gemma (source_mode/must_have/avoid -- la otra
    mitad: se enviaba vacio). Para conceptos de software no filmables, la guia
    manda motion_graphics/animation en vez de b-roll. Devuelve dict con
    youtube_query, pexels_query y characteristics; fallback deterministico si
    el LLM falla o el provider es mock."""
    fallback = {
        "youtube_query": _stock_query(scene),
        "pexels_query": _stock_query(scene),
        "characteristics": {},
    }
    try:
        from engine import qa  # lazy: qa importa medium_policy (ciclo a nivel modulo)
        if qa.provider() == "mock":
            return fallback
        user = (
            "BEAT EDITORIAL: %s\n"
            "LO QUE DICE LA VOZ: %s\n"
            "visual_proof: %s\n"
            "visual_targets (inspiracion, NO los copies literal): %s\n"
            "Escribe el contrato de busqueda." % (
                str(scene.get("editorial_point") or scene.get("intent") or "")[:300],
                str(spoken or "")[:300],
                str(scene.get("visual_proof") or "")[:200],
                ", ".join(str(t) for t in (scene.get("visual_targets") or [])),
            )
        )
        raw = qa.call_ai_json(_STOCK_QUERY_SYSTEM, user)
        yt = " ".join(re.findall(r"[0-9a-z:]+", str(raw.get("youtube_query") or "").lower())[:8])
        px = " ".join(re.findall(r"[0-9a-z]+", str(raw.get("pexels_query") or "").lower())[:7])
        mode = str(raw.get("source_mode") or "").strip().lower()
        chars = {}
        if mode in _SOURCE_MODES:
            chars["source_mode"] = mode
        must = _clean_terms(raw.get("must_have_visuals"), 3)
        if must:
            chars["must_have_visuals"] = must
        nice = _clean_terms(raw.get("nice_to_have_visuals"), 2)
        if nice:
            chars["nice_to_have_visuals"] = nice
        avoid = _clean_terms(raw.get("avoid"), 6) or list(_DEFAULT_AVOID)
        chars["avoid"] = avoid
        out = dict(fallback)
        if yt and _clip_extractor_query_valid(yt):
            out["youtube_query"] = yt
        if px and _pexels_query_valid(px):
            out["pexels_query"] = px
        out["characteristics"] = chars
        return out
    except Exception as e:
        print("  [stock-query] autor LLM fallo (%s); uso fallback deterministico" % str(e)[:80])
    return fallback


def author_stock_query(scene, spoken=""):
    """Compat: devuelve solo el query de pexels del contrato completo."""
    return author_stock_search(scene, spoken).get("pexels_query") or _stock_query(scene)


def _clip_extractor_query_valid(q):
    if not q:
        return False
    toks = _vp_query_tokens(q)
    meaningful = _vp_ce_tokens(q)
    return (len(toks) >= 3 and len(set(meaningful)) >= 3
            and len(meaningful) <= _VP_CE_MAX_TOK and len(q) <= _VP_CE_MAX_CH
            and not _vp_ce_noise(q))


def _pexels_query_valid(q):
    if not q:
        return False
    toks = _vp_query_tokens(q)
    meaningful = [t for t in toks if t not in _PEXELS_GENERIC]
    return len(toks) >= 4 and len(set(meaningful)) >= 2


def choose_media_source(scene):
    """Escalera del mandato: asset del usuario > clip_extractor > pexels > image
    > omni(google, solo si el director lo declara). Devuelve la fuente MAS RICA
    cuyo query/JSON VALIDA para esta escena -- si el query no alcanza para stock,
    baja a image (que siempre valida). El fallback real ante un proveedor caido
    ocurre en build (props_build), no aqui."""
    clip = scene.get("clip") or {}
    if clip.get("asset"):
        return "asset"
    if not _escalera_prefers_clips():
        return "image"
    q = _stock_query(scene)
    n_targets = len([t for t in (scene.get("visual_targets") or []) if str(t).strip()])
    # clip_extractor exige role hook/broll, >=2 visual_targets y query limpio
    # (mismos requisitos que validate_plan: si no, el candidato no validaria).
    if scene.get("role") in ("hook", "broll") and n_targets >= 2 and _clip_extractor_query_valid(q):
        return "clip_extractor"
    if _pexels_available() and _pexels_query_valid(q):
        return "pexels"
    return "image"


_CLIP_EXTRACTOR_ALIVE = None  # cache por proceso del ping de liveness


def _clip_extractor_available():
    """El SERVICIO clip_extractor responde healthy? Pinguea el MISMO endpoint que
    usa el provider real: {CLIP_EXTRACTOR_BASE_URL}/api/health con ok:true (no el
    vLLM directo -- ese es solo para entender el query y el servicio lo expone via
    vllm_reachable). Cacheado por proceso. CLIP_EXTRACTOR_ASSUME_UP=1 lo fuerza."""
    global _CLIP_EXTRACTOR_ALIVE
    if _CLIP_EXTRACTOR_ALIVE is not None:
        return _CLIP_EXTRACTOR_ALIVE
    if os.environ.get("CLIP_EXTRACTOR_ASSUME_UP", "").lower() in ("1", "true", "yes", "on"):
        _CLIP_EXTRACTOR_ALIVE = True
        return True
    base = os.environ.get("CLIP_EXTRACTOR_BASE_URL", "http://100.121.147.73:8765").rstrip("/")
    import urllib.request
    try:
        with urllib.request.urlopen(base + "/api/health",
                                    timeout=float(os.environ.get("CLIP_EXTRACTOR_PING_TIMEOUT", "5") or 5)) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        _CLIP_EXTRACTOR_ALIVE = data.get("ok") is True
    except Exception:
        _CLIP_EXTRACTOR_ALIVE = False
    return _CLIP_EXTRACTOR_ALIVE


def upgrade_media_escalera(plan):
    """Sube escenas image AUTORADAS a clip_extractor/pexels (video real) cuando
    MEDIA_ESCALERA prefiere clips, el proveedor esta VIVO y el query valida.

    Cierra el gap (2026-07-06): choose_media_source solo corria DENTRO de
    author_real_clip (plate->media). Una escena que el director escribio como
    source=image se quedaba image aunque hubiera video disponible -- por eso los
    reels salian 100%% foto generada (que alucina laptops imposibles, pantallas
    garabateadas, caras que driftean) en vez de metraje real. Ahora, con
    proveedor vivo, esas escenas se suben al peldaño mas rico de la escalera.

    Solo toca role hook/broll con source=image (no asset de usuario, no avatar,
    no plate/none, no google). Conserva el prompt como red de seguridad: si el
    proveedor falla en build, props degrada clip_extractor->pexels->image usando
    ese prompt. Si NINGUN proveedor de video esta vivo, es un no-op honesto.
    In place. Devuelve (plan, changes)."""
    changes = []
    if not _escalera_prefers_clips():
        return plan, changes
    pexels_ok = _pexels_available()
    clip_ok = _clip_extractor_available()
    if not (pexels_ok or clip_ok):
        return plan, changes  # sin proveedor de video vivo -> no-op
    for i, sc in enumerate(plan.get("scenes") or []):
        clip = sc.get("clip") if isinstance(sc.get("clip"), dict) else {}
        if clip.get("source") != "image" or clip.get("asset"):
            continue
        if sc.get("role") not in ("hook", "broll"):
            continue
        # Contrato de busqueda completo autorado por LLM: query estilo YouTube +
        # characteristics para clip_extractor, y variante pexels para el descenso.
        search = author_stock_search(sc)
        qyt, qpx = search["youtube_query"], search["pexels_query"]
        n_targets = len([t for t in (sc.get("visual_targets") or []) if str(t).strip()])
        target = None
        if clip_ok and n_targets >= 2 and _clip_extractor_query_valid(qyt):
            target = "clip_extractor"
        elif pexels_ok and _pexels_query_valid(qpx):
            target = "pexels"
        if not target:
            continue
        if target == "clip_extractor":
            new_clip = {"source": target, "query": qyt}
            if search.get("characteristics"):
                new_clip["characteristics"] = search["characteristics"]
            if qpx and qpx != qyt:
                new_clip["pexels_query"] = qpx  # el descenso de escalera usa el idioma de Pexels
        else:
            new_clip = {"source": target, "query": qpx}
        if clip.get("prompt"):
            new_clip["prompt"] = clip["prompt"]      # red de seguridad para el fallback de build
        if clip.get("treatment"):
            new_clip["treatment"] = clip["treatment"]
        sc["clip"] = new_clip
        sc["motion"] = "static"                       # el video real trae su propio movimiento
        sc["visual_family"] = "hook_spectacle" if sc.get("role") == "hook" else "action_proof"
        # El hook lleva un espejo plan-level (hook.visual.provider) que validate_plan
        # exige sincronizado con scene[0].clip.source (mismo sync que author_real_clip).
        if i == 0 and sc.get("role") == "hook":
            hv = plan.setdefault("hook", {}).setdefault("visual", {})
            if isinstance(hv, dict):
                hv["provider"] = target
                if new_clip.get("prompt"):
                    hv["prompt"] = new_clip["prompt"]
        changes.append({"scene": i, "action": "image_to_%s" % target})
    return plan, changes

# ---------------------------------------------------------------------------
# CRITERIO: la unica fuente de verdad. qa.py lo importa en vez de duplicar prosa.
#
# CRITERION_VERSION se estampa en cada reporte de juez (qa.normalize_report) y
# gatea la MEMORIA del juez y el consumo de reportes en auto_remediate: un
# reporte escrito bajo el criterio anterior (probatorio) NO debe re-litigarse
# ni remediar bajo el criterio nuevo (dramatizacion). Subir la version cada vez
# que el sentido del criterio cambie, no por retoques de redaccion.
# ---------------------------------------------------------------------------
CRITERION_VERSION = 4  # v4: stock real fit-gated no se re-litiga por literalidad (v3: etiqueta legible inventada)
# El bump a v4 invalida la memoria de los jueces escrita bajo v3: un blocker de
# literalidad sobre stock ('no se ve la interfaz de chat') minteado ANTES de la
# regla de no-relitigio se auto-perpetuaba via la memoria ('issue anterior NO
# resuelto' en cada corrida, porque la media legitimamente no cambia). Ese es el
# hazard exacto que el versionado existe para cortar.

# CLAUSULA DE REALISMO DE IMAGEN (fuente unica; la usan los prompts de imagen y
# los jueces via este modulo). Cambio 2026-07-05 (mandato del dueno): un envase
# 100% liso se ve FALSO/IA -- y peor en un reel que habla de leer etiquetas. La
# regla vieja prohibia TODO texto en imagen porque los modelos lo renderizaban
# garabateado; gpt-image-2 ya escribe etiquetas cortas legibles, asi que ahora se
# PERMITE (y se pide) una etiqueta creible con marca INVENTADA. Sigue vetado:
# marcas reales existentes (trademark), marcas de agua, y texto deforme/
# garabateado/sin sentido (eso ultimo es error visual real). La PRECISION del
# guion (cifras, frases, listas exactas) sigue viviendo en overlays declarados,
# no dentro de la imagen -- esa parte del contrato declared_only no cambia.
IMAGE_REALISM_CLAUSE = (
    "entorno cotidiano luminoso, luz natural suave, composicion limpia. Si aparece un "
    "envase o producto, que se vea REAL de tienda: puede llevar una etiqueta legible y un "
    "diseno de empaque verosimil -- por defecto una MARCA INVENTADA corta y creible, o la "
    "marca real UNICAMENTE si el tema/guion la nombra explicitamente (nunca marcas de agua). "
    "El texto de la etiqueta debe ser nitido y bien escrito; jamas letras deformes, "
    "garabateadas o sin sentido. Espacio inferior despejado para captions."
)

CLAIM_GENRE_CRITERION = (
    "GENERO DEL CLAIM (clasifica ANTES de juzgar el medio; el estandar es DRAMATIZAR, no probar):\n"
    "- Claim DEMOSTRABLE/FISICO -- un antes-despues, una accion/gesto, un objeto EN USO, un lugar, un efecto "
    "visible: pide media (foto/clip) con la persona/gesto/objeto que DRAMATICE la idea. Una foto o clip que "
    "evoca el gesto u objeto es SUFICIENTE; NO la marques debil por 'generica'. Una escena plate (solo texto) "
    "sobre un claim dramatizable es mismatch: marca id='medium_mismatch' (severity major) y pide role='broll' "
    "con clip.source image/pexels/clip_extractor.\n"
    "- Claim TEXTUAL/ANALITICO -- lo que DICE una etiqueta/anuncio, un criterio, una regla, un veredicto, una "
    "comparacion: la BASE sigue siendo media con personas/accion que dramatiza la idea; la PRECISION (cifra, "
    "frase, lista) vive en un OVERLAY DECLARADO (frase literal del guion) compuesto SOBRE esa media. Un envase/"
    "producto PUEDE (y suele deber) llevar una etiqueta legible con marca INVENTADA: eso hace ver el producto "
    "real y NO contradice declared_only -- lo que NO va dentro de la imagen es la PRECISION exacta del guion "
    "(esa vive en el overlay). Solo el texto deforme/garabateado es error visual; una marca real NO es defecto "
    "si el guion la nombra (mostrarla es correcto), solo lo es una marca real ajena metida sin que el tema la mencione. "
    "Un plate 100% texto "
    "es ULTIMO RECURSO (pico tipografico puntual, 3-4 por reel maximo), no la respuesta correcta por defecto: "
    "si el beat tiene persona/gesto/objeto dramatizable, el plate tambien es mismatch (major) -- pide media "
    "con el overlay declarado encima.\n"
    "VETO DE MEDIA (el UNICO caso donde pides QUITAR media existente; usa id='medium_remove'): la media "
    "CONTRADICE lo narrado o tiene un error visual obvio para un humano (texto garabateado dentro de la "
    "imagen, manos/anatomia deformes, producto distinto al del resto del reel, sujeto equivocado, avatar "
    "visiblemente montado). 'No prueba el claim' NO es razon para quitar media."
)

# Verbos/objetos que delatan un claim demostrable aunque no usen el lexico exacto
# de VISIBLE_MEDIA_TERMS (que es angosto). Complementa has_visible_media_need sin
# re-implementar el juez: sigue siendo determinista y conservador.
_DEMONSTRABLE_HINTS = re.compile(
    r"\b(mostrar|muestra|se ve|ver(?:se)?|mira|revisa(?:r)?|senala(?:r)?|apunta(?:r)?|gira(?:r)?|"
    r"aplica(?:r)?|masaj\w+|frasco|envase|etiqueta|producto|crema|piel|antes y despues|"
    r"antes-despues|en la mano|sostiene|sosteniendo)\b",
    re.I,
)

# Senales en el texto de un hallazgo del juez de que es un mismatch de medium.
# Incluye el vocabulario viejo (reportes legacy) y el nuevo (dramatizacion,
# monotonia de texto, ratio de media) para que la remediacion vea ambos.
_FINDING_MISMATCH = re.compile(
    r"\b(demostrable|clip real|media real|foto real|etiqueta legible|no prueba|no ense\w+|"
    r"inventa la prueba|generico sin|no muestra|fotografic\w+ insuficiente|referente|textual|"
    r"medium_mismatch|medium_remove|media_ratio|dramatiz\w+|overlay declarado|pico tipografico|"
    r"sin accion|sin personas|monoton\w+|pantalla(?:s)? de texto)\b",
    re.I,
)

# DIRECCION del hallazgo: el juez usa literalmente el vocabulario de
# CLAIM_GENRE_CRITERION (se lo inyectamos nosotros), asi que podemos leer que
# direccion pide sin ambiguedad -- sin esto, un hallazgo que pide REVERTIR
# foto->grafico se trataba igual que uno que pide foto->foto-mas-fuerte (bug
# real: causaba oscilacion infinita gastando llamadas reales al juez).
#
# v2 (SEMANTICA SOBRE PRECISION): la direccion 'to_graphic' (quitar la media)
# ya no existe como respuesta a un claim textual. Sus señales viejas ahora
# mapean a 'to_overlay' (CONSERVAR la media y componer la precision declarada
# encima). Quitar media ('to_remove') solo procede ante contradiccion o error
# visual obvio -- el veto legitimo del criterio.
_WANTS_REMOVE = re.compile(
    r"\bmedium_remove\b|contradice (?:lo narrado|el guion|la narracion)|texto garabateado|"
    r"manos? deformes|anatomia deforme|producto (?:distinto|inconsistente)|sujeto equivocado|"
    r"avatar (?:visiblemente )?montado",
    re.I | re.S,
)
_WANTS_OVERLAY = re.compile(
    r"\btextual\b.{0,80}(?:analitic|correct|declarad|overlay)|overlay declarado|"
    r"(?:cifra|frase|lista|precision).{0,60}overlay|"
    r"(?:grafico|texto declarado)\w*\s+(?:es|son)\s+la\s+prueba\s+correcta|"
    r"la foto no prueba|no (?:es|era) foto|(?:prueba|evidencia)\s+correcta.{0,60}grafico|"
    r"(?:regla|texto)\W*(?:\/\s*texto)?\s+declarad\w*.{0,60}(?:grafico|evidencia correcta)|"
    r"la foto (?:no prueba|tampoco (?:prueba|conecta))|referente\s+mostrado",
    re.I | re.S,
)
_WANTS_CLIP = re.compile(
    r"\bdemostrable\b.{0,80}(?:fisic|exige|necesita|dramatiz)|necesita (?:foto|clip|media) real|"
    r"exige foto\W|prueba (?:debil|inventada)|\bdramatizable\b|pide (?:media|role=.?broll)|"
    r"plate.{0,60}(?:mismatch|dramatizable)|sin (?:accion|personas)|pantalla(?:s)? de texto|monoton\w+",
    re.I | re.S,
)


def finding_direction(issue_text):
    """to_remove | to_overlay | to_clip | None, leyendo el vocabulario que el
    propio criterio (inyectado al juez) usa. None si ambiguo -> no actuar a ciegas.
    to_remove gana siempre: es el veto explicito por contradiccion/error visual."""
    if _WANTS_REMOVE.search(issue_text):
        return "to_remove"
    o = _WANTS_OVERLAY.search(issue_text)
    c = _WANTS_CLIP.search(issue_text)
    if o and not c:
        return "to_overlay"
    if c and not o:
        return "to_clip"
    if o and c:
        # ambos aparecen (ej. citando el criterio completo): el mas cercano al
        # final del texto suele ser la instruccion accionable real.
        return "to_overlay" if o.start() > c.start() else "to_clip"
    return None


def direction_base(direction):
    """Base de medium que PRODUCE una direccion: 'media' o 'plate'. El guard
    anti-oscilacion compara bases, no strings: to_clip -> to_overlay no es
    oscilacion (ambas conservan media); solo el flip media<->plate lo es.
    Retro-compatible: sidecars viejos guardan 'to_graphic' (que quitaba la
    media) -> base 'plate'."""
    if direction in ("to_clip", "to_overlay"):
        return "media"
    if direction in ("to_graphic", "to_remove", "to_plate"):
        return "plate"
    return None


def _is_plate(scene):
    return (scene.get("role") == "plate") or ((scene.get("clip") or {}).get("source") == "none")


def _has_media(scene):
    src = (scene.get("clip") or {}).get("source")
    if scene.get("role") == "avatar" or src == "kreado":
        return True  # la cara hablando es media (mitad inferior); no es un plate
    return scene.get("role") in ("broll", "hook") and src in ("asset", "pexels", "clip_extractor", "image", "google")


def classify_scene(scene):
    """Determinista-primero. Devuelve kind demostrable|textual|ambiguous + por que.

    No llama a ningun proveedor (barato, no gasta). Los casos que el juez AI
    distingue mejor se resuelven via close-the-loop (auto_remediate consume sus
    hallazgos), no aqui. Aqui capturamos los mismatches deterministas obvios.
    """
    text = scene_semantic_text(scene) or ""
    hard = has_visible_media_need(scene)  # lexico VISIBLE_MEDIA_TERMS (angosto pero firme)
    hint = bool(_DEMONSTRABLE_HINTS.search(text))
    if scene.get("layout") == "cta" or scene.get("plate_purpose") == "chapter":
        return {"kind": "textual", "confidence": 0.6, "reason": "cta/chapter: estructural, no demostrable"}
    if hard:
        return {"kind": "demostrable", "confidence": 0.9, "reason": "match VISIBLE_MEDIA_TERMS"}
    if hint:
        return {"kind": "demostrable", "confidence": 0.6, "reason": "senal de accion/objeto observable en el texto editorial"}
    return {"kind": "ambiguous", "confidence": 0.3, "reason": "sin senal deterministica; el juez AI decide"}


def _referent_from(scene):
    """Frase del referente fisico para autorar el prompt, desde los campos editoriales."""
    for key in ("editorial_point", "why_it_matters", "visual_proof", "intent"):
        v = str(scene.get(key) or "").strip()
        if len(v) > 12:
            return v[:200]
    a = scene.get("anchor") or {}
    return str(a.get("phrase") or "el objeto del que habla la voz")


def author_real_clip(scene):
    """Transforma IN PLACE un plate dramatizable -> broll+image valido, respetando
    los acoplamientos del validador (full_bleed, sin plate_purpose, family valida).

    El prompt se deriva deterministamente del texto editorial: no es tan bueno como
    uno autorado por AI, pero es un default VALIDO que desbloquea al humano; el juez
    de props (o un pase AI posterior) puede refinarlo. Lo importante: el motor ya
    eligio y actuo, nadie tuvo que decidir.

    El hook conserva role='hook' (espejo exacto de la excepcion de
    revert_to_graphic): sin esto, media-ficar la escena 0 ponia role='broll' y
    _verify_candidate rechazaba SIEMPRE el candidato por 'la primera escena debe
    ser role=hook' -- el hook era degradable a texto pero imposible de
    media-ficar, la asimetria exactamente contraria al mandato."""
    referent = _referent_from(scene)
    if scene.get("role") != "hook":
        scene["role"] = "broll"
    scene["layout"] = "full_bleed"
    scene["visual_mode"] = "concrete"
    scene.pop("plate_purpose", None)
    if not str(scene.get("intent") or "").strip():
        scene["intent"] = (referent[:80] or "accion concreta del beat")

    source = choose_media_source(scene)
    # El prompt persona-centrico se conserva SIEMPRE: es el visual de image y
    # ademas la red de seguridad para el fallback en build si clip_extractor o
    # pexels fallan (props_build baja la escalera usando este prompt).
    image_prompt = (
        "Fotografia vertical 9:16, close-up o plano medio de una persona realizando la accion del beat: "
        + referent
        + ". La persona (manos, gesto) y el objeto en uso son el sujeto dominante. "
        + IMAGE_REALISM_CLAUSE
    )
    if source == "clip_extractor":
        search = author_stock_search(scene)
        scene["visual_family"] = "action_proof" if scene.get("role") != "hook" else "hook_spectacle"
        scene["clip"] = {"source": "clip_extractor", "query": search["youtube_query"], "prompt": image_prompt}
        if search.get("characteristics"):
            scene["clip"]["characteristics"] = search["characteristics"]
        if search.get("pexels_query") and search["pexels_query"] != search["youtube_query"]:
            scene["clip"]["pexels_query"] = search["pexels_query"]
        # clip_extractor entrega video con movimiento real: no forzar Ken Burns.
        scene["motion"] = "static"
    elif source == "pexels":
        scene["visual_family"] = "action_proof" if scene.get("role") != "hook" else "hook_spectacle"
        scene["clip"] = {"source": "pexels", "query": author_stock_search(scene)["pexels_query"], "prompt": image_prompt}
        scene["motion"] = "static"
    else:  # image (siempre valida)
        scene["visual_family"] = "concrete_proof" if scene.get("role") != "hook" else "hook_spectacle"
        scene["clip"] = {
            "source": "image", "image_provider": "codex-oauth", "model": "gpt-image-2",
            "prompt": image_prompt,
        }
        # FORZAR (no "or"): el motion heredado del plate/diagrama (ej. "static") es
        # incompatible con source=image generado, que exige Ken Burns/pan (hallado
        # en corrida real: preservar el motion viejo causaba un loop de remediacion).
        scene["motion"] = "kenburns-in"
    scene["why_this_visual_not_other"] = (
        "Claim dramatizable: media con la persona/gesto/objeto en accion sostiene la retencion; "
        "la precision del texto va en overlays declarados encima, no en un panel que reemplaza la media."
    )
    scene["visual_proof"] = "Se ve a la persona/gesto/objeto dramatizando el beat (autoseleccionado por medium_policy)."
    return scene


def strengthen_media_prompt(scene):
    """La escena YA es media pero el juez pide un visual mas fuerte. Reescribe el
    prompt en clave DRAMATIZACION (persona/gesto/objeto en accion). El realismo del
    envase (etiqueta legible inventada, sin marca real ni texto garabateado) lo fija
    IMAGE_REALISM_CLAUSE. In place."""
    clip = scene.get("clip") or {}
    if clip.get("source") not in ("image", "google"):
        return scene  # solo aplica a fuentes generadas por prompt
    referent = _referent_from(scene)
    clip["prompt"] = (
        "Fotografia vertical 9:16 que DRAMATIZA el beat narrado: " + referent
        + ". Sujeto dominante: la persona/mano realizando la accion con el objeto en uso, encuadre "
        "close-up o medio. " + IMAGE_REALISM_CLAUSE
    )
    scene["clip"] = clip
    return scene


def compose_overlay_on_media(plan, idx):
    """Respuesta v2 a un claim TEXTUAL sobre una escena que YA tiene media:
    CONSERVAR la media y componer la precision como overlay declarado encima
    (antes la unica respuesta era revert_to_graphic, que borraba la media --
    el ejecutor del reel-PowerPoint). In place sobre el plan.

    Si la escena ya tiene un overlay anclado dentro de su ventana, solo se
    actualiza la prosa editorial (la precision ya esta declarada). Si no lo
    tiene y la escena tiene anchor.phrase literal, se agrega un LowerThird con
    esa frase (recortada) -- el anclaje literal preserva declared_only. El
    verify-antes-de-comprometer del caller decide si el candidato es valido."""
    scenes = plan.get("scenes") or []
    if not (0 <= idx < len(scenes)):
        return plan
    sc = scenes[idx]
    anchor_phrase = str(((sc.get("anchor") or {}).get("phrase")) or "").strip()
    overlays = plan.get("overlays")
    if not isinstance(overlays, list):
        overlays = []
        plan["overlays"] = overlays
    has_overlay = any(
        anchor_phrase and anchor_phrase == str(((o.get("anchor") or {}).get("phrase")) or "")
        or (isinstance(o.get("anchor"), dict) and o["anchor"].get("phrase") and sc.get("intent")
            and str(o["anchor"]["phrase"]) in str(sc.get("intent")))
        for o in overlays if isinstance(o, dict)
    )
    if anchor_phrase and not has_overlay:
        words = [w for w in re.split(r"\s+", anchor_phrase) if w]
        overlays.append({
            "type": "label",
            "component": "LowerThird",
            "anchor": {"phrase": anchor_phrase},
            "semantic_kind": "label",
            "placement": "safe_lower",
            "must_not_cover": ["subject"],
            "rationale": "Precision declarada compuesta sobre la media (medium_policy v2: la media dramatiza, el overlay lleva el texto).",
            "duration_ms": 2600,
            "params": {"text": " ".join(words[:5]).upper()},
        })
    sc["visual_proof"] = (
        "La media dramatiza el beat; la precision textual la lleva el overlay declarado compuesto encima."
    )
    sc["why_this_visual_not_other"] = (
        "Claim textual sobre base de media: se conserva la media (retencion) y el texto va declarado encima; "
        "un plate que reemplaza la media es ultimo recurso."
    )
    return plan


# Frases literales que has_visible_media_need busca (VISIBLE_MEDIA_TERMS) mas las
# palabras que author_real_clip/strengthen_media_prompt insertan: si sobreviven al
# revertir a grafico, el validador determinista rechaza el plate de inmediato y
# el auto-fix oscila para siempre (hallado en corrida real). Se sanean al revertir.
_SANITIZE_RE = re.compile(
    r"\b(objeto f[ií]sico|objeto real|producto f[ií]sico|persona real|gesto f[ií]sico|"
    r"accion f[ií]sica|lugar real|referente f[ií]sico del claim|foto que muestra|"
    r"claim demostrable|claim dramatizable|persona realizando la accion|"
    r"dramatizando el beat|objeto en uso)\b",
    re.I,
)


def revert_to_graphic(scene):
    """ULTIMO RECURSO (v2): quitar la media solo procede ante un hallazgo
    'to_remove' (la media CONTRADICE lo narrado o tiene error visual obvio).
    Para claims textuales la respuesta ya NO es esta: es compose_overlay_on_media
    (conservar la media, declarar la precision encima). Sanea el texto editorial
    para no re-disparar has_visible_media_need (que buscaria las mismas frases
    que NOSOTROS insertamos al convertir a clip la vez anterior)."""
    # El hook es un caso especial: role='hook' con clip.source='none' es VALIDO
    # (el validador lo permite explicitamente) y DEBE seguir siendo hook -- no
    # "plate" (hallado en corrida real: forzar role='plate' en el hook rompe
    # "la primera escena debe ser role=hook").
    if scene.get("role") != "hook":
        scene["role"] = "plate"
    scene["layout"] = "diagram"
    scene["visual_mode"] = "diagrammatic"
    scene["visual_family"] = "criteria_gate"
    scene["plate_purpose"] = scene.get("plate_purpose") or "decision_card"
    scene["clip"] = {"source": "none"}
    scene.pop("motion", None)
    for key in ("why_this_visual_not_other", "visual_proof", "intent"):
        v = str(scene.get(key) or "")
        if v:
            scene[key] = _SANITIZE_RE.sub("el criterio", v)
    scene["why_this_visual_not_other"] = (
        "Claim textual/analitico: un grafico con texto declarado (frase literal del guion) "
        "prueba el criterio mejor que una foto, que no puede mostrar texto especifico legible."
    )
    scene["visual_proof"] = "El grafico declarado muestra el criterio/veredicto en texto, anclado a la frase literal del guion."
    vt = scene.get("visual_targets")
    if isinstance(vt, list):
        scene["visual_targets"] = [_SANITIZE_RE.sub("criterio", str(x)) for x in vt]
    return scene


def _sync_hook_visual(plan, sc):
    """Si la escena 0 (hook) gano media, el plan-level hook.visual debe seguir a
    clip.source o validate_plan rechaza el plan (coinciden por contrato)."""
    if sc.get("role") != "hook":
        return
    hv = plan.setdefault("hook", {}).setdefault("visual", {})
    if isinstance(hv, dict):
        hv["provider"] = (sc.get("clip") or {}).get("source") or "image"
        hv["prompt"] = (sc.get("clip") or {}).get("prompt") or hv.get("prompt") or ""


def enforce(plan, skip_scenes=None):
    """Pasada deterministica: corrige los mismatches OBVIOS antes del gate, para que
    el plan nazca correcto. Devuelve (plan_modificado, cambios[list]). No gasta:
    solo transforma el JSON; la generacion de media la hace props con su cap normal.

    v2 (SEMANTICA SOBRE PRECISION): tres pasadas --
    1. hook: si es 100%-texto sin hook_plate_reason, se media-fica (el hook debe
       MOSTRAR la creencia/accion).
    2. plates con señal demostrable: umbral baja de 0.9 a 0.6 -- el lexico duro
       de VISIBLE_MEDIA_TERMS (0.9) casi nunca matchea texto editorial real, asi
       que enforce convertia ~0 escenas y el plan nacia texto-pesado.
    3. racha: >MAX_CONSECUTIVE_TEXT_SCENES escenas 100%-texto seguidas -> se
       convierte la del medio (la zona de abandono 14-26s era exactamente esto).

    skip_scenes: indices que el juez ya disputo u orillo a plate (sidecar de
    auto_remediate) -- enforce NO pelea con una decision del juez (anti-oscilacion
    entre capas: enforce sube, juez baja, enforce sube...)."""
    skip = set(skip_scenes or [])
    changes = []
    scenes = plan.get("scenes") or []
    try:
        from engine._generated import MAX_CONSECUTIVE_TEXT_SCENES as _MAXTXT
    except Exception:
        _MAXTXT = 2

    def _textish(sc):
        return (sc.get("clip") or {}).get("source") not in (
            "asset", "pexels", "clip_extractor", "image", "google", "kreado"
        ) and sc.get("role") != "avatar"

    # 1) hook sin media (salvo override deliberado)
    meta = plan.get("meta") or {}
    if scenes and 0 not in skip and scenes[0].get("role") == "hook" and _textish(scenes[0]) \
            and len(str(meta.get("hook_plate_reason") or "").strip()) < 20:
        author_real_clip(scenes[0])
        _sync_hook_visual(plan, scenes[0])
        changes.append({"scene": 0, "action": "plate_to_clip", "reason": "hook debe mostrar la creencia/accion (mandato v2)"})

    # 2) plates con señal demostrable (>=0.6: hints de accion/objeto observable)
    def _has_last_resort_reason(sc):
        # Mismo umbral que validate_plan: un plate con razon declarada (>=20
        # chars) es una decision EDITORIAL deliberada del director, no un
        # mismatch. Sin este check, enforce reconvertia en cada corrida un
        # plate que el director revirtio a proposito (hallado en produccion
        # real: el diagrama de profundidad, elogiado en revision humana como
        # la mejor escena, se re-convertia a foto generica cada vez que
        # corria el pipeline porque su texto matcheaba 'crema' en el hint).
        return len(str(sc.get("plate_last_resort_reason") or "").strip()) >= 20

    for i, sc in enumerate(scenes):
        if i in skip or not _is_plate(sc) or sc.get("role") == "hook":
            continue
        if sc.get("layout") == "cta" or sc.get("plate_purpose") in ("chapter", "cta_resource"):
            continue
        if _has_last_resort_reason(sc):
            continue
        verdict = classify_scene(sc)
        if verdict["kind"] == "demostrable" and verdict["confidence"] >= 0.6:
            author_real_clip(sc)
            changes.append({"scene": i, "action": "plate_to_clip", "reason": verdict["reason"]})

    # 3) rachas de texto: convertir la escena del medio hasta que ninguna racha
    # exceda el maximo (o no queden candidatas legales).
    guard = 0
    while guard < len(scenes) + 1:
        guard += 1
        run = []
        fixed = False
        for k, sc in enumerate(list(scenes) + [None]):
            if sc is not None and _textish(sc):
                run.append(k)
                continue
            if len(run) > _MAXTXT:
                cands = [
                    k2 for k2 in run
                    if k2 not in skip and scenes[k2].get("role") != "hook"
                    and scenes[k2].get("layout") != "cta"
                    and scenes[k2].get("plate_purpose") not in ("chapter", "cta_resource")
                    and not _has_last_resort_reason(scenes[k2])
                ]
                if cands:
                    mid = cands[len(cands) // 2]
                    author_real_clip(scenes[mid])
                    changes.append({"scene": mid, "action": "plate_to_clip",
                                    "reason": "racha de %d escenas 100%%-texto (max %d)" % (len(run), _MAXTXT)})
                    fixed = True
                    break
            run = []
        if not fixed:
            break
    return plan, changes


# ---------------------------------------------------------------------------
# COLOCACION AUTOMATICA DEL AVATAR (mandato 2026-07-06): el motor pone la cara
# hablando en los DOS mejores momentos -- el aha (giro/veredicto, maxima
# autoridad) y el cierre (ultima escena antes del CTA, remate a camara) -- en
# vez de que el director elija a mano. El visual planeado de esa escena NO se
# pierde: pasa a ser el companion (mitad superior); el avatar 16:9 va abajo. Si
# la escena era plate sin media, el companion usa motion graphics (source=motion,
# ya implementado en el renderer).
# ---------------------------------------------------------------------------

# Señales de que un beat es el AHA: giro, veredicto, sintesis, criterio -- el
# momento de maxima autoridad, ideal para la cara a camara. Bilingue (mismo
# patron que script_audit/llm/qa): los campos editoriales de un reel en ingles
# se escriben en ingles, un regex monolingue nunca encontraria el aha.
_AHA_CUES_ES = re.compile(
    r"\b(la regla|la verdad|en realidad|el secreto|la clave|lo que importa|"
    r"la diferencia|en resumen|recuerda|por eso|el error|el punto|el criterio|"
    r"el veredicto|se reduce a|no es\b.{0,40}\bes\b|aha|simple|en el fondo)\b",
    re.I,
)
_AHA_CUES_EN = re.compile(
    r"\b(the rule|the truth|in reality|reality is|the secret|the key|what matters|"
    r"the difference|in short|remember|that'?s why|the mistake|the point|the criterion|"
    r"the verdict|it comes down to|isn'?t\b.{0,60}\b(it'?s|they'?re|you'?re)\b|"
    r"aren'?t\b.{0,60}\b(it'?s|they'?re|you'?re)\b|real money|actual money|the profit is|aha|simple|at its core|the real)\b",
    re.I,
)
_AHA_CUES = _AHA_CUES_ES  # compat: default es


def _aha_cues_for(language):
    return _AHA_CUES_EN if (language or "es").strip().lower() == "en" else _AHA_CUES_ES


def _avatar_semantic_text(scene):
    a = scene.get("anchor") or {}
    return " ".join(str(scene.get(k) or "") for k in (
        "intent", "editorial_point", "why_it_matters", "visual_proof")) + " " + str(a.get("phrase") or "")


def _avatar_protected(scene):
    # plate/diagrama deliberado (el director declaro por que): no lo tocamos.
    return len(str(scene.get("plate_last_resort_reason") or "").strip()) >= 20


def _cta_index(scenes):
    for i in range(len(scenes) - 1, -1, -1):
        s = scenes[i]
        if s.get("layout") == "cta" or s.get("role") == "cta" or s.get("plate_purpose") == "cta_resource":
            return i
    return len(scenes)


def _avatar_candidate_indices(scenes, cta_i):
    out = []
    for i, s in enumerate(scenes):
        if s.get("role") == "hook" or i >= cta_i:
            continue
        if s.get("layout") == "cta" or s.get("plate_purpose") in ("cta_resource", "chapter"):
            continue
        if _avatar_protected(s):
            continue
        out.append(i)
    return out


def _aha_score(scene, i, cta_i, language="es"):
    score = 0.0
    if _aha_cues_for(language).search(_avatar_semantic_text(scene)):
        score += 3.0
    if cta_i > 1:  # el aha suele caer al ~68% del recorrido hacia el cierre
        score += 1.0 - abs(i / float(cta_i) - 0.68) * 2.0
    return score


_AVATAR_TERMS_BY_LANG = {
    "es": ("autoridad", "confianza", "humano", "humana", "presentador", "ancla",
           "criterio", "advertencia", "pivote"),
    "en": ("authority", "confidence", "credibility", "human", "presenter", "anchor",
           "criteria", "criterion", "warning", "pivot"),
}
_AVATAR_TERMS_SENTENCE_BY_LANG = {
    "es": " Se ve al presentador dando el criterio a camara (autoridad/confianza).",
    "en": " The presenter delivers the point to camera (authority/confidence).",
}


def _ensure_avatar_terms(scene, language="es"):
    """validate_plan exige un termino de autoridad en intent/editorial_point/
    why_it_matters/visual_proof (bilingue, ver _AVATAR_TERMS_BY_LANG). Si no
    hay, lo anadimos a visual_proof en el idioma del reel."""
    lang = (language or "es").strip().lower()
    terms = _AVATAR_TERMS_BY_LANG.get(lang, _AVATAR_TERMS_BY_LANG["es"])
    txt = " ".join(str(scene.get(k) or "") for k in (
        "intent", "editorial_point", "why_it_matters", "visual_proof")).lower()
    if not any(t in txt for t in terms):
        vp = str(scene.get("visual_proof") or "").strip()
        sentence = _AVATAR_TERMS_SENTENCE_BY_LANG.get(lang, _AVATAR_TERMS_SENTENCE_BY_LANG["es"])
        scene["visual_proof"] = (vp + sentence).strip()


_WHY_AVATAR_SENTENCE_BY_LANG = {
    "es": "El presentador da el criterio a camara: mas autoridad que una foto en este beat.",
    "en": "The presenter delivers the point to camera: more authority than a photo for this beat.",
}


def _scene_to_avatar(scene, language="es"):
    """Convierte IN PLACE una escena a role='avatar'. El visual planeado pasa a
    companion; el avatar 16:9 va abajo. Preserva anchor/timing/beats."""
    clip = scene.get("clip") or {}
    src = clip.get("source")
    if src in ("image", "pexels", "clip_extractor", "asset", "google"):
        companion = {"source": src}
        for k in ("prompt", "query", "asset", "image_provider", "model", "motion", "characteristics"):
            if clip.get(k) is not None:
                companion[k] = clip[k]
        if src == "image":
            companion.setdefault("motion", "kenburns-in")
    else:  # plate/none -> motion graphics del concepto (source=motion, implementado)
        companion = {"source": "motion"}
    scene["role"] = "avatar"
    scene["layout"] = "full_bleed"
    scene["avatar_layout"] = "split_h"
    scene["caption_position"] = "bottom"
    scene["visual_family"] = "avatar_human"
    scene.pop("plate_purpose", None)
    scene["clip"] = {"source": "kreado", "avatar_key": clip.get("avatar_key") or "default", "companion": companion}
    if not str(scene.get("why_this_visual_not_other") or "").strip():
        lang = (language or "es").strip().lower()
        scene["why_this_visual_not_other"] = _WHY_AVATAR_SENTENCE_BY_LANG.get(lang, _WHY_AVATAR_SENTENCE_BY_LANG["es"])
    _ensure_avatar_terms(scene, language)
    return scene


def _avatar_to_broll(scene):
    """Revierte un avatar a broll: el companion vuelve a ser el visual de la escena."""
    clip = scene.get("clip") or {}
    comp = clip.get("companion") if isinstance(clip.get("companion"), dict) else {}
    csrc = comp.get("source")
    scene.pop("avatar_layout", None)
    if csrc in ("image", "pexels", "clip_extractor", "asset", "google"):
        newclip = {"source": csrc}
        for k in ("prompt", "query", "asset", "image_provider", "model", "characteristics"):
            if comp.get(k) is not None:
                newclip[k] = comp[k]
        scene["role"] = "broll"
        scene["layout"] = "full_bleed"
        scene["clip"] = newclip
        # motion va a NIVEL DE ESCENA, no dentro del clip (schema).
        scene["motion"] = comp.get("motion") or ("kenburns-in" if csrc == "image" else "static")
    else:  # companion era motion/none -> autora un broll con la escalera
        scene["role"] = "broll"
        author_real_clip(scene)
    return scene


def place_avatar(plan):
    """Coloca las apariciones de avatar en el aha + el cierre (shift-left, como
    enforce). Devuelve (plan, changes).

    - avatar_policy='auto': el motor (re)coloca SIEMPRE en aha+cierre.
    - avatar_policy='required': si el director puso menos de N, el motor completa
      en aha+cierre; si ya puso N, se respeta su eleccion (backward compat).
    - avatar_policy='disabled': no toca nada."""
    changes = []
    meta = plan.get("meta") or {}
    policy = meta.get("avatar_policy", "required")
    language = meta.get("language", "es")
    if policy == "disabled":
        return plan, changes
    try:
        from engine._generated import AVATAR_APPEARANCES as _N
    except Exception:
        _N = 2
    try:
        _N = int(meta.get("avatar_appearances", _N))
    except Exception:
        pass
    scenes = plan.get("scenes") or []
    existing = [i for i, s in enumerate(scenes) if s.get("role") == "avatar"]
    if policy != "auto" and len(existing) == _N:
        return plan, changes  # el director ya coloco: respetar

    cta_i = _cta_index(scenes)
    cands = _avatar_candidate_indices(scenes, cta_i)
    if len(cands) < _N:
        return plan, changes  # sin candidatas suficientes: que hable validate_plan

    # cierre = ultima candidata antes del CTA; aha = mejor giro, no adyacente.
    targets = []
    if _N >= 1:
        cierre = cands[-1]
        targets.append(cierre)
    if _N >= 2:
        pool = [i for i in cands if i not in targets]
        non_adjacent = [i for i in pool if all(abs(i - t) >= 2 for t in targets)]
        aha_pool = non_adjacent or pool
        aha = max(aha_pool, key=lambda i: _aha_score(scenes[i], i, cta_i, language))
        targets.append(aha)
    # apariciones extra (N>2): siguientes mejores por señal de giro
    while len(targets) < _N:
        pool = [i for i in cands if i not in targets]
        if not pool:
            break
        targets.append(max(pool, key=lambda i: _aha_score(scenes[i], i, cta_i, language)))
    target_set = set(targets)

    for i in existing:  # revertir avatares fuera de los targets (reposicion)
        if i not in target_set:
            _avatar_to_broll(scenes[i])
            changes.append({"scene": i, "action": "avatar_to_broll", "reason": "reposicion a aha+cierre"})
    for i in sorted(target_set):
        if scenes[i].get("role") != "avatar":
            role_before = "cierre" if i == targets[0] else "aha"
            _scene_to_avatar(scenes[i], language)
            changes.append({"scene": i, "action": "scene_to_avatar", "reason": role_before})
    return plan, changes


def finding_is_medium_mismatch(issue):
    """Un blocking_issue del juez apunta a un mismatch de medium?
    Prefiere el id estructurado (jueces nuevos), cae a heuristica de texto (reportes
    viejos, sin re-correr el juez -> sin gasto)."""
    if not isinstance(issue, dict):
        return False
    if str(issue.get("id") or "").lower() in ("medium_mismatch", "medium-mismatch"):
        return True
    blob = " ".join(str(issue.get(k) or "") for k in ("issue", "fix"))
    return bool(_FINDING_MISMATCH.search(blob))
