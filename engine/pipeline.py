#!/usr/bin/env python3
"""Runner del pipeline v2: etapas puras, artefactos explicitos y circuit breaker.

Etapas (cada una lee/escribe artefactos en work/ y es re-ejecutable sola):
  audition  -> work/script_winner.json          (candidatos multi-proveedor + ganador)
  plan      -> valida contracts/<plan>.json      (validate_plan + qa plan + preview)
  props     -> remotion/props.json               (tts + align + resolve + media + props + validate + qa)
  render    -> out/reel.mp4                      (remotion render + qa render)

Regla central (leccion del bucle de 1h en v1): NINGUNA etapa reintenta en
silencio. Cada etapa corre 1 vez; si falla, el pipeline PARA con el reporte.
Quien decide reintentar es el director (skill/humano), con un tope duro de
MAX_STAGE_RETRIES visible en work/pipeline_state.json.

Uso:
  python -m engine.pipeline audition --topic "..."
  python -m engine.pipeline plan contracts/mi_plan.json
  python -m engine.pipeline props contracts/mi_plan.json
  python -m engine.pipeline render
  python -m engine.pipeline full contracts/mi_plan.json
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

from engine.config import (
    ROOT, REMOTION_DIR, WORK_DIR, MAX_STAGE_RETRIES, ensure_dirs, production_mode,
    subprocess_env,
)

STATE_PATH = os.path.join(WORK_DIR, "pipeline_state.json")


def _load_state():
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception:
        return {"attempts": {}, "history": []}


def _save_state(state):
    ensure_dirs()
    json.dump(state, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _record(state, stage, ok, detail=""):
    state["history"].append({
        "stage": stage, "ok": ok, "detail": str(detail)[:400],
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    _save_state(state)


def _check_budget(state, stage):
    """Circuit breaker: si la etapa ya agoto sus intentos, PARA con reporte."""
    n = state["attempts"].get(stage, 0)
    if n >= MAX_STAGE_RETRIES + 1:
        fails = [h for h in state["history"] if h["stage"] == stage and not h["ok"]]
        raise SystemExit(
            "CIRCUIT BREAKER: etapa '%s' fallo %d veces (tope %d). NO se reintenta mas.\n"
            "Ultimos errores:\n%s\n"
            "Corrige la causa raiz y resetea con: python -m engine.pipeline reset %s"
            % (stage, n, MAX_STAGE_RETRIES + 1,
               "\n".join("  - " + f["detail"][:200] for f in fails[-3:]), stage))
    state["attempts"][stage] = n + 1
    _save_state(state)


def stage_audition(topic, language="es"):
    from engine import audition
    return audition.run(topic, language)


def _viewer_gate(checkpoint, *paths):
    """Filtro ESPECTADOR: corre DESPUES del gate tecnico de cada etapa.
    El QA tecnico pregunta 'esta correcto?'; este pregunta 'un humano en
    Instagram pararia el scroll, lo veria completo y le creeria?'. Sus
    hallazgos son decisiones creativas del director (hook, tono, medio),
    no de auto_remediate."""
    from engine import viewer_qa
    report = viewer_qa.run_checkpoint(checkpoint, *paths)
    if not report.get("ok"):
        raise RuntimeError("VIEWER QA %s fallo: score=%s%s" % (
            checkpoint, report.get("score"),
            (" | " + str(report.get("verdict"))[:180]) if report.get("verdict") else ""))


def stage_plan(plan_path):
    from engine import validate_plan, qa, preview
    # SHIFT-LEFT: antes del gate, el motor corrige los mismatches de medium OBVIOS
    # (plate deterministicamente demostrable -> clip real), para que el plan llegue
    # correcto sin que un humano tenga que decidir. Lo sutil lo cierra auto_remediate
    # con los hallazgos del juez. Ambos usan el MISMO criterio (medium_policy).
    if os.environ.get("NO_AUTO_REMEDIATE", "").lower() not in ("1", "true", "yes", "on"):
        try:
            from engine import medium_policy
            from engine import auto_remediate as _ar
            with open(plan_path, encoding="utf-8-sig") as f:
                _plan = json.load(f)
            # enforce salta escenas que el juez ya orillo a plate (sidecar):
            # sin esto, enforce y la remediacion post-juez oscilarian entre capas.
            _plan, _changes = medium_policy.enforce(_plan, skip_scenes=_ar.scenes_with_plate_base(plan_path))
            # Escalera: sube escenas image autoradas a clip_extractor/pexels (video
            # real) si MEDIA_ESCALERA prefiere clips y hay proveedor vivo. Cierra el
            # gap por el que los reels salian 100% foto generada. No-op si no hay
            # proveedor de video disponible.
            _plan, _up_changes = medium_policy.upgrade_media_escalera(_plan)
            # Colocacion del avatar en aha+cierre (auto, o completar si el director
            # puso menos de N). Corre DESPUES de enforce/upgrade: el visual ya
            # resuelto de la escena elegida pasa a ser el companion del avatar.
            _plan, _av_changes = medium_policy.place_avatar(_plan)
            _changes = (_changes or []) + (_up_changes or []) + (_av_changes or [])
            if _changes:
                with open(plan_path, "w", encoding="utf-8") as f:
                    json.dump(_plan, f, ensure_ascii=False, indent=1)
                print("[medium-policy] shift-left: %d cambio(s): %s" % (
                    len(_changes), ", ".join("#%d/%s" % (c["scene"], c.get("action", "?")) for c in _changes)))
        except Exception as _e:
            print("[medium-policy] enforce omitido (%s)" % str(_e)[:150])
    rc = validate_plan.main(plan_path)
    if rc:
        raise RuntimeError("validate_plan fallo (ver salida)")
    # Gate de guion AQUI y no solo en props: un guion que el juez rechazaria
    # debe rebotar antes de aprobar el plan (evita pasar plan y morir en props).
    script_report = qa.run_stage("script", plan_path)
    if not script_report.get("ok"):
        raise RuntimeError("AI QA script fallo: score=%s" % script_report.get("score"))
    _viewer_gate("script", plan_path)  # aprueba el guion (filtro espectador)
    report = qa.run_stage("plan", plan_path)
    if not report.get("ok"):
        raise RuntimeError("AI QA plan fallo: score=%s issues=%s" % (
            report.get("score"), [i.get("issue", "")[:80] for i in report.get("blocking_issues", [])[:3]]))
    preview.main_for(plan_path)
    _viewer_gate("motion", plan_path)  # aprueba motion graphics (contact sheet)
    return "PLAN OK + PREVIEW OK"


def stage_props(plan_path):
    from engine import voice, validate_props, qa
    voice.main(plan_path)  # valida plan + gates script/tts/plan + TTS + alignment + hook + props_build
    props_path = os.path.join(REMOTION_DIR, "props.json")
    rc = validate_props.main(props_path)
    if rc:
        raise RuntimeError("validate_props fallo")
    report = qa.run_stage("props", props_path)
    if not report.get("ok"):
        raise RuntimeError("AI QA props fallo: score=%s" % report.get("score"))
    _viewer_gate("broll", props_path)  # aprueba broll/media (filtro espectador)
    return "PROPS OK"


def stage_render():
    from engine import qa
    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    mp4 = os.path.join(out_dir, "reel.mp4")
    res = subprocess.run(
        ["npx", "remotion", "render", "Reel", mp4, "--props=%s" % os.path.join(REMOTION_DIR, "props.json")],
        cwd=REMOTION_DIR, capture_output=True, text=True, shell=(os.name == "nt"), env=subprocess_env())
    if res.returncode != 0:
        raise RuntimeError("remotion render fallo:\n%s" % res.stderr[-800:])
    report = qa.run_stage("render", mp4, os.path.join(REMOTION_DIR, "props.json"))
    if not report.get("ok"):
        raise RuntimeError("AI QA render fallo: score=%s" % report.get("score"))
    _viewer_gate("final", mp4, os.path.join(REMOTION_DIR, "props.json"))  # aprueba video final
    return "RENDER OK: %s" % mp4


def main():
    ap = argparse.ArgumentParser(description="reel-engine-v2 pipeline")
    ap.add_argument("stage", choices=["audition", "plan", "props", "render", "full", "reset", "status"])
    ap.add_argument("plan", nargs="?", help="contracts/<plan>.json")
    ap.add_argument("--topic", default=os.environ.get("TOPIC", ""))
    ap.add_argument("--language", default=os.environ.get("SCRIPT_LANGUAGE", "es"),
                     help="Idioma del guion para la etapa audition: es (default) | en")
    args = ap.parse_args()
    ensure_dirs()
    state = _load_state()

    if args.stage == "status":
        print(json.dumps(state, ensure_ascii=False, indent=1))
        return
    if args.stage == "reset":
        target = args.plan  # segundo posicional reutilizado como nombre de etapa
        if target:
            state["attempts"].pop(target, None)
        else:
            state["attempts"] = {}
        _save_state(state)
        print("intentos reseteados: %s" % (target or "todos"))
        return

    stages = [args.stage] if args.stage != "full" else ["plan", "props", "render"]
    if args.stage in ("plan", "props", "full") and not args.plan:
        raise SystemExit("falta el path del plan")
    no_auto = os.environ.get("NO_AUTO_REMEDIATE", "").lower() in ("1", "true", "yes", "on")
    for stage in stages:
        _check_budget(state, stage)
        while True:
            try:
                if stage == "audition":
                    out = stage_audition(args.topic, args.language)
                elif stage == "plan":
                    out = stage_plan(args.plan)
                elif stage == "props":
                    out = stage_props(args.plan)
                else:
                    out = stage_render()
                break
            # SystemExit de los gates (validadores/QA) TAMBIEN cuenta como intento
            # fallido: el circuit breaker debe ver todos los fallos.
            except (Exception, SystemExit) as e:
                # CIERRA EL LOOP: en vez de bloquear y preguntarle al humano si la
                # solucion es cambiar el medium, el motor consume los hallazgos del
                # juez, aplica el transform de medium y REINTENTA el mismo stage
                # con el plan corregido -- sin quemar el circuit breaker (el cap
                # vive en auto_remediate). Solo si no hay nada que remediar, falla.
                remedy = None
                if not no_auto and stage in ("plan", "props", "render") and args.plan:
                    try:
                        from engine import auto_remediate
                        remedy = auto_remediate.try_auto_remediate(stage, args.plan)
                    except Exception as re:
                        print("[auto-remediate] error (ignorado): %s" % str(re)[:200])
                if remedy is not None and remedy.changed:
                    _record(state, stage, False, "auto-remediado: %s" % remedy.detail)
                    _save_state(state)
                    print("[auto-remediate] %s: %s -> reintento sin gastar intento" % (stage, remedy.detail))
                    continue
                _record(state, stage, False, str(e))
                raise SystemExit("ETAPA '%s' FALLO (intento %d/%d): %s" % (
                    stage, state["attempts"][stage], MAX_STAGE_RETRIES + 1, str(e)[:400]))
        _record(state, stage, True, out)
        state["attempts"][stage] = 0  # exito resetea el presupuesto de esa etapa
        _save_state(state)
        print("[%s] %s" % (stage, out))


if __name__ == "__main__":
    main()
