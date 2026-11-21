# -*- coding: utf-8 -*-
"""Filtro ESPECTADOR: el ultimo gate de cada etapa (mandato del dueno 2026-07-05).

qa.py es el QA Director: verifica correccion tecnica/semantica (anchors,
colisiones, contradicciones, consistencia de producto). Este modulo agrega la
pregunta que ningun juez tecnico hace: un humano promedio en Instagram,
pararia el scroll? lo veria hasta el final? le suena a sermon? le cree?
Persona de consumidor impaciente, no de director.

Checkpoints (cada uno corre DESPUES de que el gate tecnico de su etapa paso):
  script -> stage plan   (aprueba el guion: dolor real del hook, tono, oralidad)
  motion -> stage plan   (aprueba motion graphics: contact sheet de overlays/plates)
  broll  -> stage props  (aprueba broll/media: look IA, producto creible, avatar humano)
  final  -> stage render (aprueba video final: las 4 preguntas + segundo de fuga)

ANTI-VARIANZA (leccion de la corrida real 2026-07-05: 7 evaluaciones del mismo
render dieron 7 hallazgos distintos y mutuamente contradictorios, varios
describiendo elementos inexistentes en el frame): cada checkpoint corre
VIEWER_RUNS veces y un blocker solo bloquea si PERSISTE (mismo id+scene) en
TODAS las corridas; el que no persiste se degrada a major anotado como
varianza. El score es el promedio. La persistencia es el mismo criterio que
uso el humano para separar el hallazgo real (pseudo-etiqueta: 2/2 corridas)
de las alucinaciones (texto 'cortado' inexistente: 1/7).

Los hallazgos de este juez son decisiones CREATIVAS (hook, tono, medio, casting
del visual): el fix es del director, no de auto_remediate. Por eso sus reportes
viven en viewer_{checkpoint}_latest.json y auto_remediate no los consume.
"""
import argparse
import datetime as dt
import json
import os
import sys

from engine import qa
from engine import _generated as GEN
from engine.config import ROOT

WORK = qa.WORK  # work/ai_qa
RUBRIC_VERSION = 1
CHECKPOINTS = ("script", "motion", "broll", "final")


def _min_score():
    return int(os.environ.get("VIEWER_QA_MIN_SCORE", str(getattr(GEN, "VIEWER_MIN_SCORE", 70))))


def _runs():
    return max(1, int(os.environ.get("VIEWER_QA_RUNS", str(getattr(GEN, "VIEWER_RUNS", 2)))))


def enabled():
    return qa.env_bool("VIEWER_QA_ENABLED", True)


def required():
    return qa.env_bool("VIEWER_QA_REQUIRED", True)


def default_out(checkpoint):
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, "viewer_%s_latest.json" % checkpoint)


def _neutralized_reasons():
    reasons = []
    if qa.provider() == "mock":
        reasons.append("AI_QA_PROVIDER=mock")
    if not enabled():
        reasons.append("VIEWER_QA_ENABLED=0")
    if not required():
        reasons.append("VIEWER_QA_REQUIRED=0")
    return reasons


SYSTEM_PROMPT = """Eres una persona promedio de 25-45 anios haciendo scroll en Instagram Reels de noche, con el pulgar listo para seguir de largo. NO eres director, NO eres QA, no conoces la jerga de este motor y no te importa: juzgas SOLO como consumidor que decide en 1 segundo.
Tu unico trabajo: decidir si este contenido te para el scroll, te retiene hasta el final, te suena a sermon, y te da confianza. Se brutalmente honesto en AMBAS direcciones: no perdones contenido flojo, pero tampoco inventes defectos para sonar critico -- si lo verias completo, dilo y aprueba.
NO evalues tecnica interna (anchors, colisiones de layout, SFX, timing de captions, consistencia de props): eso ya lo reviso otro juez antes que tu. Tu miras/escuchas lo que un espectador ve, punto.
Devuelve SOLO JSON valido:
{
  "ok": true/false,
  "score": 0-100,
  "subscores": {"scroll_stop": 0-25, "watch_through": 0-25, "tone": 0-25, "trust": 0-25},
  "drop_second": <segundo aproximado en que un espectador impaciente se iria, o null si aguanta completo>,
  "verdict": "<tu veredicto en 1-2 frases, como se lo contarias a un amigo>",
  "blocking_issues": [{"id":"defecto_en_snake_case","severity":"blocker|major|minor","scene":0,"issue":"...","fix":"..."}],
  "warnings": ["..."],
  "notes": "..."
}
score = scroll_stop + watch_through + tone + trust.
IDs ESTABLES: el id nombra el DEFECTO, no tu frase. Ejemplos canonicos: hook_sin_dolor, tono_sermon, pantalla_powerpoint, look_ia_generico, manos_raras, frasco_sin_etiqueta, avatar_ojos_cerrados, relleno_educativo, cta_vendedor. Mismo defecto = mismo id siempre.
SEVERIDAD: blocker = jamas pararias el scroll, o te iras antes del 40%, o no le creerias nada; major = te molesta pero quiza sigues; minor = detalle. No uses blocker para gustos personales."""


def _prev_block(checkpoint, artifact):
    """Memoria del juez (mismo patron que qa.py): sin ella cada ronda re-litiga
    lo aceptado. Gateada por rubric_version y artifact."""
    try:
        prev = qa.load_json(default_out(checkpoint))
        if prev.get("checkpoint") == checkpoint and prev.get("artifact") == artifact \
                and prev.get("rubric_version") == RUBRIC_VERSION:
            return (
                "TU REPORTE ANTERIOR sobre una version previa de ESTE contenido (ya corregida):\n"
                "score=%s\nissues=%s\n"
                "REGLA DE CONSISTENCIA: evalua primero si cada issue anterior fue resuelto. NO reabras "
                "aspectos que antes no marcaste, salvo evidencia NUEVA introducida por la correccion. "
                "Contenido que resolvio tus blockers sin crear problemas nuevos debe aprobar.\n"
                % (prev.get("score"), json.dumps([
                    {"id": i.get("id"), "scene": i.get("scene"), "issue": str(i.get("issue"))[:160]}
                    for i in (prev.get("blocking_issues") or [])[:8]
                ], ensure_ascii=False))
            )
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Contexto por checkpoint: (user_prompt, images, artifact)

def _script_ctx(plan_path):
    plan = qa.load_json(plan_path)
    artifact = os.path.abspath(plan_path)
    meta = plan.get("meta") or {}
    user = (
        "CHECKPOINT=GUION. Todavia no hay nada filmado: solo el guion que se narrara, su hook y su CTA. "
        "Imagina que te lo narran sobre visuales tipicos del tema.\n"
        + _prev_block("script", artifact)
        + "Responde como espectador:\n"
        "1) SCROLL (scroll_stop): el hook te toca un dolor/deseo que TU ya tienes, o niega una creencia "
        "que nadie tiene? Un hook que responde una pregunta que el espectador nunca se hizo = hook_sin_dolor. "
        "El dolor real del nicho suele ser 'gaste plata/tiempo y sigo igual', no una premisa tecnica.\n"
        "2) RETENCION (watch_through): en que parte te aburres? La promesa del hook se paga a tiempo? "
        "Si el mensaje cabe en menos segundos que el objetivo, el relleno es un hallazgo (relleno_educativo).\n"
        "3) TONO (tone): conversacion de igual a igual o profesor con dedo levantado? Sermon/regano/clase "
        "= tono_sermon. La honestidad sin regano SUMA confianza.\n"
        "4) CONFIANZA (trust): alguna frase suena a vendedor o claim inflado (cta_vendedor)? Y al reves: "
        "que frase te hace confiar mas? Nombrala en notes.\n"
        "5) ORALIDAD: frases que nadie diria en voz alta a un amigo.\n"
        "Duracion objetivo: %ss.\n"
        "GUION JSON:\n%s" % (
            meta.get("target_seconds"),
            json.dumps(qa.script_payload(plan), ensure_ascii=False, indent=2),
        )
    )
    return user, [], artifact


def _motion_ctx(plan_path):
    """Input VERAZ para el juez de motion (leccion 2026-07-06): el contact sheet
    completo mostraba las escenas media-backed como pantallas negras con una
    palabra (preview renderiza SIN media por diseno) y la VISION le gana a la
    instruccion -- el juez dictamino 'PowerPoint oscuro' sobre 9 celdas que
    llevaran foto real (score 53, mayoria falsos positivos). Ahora se adjuntan
    SOLO los stills que puede juzgar tal cual: plates/CTA (se veran asi en el
    final) y escenas con overlay declarado (para aprobar el grafico, con
    etiqueta POR IMAGEN de que debajo habra foto). Los captions quedan fuera
    explicitamente: word_pop congelado en 1 frame parece 'card con palabra
    suelta' pero es un subtitulo animado; los juzga el checkpoint final."""
    plan = qa.load_json(plan_path)
    artifact = os.path.abspath(plan_path)
    prev_dir = os.path.join(ROOT, "work", "preview")
    if not os.path.isdir(prev_dir):
        raise RuntimeError("no existe work/preview/; corre la etapa plan (preview) primero")

    # Overlays -> escena con la MISMA resolucion sintetica que uso preview.
    from engine import resolve as plan_resolve
    from engine.preview import rough_alignment
    resolved = plan_resolve.resolve(plan, rough_alignment(plan.get("script") or ""))
    r_scenes = resolved.get("scenes") or []
    overlay_scenes = set()
    for o in resolved.get("overlays") or []:
        start = int(o.get("startMs") or 0)
        for i, rs in enumerate(r_scenes):
            if int(rs.get("fromMs") or 0) <= start < int(rs.get("toMs") or 0):
                overlay_scenes.add(i)
                break

    scenes = plan.get("scenes") or []
    images, labels = [], []
    media_backed = 0
    for i, s in enumerate(scenes):
        clip = s.get("clip") if isinstance(s.get("clip"), dict) else {}
        src = clip.get("source")
        text_base = (s.get("role") == "plate") or src in (None, "", "none")
        if not text_base:
            media_backed += 1
        if not text_base and i not in overlay_scenes:
            continue  # foto/clip sin grafico encima: nada que aprobar en este checkpoint
        still = os.path.join(prev_dir, "prev_%02d_scene%02d_%s.png" % (i, i, s.get("role") or "broll"))
        if not os.path.exists(still):
            continue
        images.append(still)
        labels.append({
            "image_index": len(images),
            "scene": i,
            "role": s.get("role"),
            "se_vera_asi_en_el_final": bool(text_base),
            "nota": (
                "Pantalla de texto/tarjeta REAL del reel final: juzgala tal cual."
                if text_base else
                "Debajo de este grafico habra FOTO/VIDEO real que el preview NO muestra: juzga SOLO el "
                "grafico (legibilidad de un vistazo, jerarquia, si aporta algo que la voz no dice)."
            ),
        })
    cta_still = os.path.join(prev_dir, "prev_%02d_cta.png" % len(scenes))
    if os.path.exists(cta_still):
        images.append(cta_still)
        labels.append({
            "image_index": len(images),
            "scene": "cta",
            "se_vera_asi_en_el_final": True,
            "nota": "Tarjeta CTA en su momento medio: juzgala tal cual.",
        })
    if not images:
        raise RuntimeError("no hay stills de preview aplicables; corre la etapa plan (preview) primero")

    hard_fact = (
        "DATO DURO del plan (no adivines la proporcion): %d de %d escenas llevan foto/video REAL de fondo "
        "en el render final. Esas fotos NO estan adjuntas (el preview no genera media cara). NO juzgues la "
        "proporcion media/texto ni digas que el reel 'es puro texto': eso lo valida otro gate deterministico.\n"
        % (media_backed, len(scenes))
    )
    user = (
        "CHECKPOINT=MOTION_GRAPHICS. Las imagenes adjuntas son SOLO las pantallas que puedes juzgar tal "
        "cual: tarjetas/plates que se veran asi en el reel final, y graficos (listas, comparativas, "
        "palabras clave) que en el reel final van COMPUESTOS SOBRE foto/video real. Lee la nota de CADA "
        "imagen antes de juzgarla.\n"
        + hard_fact
        + _prev_block("motion", artifact)
        + "IGNORA los captions (la palabra suelta tipo pill cerca del centro/abajo): son subtitulos "
        "palabra-por-palabra congelados en un frame por el preview, NO son tarjetas ni cards; los juzga "
        "otro checkpoint sobre el video real en movimiento.\n"
        "Como espectador, juzga SOLO los graficos adjuntos:\n"
        "1) El texto grande de cada grafico se lee de UN vistazo (1 segundo)? Si hay que leer parrafos, dilo.\n"
        "2) Cada grafico aporta algo que la voz no dice (estructura, contraste, jerarquia), o es relleno "
        "bonito? El grafico que solo repite la locucion es candidato a sobrar.\n"
        "3) Entre las pantallas marcadas se_vera_asi_en_el_final=true: alguna se siente diapositiva de "
        "PowerPoint que te haria seguir de largo? = pantalla_powerpoint.\n"
        "IMAGENES ADJUNTAS:\n%s\n"
        "GUION (lo que la voz narra):\n%s" % (
            json.dumps(labels, ensure_ascii=False, indent=2),
            qa.compact_text(plan.get("script"), 2500),
        )
    )
    return user, images, artifact


def _broll_ctx(props_path):
    props = qa.load_json(props_path)
    artifact = os.path.abspath(props_path)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    max_images = int(os.environ.get("AI_QA_PROPS_MAX_IMAGES", "30") or 30)
    images, labels = qa.sample_media_images(
        props, os.path.join(WORK, "viewer_broll_frames_%s" % stamp), max_images=max_images)
    user = (
        "CHECKPOINT=BROLL. Las imagenes adjuntas son la media real de cada escena (SIN los overlays "
        "graficos que se componen encima). caption_text en cada label te dice que se narra sobre esa media.\n"
        + _prev_block("broll", artifact)
        + "Miralas como consumidor, no como tecnico:\n"
        "1) LOOK IA/STOCK (trust): alguna se siente 'contenido generico de marca hecho con IA'? Personas "
        "demasiado perfectas, fondos plasticos, iluminacion irreal = look_ia_generico. Manos/anatomia "
        "raras = manos_raras.\n"
        "2) PRODUCTO CREIBLE (trust): el producto se ve como algo que existe y comprarias? Un envase 100%% "
        "liso sin etiqueta cuando la narracion habla de etiquetas/marcas/comprar resta credibilidad = "
        "frasco_sin_etiqueta. Fix valido: una etiqueta LEGIBLE con marca INVENTADA creible (o un clip/asset "
        "real de producto). Lo unico que sigue siendo defecto es el texto DEFORME/garabateado dentro de la "
        "imagen o una marca real que el guion no menciona, no la etiqueta en si.\n"
        "3) AVATAR HUMANO (trust): si hay presentador, parece hablar natural CON OJOS ABIERTOS mirando a "
        "camara en la MAYORIA de sus muestras? Un frame parpadeando es normal; ojos cerrados en la mayoria "
        "= avatar_ojos_cerrados (blocker: parece dormido/IA y mata la confianza justo donde deberia darla).\n"
        "4) ESCENIFICACION (watch_through): cada media dramatiza lo que su caption dice, o es wallpaper "
        "decorativo intercambiable?\n"
        "IMAGENES ADJUNTAS:\n%s" % json.dumps(labels, ensure_ascii=False, indent=2)
    )
    return user, images, artifact


def _final_ctx(mp4, props_path):
    props = qa.load_json(props_path)
    artifact = os.path.abspath(mp4)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    images, labels = qa.sample_render_images(mp4, props, os.path.join(WORK, "viewer_final_frames_%s" % stamp))
    narration = qa.compact_text(
        " ".join(qa.caption_token(c) for c in (props.get("captions") or []) if qa.caption_token(c)), 2500)
    cta = props.get("cta") or {}
    user = (
        "CHECKPOINT=VIDEO_FINAL. Frames del MP4 final (1 por escena + contact sheet 2fps del video "
        "completo) mas la narracion. Este es el ULTIMO filtro antes de publicar.\n"
        + _prev_block("final", artifact)
        + "Las 4 preguntas del espectador (responde las 4 en notes, sin rodeos):\n"
        "1) PARARIAS el scroll en el primer segundo? Por que si o no? El 80%% ve sin audio: el primer "
        "frame comunica SOLO (sin voz) de que va y por que me importa?\n"
        "2) Lo verias HASTA EL FINAL? drop_second es OBLIGATORIO: el segundo aproximado donde el "
        "espectador impaciente se va (o null si aguanta). Racha de pantallas de texto = donde se suelta.\n"
        "3) Es PREACHY o aburrido? Sermon, clase, dedo levantado, exceso de letra.\n"
        "4) Te da CONFIANZA? Guardarias/compartirias/harias el CTA ('%s')? Que se siente IA-generico y "
        "que se siente humano-real?\n"
        "No re-litigues layout tecnico (eso ya paso QA); juzga la EXPERIENCIA de verlo.\n"
        "DURACION: %.1fs\n"
        "NARRACION COMPLETA:\n%s\n"
        "FRAMES ADJUNTOS:\n%s" % (
            cta.get("button") or cta.get("text") or "",
            (props.get("totalMs") or 0) / 1000.0,
            narration,
            json.dumps(labels, ensure_ascii=False, indent=2),
        )
    )
    return user, images, artifact


_CTX = {"script": _script_ctx, "motion": _motion_ctx, "broll": _broll_ctx, "final": _final_ctx}


# ---------------------------------------------------------------------------
# Fusion anti-varianza de N corridas

def _issue_key(it):
    return (str(it.get("id") or "").strip().lower(), it.get("scene"))


def _int_or(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def _merge_runs(raws):
    n = len(raws)
    score = int(round(sum(_int_or(r.get("score")) for r in raws) / max(1, n)))
    subs = {}
    for k in ("scroll_stop", "watch_through", "tone", "trust"):
        vals = [_int_or((r.get("subscores") or {}).get(k), None) for r in raws]
        vals = [v for v in vals if v is not None]
        subs[k] = int(round(sum(vals) / len(vals))) if vals else None
    drops = [r.get("drop_second") for r in raws if isinstance(r.get("drop_second"), (int, float))]
    drop = round(sum(drops) / len(drops), 1) if drops else None

    # Persistencia: un blocker solo sigue siendo blocker si aparece (mismo
    # id+scene) en TODAS las corridas. Lo demas se degrada a major anotado.
    per_run_keys = []
    for r in raws:
        keys = set()
        for it in (r.get("blocking_issues") or []):
            if isinstance(it, dict) and str(it.get("severity", "")).lower() in ("blocker", "critical"):
                keys.add(_issue_key(it))
        per_run_keys.append(keys)
    persistent = set.intersection(*per_run_keys) if per_run_keys else set()

    merged, seen = [], set()
    for r in raws:
        for it in (r.get("blocking_issues") or []):
            if not isinstance(it, dict):
                continue
            key = _issue_key(it)
            if key in seen:
                continue
            seen.add(key)
            it = dict(it)
            sev = str(it.get("severity", "")).lower()
            if sev in ("blocker", "critical") and key not in persistent and n > 1:
                count = sum(1 for ks in per_run_keys if key in ks)
                it["severity"] = "major"
                it["issue"] = "[varianza del juez: %d/%d corridas] %s" % (count, n, it.get("issue", ""))
            merged.append(it)

    warnings = []
    for r in raws:
        for w in (r.get("warnings") or []):
            if w not in warnings:
                warnings.append(w)
    verdicts = [str(r.get("verdict") or "").strip() for r in raws if str(r.get("verdict") or "").strip()]
    return {
        "score": score,
        "subscores": subs,
        "drop_second": drop,
        "verdict": verdicts[0] if verdicts else "",
        "all_verdicts": verdicts,
        "blocking_issues": merged,
        "warnings": warnings,
        "notes": " | ".join(qa.compact_text(r.get("notes"), 400) for r in raws if r.get("notes")),
    }


# ---------------------------------------------------------------------------

def run_checkpoint(checkpoint, *paths):
    """Corre el filtro espectador de un checkpoint y devuelve el reporte dict.
    Escribe work/ai_qa/viewer_{checkpoint}_latest.json (memoria del juez)."""
    if checkpoint not in CHECKPOINTS:
        raise ValueError("checkpoint invalido: %s (validos: %s)" % (checkpoint, ", ".join(CHECKPOINTS)))
    out = default_out(checkpoint)
    threshold = _min_score()

    neutralized = _neutralized_reasons()
    if qa.production_mode() and neutralized:
        report = _base_report(checkpoint, paths[0] if paths else None, threshold, ok=False, score=0)
        report["blocking_issues"] = [{
            "id": "viewer_qa_neutralized_in_production",
            "severity": "blocker",
            "scene": None,
            "issue": "PROVIDER_MODE=real pero el filtro espectador esta neutralizado: %s." % ", ".join(neutralized),
            "fix": "En produccion el filtro espectador es obligatorio (mismo contrato que el juez tecnico).",
        }]
        qa.dump_report(report, out)
        print("VIEWER QA FAIL: %s neutralizado en produccion (%s)" % (checkpoint, ", ".join(neutralized)))
        return report
    if not enabled():
        report = _base_report(checkpoint, paths[0] if paths else None, threshold, ok=True, score=100)
        report["warnings"] = ["VIEWER_QA_ENABLED=0"]
        report["skipped"] = True
        qa.dump_report(report, out)
        print("VIEWER QA SKIP: VIEWER_QA_ENABLED=0")
        return report

    try:
        user, images, artifact = _CTX[checkpoint](*paths)
        vision = bool(images)
        raws = []
        for _ in range(_runs()):
            raws.append(qa.call_ai_json(SYSTEM_PROMPT, user, images=images, vision_required=vision))
        merged = _merge_runs(raws)
        has_blocker = any(
            str(i.get("severity", "")).lower() in ("blocker", "critical")
            for i in merged["blocking_issues"] if isinstance(i, dict))
        ok = merged["score"] >= threshold and not has_blocker
        report = _base_report(checkpoint, artifact, threshold, ok=ok, score=merged["score"])
        report.update({
            "runs": len(raws),
            "subscores": merged["subscores"],
            "drop_second": merged["drop_second"],
            "verdict": merged["verdict"],
            "all_verdicts": merged["all_verdicts"],
            "blocking_issues": merged["blocking_issues"],
            "warnings": merged["warnings"],
            "notes": merged["notes"],
            "raw_runs": raws,
        })
    except Exception as e:
        report = _base_report(checkpoint, paths[0] if paths else None, threshold, ok=False, score=0)
        report["blocking_issues"] = [{
            "id": "viewer_qa_runtime",
            "severity": "blocker",
            "scene": None,
            "issue": str(e)[:400],
            "fix": "Corrige el proveedor AI_QA_PROVIDER o el artefacto de entrada.",
        }]

    qa.dump_report(report, out)
    if report["ok"]:
        print("VIEWER QA OK: %s score=%s drop=%s report=%s" % (
            checkpoint, report["score"], report.get("drop_second"), out))
    else:
        print("VIEWER QA FAIL: %s score=%s drop=%s report=%s" % (
            checkpoint, report["score"], report.get("drop_second"), out))
        if report.get("verdict"):
            print("  veredicto: %s" % report["verdict"])
        for item in report.get("blocking_issues") or []:
            if isinstance(item, dict):
                print("  %s scene=%s [%s]: %s" % (
                    item.get("severity", "issue"), item.get("scene"), item.get("id"),
                    str(item.get("issue"))[:200]))
    if not report["ok"] and not required():
        report = dict(report)
        report["ok"] = True
        report["warnings"] = list(report.get("warnings") or []) + ["VIEWER_QA_REQUIRED=0: fallo ignorado"]
    return report


def _base_report(checkpoint, artifact, threshold, ok, score):
    return {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stage": "viewer_%s" % checkpoint,
        "checkpoint": checkpoint,
        "provider": qa.provider(),
        "artifact": os.path.abspath(artifact) if artifact else None,
        "rubric_version": RUBRIC_VERSION,
        "ok": ok,
        "score": score,
        "min_score": threshold,
        "blocking_issues": [],
        "warnings": [],
    }


def main():
    parser = argparse.ArgumentParser(description="Filtro espectador (viewer QA) de Reel Engine")
    parser.add_argument("checkpoint", choices=list(CHECKPOINTS))
    parser.add_argument("paths", nargs="+", help="script/motion: plan.json | broll: props.json | final: reel.mp4 props.json")
    args = parser.parse_args()
    report = run_checkpoint(args.checkpoint, *args.paths)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
