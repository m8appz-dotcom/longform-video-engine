# -*- coding: utf-8 -*-
"""Cierra el loop: cuando un gate falla con hallazgos de mismatch de medium, el
motor ACTUA sobre ellos y reintenta -- en vez de bloquear y preguntarle al humano
"esa es la solucion?". Consume el reporte del juez que ya corrio (work/ai_qa/
{stage}_latest.json), no gasta en re-clasificar: el juez ya es la autoridad.

Control de gasto: MAX_AUTO_REMEDIATE (env) topa cuantas remediaciones automaticas
por plan; el flag se guarda en el plan para no loopear. Convertir a clip solo
reescribe el JSON; el gasto real (imagen) lo hace props con su cap normal.
"""
import contextlib
import hashlib
import io
import json
import os
import tempfile

from engine import medium_policy
from engine.config import WORK_DIR


def _verify_candidate(plan):
    """Corre el validador DETERMINISTICO (gratis, sin AI) sobre el plan candidato
    en un archivo temporal, sin tocar plan_path. Devuelve (ok, error_lines).
    validate_plan.main() imprime los errores a stdout y no los devuelve; se
    capturan parseando las lineas '  - ...' que emite."""
    from engine import validate_plan
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="auto_remediate_verify_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = validate_plan.main(tmp_path)
        lines = [ln[4:].strip() for ln in buf.getvalue().splitlines() if ln.startswith("  - ")]
        return (rc == 0), lines
    except Exception as e:
        return False, ["verificacion fallo: %s" % e]
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _cap():
    try:
        return int(os.environ.get("MAX_AUTO_REMEDIATE", "3"))
    except ValueError:
        return 3


def _report_path(stage):
    # Los reportes del juez viven en work/ai_qa/ (qa.py default_out), no en work/.
    return os.path.join(WORK_DIR, "ai_qa", "%s_latest.json" % stage)


# El conteo de auto-remediaciones vive en un SIDECAR, no en el plan: el contrato
# debe quedar schema-limpio (additionalProperties:false). Sidecar keyed por plan.
def _sidecar_path():
    return os.path.join(WORK_DIR, "auto_remediate_state.json")


def _get_count(plan_path):
    st = _load(_sidecar_path())
    entry = st.get(os.path.abspath(plan_path), 0)
    if isinstance(entry, dict):
        return int(entry.get("count", 0))
    return int(entry or 0)


def _last_consumed_hash(plan_path, stage):
    st = _load(_sidecar_path())
    entry = st.get(os.path.abspath(plan_path))
    if isinstance(entry, dict):
        return (entry.get("consumed_hashes") or {}).get(stage)
    return None


def _last_direction(plan_path, idx):
    st = _load(_sidecar_path())
    entry = st.get(os.path.abspath(plan_path))
    if isinstance(entry, dict):
        return (entry.get("directions") or {}).get(str(idx))
    return None


def scenes_with_plate_base(plan_path):
    """Indices de escenas cuya ULTIMA direccion registrada en el sidecar tiene
    base 'plate' (el juez las revirtio o las disputo hacia texto). enforce las
    salta para no pelear con el juez (anti-oscilacion ENTRE capas: enforce sube
    a media, juez baja a plate, enforce vuelve a subir...)."""
    st = _load(_sidecar_path())
    entry = st.get(os.path.abspath(plan_path))
    if not isinstance(entry, dict):
        return set()
    out = set()
    for k, d in (entry.get("directions") or {}).items():
        if medium_policy.direction_base(d) == "plate":
            try:
                out.add(int(k))
            except (TypeError, ValueError):
                pass
    return out


def _report_hash(report):
    # Huella del CONTENIDO de hallazgos (no del archivo): si el gate determinista
    # falla antes de que el juez vuelva a correr, el reporte en disco es el mismo
    # de la ronda anterior. Sin esto, auto_remediate re-aplicaria el mismo fix sin
    # sentido en bucle (hallado en corrida real: 3 rondas de "prompt_strengthened"
    # sin avanzar porque el error real -- motion='static' -- no era de medium).
    blob = json.dumps(report.get("blocking_issues") or [], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _bump_count(plan_path, applied, report_hash, stage, directions):
    p = _sidecar_path()
    st = _load(p)
    key = os.path.abspath(plan_path)
    entry = st.get(key) if isinstance(st.get(key), dict) else {"count": int(st.get(key, 0) or 0), "log": []}
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["log"] = (entry.get("log") or []) + applied
    hashes = entry.get("consumed_hashes") or {}
    hashes[stage] = report_hash
    entry["consumed_hashes"] = hashes
    dirs = entry.get("directions") or {}
    dirs.update(directions)
    entry["directions"] = dirs
    st[key] = entry
    try:
        os.makedirs(WORK_DIR, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return entry["count"]


def _load(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _demote_unfit_stock(report):
    """Cierra el loop juez->escalera (mandato 2026-07-07): si props_qa BLOQUEA una
    escena cuya media vino de un peldaño de stock (pexels/clip_extractor), ese
    asset queda vetado (fit=false en su sidecar .fit.json, misma firma) para que
    en el retry la escalera BAJE al siguiente peldaño en vez de re-aceptar el
    mismo clip. El fit-gate de build es la primera opinion; props_qa es la
    segunda: cuando la segunda veta, la escalera obedece. Devuelve indices."""
    from engine.config import REMOTION_DIR
    props_path = os.path.join(REMOTION_DIR, "props.json")
    props = _load(props_path)
    scenes = props.get("scenes") or []
    demoted = []
    for it in (report.get("blocking_issues") or []):
        if not isinstance(it, dict) or str(it.get("severity", "")).lower() not in ("blocker", "critical"):
            continue
        idx = it.get("scene")
        if not isinstance(idx, int) or not (0 <= idx < len(scenes)):
            continue
        sc = scenes[idx]
        if sc.get("source") not in ("pexels", "clip_extractor"):
            continue
        media = str(sc.get("media") or "")
        if not media:
            continue
        dst = os.path.join(REMOTION_DIR, "public", *media.split("/"))
        # La firma vigente vive en el sidecar .fit.json (escrito por el fit-gate)
        # o en el .meta.json del asset; sin firma no se puede vetar con precision.
        sig = None
        for cand in (dst + ".fit.json", dst + ".meta.json"):
            data = _load(cand)
            if data.get("signature"):
                sig = data["signature"]
                break
        if not sig:
            continue
        try:
            with open(dst + ".fit.json", "w", encoding="utf-8") as f:
                json.dump({"signature": sig, "fit": False,
                           "reason": "props_qa veto: %s" % str(it.get("issue") or "")[:220]},
                          f, ensure_ascii=False)
            demoted.append(idx)
        except Exception:
            continue
    return demoted


class RemediationResult(object):
    def __init__(self, changed, n, detail):
        self.changed = changed
        self.n = n
        self.detail = detail

    def __repr__(self):
        return "RemediationResult(changed=%s, n=%d, %r)" % (self.changed, self.n, self.detail)


def try_auto_remediate(stage, plan_path):
    """Lee el reporte del juez de `stage`, aplica el transform de medium a las
    escenas con mismatch y reescribe el plan. Devuelve RemediationResult.

    No incrementa el circuit breaker: el runner debe llamar a esto ANTES de contar
    el fallo, y reintentar el stage si changed=True (hasta el cap)."""
    if stage not in ("plan", "props", "render"):
        return RemediationResult(False, 0, "stage no remediable")
    report = _load(_report_path(stage))
    # GATE DE VERSION DE CRITERIO: un reporte escrito bajo el criterio anterior
    # (probatorio) pide exactamente las degradaciones a plate que el criterio v2
    # prohibe. No remediar con el: esperar a que el juez re-corra y escriba un
    # reporte con la version vigente. (Reportes pre-versionado no traen el campo.)
    if report and report.get("criterion_version") != medium_policy.CRITERION_VERSION:
        return RemediationResult(False, 0,
            "reporte del juez con criterion_version=%r (vigente %r); no se remedia con criterio viejo"
            % (report.get("criterion_version"), medium_policy.CRITERION_VERSION))
    issues = report.get("blocking_issues") or []
    mismatches = [it for it in issues if medium_policy.finding_is_medium_mismatch(it)]
    if not mismatches:
        return RemediationResult(False, 0, "sin hallazgos de mismatch de medium")

    report_hash = _report_hash(report)
    if report_hash == _last_consumed_hash(plan_path, stage):
        # Mismo reporte que ya remediamos: el gate fallo de nuevo ANTES de que el
        # juez volviera a correr (un error deterministico nuevo y NO relacionado
        # con medium esta bloqueando). Reaplicar el mismo fix es inutil -- dejar
        # que el error real suba al humano/breaker en vez de loopear.
        return RemediationResult(False, 0, "reporte identico ya remediado; el bloqueo actual no es de medium")

    # LOOP JUEZ->ESCALERA (antes que la logica de medium): stock vetado por
    # props_qa se degrada a nivel de ASSET (fit=false) y el retry de la etapa
    # baja la escalera. No toca el plan JSON; respeta cap y hash-consumido.
    if stage == "props":
        already_now = _get_count(plan_path)
        if already_now < _cap():
            demoted = _demote_unfit_stock(report)
            if demoted:
                _bump_count(plan_path,
                            [{"scene": i, "action": "stock_demoted"} for i in demoted],
                            report_hash, stage, {})
                return RemediationResult(True, len(demoted),
                    "stock vetado por el juez degradado en escena(s) %s; la escalera bajara al siguiente peldaño" % demoted)

    try:
        with open(plan_path, encoding="utf-8-sig") as f:
            plan = json.load(f)
    except Exception as e:
        return RemediationResult(False, 0, "no pude leer el plan: %s" % e)

    already = _get_count(plan_path)
    if already >= _cap():
        return RemediationResult(False, 0, "cap de auto-remediacion alcanzado (%d); escalar a humano" % _cap())

    scenes = plan.get("scenes") or []
    applied = []
    directions = {}
    contested = []
    seen = set()
    for it in mismatches:
        idx = it.get("scene")
        if not isinstance(idx, int) or idx < 0 or idx >= len(scenes) or idx in seen:
            continue
        seen.add(idx)
        sc = scenes[idx]
        direction = medium_policy.finding_direction(str(it.get("issue") or "") + " " + str(it.get("fix") or ""))
        prev_direction = _last_direction(plan_path, idx)

        # ANTI-OSCILACION: si esta escena YA cambio de BASE de medium antes y el
        # juez ahora pide la base CONTRARIA otra vez, es un desacuerdo del juez
        # consigo mismo (hallado en corrida real: 0/1/5 rebotando foto<->grafico,
        # gastando llamadas reales sin converger). No tocar mas: dejar que
        # surja como blocker normal y el humano decida el genero, no el motor.
        # v2: se comparan BASES (media vs plate) via direction_base, no strings:
        # to_clip -> to_overlay conserva la media y NO es oscilacion; los sidecars
        # viejos con 'to_graphic' normalizan a base 'plate' (retrocompatible).
        prev_base = medium_policy.direction_base(prev_direction)
        new_base = medium_policy.direction_base(direction)
        if prev_base and new_base and prev_base != new_base:
            contested.append(idx)
            continue

        if direction == "to_remove" and medium_policy._has_media(sc):
            # Veto legitimo (contradiccion / error visual obvio): unica ruta que
            # todavia quita media. revert_to_graphic solo ve la ESCENA; la
            # sincronia hook.visual<->clip.source la cierra el caller.
            medium_policy.revert_to_graphic(sc)
            if idx == 0 and sc.get("role") == "hook":
                hv = plan.get("hook", {}).get("visual")
                if isinstance(hv, dict):
                    hv["provider"] = "none"
                    hv.pop("prompt", None)
            applied.append({"scene": idx, "action": "clip_to_plate"})
            directions[idx] = direction
        elif direction == "to_overlay" and medium_policy._has_media(sc):
            # Claim textual sobre media: CONSERVAR la media, declarar la
            # precision encima (antes esto era clip_to_plate: el ejecutor del
            # reel-PowerPoint).
            medium_policy.compose_overlay_on_media(plan, idx)
            applied.append({"scene": idx, "action": "overlay_added"})
            directions[idx] = direction
        elif medium_policy._is_plate(sc) and direction != "to_remove":
            medium_policy.author_real_clip(sc)
            # Espejo del sync del brazo de veto: si media-ficamos el hook, el
            # plan-level hook.visual debe seguir a clip.source o validate_plan
            # rechaza el candidato siempre (asimetria hallada en auditoria v2).
            if idx == 0 and sc.get("role") == "hook":
                hv = plan.setdefault("hook", {}).setdefault("visual", {})
                if isinstance(hv, dict):
                    hv["provider"] = (sc.get("clip") or {}).get("source") or "image"
                    hv["prompt"] = (sc.get("clip") or {}).get("prompt") or hv.get("prompt") or ""
            applied.append({"scene": idx, "action": "plate_to_clip"})
            directions[idx] = direction or "to_clip"
        elif medium_policy._has_media(sc):
            medium_policy.strengthen_media_prompt(sc)
            applied.append({"scene": idx, "action": "prompt_strengthened"})
            directions[idx] = direction or "to_clip"

    if not applied:
        msg = "hallazgos de medium pero ninguna escena transformable"
        if contested:
            msg = "escena(s) %s en desacuerdo del juez consigo mismo (oscilacion); dejando de tocarlas, escalar a humano" % contested
        return RemediationResult(False, 0, msg)

    # VERIFICAR-ANTES-DE-COMPROMETER: un transform de UNA escena puede romper
    # invariantes de TODO el plan que el transform no puede ver (hallado en
    # corrida real: revertir 2 escenas a plate dejo el plan por debajo del
    # minimo de media_policy, con familia de plate repetida, y huecos de
    # cobertura). Si el candidato no valida limpio, NO comprometer: mejor
    # escalar la falla original que escribir un plan roto que el SIGUIENTE
    # intento recien descubriria (desperdiciando un ciclo completo).
    ok, verify_errors = _verify_candidate(plan)
    if not ok:
        return RemediationResult(False, 0,
            "el fix rompe invariantes del plan (%s); no aplicado, escalando la falla original" %
            "; ".join(verify_errors[:2]))

    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    _bump_count(plan_path, applied, report_hash, stage, directions)  # conteo+hash+direccion en sidecar
    detail = "auto-remediadas %d escena(s): %s" % (
        len(applied), ", ".join("#%d/%s" % (a["scene"], a["action"]) for a in applied))
    return RemediationResult(True, len(applied), detail)
