#!/usr/bin/env python3
"""AI QA gates for Reel Engine.

The deterministic scripts still verify mechanics (JSON, files, ffprobe, audio).
This script is the blocking creative/semantic reviewer at each pipeline border:
plan, props/assets and rendered MP4.
"""
import argparse
import base64
import datetime as dt
import json
import math
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from array import array

from engine.config import ROOT, REMOTION_DIR as _REM, WORK_DIR as _WORK  # V2PORT
# Fuente UNICA del criterio de medium (antes duplicado en prosa en plan_qa/render_qa).
from engine.medium_policy import CLAIM_GENRE_CRITERION as MEDIUM_CRITERION
from engine.medium_policy import CRITERION_VERSION
REMOTION = os.path.join(ROOT, "remotion")
PUBLIC = os.path.join(REMOTION, "public")
PUBLIC_MEDIA = os.path.join(PUBLIC, "media")
WORK = os.path.join(ROOT, "work", "ai_qa")

from engine import media_tools
from engine import _generated as GEN  # V2PORT: registro unico


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return bool(default)
    return raw.lower() in ("1", "true", "yes", "on")


def enabled():
    return env_bool("AI_QA_ENABLED", True)


def required():
    return env_bool("AI_QA_REQUIRED", True)


def provider():
    return (os.environ.get("AI_QA_PROVIDER") or os.environ.get("LLM_PROVIDER") or "codex").lower()


def production_mode():
    """True cuando la corrida es productiva (PROVIDER_MODE=real)."""
    return os.environ.get("PROVIDER_MODE", "mock").lower() == "real"


def qa_gate_bypass_enabled():
    return env_bool("ALLOW_QA_GATE_BYPASS", False)


def production_judge_neutralized():
    """Lista de flags que apagan el juez semantico. Vacia = juez activo.

    En produccion (PROVIDER_MODE=real) ninguno de estos debe estar activo: el
    juez LLM es la unica defensa de la mitad semantica de varios criterios
    (C1/C2/C3/C4/C5/C8/C9). Si se neutraliza, esas garantias desaparecen sin
    que ningun otro gate lo note.
    """
    reasons = []
    if provider() == "mock":
        reasons.append("AI_QA_PROVIDER=mock")
    if not enabled():
        reasons.append("AI_QA_ENABLED=0")
    if not required():
        reasons.append("AI_QA_REQUIRED=0")
    if qa_gate_bypass_enabled():
        reasons.append("ALLOW_QA_GATE_BYPASS=1")
    return reasons


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def dump_report(report, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def compact_text(text, limit=1200):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def json_from_text(text):
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    m = re.search(r"\{.*\}", cleaned, re.S)
    if not m:
        raise RuntimeError("AI QA no devolvio JSON: %s" % cleaned[:500])
    return json.loads(m.group(0))


def data_url(path):
    ext = os.path.splitext(path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    with open(path, "rb") as f:
        return "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode("ascii"))


def _gemini_upload_file(path, key):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    size = os.path.getsize(path)
    start_url = "https://generativelanguage.googleapis.com/upload/v1beta/files?key=%s" % urllib.parse.quote(key, safe="")
    start_body = json.dumps({"file": {"display_name": os.path.basename(path)}}).encode("utf-8")
    request = urllib.request.Request(start_url, data=start_body, method="POST", headers={
        "Content-Type": "application/json",
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(size),
        "X-Goog-Upload-Header-Content-Type": mime,
    })
    with urllib.request.urlopen(request, timeout=int(os.environ.get("AI_QA_UPLOAD_TIMEOUT", "600"))) as response:
        upload_url = response.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError("Gemini Files no devolvio URL de upload")
    with open(path, "rb") as handle:
        payload = handle.read()
    request = urllib.request.Request(upload_url, data=payload, method="POST", headers={
        "Content-Length": str(size),
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize",
    })
    with urllib.request.urlopen(request, timeout=int(os.environ.get("AI_QA_UPLOAD_TIMEOUT", "600"))) as response:
        uploaded = json.loads(response.read().decode("utf-8"))
    file_info = uploaded.get("file") or uploaded
    name = str(file_info.get("name") or "")
    deadline = time.time() + int(os.environ.get("AI_QA_FILE_PROCESS_TIMEOUT", "600"))
    while str(file_info.get("state") or "").upper() not in {"ACTIVE", "FAILED"} and time.time() < deadline:
        time.sleep(2)
        status_url = "https://generativelanguage.googleapis.com/v1beta/%s?key=%s" % (name, urllib.parse.quote(key, safe=""))
        with urllib.request.urlopen(status_url, timeout=60) as response:
            file_info = json.loads(response.read().decode("utf-8"))
    if str(file_info.get("state") or "").upper() != "ACTIVE":
        raise RuntimeError("Gemini Files no activo el archivo: %s" % str(file_info.get("state") or "timeout"))
    return file_info


def _gemini_delete_file(name, key):
    if not name:
        return
    url = "https://generativelanguage.googleapis.com/v1beta/%s?key=%s" % (name, urllib.parse.quote(key, safe=""))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=60):
            pass
    except Exception:
        pass


def _gemini_ai_json(system_prompt, user_prompt, images=None, files=None):
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY no configurada para QA fallback")
    model = os.environ.get("GEMINI_QA_MODEL", "gemini-2.5-flash")
    parts = [{"text": system_prompt + "\n\n" + user_prompt}]
    for path in images or []:
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as handle:
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(handle.read()).decode("ascii")}})
    uploaded = []
    try:
        for path in files or []:
            info = _gemini_upload_file(path, key)
            uploaded.append(info)
            parts.append({"file_data": {"mime_type": str(info.get("mimeType") or mimetypes.guess_type(path)[0] or "application/octet-stream"), "file_uri": info["uri"]}})
    except Exception:
        for info in uploaded:
            _gemini_delete_file(str(info.get("name") or ""), key)
        raise
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (urllib.parse.quote(model, safe=""), urllib.parse.quote(key, safe=""))
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={"Content-Type": "application/json"})
    try:
        try:
            with urllib.request.urlopen(req, timeout=int(os.environ.get("AI_QA_TIMEOUT", "600"))) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError("Gemini QA HTTP %s: %s" % (exc.code, exc.read()[:300])) from exc
    finally:
        for info in uploaded:
            _gemini_delete_file(str(info.get("name") or ""), key)
    candidates = payload.get("candidates") or []
    text = "".join(part.get("text", "") for part in ((candidates[0].get("content") or {}).get("parts") or [])) if candidates else ""
    if not text:
        raise RuntimeError("Gemini QA no devolvio texto")
    return json_from_text(text)


def _local_vision_ai_json(system_prompt, user_prompt, images=None):
    base = os.environ.get("LOCAL_VISION_BASE_URL", "http://127.0.0.1:18101/v1").rstrip("/")
    model = os.environ.get("LOCAL_VISION_MODEL", "gemma-local")
    content = [{"type": "text", "text": user_prompt}]
    for path in images or []:
        content.append({"type": "image_url", "image_url": {"url": data_url(path)}})
    body = {"model": model, "temperature": 0.1, "max_tokens": int(os.environ.get("AI_QA_MAX_TOKENS", "1400")), "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}]}
    headers = {"Content-Type": "application/json"}
    if os.environ.get("LOCAL_VISION_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["LOCAL_VISION_API_KEY"]
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get("AI_QA_TIMEOUT", "240"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Local vision HTTP %s: %s" % (exc.code, exc.read()[:300])) from exc
    text = str((((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""))
    if not text:
        raise RuntimeError("Local vision no devolvio texto")
    return json_from_text(text)


def _fallback_ai_json(system_prompt, user_prompt, images):
    failures = []
    chain = [item.strip().lower() for item in os.environ.get("AI_QA_FALLBACK_CHAIN", os.environ.get("AI_QA_FALLBACK_PROVIDER", "")).split(",") if item.strip()]
    for fallback in chain:
        try:
            if fallback in ("gemini", "google"):
                return _gemini_ai_json(system_prompt, user_prompt, images=images)
            if fallback in ("local", "local-vision", "gemma-vision", "spark-vision"):
                return _local_vision_ai_json(system_prompt, user_prompt, images=images)
        except Exception as exc:
            failures.append("%s: %s" % (fallback, str(exc)[:180]))
    raise RuntimeError("fallbacks QA agotados: " + " | ".join(failures))


def call_ai_json(system_prompt, user_prompt, images=None, vision_required=False):
    images = images or []
    p = provider()
    if p == "mock":
        return {"ok": True, "score": 100, "blocking_issues": [], "warnings": ["AI_QA_PROVIDER=mock"], "notes": "mock"}
    if p in ("codex", "real", "codex-oauth"):
        from providers import codex_oauth
        content = [{"type": "input_text", "text": user_prompt}]
        for path in images:
            content.append({"type": "input_image", "image_url": data_url(path)})
        try:
            text = codex_oauth.responses(
                [{"role": "user", "content": content}],
                instructions=system_prompt,
                timeout=int(os.environ.get("AI_QA_TIMEOUT", "240")),
            )
            return json_from_text(text)
        except Exception:
            if os.environ.get("AI_QA_FALLBACK_CHAIN") or os.environ.get("AI_QA_FALLBACK_PROVIDER"):
                return _fallback_ai_json(system_prompt, user_prompt, images)
            raise
    if images and vision_required:
        return {
            "ok": False,
            "score": 0,
            "blocking_issues": [{
                "id": "vision_provider_missing",
                "severity": "blocker",
                "scene": None,
                "issue": "AI_QA_PROVIDER=%s no puede revisar imagenes/video." % p,
                "fix": "Usa AI_QA_PROVIDER=codex para QA visual o desactiva AI_QA_REQUIRED solo en pruebas.",
            }],
            "warnings": [],
        }
    if p in ("gemma", "spark", "vllm", "openai-compatible", "compat", "litellm"):
        import llm
        base = (
            os.environ.get("VLLM_BASE_URL")
            or os.environ.get("LLM_BASE_URL")
            or os.environ.get("LITELLM_BASE_URL")
            or "http://spark:18100/v1"
        )
        model = os.environ.get("VLLM_MODEL") or os.environ.get("LLM_MODEL") or os.environ.get("LITELLM_MODEL") or "gemma-local"
        key = os.environ.get("VLLM_API_KEY") or os.environ.get("LLM_API_KEY") or os.environ.get("LITELLM_API_KEY") or ""
        return llm.OpenAICompatLLM(p, base, model, key)._chat_json(
            system_prompt,
            user_prompt,
            "ai-qa-%s" % p,
            int(os.environ.get("AI_QA_MAX_TOKENS", "1400")),
        )
    raise RuntimeError("AI_QA_PROVIDER no soportado: %s" % p)


def normalize_report(stage, raw, artifact=None):
    blocking = raw.get("blocking_issues") if isinstance(raw.get("blocking_issues"), list) else []
    warnings = raw.get("warnings") if isinstance(raw.get("warnings"), list) else []
    score = raw.get("score", 0)
    try:
        score = int(score)
    except Exception:
        score = 0
    threshold = int(os.environ.get("AI_QA_MIN_SCORE", "75"))
    ok = bool(raw.get("ok")) and score >= threshold and not any(
        str(x.get("severity", "")).lower() in ("blocker", "critical") for x in blocking if isinstance(x, dict)
    )
    return {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stage": stage,
        "provider": provider(),
        "artifact": artifact,
        # Version del criterio bajo el que se emitio el reporte: gatea la memoria
        # del juez (abajo) y el consumo en auto_remediate. Un reporte del criterio
        # probatorio viejo no debe re-litigarse bajo el criterio de dramatizacion.
        "criterion_version": CRITERION_VERSION,
        "ok": ok,
        "score": score,
        "min_score": threshold,
        "blocking_issues": blocking,
        "warnings": warnings,
        "raw": raw,
    }


SYSTEM_PROMPT = """Eres QA Director de Reel Engine.
Tu trabajo es bloquear errores creativos, semanticos y visuales antes de que el pipeline gaste tiempo.
No seas amable. Si algo puede producir un reel confuso, ilegible, vacio, mal sincronizado, con visual que CONTRADICE lo narrado, o con un error visual obvio para un humano (texto garabateado dentro de la imagen, manos/anatomia deformes, producto inconsistente entre escenas, colisiones de layout, avatar visiblemente montado), falla.
INVARIANTE: SEMANTICA SOBRE PRECISION. Un visual que DRAMATIZA la idea (persona/gesto/objeto en accion) gana sobre un panel de texto probatorio. NO exijas que la media PRUEBE el claim: la precision (cifras, palabras, listas) vive en overlays declarados compuestos SOBRE la media.
SEVERIDAD: reserva "blocker" para (a) contradiccion con lo narrado, (b) error visual obvio, (c) balance de medio roto (mayoria de pantallas sin media/accion, o mas de 2 escenas 100% texto seguidas). Un visual "debil/generico/mejorable" es major o minor, nunca blocker.
Devuelve SOLO JSON valido:
{
  "ok": true/false,
  "score": 0-100,
  "blocking_issues": [{"id":"...","severity":"blocker|major|minor","scene":0,"issue":"...","fix":"..."}],
  "warnings": ["..."],
  "notes": "..."
}
Regla: cualquier issue blocker o score menor al minimo hace fallar el QA."""


def scene_summary(scene, idx, overlays=None, cta=None):
    clip = scene.get("clip") if isinstance(scene.get("clip"), dict) else {}
    item = {
        "idx": idx,
        "role": scene.get("role"),
        "layout": scene.get("layout"),
        "anchor": scene.get("anchor"),
        "clip": {
            "source": clip.get("source") or scene.get("source"),
            "query": clip.get("query"),
            "prompt": compact_text(clip.get("prompt"), 500),
            "asset": clip.get("asset"),
            "media": scene.get("media") or clip.get("media"),
            "companion": clip.get("companion"),
        },
        "editorial_point": scene.get("editorial_point"),
        "why_it_matters": scene.get("why_it_matters"),
        "visual_proof": scene.get("visual_proof"),
        "visual_targets": scene.get("visual_targets"),
        "visual_beats": scene.get("visual_beats"),
        "auto_sfx_from_visual_beats": True,
        "auto_sfx_from_overlays": True,
        "plate_purpose": scene.get("plate_purpose"),
        "matched_global_overlays": scene.get("overlays") or overlays or [],
    }
    if cta is not None and (scene.get("layout") == "cta" or scene.get("plate_purpose") == "cta_resource"):
        item["cta"] = cta
    return item


def plan_payload(plan):
    scenes = plan.get("scenes") or []
    overlays = plan.get("overlays") or []

    def anchor_key(item):
        anchor = item.get("anchor") if isinstance(item.get("anchor"), dict) else {}
        return anchor.get("phrase") or anchor.get("at")

    overlays_by_anchor = {}
    for overlay in overlays:
        key = anchor_key(overlay)
        if key:
            overlays_by_anchor.setdefault(key, []).append(overlay)

    return {
        "hook": plan.get("hook"),
        "script": compact_text(plan.get("script"), 5000),
        "style": (plan.get("meta") or {}).get("style"),
        "cta": plan.get("cta"),
        "scenes": [
            scene_summary(sc, i, overlays_by_anchor.get(anchor_key(sc), []), plan.get("cta"))
            for i, sc in enumerate(scenes)
        ],
        "overlays": {
            "mode": "global_overlays_matched_into_scene_summaries",
            "count": len(overlays),
        },
        "sfx": {
            "manual": plan.get("sfx"),
            "engine_policy": "plan_to_props derives additional audible SFX from overlay components and semantic visual_beats using derive_animation_sfx and derive_pacing_sfx, then dedupes to respect minimum spacing.",
            "derived_from": ["StepList item reveals", "KeywordPop", "callout_target", "insert_card", "component_state", "layout_swap"],
        },
    }


def caption_token(caption):
    return str(
        caption.get("word")
        or caption.get("text")
        or caption.get("caption")
        or ""
    ).strip()


def caption_text_for_scene(captions, start_ms, end_ms, limit=500):
    words = []
    for caption in captions or []:
        c0 = int(caption.get("startMs", caption.get("fromMs", 0)) or 0)
        c1 = int(caption.get("endMs", caption.get("toMs", c0)) or c0)
        if c1 >= start_ms and c0 <= end_ms:
            token = caption_token(caption)
            if token:
                words.append(token)
    return compact_text(" ".join(words), limit)


def props_payload(props):
    scenes = []
    captions = props.get("captions") or []
    for i, sc in enumerate(props.get("scenes") or []):
        item = scene_summary(sc, i)
        media = sc.get("media")
        if media:
            item["media_exists"] = os.path.exists(public_path(media))
        item["fromMs"] = sc.get("fromMs")
        item["toMs"] = sc.get("toMs")
        item["durationMs"] = int(sc.get("toMs", 0) or 0) - int(sc.get("fromMs", 0) or 0)
        item["caption_text"] = caption_text_for_scene(
            captions,
            int(sc.get("fromMs", 0) or 0),
            int(sc.get("toMs", 0) or 0),
        )
        scenes.append(item)
    return {
        "hook": props.get("hook"),
        "style": props.get("style"),
        "policies": props.get("policies"),
        "totalMs": props.get("totalMs"),
        "providerMode": props.get("providerMode"),
        "scenes": scenes,
        "overlays": props.get("overlays"),
        "sfx": props.get("sfx"),
        "cta": props.get("cta"),
        "caption_sample": captions[:20],
        "caption_count": len(captions),
    }


def script_payload(plan):
    meta = plan.get("meta") or {}
    return {
        "topic": meta.get("topic"),
        "language": meta.get("language"),
        "target_seconds": meta.get("target_seconds"),
        "hook": plan.get("hook"),
        "script": plan.get("script"),
        "cta": plan.get("cta"),
        "angle_type": meta.get("angle_type"),
        "angle_sentence": meta.get("angle_sentence"),
        "narrative_structure": meta.get("narrative_structure"),
    }


def normalize_word(word):
    text = str(word or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9ñ]+", "", text)


# Muletillas por idioma: "e"/"em"/"este" son ambiguas en ingles (palabras
# reales), asi que el set EN se limita a interjecciones de disfluencia real
# (mismo criterio de disciplina que el set ES: nada de conectores validos).
FILLER_WORDS_BY_LANG = {
    "es": {"eh", "e", "em", "emm", "mmm", "um", "uh", "ajam", "este", "estee"},
    "en": {"um", "uh", "erm", "ah", "hmm", "huh"},
}
# Numeros cortos hablados que NO deben marcarse como "habla silabeada" solo
# por durar >=700ms (uno/two/three son legitimamente cortos y frecuentes en
# countdowns). Compat: FILLER_WORDS sigue apuntando a 'es' por defecto.
SHORT_NUMBER_WORDS_BY_LANG = {
    "es": {"uno", "dos", "tres"},
    "en": {"one", "two", "six", "ten"},
}
FILLER_WORDS = FILLER_WORDS_BY_LANG["es"]


def filler_words_for(language):
    return FILLER_WORDS_BY_LANG.get((language or "es").strip().lower(), FILLER_WORDS_BY_LANG["es"])


def short_number_words_for(language):
    return SHORT_NUMBER_WORDS_BY_LANG.get((language or "es").strip().lower(), SHORT_NUMBER_WORDS_BY_LANG["es"])


def read_wav_peak(path):
    try:
        with wave.open(path, "rb") as wf:
            if wf.getsampwidth() != 2:
                return None
            channels = wf.getnchannels()
            raw = wf.readframes(wf.getnframes())
        samples = array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
        if not samples:
            return 0.0
        if channels > 1:
            return max(abs(x) for x in samples) / 32768.0
        return max(abs(x) for x in samples) / 32768.0
    except Exception:
        return None


def dbfs(value):
    if value is None:
        return None
    value = float(value or 0)
    if value <= 1e-12:
        return -120.0
    return round(20.0 * math.log10(value), 1)


def probe_duration_ms(path):
    rr = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return int(float((rr.stdout or "").strip()) * 1000)
    except Exception:
        return 0


def detect_silence_windows(path):
    rr = run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-af", "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-",
    ])
    text = (rr.stderr or "") + "\n" + (rr.stdout or "")
    out = []
    start = None
    for line in text.splitlines():
        m = re.search(r"silence_start:\s*([0-9.]+)", line)
        if m:
            start = float(m.group(1))
            continue
        m = re.search(r"silence_end:\s*([0-9.]+).*silence_duration:\s*([0-9.]+)", line)
        if m and start is not None:
            out.append({
                "start_ms": int(start * 1000),
                "end_ms": int(float(m.group(1)) * 1000),
                "duration_ms": int(float(m.group(2)) * 1000),
            })
            start = None
    return out


def _tokenize_words(text):
    return [normalize_word(w) for w in re.findall(r"[0-9A-Za-zÀ-ɏ]+", str(text or "")) if normalize_word(w)]


def _word_edit_distance(ref, hyp):
    n, m = len(ref), len(hyp)
    if n == 0:
        return m
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        ri = ref[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ri == hyp[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[m]


def word_error_rate(script_text, transcript_words):
    """WER entre el guion y la transcripcion STT independiente (C7).

    Detecta frases omitidas, palabras mal leidas o duplicadas que ni el alignment
    (derivado del propio TTS) ni los blockers de fillers/pacing capturan. Devuelve
    None si no hay transcripcion o guion (p.ej. STT no corrio).
    """
    ref = _tokenize_words(script_text)
    hyp = [normalize_word(w.get("word")) for w in transcript_words
           if isinstance(w, dict) and normalize_word(w.get("word"))]
    if not ref or not hyp:
        return None
    return round(_word_edit_distance(ref, hyp) / len(ref), 3)


def tts_metrics(audio_path, alignment_path=None, plan_path=None):
    alignment = {}
    if alignment_path and os.path.exists(alignment_path):
        alignment = load_json(alignment_path)
    plan = load_json(plan_path) if plan_path and os.path.exists(plan_path) else {}
    language = (plan.get("meta") or {}).get("language", "es")
    fillers_lang = filler_words_for(language)
    short_numbers = short_number_words_for(language)
    words = alignment.get("words") if isinstance(alignment.get("words"), list) else []
    word_items = []
    for item in words:
        try:
            start = int(item.get("start_ms", 0))
            end = int(item.get("end_ms", start))
            word_items.append({
                "word": str(item.get("word", "")),
                "norm": normalize_word(item.get("word", "")),
                "start_ms": start,
                "end_ms": end,
                "duration_ms": max(0, end - start),
            })
        except Exception:
            continue
    gaps = []
    for prev, cur in zip(word_items, word_items[1:]):
        gap = int(cur["start_ms"]) - int(prev["end_ms"])
        if gap > 0:
            gaps.append(gap)
    duration_ms = probe_duration_ms(audio_path)
    word_count = len(word_items)
    wpm = round(word_count / max(duration_ms / 60000.0, 0.001), 1) if duration_ms else 0.0
    fillers = [w for w in word_items if w["norm"] in fillers_lang]
    long_short_words = [
        w for w in word_items
        if len(w["norm"]) <= 4 and w["duration_ms"] >= 700 and w["norm"] not in short_numbers
    ]
    long_words = [w for w in word_items if w["duration_ms"] >= 1050]
    long_gaps = [g for g in gaps if g >= 450]
    silence = detect_silence_windows(audio_path) if os.path.exists(audio_path) else []
    peak = dbfs(read_wav_peak(audio_path)) if os.path.exists(audio_path) else None
    first_words = [w["norm"] for w in word_items[:4]]
    script_text = plan.get("script") or ""
    transcript = independent_tts_transcript(audio_path)
    transcript_words = transcript.get("words") or []
    transcript_first = [normalize_word(w.get("word")) for w in transcript_words[:6] if isinstance(w, dict)]
    transcript_fillers = [
        {"word": w.get("word"), "start_ms": w.get("start_ms"), "end_ms": w.get("end_ms")}
        for w in transcript_words
        if isinstance(w, dict) and normalize_word(w.get("word")) in fillers_lang
    ]
    return {
        "audio_path": os.path.abspath(audio_path),
        "alignment_path": os.path.abspath(alignment_path) if alignment_path else None,
        "duration_ms": duration_ms,
        "word_count": word_count,
        "wpm": wpm,
        "peak_dbfs": peak,
        "first_words": first_words,
        "filler_count": len(fillers),
        "filler_words": fillers[:10],
        "starts_with_filler": bool(first_words and first_words[0] in fillers_lang),
        "long_short_words": long_short_words[:12],
        "long_words": long_words[:12],
        "long_gap_count": len(long_gaps),
        "long_gaps_ms": long_gaps[:20],
        "silence_windows": silence[:20],
        "silence_count": len(silence),
        "independent_transcript": transcript,
        "transcript_first_words": transcript_first,
        "transcript_filler_count": len(transcript_fillers),
        "transcript_filler_words": transcript_fillers[:12],
        "transcript_starts_with_filler": bool(transcript_first and transcript_first[0] in fillers_lang),
        "transcript_wer": word_error_rate(script_text, transcript_words),
        "script": compact_text(script_text, 2500),
    }


def multipart_form(fields, file_field, file_path):
    boundary = "----reel-engine-%s" % uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        if value is None:
            continue
        chunks.extend([
            ("--%s\r\n" % boundary).encode("utf-8"),
            ('Content-Disposition: form-data; name="%s"\r\n\r\n' % key).encode("utf-8"),
            str(value).encode("utf-8"),
            b"\r\n",
        ])
    filename = os.path.basename(file_path)
    ctype = mimetypes.guess_type(file_path)[0] or "audio/wav"
    chunks.extend([
        ("--%s\r\n" % boundary).encode("utf-8"),
        ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (file_field, filename)).encode("utf-8"),
        ("Content-Type: %s\r\n\r\n" % ctype).encode("utf-8"),
    ])
    with open(file_path, "rb") as f:
        chunks.append(f.read())
    chunks.extend([b"\r\n", ("--%s--\r\n" % boundary).encode("utf-8")])
    return boundary, b"".join(chunks)


def elevenlabs_stt_transcript(audio_path):
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("falta ELEVENLABS_API_KEY para ElevenLabs STT")
    model = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2")
    language = os.environ.get("ELEVENLABS_STT_LANGUAGE", "spa")
    fields = {
        "model_id": model,
        "timestamps_granularity": "word",
        "language_code": language,
        "tag_audio_events": "true",
        "no_verbatim": "false",
        "diarize": "false",
    }
    boundary, body = multipart_form(fields, "file", audio_path)
    url = "https://api.elevenlabs.io/v1/speech-to-text"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "xi-api-key": key,
            "Content-Type": "multipart/form-data; boundary=%s" % boundary,
            "Accept": "application/json",
        },
        method="POST",
    )
    timeout = int(os.environ.get("ELEVENLABS_STT_TIMEOUT", "180"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError("ElevenLabs STT HTTP %s: %s" % (e.code, detail))
    words = []
    for item in data.get("words") or []:
        if item.get("type") and item.get("type") != "word":
            continue
        text = str(item.get("text") or item.get("word") or "").strip()
        if not text:
            continue
        start = item.get("start")
        end = item.get("end")
        words.append({
            "word": text,
            "start_ms": int(float(start or 0) * 1000),
            "end_ms": int(float(end or start or 0) * 1000),
        })
    return {
        "ok": True,
        "provider": "elevenlabs_stt",
        "model": model,
        "language_code": data.get("language_code"),
        "language_probability": data.get("language_probability"),
        "word_count": len(words),
        "text": compact_text(data.get("text") or " ".join(w["word"] for w in words), 2500),
        "words": words[:160],
    }


def whisperx_transcript(audio_path):
    from aligner import WhisperXAligner
    aligned = WhisperXAligner().align(audio_path, None)
    words = [
        {
            "word": str(w.get("word", "")).strip(),
            "start_ms": int(w.get("start_ms", 0) or 0),
            "end_ms": int(w.get("end_ms", 0) or 0),
        }
        for w in aligned.get("words") or []
    ]
    text = " ".join(w["word"] for w in words if w.get("word"))
    return {
        "ok": True,
        "provider": "whisperx",
        "word_count": len(words),
        "text": compact_text(text, 2500),
        "words": words[:160],
    }


def independent_tts_transcript(audio_path):
    if not os.path.exists(audio_path):
        return {"ok": False, "required": tts_transcript_required(), "error": "audio_missing"}
    if not env_bool("TTS_QA_TRANSCRIBE", True):
        return {"ok": False, "required": tts_transcript_required(), "skipped": "TTS_QA_TRANSCRIBE=0"}
    required_now = tts_transcript_required()
    if not required_now and not env_bool("TTS_QA_TRANSCRIBE_OPTIONAL", False):
        return {"ok": False, "required": False, "skipped": "transcripcion no requerida"}
    providers = [
        p.strip().lower()
        for p in os.environ.get("TTS_QA_TRANSCRIBE_PROVIDER", "elevenlabs,whisperx").split(",")
        if p.strip()
    ]
    errors = []
    for p in providers:
        try:
            if p in ("elevenlabs", "scribe", "elevenlabs_stt"):
                return elevenlabs_stt_transcript(audio_path)
            if p == "whisperx":
                return whisperx_transcript(audio_path)
        except Exception as e:
            errors.append({"provider": p, "error": str(e)[:500]})
    return {"ok": False, "required": required_now, "providers": providers, "attempts": errors}


def tts_transcript_required():
    if "TTS_QA_REQUIRE_TRANSCRIPT" in os.environ:
        return env_bool("TTS_QA_REQUIRE_TRANSCRIPT", True)
    return os.environ.get("PROVIDER_MODE", "mock").lower() == "real"


def tts_metric_blockers(metrics):
    blockers = []
    if not metrics.get("duration_ms"):
        blockers.append({
            "id": "tts_audio_missing",
            "severity": "blocker",
            "scene": None,
            "issue": "No se pudo medir la duración del audio TTS.",
            "fix": "Regenera TTS y confirma que voice.wav exista y ffprobe lo pueda leer.",
        })
    if metrics.get("starts_with_filler"):
        blockers.append({
            "id": "tts_starts_with_filler",
            "severity": "blocker",
            "scene": None,
            "issue": "La voz empieza con una muletilla o arranque sucio: %s." % ", ".join(metrics.get("first_words") or []),
            "fix": "Regenera TTS con la misma voz aprobada y ajusta settings/puntuacion si hace falta; no avances si el primer sonido no es la primera palabra real del guion.",
        })
    if metrics.get("filler_count", 0) >= 2:
        blockers.append({
            "id": "tts_fillers",
            "severity": "blocker",
            "scene": None,
            "issue": "La alineación detecta varias muletillas o sonidos tipo eh/uh/mmm.",
            "fix": "Regenera TTS con la misma voz aprobada, ajusta settings o limpia el texto de entrada; el audio final no puede tener muletillas no escritas.",
        })
    if metrics.get("wpm", 0) and (metrics["wpm"] < 120 or metrics["wpm"] > 195):
        blockers.append({
            "id": "tts_bad_pacing",
            "severity": "blocker",
            "scene": None,
            "issue": "Ritmo de TTS fuera de rango para Reel: %.1f palabras/minuto." % metrics["wpm"],
            "fix": "Ajusta speed/voice settings y regenera TTS hasta quedar aprox. 130-185 wpm.",
        })
    if len(metrics.get("long_short_words") or []) >= 3:
        blockers.append({
            "id": "tts_syllabic_delivery",
            "severity": "blocker",
            "scene": None,
            "issue": "Varias palabras cortas duran demasiado; sugiere habla silabeada o robótica.",
            "fix": "Mantén la misma voz aprobada, ajusta settings o puntuacion y regenera; no uses este TTS para captions ni render.",
        })
    if metrics.get("long_gap_count", 0) >= 8:
        blockers.append({
            "id": "tts_too_many_pauses",
            "severity": "blocker",
            "scene": None,
            "issue": "Demasiadas pausas largas entre palabras: %d." % metrics.get("long_gap_count", 0),
            "fix": "Regenera TTS o ajusta el texto/voz; las pausas rompen fluidez de Reel.",
        })
    transcript = metrics.get("independent_transcript") or {}
    if not transcript.get("ok") and transcript.get("required"):
        blockers.append({
            "id": "tts_independent_transcript_missing",
            "severity": "blocker",
            "scene": None,
            "issue": "No se pudo transcribir el TTS de forma independiente; no se puede verificar si empieza con eh/uh o si habla raro.",
            "fix": "Instala/configura WhisperX o pon TTS_QA_REQUIRE_TRANSCRIPT=0 solo para pruebas. En produccion no avances sin transcripcion independiente.",
        })
    if metrics.get("transcript_starts_with_filler"):
        blockers.append({
            "id": "tts_transcript_starts_with_filler",
            "severity": "blocker",
            "scene": None,
            "issue": "La transcripcion independiente detecta que el audio arranca con muletilla: %s." % ", ".join(metrics.get("transcript_first_words") or []),
            "fix": "Regenera TTS con la misma voz aprobada y ajusta settings/puntuacion; el primer sonido audible debe ser la primera palabra real del guion.",
        })
    if metrics.get("transcript_filler_count", 0) >= 1:
        blockers.append({
            "id": "tts_transcript_fillers",
            "severity": "blocker",
            "scene": None,
            "issue": "La transcripcion independiente detecta muletillas en el audio.",
            "fix": "Regenera TTS con la misma voz aprobada; si el texto no contiene esas muletillas, ajusta settings o puntuacion. No cambies voz ni proveedor.",
        })
    peak_dbfs = metrics.get("peak_dbfs")
    if peak_dbfs is not None and peak_dbfs >= -0.1:
        blockers.append({
            "id": "tts_clipping",
            "severity": "blocker",
            "scene": None,
            "issue": "El audio TTS llega a fondo de escala (peak %.2f dBFS): posible clipping/glitch digital." % peak_dbfs,
            "fix": "Baja el nivel de sintesis o re-normaliza con headroom (peak <= -1 dBFS) y regenera; el clipping suena como chasquido en movil.",
        })
    wer = metrics.get("transcript_wer")
    if wer is not None and wer > 0.35:
        blockers.append({
            "id": "tts_transcript_divergence",
            "severity": "blocker",
            "scene": None,
            "issue": "La transcripcion independiente diverge del guion (WER %.0f%%): el audio omite o cambia texto narrado." % (wer * 100),
            "fix": "Confirma que el TTS leyo el guion completo y correcto; regenera si falta una frase o pronuncia mal palabras clave. El giro fino lo juzga ademas el LLM.",
        })
    return blockers


def public_path(media):
    media = str(media or "").replace("\\", "/")
    if os.path.isabs(media):
        return media
    if media.startswith(("media/", "runs/", "fixtures/")):
        return os.path.join(PUBLIC, *media.split("/"))
    return os.path.join(PUBLIC_MEDIA, media)


def run(args):
    return media_tools.run(args, capture_output=True, text=True)


def sample_media_images(props, out_dir, max_images=30):
    os.makedirs(out_dir, exist_ok=True)
    images = []
    labels = []
    captions = props.get("captions") or []
    for i, sc in enumerate(props.get("scenes") or []):
        if len(images) >= max_images:
            break
        media = sc.get("media")
        if not media:
            continue
        path = public_path(media)
        if not os.path.exists(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        start_ms = int(sc.get("fromMs", 0) or 0)
        end_ms = int(sc.get("toMs", start_ms) or start_ms)
        scene_duration_s = max(0.25, (end_ms - start_ms) / 1000.0)
        caption_text = caption_text_for_scene(captions, start_ms, end_ms)

        def add_label(sample, at_seconds, image_path):
            images.append(image_path)
            labels.append({
                "image_index": len(images),
                "scene": i,
                "sample": sample,
                "at_seconds": round(float(at_seconds or 0), 2),
                "role": sc.get("role"),
                "source": sc.get("source"),
                "media": media,
                "caption_text": caption_text,
                "visual_targets": sc.get("visual_targets"),
                "visual_proof": sc.get("visual_proof"),
                "editorial_point": sc.get("editorial_point"),
                "why_it_matters": sc.get("why_it_matters"),
            })

        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            add_label("still", 0, path)
        elif ext in (".mp4", ".mov", ".m4v", ".webm"):
            media_duration_ms = probe_duration_ms(path) or 0
            media_duration_s = media_duration_ms / 1000.0 if media_duration_ms else scene_duration_s
            usable_duration_s = max(0.25, min(media_duration_s, scene_duration_s))
            samples = [
                ("start", max(0.05, usable_duration_s * 0.20)),
                ("mid", max(0.05, usable_duration_s * 0.50)),
                ("end", max(0.05, usable_duration_s * 0.80)),
            ]
            seen = set()
            for sample, at in samples:
                if len(images) >= max_images:
                    break
                at = min(max(0.05, at), max(0.05, usable_duration_s - 0.08))
                key = round(at, 2)
                if key in seen:
                    continue
                seen.add(key)
                out = os.path.join(out_dir, "scene_%02d_%s.jpg" % (i, sample))
                rr = run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % at, "-i", path, "-frames:v", "1", out])
                if rr.returncode == 0 and os.path.exists(out):
                    add_label(sample, at, out)
        else:
            continue
    return images, labels


def sample_render_images(mp4, props, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    fps = int(props.get("fps") or 24)
    frames = []
    labels = []
    captions = props.get("captions") or []
    for i, sc in enumerate(props.get("scenes") or []):
        start = int(sc.get("fromMs", 0) or 0)
        end = int(sc.get("toMs", start + 500) or start + 500)
        if end <= start:
            continue
        at = (start + end) / 2000.0
        out = os.path.join(out_dir, "render_scene_%02d.jpg" % i)
        rr = run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % at, "-i", mp4, "-frames:v", "1", out])
        if rr.returncode == 0 and os.path.exists(out):
            frames.append(out)
            labels.append({
                "image_index": len(frames),
                "scene": i,
                "at_seconds": round(at, 2),
                "role": sc.get("role"),
                "source": sc.get("source"),
                "caption_text": caption_text_for_scene(captions, start, end),
                "visual_targets": sc.get("visual_targets"),
                "visual_proof": sc.get("visual_proof"),
                "overlay_components": [o.get("component") for o in props.get("overlays") or [] if int(o.get("fromMs", 0) or 0) <= at * 1000 <= int(o.get("toMs", 0) or 0)],
            })
    contact = os.path.join(out_dir, "contact_2fps.jpg")
    rr = run(["ffmpeg", "-y", "-v", "error", "-i", mp4, "-vf", "fps=2,scale=180:-1,tile=6x10", "-frames:v", "1", contact])
    if rr.returncode == 0 and os.path.exists(contact):
        frames.insert(0, contact)
        labels.insert(0, {"image_index": 1, "scene": "contact_sheet", "note": "contact sheet 2fps del MP4 completo"})
    return frames[:12], labels[:12]


MEDIA_FIT_CRITERION_VERSION = "longform-fit-v8-perceptual-salience"

MEDIA_FIT_SYSTEM = """Eres un editor de video profesional seleccionando material para un video longform de YouTube.
Tu unico trabajo: decidir si el material candidato SIRVE para el beat narrado.
El material debe mostrar el objeto, accion, comparacion o mecanismo central del beat.
Un plano generico del grupo demografico NO basta: una mujer caminando no sirve para
explicar piel, grasa, ingredientes, etiquetas, medidas o pruebas. B-roll evocativo
es valido solo si dramatiza de forma reconocible el significado concreto.
El texto preciso puede ser añadido después por un overlay de Remotion; no exijas
que el asset tenga físicamente impresa la frase del overlay. Rechaza por razones que un espectador notaria:
REGLA DURA: nunca rechaces SOLO porque una etiqueta generica no imprime una palabra,
ingrediente, porcentaje o plazo que ya aparece en OVERLAY. Si el objeto visual es
la categoria correcta y el overlay aporta esa precision, fit=true salvo otro defecto.
Esto incluye tiempo: si el asset muestra claramente la misma postura en varias fotos
y OVERLAY dice semanas/meses, no exijas fechas legibles dentro de calendarios.
JUZGA A VELOCIDAD NORMAL Y A 1080p, no como perito ampliando pixeles. El detalle se
evalua por SALIENCIA declarada: focal = debe leerse o verse con claridad; required =
el objeto debe ser reconocible pero el microtexto puede ser imperceptible; incidental =
no bloquees texto, etiqueta o detalle diminuto que una persona no alcanzaria a notar.
Una etiqueta obviamente vacia en un envase focal sigue fallando por aspecto artificial;
una etiqueta diminuta fuera del foco no se inspecciona ni se convierte en blocker.
- sujeto/accion sin relacion concreta con lo narrado o que lo contradice,
- en el hook, categoria de producto incorrecta (suplemento, pastillas o botella
  ingerible cuando la voz y el titulo hablan de una crema cosmetica topica),
- si el requisito del hook pide crema topica, debe verse un tarro o tubo cosmetico
  reconocible y preferiblemente la textura de crema. Rechaza cualquier capsula,
  tableta, botella cilindrica de suplemento o producto capilar, aunque su etiqueta
  muestre una silueta corporal o palabras relacionadas con adelgazar,
- plantillas/placeholders (pantalla chroma verde, mockups vacios, slates),
- cualquier logo, marca real o watermark de terceros visible, incluso semitransparente.
  Una marca ficticia declarada por el motor no es una marca de terceros: es valida
  si el texto es legible, coherente y no imita una marca real,
- tutoriales ajenos con UI/menus/texto denso en pantalla,
- texto garabateado/deforme dentro de la imagen,
- texto LEGIBLE cuyo idioma o contenido no corresponde al reel (p.ej. una pizarra
  con palabras en otro idioma, o de un tema distinto al narrado),
- calidad rota (pixelado extremo, bloques de compresion, artefactos).
No inventes otros criterios. "No dramatiza directamente" o "es demasiado tecnico"
NO son razones de rechazo si la imagen sigue relacionada y legible.
Devuelve SOLO JSON valido: {"fit": true/false, "reason": "<una frase concreta>"}"""


def media_fit_check(media, scene, spoken=""):
    """Gate de aceptacion visual POR PELDAÑO de la escalera (mandato 2026-07-07):
    el sistema debe VER lo que devolvio el proveedor y decidir apto/no-apto ANTES
    de aceptarlo; no-apto baja al siguiente peldaño. Antes solo se descendia por
    fallo TECNICO, y un clip irrelevante (caminadora para 'automation', chroma
    verde para 'chat') se colaba hasta el render. Devuelve (fit, reason).
    MEDIA_FIT=0 lo desactiva. Fail-open ante errores del juez (props_qa sigue
    siendo el gate final de la etapa)."""
    if not env_bool("MEDIA_FIT", True):
        return True, "MEDIA_FIT=0"
    path = public_path(media)
    if not os.path.exists(path):
        return False, "archivo no existe"
    ext = os.path.splitext(path)[1].lower()
    frames = []
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        frames = [path]
    else:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ%f")
        out_dir = os.path.join(WORK, "media_fit_%s" % stamp)
        os.makedirs(out_dir, exist_ok=True)
        dur_ms = probe_duration_ms(path) or 2000
        for tag, frac in (("start", 0.15), ("mid", 0.5), ("end", 0.85)):
            at = max(0.05, dur_ms / 1000.0 * frac)
            fp = os.path.join(out_dir, "fit_%s.jpg" % tag)
            rr = run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % at, "-i", path, "-frames:v", "1", fp])
            if rr.returncode == 0 and os.path.exists(fp):
                frames.append(fp)
    if not frames:
        return True, "sin frames extraibles (fail-open)"
    salience = str(scene.get("detail_salience") or scene.get("detailSalience") or (
        "focal" if scene.get("requires_readable_data") or scene.get("requiresReadableData")
        else "required" if str(scene.get("proof_kind") or scene.get("proofKind") or scene.get("mediaNeedKind") or "") == "product_inspection"
        else "incidental"
    ))
    user = (
        "BEAT NARRADO: %s\n"
        "LO QUE DICE LA VOZ EN ESTA ESCENA: %s\n"
        "visual_targets (inspiracion, no literalidad): %s\n"
        "visual_proof: %s\n"
        "ROL: %s\n"
        "REQUISITO INNEGOCIABLE DEL HOOK: %s\n"
        "OVERLAY QUE AÑADIRÁ REMOTION: %s | %s\n"
        "MARCA FICTICIA DECLARADA POR EL MOTOR: %s\n"
        "SALIENCIA PERCEPTUAL DEL DETALLE: %s\n"
        "MODO TEMPORAL: %s (una imagen puede implicar accion; initial_final debe mostrar dos estados; continuous debe permitir observar la trayectoria).\n"
        "Si esta marca aparece legible en packaging generado, no la rechaces como marca de terceros. "
        "No exijas que el asset repita ese texto: evalua la imagen junto con el overlay declarado. "
        "Las imagenes adjuntas son frames del material candidato (start/mid/end). "
        "Sirve este material para este beat?" % (
            compact_text(scene.get("editorial_point") or scene.get("intent"), 300),
            compact_text(spoken, 300),
            json.dumps(scene.get("visual_targets") or [], ensure_ascii=False),
            compact_text(scene.get("visual_proof"), 200),
            compact_text(scene.get("role"), 30),
            compact_text(scene.get("hook_requirement"), 300),
            compact_text(scene.get("screen_copy"), 80),
            compact_text(scene.get("subcopy"), 120),
            compact_text(scene.get("fictional_label"), 80) or "ninguna",
            salience,
            compact_text(scene.get("temporal_evidence_mode") or scene.get("temporalEvidenceMode"), 30) or "implied",
        )
    )
    original_timeout = os.environ.get("AI_QA_TIMEOUT")
    media_timeout = os.environ.get("MEDIA_FIT_AI_TIMEOUT", "75")
    try:
        os.environ["AI_QA_TIMEOUT"] = media_timeout
        raw = call_ai_json(MEDIA_FIT_SYSTEM, user, images=frames, vision_required=True)
    except Exception as e:
        if production_mode():
            return False, "fit-check sin juez disponible: %s" % str(e)[:120]
        return True, "fit-check error (fail-open en mock): %s" % str(e)[:100]
    finally:
        if original_timeout is None:
            os.environ.pop("AI_QA_TIMEOUT", None)
        else:
            os.environ["AI_QA_TIMEOUT"] = original_timeout
    fit = bool(raw.get("fit", raw.get("ok", True)))
    return fit, str(raw.get("reason") or "")[:200]


def plan_qa(plan_path):
    plan = load_json(plan_path)
    notes = ""
    # Memoria del juez: su reporte anterior entra al prompt con regla de
    # consistencia. Sin esto, cada ronda re-litiga lo aceptado y el gate
    # nunca converge (aprendido en la primera corrida real de v2).
    prev_block = ""
    try:
        prev = load_json(default_out("plan"))
        # criterion_version: la memoria solo aplica entre reportes del MISMO
        # criterio; un reporte probatorio viejo obligaria al juez v2 a exigir
        # los plates que el criterio nuevo prohibe (hazard de migracion).
        if prev.get("stage") == "plan" and prev.get("artifact") == os.path.abspath(plan_path) \
                and prev.get("criterion_version") == CRITERION_VERSION:
            prev_block = (
                "TU REPORTE ANTERIOR sobre una version previa de ESTE plan (ya corregida):\n"
                "score=%s\nissues=%s\n"
                "REGLA DE CONSISTENCIA: evalua primero si cada issue anterior fue resuelto. "
                "NO reabras aspectos que en tu reporte anterior no marcaste como issue, salvo que cites "
                "evidencia NUEVA introducida por la correccion. Un plan que resolvio todos tus blockers "
                "anteriores sin introducir problemas nuevos debe aprobar.\n"
                % (prev.get("score"), json.dumps([
                    {"scene": i.get("scene"), "issue": str(i.get("issue"))[:200]}
                    for i in (prev.get("blocking_issues") or [])[:8]
                ], ensure_ascii=False))
            )
    except Exception:
        pass
    user = (
        "STAGE=PLAN. Revisa antes de proveedores.\n"
        + prev_block
        + ("REGLAS DEL MAPA EDITABLE:\n%s\n" % notes if notes else "")
        + "Bloquea si el guion suena generico/raro, si no hay mensaje claro, si el hook no da contexto, "
        "si alguna escena CONTRADICE lo narrado, si hay plates vacios, "
        "si faltan SFX para animaciones, si captions/overlays pueden taparse, o si Remotion tendria que inventar contenido.\n"
        "HOOK: debe MOSTRAR la creencia/accion del gancho (persona, gesto, objeto -- media generada es valida "
        "como dramatizacion, no la vetes por 'no ser evidencia'). Un hook 100%% texto es issue major salvo pico "
        "tipografico deliberado con razon declarada.\n"
        "BALANCE DE MEDIO (usa id='media_ratio', severity blocker): (i) la MAYORIA de las escenas body (~60%%+) "
        "debe tener media de personas/accion como base; (ii) mas de 2 escenas 100%% texto consecutivas = blocker; "
        "(iii) golpes tipograficos de pantalla completa: maximo 3-4 por reel, como picos, no como escenas de "
        "relleno; 3+ pantallas casi identicas seguidas = blocker de retencion.\n"
        "CONTRATO declared_only (no lo confundas con inventar): items/labels/words declarados en el plan que son "
        "frases LITERALES del guion son el mecanismo correcto del motor, no Remotion inventando. Bloquea contenido "
        "declarado SOLO si no aparece en el guion o contradice lo narrado. NO exijas que texto especifico sea "
        "legible dentro de media real o generada: eso es precisamente lo poco fiable que el contrato evita. "
        "El destino por defecto del texto declarado es un OVERLAY compuesto sobre media, no un plate que "
        "reemplaza la media.\n"
        + MEDIUM_CRITERION + "\n"
        "RETENCION SEMANTICA (los umbrales numericos ya los valida otro script; tu juzgas lo que ellos no ven):\n"
        "1) Cadena de curiosidad: para CADA escena, di que pregunta deja abierta que la siguiente responde. "
        "Si una escena no abre pregunta ni paga una anterior, es relleno: blocker.\n"
        "2) Beats de relleno: un visual_beat que cambia pixeles sin agregar informacion NI dramatizar/sostener "
        "la energia de lo narrado, puesto solo para cumplir el timer de pacing, es un issue major; nombralo. "
        "Un beat de accion (gesto, uso del producto, reaccion humana) que acompana la voz NO es relleno aunque "
        "no aporte dato nuevo.\n"
        "3) Segundo de fuga: responde OBLIGATORIAMENTE en notes en que segundo un espectador impaciente abandonaria y por que. "
        "Si ese punto cae antes del 60 por ciento del video, propone el fix concreto. Si la causa es una racha "
        "de escenas de texto o pantallas casi identicas, emite blocker (no solo nota) con fix de conversion a media.\n"
        "PLAN JSON RESUMIDO:\n%s" % json.dumps(plan_payload(plan), ensure_ascii=False, indent=2)
    )
    raw = call_ai_json(SYSTEM_PROMPT, user)
    return normalize_report("plan", raw, os.path.abspath(plan_path))


def script_qa(plan_path):
    plan = load_json(plan_path)
    notes = ""
    # Memoria del juez (mismo fix que plan_qa): sin ella, cada ronda re-litiga
    # lo aceptado y contradice sus propias exigencias de la ronda anterior.
    prev_block = ""
    try:
        prev = load_json(default_out("script"))
        if prev.get("stage") == "script" and prev.get("artifact") == os.path.abspath(plan_path) \
                and prev.get("criterion_version") == CRITERION_VERSION:
            prev_block = (
                "TU REPORTE ANTERIOR sobre una version previa de ESTE guion (ya corregida):\n"
                "score=%s\nissues=%s\n"
                "REGLA DE CONSISTENCIA: evalua primero si cada issue anterior fue resuelto. "
                "NO reabras aspectos que antes no marcaste, salvo evidencia NUEVA introducida por la "
                "correccion. Un guion que resolvio tus blockers sin crear problemas nuevos debe aprobar.\n"
                % (prev.get("score"), json.dumps([
                    {"issue": str(i.get("issue"))[:200]}
                    for i in (prev.get("blocking_issues") or [])[:8]
                ], ensure_ascii=False))
            )
    except Exception:
        pass
    user = (
        "STAGE=SCRIPT. Revisa SOLO el guion antes de TTS.\n"
        + prev_block
        + ("REGLAS DEL MAPA EDITABLE:\n%s\n" % notes if notes else "")
        + "Bloquea si el guion suena generico, flojo, raro, con modismos forzados, sin espanol neutro natural, "
        "sin mensaje claro, sin hook inmediato, sin primer pico antes de 5s, repetitivo, "
        "sin mecanismo/evidencia simple, con CTA desconectado o con frases que no se dirian en voz alta.\n"
        "Estructura: el plan declara meta.narrative_structure (arc=giro, case=caso/historia, countdown=lista jerarquica). "
        "Verifica que el guion CUMPLE la estructura declarada y que esa estructura le queda al tema; "
        "un tema con protagonista/evento narrado como arc generico es un issue major.\n"
        "Retencion: responde en notes en que segundo un espectador impaciente abandonaria y por que.\n"
        "Claims dramatizables: bloquea SOLO claims que NINGUN visual puede siquiera dramatizar o evocar con "
        "una persona/gesto/objeto en pantalla. Un verbo funcional (activa, estimula, potencia) es valido si "
        "el guion sugiere el gesto/escena que lo dramatiza (masaje, aplicacion del producto, antes/despues); "
        "NO exijas que el visual pruebe el proceso interno -- el estandar es dramatizar, no demostrar.\n"
        "No revises escenas, assets ni Remotion todavia. Este gate decide si vale la pena gastar TTS.\n"
        "GUION JSON:\n%s" % json.dumps(script_payload(plan), ensure_ascii=False, indent=2)
    )
    raw = call_ai_json(SYSTEM_PROMPT, user)
    return normalize_report("script", raw, os.path.abspath(plan_path))


def tts_qa(audio_path, alignment_path=None, plan_path=None):
    metrics = tts_metrics(audio_path, alignment_path, plan_path)
    metric_blockers = tts_metric_blockers(metrics)
    notes = ""
    user = (
        "STAGE=TTS. Revisa si la voz generada puede avanzar a escenas/assets.\n"
        + ("REGLAS DEL MAPA EDITABLE:\n%s\n" % notes if notes else "")
        + "La identidad de voz es fija: no recomiendes cambiar voice_id, voz, clon ni proveedor como solucion. "
        "Si falla, el fix permitido es regenerar con la misma voz aprobada, ajustar settings permitidos, limpiar puntuacion/texto o bloquear.\n"
        + "Debes bloquear muletillas audibles, arranque con eh/uh/mmm, voz robotica, habla silabeada, "
        "pausas raras, ritmo demasiado rapido/lento, mala fluidez o desalineacion evidente. "
        "Usa la transcripcion independiente cuando exista; si no existe y esta marcada required, falla.\n"
        "No revises escenas ni Remotion todavia.\n"
        "TTS METRICS:\n%s" % json.dumps(metrics, ensure_ascii=False, indent=2)
    )
    raw = call_ai_json(SYSTEM_PROMPT, user)
    if not isinstance(raw.get("blocking_issues"), list):
        raw["blocking_issues"] = []
    raw["blocking_issues"].extend(metric_blockers)
    if metric_blockers:
        raw["ok"] = False
        try:
            raw["score"] = min(int(raw.get("score") or 0), 60)
        except Exception:
            raw["score"] = 0
    report = normalize_report("tts", raw, os.path.abspath(audio_path))
    report["metrics"] = metrics
    return report


def props_qa(props_path):
    props = load_json(props_path)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    max_images = int(os.environ.get("AI_QA_PROPS_MAX_IMAGES", "30") or 30)
    images, labels = sample_media_images(props, os.path.join(WORK, "props_frames_%s" % stamp), max_images=max_images)
    notes = ""
    # Memoria del juez (mismo fix que plan_qa/script_qa): sin ella, cada ronda
    # re-litiga escenas ya aceptadas que ni siquiera cambiaron de asset.
    prev_block = ""
    try:
        prev = load_json(default_out("props"))
        if prev.get("stage") == "props" and prev.get("artifact") == os.path.abspath(props_path) \
                and prev.get("criterion_version") == CRITERION_VERSION:
            prev_block = (
                "TU REPORTE ANTERIOR sobre una version previa de este props (ya corregida):\n"
                "score=%s\nissues=%s\n"
                "REGLA DE CONSISTENCIA: evalua primero si cada issue anterior fue resuelto. Si una escena que "
                "antes NO marcaste como issue no cambio de asset/overlay entre esa version y esta, NO la "
                "reabras ahora por un angulo distinto del mismo frame -- eso es variabilidad de tu propio "
                "juicio, no un defecto nuevo. Un props que resolvio tus blockers anteriores sin introducir "
                "problemas nuevos en escenas que SI cambiaron debe aprobar.\n"
                % (prev.get("score"), json.dumps([
                    {"scene": i.get("scene"), "issue": str(i.get("issue"))[:200]}
                    for i in (prev.get("blocking_issues") or [])[:8]
                ], ensure_ascii=False))
            )
    except Exception:
        pass
    user = (
        "STAGE=PROPS_ASSETS. Revisa antes de render.\n"
        + prev_block
        + ("REGLAS DEL MAPA EDITABLE:\n%s\n" % notes if notes else "")
        + "Ahora ya hay media resuelta. Las imagenes adjuntas son muestras por escena; en video pueden incluir start/mid/end. "
        "IMPORTANTE: las imagenes adjuntas son SOLO el fondo fotografico generado, SIN los overlays graficos (StepList, StatRing, "
        "LowerThird, SplitCompare, etc.) que se componen encima en el render final. Si el props JSON de esa escena declara un overlay "
        "cuyo item_anchors/params ya cubre la PRECISION del guion (una cifra, frase o lista EXACTA), NO exijas que la FOTO reproduzca "
        "ESE texto del guion -- esa precision vive en el overlay. Evalua packaging por SALIENCIA PERCEPTUAL a 1080p y velocidad normal: "
        "si es el sujeto focal o la escena exige leerlo, un envase 100%% liso o una etiqueta claramente corrupta se ve FALSO/IA; si el "
        "envase es incidental o el detalle seria imperceptible para una persona, NO hagas pixel-peeping ni bloquees microtexto que no se ve. "
        "Una etiqueta legible con marca inventada es deseable cuando el envase es focal. Lo unico vetado dentro de la "
        "imagen es texto deforme/garabateado/sin sentido, o una marca real que el guion NO menciona (si el guion nombra una marca, mostrarla es correcto). "
        "Bloquea la falta de evidencia SOLO cuando ningun overlay declarado cubre el claim, o cuando el fondo "
        "CONTRADICE el guion o muestra el sujeto/producto equivocado.\n"
        "Compara cada muestra contra caption_text, visual_targets, visual_proof y editorial_point de ESA escena. "
        "Nota: visual_proof describe QUE dramatiza/escenifica el visual, no una prueba forense; evalua si la "
        "escena lo dramatiza, no si lo demuestra.\n"
        "STOCK REAL (source pexels/clip_extractor): esa media ya paso un fit-gate de vision al elegirse. Sus "
        "visual_targets fueron material del QUERY de busqueda, NO una shot list: NO bloquees porque 'falta X "
        "elemento en pantalla' (interfaz, tabs, cursor) si la escena dramatiza el beat con persona/gesto/objeto "
        "coherente. Para stock real bloquea SOLO: contradiccion narrativa evidente, marcas/logos ajenos, texto "
        "legible de otro idioma/tema, o placeholder (chroma/mockup).\n"
        "VETO DE MEDIA: bloquea una media SOLO si CONTRADICE lo narrado o tiene un error visual obvio "
        "(manos/anatomia deformes, texto garabateado dentro de la imagen, producto visualmente distinto al de "
        "otras escenas, sujeto equivocado). B-roll evocativo de personas/accion que dramatiza el beat es "
        "correcto aunque no lo 'pruebe'. El producto protagonista repetido entre escenas es CONSISTENCIA "
        "deseada, no repeticion injustificada; repeticion penalizable = mismo encuadre identico sin cambio de beat. "
        "Bloquea tambien media faltante, captions poco legibles, overlays que probablemente tapan captions/sujeto "
        "y SFX mal anclados.\n"
        "CONSISTENCIA DE OBJETO: el producto/objeto protagonista debe ser visualmente el MISMO en todas las "
        "escenas donde aparece (tipo de envase, forma, color aproximado). Compara las muestras ENTRE SI, no solo "
        "contra su escena; tarro en una escena y botella en otra = id='product_inconsistency' (major; blocker "
        "solo si es irreconciliable regenerando una imagen).\n"
        "BALANCE DE MEDIO: las escenas plate no tienen imagen adjunta -- evalualas desde el JSON con el mismo "
        "rigor: mas de 2 escenas 100%% texto consecutivas o mayoria del body sin media = blocker id='media_ratio'.\n"
        "IMAGENES ADJUNTAS:\n%s\n"
        "PROPS JSON RESUMIDO:\n%s" % (
            json.dumps(labels, ensure_ascii=False, indent=2),
            json.dumps(props_payload(props), ensure_ascii=False, indent=2),
        )
    )
    raw = call_ai_json(SYSTEM_PROMPT, user, images=images, vision_required=bool(images))
    report = normalize_report("props", raw, os.path.abspath(props_path))
    report["sampled_images"] = images
    report["image_labels"] = labels
    return report


def render_qa(mp4, props_path):
    props = load_json(props_path)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    images, labels = sample_render_images(mp4, props, os.path.join(WORK, "render_frames_%s" % stamp))
    notes = ""
    # Memoria del juez (mismo fix que plan_qa/script_qa/props_qa): sin ella no
    # hay forma de distinguir "no mejoro nada" real de "el juez repite su
    # veredicto anterior sin acreditar cambios" -- score identico 3 rondas
    # seguidas pese a cambios reales de motor/plan fue la senal.
    prev_block = ""
    try:
        prev = load_json(default_out("render"))
        if prev.get("stage") == "render" and prev.get("artifact") == os.path.abspath(mp4) \
                and prev.get("criterion_version") == CRITERION_VERSION:
            prev_block = (
                "TU REPORTE ANTERIOR sobre una version previa de ESTE render (ya corregida):\n"
                "score=%s\nissues=%s\n"
                "REGLA DE CONSISTENCIA: evalua primero, escena por escena, si el issue anterior fue resuelto "
                "por un cambio real (fondo mas fuerte, overlay nuevo, duracion extendida). Si SI cambio algo "
                "concreto en esa escena respecto a lo que describiste antes, no repitas el MISMO texto de "
                "critica sin reconocer el cambio -- vuelve a evaluar esa escena desde cero con lo que ves ahora. "
                "Si una escena no cambio en absoluto, tu veredicto anterior sigue valiendo.\n"
                % (prev.get("score"), json.dumps([
                    {"scene": i.get("scene"), "issue": str(i.get("issue"))[:200]}
                    for i in (prev.get("blocking_issues") or [])[:8]
                ], ensure_ascii=False))
            )
    except Exception:
        pass
    user = (
        "STAGE=RENDER_MP4. Revisa el video renderizado antes de entregar.\n"
        + prev_block
        + ("REGLAS DEL MAPA EDITABLE:\n%s\n" % notes if notes else "")
        + "Usa las imagenes adjuntas. Bloquea si captions no se leen, overlays tapan cosas, hay plates vacios, "
        "el visual CONTRADICE lo narrado, hay texto DEFORME/garabateado/sin sentido dentro de la media, "
        "manos/anatomia deformes, el producto protagonista cambia visualmente entre escenas, avatar/companion "
        "estan mal compuestos, CTA no se entiende o el reel no parece profesional para Reels. "
        "OJO: una etiqueta LEGIBLE y bien escrita (marca inventada, o real si el guion la nombra) NO es "
        "defecto. Aplica saliencia perceptual: texto corrupto visible en un objeto focal falla; microtexto incidental "
        "que no seria perceptible a 1080p y velocidad normal se ignora. No amplíes pixeles para inventar defectos.\n"
        "EL MEDIO YA SE DECIDIO en plan/props: NO re-litigues aqui la eleccion media-vs-plate ni pidas convertir "
        "escenas; en render la media solo se veta por contradiccion o error visual obvio (id='medium_remove').\n"
        "STOCK REAL (source pexels/clip_extractor): ya paso un fit-gate de vision Y el juez de props. 'No "
        "aterriza claramente el concepto' o 'no se ve X elemento en pantalla' NO son blockers para stock que "
        "dramatiza el beat con persona/gesto coherente -- eso es re-litigar la eleccion. Blocker solo por "
        "contradiccion evidente, marcas ajenas o placeholder roto.\n"
        "ESCENAS DE AVATAR: split_h es un diseno DELIBERADO de tres bandas fijas (mandato del producto, no un "
        "accidente de layout): companion/broll arriba, franja de captions en el medio (fondo solido plano "
        "cuando no hay caption activo -- NO es 'espacio vacio muerto', es la zona reservada para no tapar la "
        "cara), avatar 16:9 completo abajo SIN recortar. NO apliques 'top-heavy' ni 'franja sin funcion' ni "
        "'un elemento dominante' a esta estructura: evalua cada banda por separado (companion+overlay = una "
        "unidad compositiva, avatar = otra). Bloquea SOLO si dentro de UNA banda hay colision real (overlay "
        "tapando al companion, texto compitiendo con otro texto) o si el avatar mismo se ve recortado/mal "
        "encuadrado -- no por la existencia de las tres bandas en si.\n"
        "RUBRICA DE COMPOSICION (para el resto: plates, diagramas, overlays compuestos y escenas full-bleed "
        "con foto/clip se evaluan como cinematografia: sujeto claro, encuadre no accidental, zona de caption "
        "despejada -- el espacio negativo natural de una foto NO es 'franja sin funcion'):\n"
        "a) UN elemento dominante claro por pantalla; dos piezas del mismo peso visual compitiendo = major.\n"
        "b) Espacio vacio intencional vs muerto: una franja grande sin funcion (ni respiro compositivo ni zona de caption) = major.\n"
        "c) Contraste de escala: si todos los elementos pesan igual la pantalla es plana = minor; con 3+ piezas = major.\n"
        "d) Color de acento en maximo 2 zonas por frame; acento regado pierde jerarquia = minor.\n"
        "e) Composicion top-heavy: contenido apretado arriba con la mitad inferior vacia (fuera de la banda del caption) = major.\n"
        "f) Fondo decorativo sin funcion (glow/mancha de color detras de un plate) = major.\n"
        "IMAGENES ADJUNTAS:\n%s\n"
        "PROPS JSON RESUMIDO:\n%s" % (
            json.dumps(labels, ensure_ascii=False, indent=2),
            json.dumps(props_payload(props), ensure_ascii=False, indent=2),
        )
    )
    raw = call_ai_json(SYSTEM_PROMPT, user, images=images, vision_required=True)
    report = normalize_report("render", raw, os.path.abspath(mp4))
    report["sampled_images"] = images
    report["image_labels"] = labels
    return report


def default_out(stage):
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, "%s_latest.json" % stage)


def main():
    parser = argparse.ArgumentParser(description="AI QA gates for Reel Engine")
    parser.add_argument("stage", choices=["script", "tts", "plan", "props", "render"])
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    out = args.out or default_out(args.stage)
    neutralized = production_judge_neutralized()
    if production_mode() and neutralized:
        dump_report({
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "stage": args.stage,
            "provider": provider(),
            "artifact": args.paths[0] if args.paths else None,
            "ok": False,
            "score": 0,
            "min_score": int(os.environ.get("AI_QA_MIN_SCORE", "75")),
            "blocking_issues": [{
                "id": "ai_qa_judge_neutralized_in_production",
                "severity": "blocker",
                "scene": None,
                "issue": "PROVIDER_MODE=real pero el juez semantico esta neutralizado: %s." % ", ".join(neutralized),
                "fix": "En produccion usa AI_QA_PROVIDER real (codex/vllm), AI_QA_ENABLED=1, AI_QA_REQUIRED=1 y sin ALLOW_QA_GATE_BYPASS. Estos toggles solo se permiten fuera de PROVIDER_MODE=real.",
            }],
            "warnings": [],
            "production_judge_neutralized": neutralized,
        }, out)
        print("AI QA FAIL: PROVIDER_MODE=real no permite neutralizar el juez semantico (%s)" % ", ".join(neutralized))
        return 1
    if not enabled():
        dump_report({
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "stage": args.stage,
            "provider": provider(),
            "artifact": args.paths[0] if args.paths else None,
            "ok": True,
            "score": 100,
            "min_score": int(os.environ.get("AI_QA_MIN_SCORE", "75")),
            "blocking_issues": [],
            "warnings": ["AI_QA_ENABLED=0"],
            "skipped": True,
    }, out)
        print("AI QA SKIP: AI_QA_ENABLED=0")
        return 0
    try:
        if args.stage == "script":
            report = script_qa(args.paths[0])
        elif args.stage == "tts":
            if len(args.paths) < 1:
                print("uso: ai_qa.py tts <voice.wav> [word_alignment.json] [plan.json]")
                return 2
            alignment_path = args.paths[1] if len(args.paths) >= 2 else None
            plan_path = args.paths[2] if len(args.paths) >= 3 else None
            report = tts_qa(args.paths[0], alignment_path, plan_path)
        elif args.stage == "plan":
            report = plan_qa(args.paths[0])
        elif args.stage == "props":
            report = props_qa(args.paths[0])
        else:
            if len(args.paths) < 2:
                print("uso: ai_qa.py render <mp4> <props.json>")
                return 2
            report = render_qa(args.paths[0], args.paths[1])
    except Exception as e:
        report = normalize_report(args.stage, {
            "ok": False,
            "score": 0,
            "blocking_issues": [{
                "id": "ai_qa_runtime",
                "severity": "blocker",
                "scene": None,
                "issue": str(e),
                "fix": "Corrige proveedor AI_QA_PROVIDER/CODEX_HOME/VLLM o desactiva AI_QA_REQUIRED solo en pruebas.",
            }],
            "warnings": [],
        }, artifact=args.paths[0] if args.paths else None)
    dump_report(report, out)
    if report["ok"]:
        print("AI QA OK: %s score=%s report=%s" % (args.stage, report["score"], out))
        return 0
    print("AI QA FAIL: %s score=%s report=%s" % (args.stage, report["score"], out))
    for item in report.get("blocking_issues") or []:
        if isinstance(item, dict):
            print("  %s scene=%s: %s" % (item.get("severity", "issue"), item.get("scene"), item.get("issue")))
    return 1 if required() else 0


if __name__ == "__main__":
    sys.exit(main())


def run_stage(stage, *paths):
    """Adapter programatico del gate: corre la etapa y devuelve el reporte dict.
    Reusa main() (con toda su logica de neutralizacion/min_score) via argv."""
    import sys as _sys
    argv = _sys.argv
    _sys.argv = ["qa", stage] + [str(p) for p in paths]
    try:
        rc = main()
    finally:
        _sys.argv = argv
    try:
        report = json.load(open(default_out(stage), encoding="utf-8"))
    except Exception:
        report = {}
    report["ok"] = bool(report.get("ok")) and not rc
    return report
