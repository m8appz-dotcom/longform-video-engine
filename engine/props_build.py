#!/usr/bin/env python3
import hashlib, json, os, re, subprocess, shutil, sys
from engine.config import ROOT as HERE  # V2PORT
ROOT=os.environ.get("ENGINE_ROOT", HERE)
REM=os.environ.get("REMOTION_DIR", os.path.join(ROOT,"remotion"))
WORK=os.environ.get("WORK_DIR", os.path.join(ROOT,"work"))
PUB=os.path.join(REM,"public","media"); os.makedirs(PUB,exist_ok=True)

from engine import media_tools
from engine import resolve as plan_resolve
from engine import pacing as pacing_utils
from providers.core import sanitize_clip_extractor_query
from engine import _generated as GEN  # V2PORT: registro unico
SUPPORTED_OVERLAY_COMPONENTS = set(GEN.COMPONENTS)
def run(a): return media_tools.run(a,capture_output=True,text=True)
def allow_asset_fallbacks():
    return os.environ.get("ALLOW_ASSET_FALLBACKS","").lower() in ("1","true","yes")
def should_regen(name):
    return (
        os.environ.get("REGEN_ASSETS","").lower() in ("1","true","yes") or
        os.environ.get(name,"").lower() in ("1","true","yes")
    )
def env_truthy(name):
    return os.environ.get(name,"").lower() in ("1","true","yes","on")
def no_provider_calls():
    return env_truthy("NO_PROVIDER_CALLS")
def allow_qa_gate_bypass():
    return env_truthy("ALLOW_QA_GATE_BYPASS")
def production_mode():
    return os.environ.get("PROVIDER_MODE","mock").lower()=="real"
def load_qa_gate(name):
    path=os.path.join(WORK,"ai_qa","%s_latest.json"%name)
    try:
        data=json.load(open(path,encoding="utf-8-sig"))
    except Exception:
        return {"ok":False,"missing":True,"report":path}
    return {
        "ok":bool(data.get("ok")),
        "score":data.get("score"),
        "stage":data.get("stage"),
        "created_at":data.get("created_at"),
        "skipped":bool(data.get("skipped")),
        "blocking_issues":data.get("blocking_issues") or [],
        "report":path,
    }
def require_qa_gates(gates):
    # El bypass solo aplica fuera de produccion; con PROVIDER_MODE=real se ignora
    # y se exige el gate real (cierra Fuga #1).
    if allow_qa_gate_bypass() and not production_mode():
        return
    missing=[]; failed=[]; skipped=[]
    for name in ("script","tts","plan"):
        gate=gates.get(name) or {}
        if gate.get("missing"):
            missing.append(name)
        elif gate.get("skipped") and production_mode():
            # skipped:true (AI_QA_ENABLED=0) no cuenta como aprobado en produccion
            skipped.append(name)
        elif not gate.get("ok"):
            failed.append("%s(score=%s)"%(name, gate.get("score")))
    if missing or failed or skipped:
        bits=[]
        if missing:
            bits.append("faltan %s"%", ".join(missing))
        if failed:
            bits.append("fallaron %s"%", ".join(failed))
        if skipped:
            bits.append("saltados sin juez (no permitido en produccion) %s"%", ".join(skipped))
        raise SystemExit("QA gate requerido antes de props: %s"%"; ".join(bits))
def reuse_omni_video_clips():
    return env_truthy("REUSE_OMNI_VIDEO_CLIPS")
def guarded_video_cache(regen_name):
    return reuse_omni_video_clips() and regen_name in ("REGEN_AVATAR", "REGEN_VIDEO")
def min_media_bytes(dst):
    ext=os.path.splitext(dst)[1].lower()
    if ext==".mp4":
        return int(os.environ.get("MIN_VIDEO_BYTES","120000") or 120000)
    if ext in (".png",".jpg",".jpeg",".webp"):
        return int(os.environ.get("MIN_IMAGE_BYTES","80000") or 80000)
    return 1
def media_meta_path(dst):
    return dst + ".meta.json"

def media_signature(kind, **fields):
    payload = {"kind": kind, **fields}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

def write_media_meta(dst, signature, **fields):
    if not signature:
        return
    meta = {"signature": signature, "fingerprint_version": 2, **fields}
    with open(media_meta_path(dst), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

def existing_media(dst, media_name, regen_name, signature=None):
    if not os.path.exists(dst):
        if guarded_video_cache(regen_name) or no_provider_calls():
            raise RuntimeError("cache requerida pero falta %s; no llamo proveedor" % media_name)
        return False
    if should_regen(regen_name):
        if guarded_video_cache(regen_name) or no_provider_calls():
            print("  cache protegida %s: ignoro %s/REGEN_ASSETS para evitar llamada a proveedor"%(media_name, regen_name))
        else:
            return False
    if not os.path.exists(dst):
        return False
    size=os.path.getsize(dst)
    minimum=min_media_bytes(dst)
    if size < minimum:
        if guarded_video_cache(regen_name) or no_provider_calls():
            raise RuntimeError("cache %s invalida (%d bytes < %d); no llamo proveedor"%(media_name,size,minimum))
        print("  cache invalida %s: %d bytes < %d; regenerando"%(media_name,size,minimum))
        return False
    if signature:
        try:
            meta=json.load(open(media_meta_path(dst), encoding="utf-8"))
        except Exception:
            if guarded_video_cache(regen_name):
                print("  cache protegida %s: sin fingerprint; adopto cache legacy para evitar gasto Omni"%media_name)
                write_media_meta(dst, signature, kind="legacy_video_cache_adopted")
                return True
            if no_provider_calls():
                raise RuntimeError("cache %s sin fingerprint; no llamo proveedor"%media_name)
            print("  cache invalida %s: sin fingerprint; regenerando"%media_name)
            return False
        if meta.get("signature") != signature:
            if guarded_video_cache(regen_name):
                if meta.get("fingerprint_version") != 2:
                    print("  cache protegida %s: fingerprint legacy; adopto cache para evitar gasto Omni"%media_name)
                    write_media_meta(dst, signature, kind=meta.get("kind","legacy_video_cache_adopted"))
                    return True
                raise RuntimeError("cache %s no coincide con fingerprint; no llamo proveedor de video"%media_name)
            if no_provider_calls():
                raise RuntimeError("cache %s no coincide con fingerprint; no llamo proveedor"%media_name)
            print("  cache invalida %s: fingerprint distinto; regenerando"%media_name)
            return False
    return True
ASSET_MANIFEST=[]
def record_asset(kind, media, provider=None, signature=None, **fields):
    if not media:
        return
    entry={"kind":kind,"media":media}
    if provider:
        entry["provider"]=provider
    if signature:
        entry["signature"]=signature
    entry.update({k:v for k,v in fields.items() if v is not None})
    ASSET_MANIFEST.append(entry)
def write_asset_manifest():
    path=os.path.join(REM,"asset_manifest.json")
    with open(path,"w",encoding="utf-8") as f:
        json.dump({"assets":ASSET_MANIFEST},f,ensure_ascii=False,indent=1)
    return path
def slug(s):
    out=re.sub(r"[^a-z0-9]+","-",str(s or "").lower()).strip("-")
    return out[:42] or "asset"
def apply_subject_lock(prompt, lock):
    """Producto/objeto heroe consistente entre escenas (meta.subject_lock).
    gpt-image-2 no acepta imagen de referencia ni seed: sin una descripcion
    canonica compartida, cada prompt inventa un envase distinto (tarro vs
    botella, hallado en revision humana). Se concatena DESPUES del prompt para
    no diluir los prefijos no-text del provider; al entrar al prompt tambien
    entra al media_signature, asi que el cache invalida solo."""
    p = str(prompt or "")
    lock = str(lock or "").strip()
    if lock and "subject lock" not in p.lower():
        return p + " Producto heroe (identico en todas las escenas, subject lock): " + lock + "."
    return p


# Detecta si un prompt muestra al protagonista humano (persona, o sus manos en
# accion). Bilingue. Un prompt de solo-objeto (telefono, diagrama, dashboard sin
# nadie) NO matchea, para no forzar una persona donde no debe haberla.
_PERSON_IN_PROMPT = re.compile(
    r"\b(person|people|man|woman|men|women|adult|guy|girl|someone|somebody|"
    r"he|she|his|her|their hands?|a hand|hands?\b|sitting|standing|pointing|"
    r"staring|holding|typing|leaning|arms crossed|"
    r"persona|hombre|mujer|gente|mano|manos|sostiene|sosteniendo|de pie|sentad[oa]|"
    r"senala|senalando|presentador|presentadora)\b",
    re.I,
)


def apply_person_lock(prompt, lock):
    """Protagonista humano consistente entre escenas (meta.person_lock).
    Analogo a subject_lock pero para la PERSONA: sin esto, cada gpt-image-2
    inventa una cara/edad/peinado distintos y el reel se ve con 3-4 personas
    diferentes (hallado en revision real del reel de AI money: pelo lacio vs
    rizado, y una mano de mujer en el cierre). A diferencia del producto, NO se
    aplica a TODOS los prompts: solo a los que muestran una persona o sus manos
    (via _PERSON_IN_PROMPT), para no meter un protagonista en la escena del
    telefono o el diagrama. Entra al media_signature igual que subject_lock."""
    p = str(prompt or "")
    lock = str(lock or "").strip()
    if lock and "person lock" not in p.lower() and _PERSON_IN_PROMPT.search(p):
        return p + " La persona mostrada es SIEMPRE el mismo individuo, identico en todas las escenas (person lock): " + lock + "."
    return p


def apply_locks(prompt, subject_lock, person_lock):
    """Aplica ambos locks (producto + persona) en orden. Punto unico para que
    todos los call sites de generacion de imagen queden consistentes."""
    return apply_person_lock(apply_subject_lock(prompt, subject_lock), person_lock)


def hydrate_overlay_image_slots(overlays, provider, subject_lock=""):
    regen=os.environ.get("REGEN_OVERLAY_IMAGES","").lower() in ("1","true","yes")
    for oi,o in enumerate(overlays or []):
        params=o.get("params") if isinstance(o.get("params"),dict) else {}
        slots=params.get("image_slots")
        if not isinstance(slots,list):
            continue
        for si,slot in enumerate(slots):
            if not isinstance(slot,dict):
                continue
            if slot.get("src"):
                continue
            asset=slot.get("asset")
            if isinstance(asset,str) and asset:
                if re.match(r"^https?://",asset) or asset.startswith("media/"):
                    slot["src"]=asset
                elif os.path.exists(asset):
                    name="overlay_%02d_%02d_%s%s"%(oi,si,slug(slot.get("id") or slot.get("role")),os.path.splitext(asset)[1] or ".png")
                    dst=os.path.join(PUB,name)
                    shutil.copy(asset,dst)
                    slot["src"]="media/"+name
                continue
            prompt=apply_subject_lock(slot.get("prompt"), subject_lock)
            if not prompt:
                continue
            name="overlay_%02d_%02d_%s.png"%(oi,si,slug(slot.get("id") or slot.get("role")))
            dst=os.path.join(PUB,name)
            try:
                model=slot.get("model") or os.environ.get("CODEX_IMAGE_MODEL","gpt-image-2")
                sig=media_signature(
                    "overlay_image",
                    prompt=prompt,
                    model=model,
                    size=slot.get("size") or "",
                    slot_id=slot.get("id") or slot.get("role") or si,
                )
                if not existing_media(dst, "media/"+name, "REGEN_OVERLAY_IMAGES", signature=sig):
                    provider.image_asset(prompt,dst,model=model,size=slot.get("size"))
                    write_media_meta(dst, sig, kind="overlay_image", prompt=prompt, model=model, size=slot.get("size") or "")
                slot["src"]="media/"+name
                record_asset("overlay_image", slot["src"], provider=getattr(provider,"mode","unknown"), signature=sig, component=o.get("component"))
            except Exception as e:
                msg="overlay image %s/%s fallo: %s"%(o.get("component"),slot.get("id") or slot.get("role") or si,str(e)[:140])
                if no_provider_calls() or (provider.mode=="real" and not allow_asset_fallbacks()):
                    raise SystemExit(msg)
                print("  %s -> fallback grafico permitido"%msg)
                slot["src"]=""
                slot["fallback"]="glyph"
    return overlays
def build(plan_path, alignment_path):
    """Construye remotion/props.json desde un plan resuelto + alignment real."""
    plan=json.load(open(plan_path,encoding="utf-8")); al=json.load(open(alignment_path,encoding="utf-8"))
    r=plan_resolve.resolve(plan,al); brand=plan["meta"]["brand"]; style=dict(plan.get("meta",{}).get("style",{}) or {}); hx=lambda c:c if c.startswith("#") else "#"+c
    style.setdefault("caption_granularity", "word")
    style.setdefault("caption_decoration", "none")
    style.setdefault("caption_emphasis_policy", "smart_stopwords")
    style.setdefault("caption_readability_mode", "adaptive_boxed")
    style.setdefault("render_policy", "declared_only")
    style.setdefault("hook_overlay", "none")
    style.setdefault("progress_bar", "none")
    style.setdefault("texture", "subtle")
    raw=[]
    for w in al["words"]:
        c=re.sub(r"^[^\w]+|[^\w]+$","",w["word"]).strip() or w["word"].strip()
        if c: raw.append({"word":c,"startMs":int(w["start_ms"]),"endMs":int(w["end_ms"])})
    caps=[]
    for i,c in enumerate(raw):
        nxt=raw[i+1]["startMs"] if i+1<len(raw) else c["endMs"]
        caps.append({"word":c["word"],"startMs":c["startMs"],"endMs":max(c["endMs"],nxt)})
    from providers.core import get_providers; P=get_providers(1080,1920)
    subject_lock=str((plan.get("meta") or {}).get("subject_lock") or "").strip()
    person_lock=str((plan.get("meta") or {}).get("person_lock") or "").strip()
    hydrate_overlay_image_slots(r.get("overlays",[]), P, subject_lock=subject_lock)
    voice=os.path.join(WORK,"voice.wav"); amb=os.path.join(WORK,"ambient.wav")
    def avatar_clip_reuse_enabled():
        # Identity continuity is handled through avatar_key/prompt. Reusing the same
        # rendered clip is only safe when the spoken segment also matches.
        if os.environ.get("REUSE_AVATAR_CLIP","0").lower() not in ("1","true","yes","on"):
            return False
        provider=os.environ.get("AVATAR_PROVIDER","").lower()
        return provider in ("", "kreado", "kreado-ai", "kreadoai")
    def avatar_dialogue_enabled():
        return False
    def avatar_runtime_provider(source=None):
        runtime=(os.environ.get("AVATAR_PROVIDER") or source or "kreado").lower()
        if runtime in ("google", "gemini", "omni", "seedance", "wavespeed"):
            raise RuntimeError("AVATAR_PROVIDER legacy no permitido: %s. Usa AVATAR_PROVIDER=kreado." % runtime)
        return runtime
    def avatar_aspect_ratio_for(source=None):
        runtime=avatar_runtime_provider(source)
        if runtime in ("kreado", "kreado-ai", "kreadoai"):
            return os.environ.get("KREADO_ASPECT_RATIO", "16:9")
        return "9:16"
    def short_hash(text):
        return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:16]
    def video_model_for(source, avatar=False):
        runtime=avatar_runtime_provider(source) if avatar else (source or "")
        if avatar and runtime in ("kreado", "kreado-ai", "kreadoai"):
            return "kreado-human-%s" % (os.environ.get("KREADO_HUMAN_ID") or "515947")
        return os.environ.get("OMNI_VIDEO_MODEL", "gemini-omni-flash-preview")
    def video_resolution_for(avatar=False):
        if avatar and avatar_runtime_provider() in ("kreado", "kreado-ai", "kreadoai"):
            return "kreado-render"
        return os.environ.get("OMNI_VIDEO_DELIVERY", "uri")
    def avatar_signature_needs_spoken(source=None):
        runtime=avatar_runtime_provider(source)
        return runtime in ("kreado", "kreado-ai", "kreadoai")

    def avatar_companion_prompt(scene, spoken):
        clip=scene.get("clip", {}) or {}
        companion=clip.get("companion") if isinstance(clip.get("companion"), dict) else {}
        if companion.get("prompt"):
            return companion["prompt"]
        explicit=clip.get("companion_prompt") or scene.get("avatar_companion_prompt")
        if explicit:
            return explicit
        editorial_context=str(scene.get("editorial_point") or "").lower()
        primary_context=" ".join(str(x or "") for x in [
            spoken,
            scene.get("editorial_point"),
            scene.get("visual_proof"),
            scene.get("intent"),
            " ".join(scene.get("visual_targets") or []),
        ]).lower()
        context=" ".join([primary_context, str(scene.get("why_it_matters") or ""), str(scene.get("why_this_visual_not_other") or "")]).lower()
        targets=" ".join(scene.get("visual_targets") or []).strip()
        if targets:
            subject=targets
        else:
            subject=str(
                scene.get("visual_proof") or scene.get("editorial_point") or scene.get("intent")
                or "the concrete idea spoken in this scene"
            ).strip()
        return (
            "Square 1:1 premium editorial still for the top half of a vertical reel. "
            "Create a unique companion image for this avatar scene, not a reused B-roll from another scene. "
            f"Main visual: {subject}. "
            "Clean background and accents aligned to the brand palette, one clear focal idea, natural editorial light, "
            "no readable text, no numbers, no logos, no watermark, no UI, no talking-head presenter."
        )

    def publish_user_asset(asset, prefix, idx):
        if not isinstance(asset, str) or not asset.strip():
            raise RuntimeError("asset de usuario vacio")
        asset=asset.strip()
        if re.match(r"^https?://", asset) or asset.startswith("media/"):
            return asset
        src=asset if os.path.isabs(asset) else os.path.join(ROOT, asset)
        if not os.path.exists(src):
            raise RuntimeError("asset de usuario no existe: %s" % asset)
        ext=os.path.splitext(src)[1].lower() or ".mp4"
        name="%s_%d%s" % (prefix, idx, ext)
        dst=os.path.join(PUB, name)
        shutil.copy(src, dst)
        return "media/" + name

    def engine_generated_clip_extractor_reference(asset):
        text = str(asset or "").strip().lower().replace("\\", "/")
        return bool(
            re.search(r"(^|/)broll_clip_extractor_\d+\.mp4$", text)
            or re.search(r"(^|/)clip_extractor", text)
            or re.search(r"(^|/)work/clips/", text)
            or text.endswith(".clip_extractor.json")
        )

    def avatar_companion_query(scene, spoken):
        clip=scene.get("clip", {}) or {}
        companion=clip.get("companion") if isinstance(clip.get("companion"), dict) else {}
        if companion.get("query"):
            return companion["query"]
        context=" ".join(str(x or "") for x in [
            spoken,
            scene.get("editorial_point"),
            scene.get("visual_proof"),
            scene.get("intent"),
            " ".join(scene.get("visual_targets") or []),
            scene.get("why_it_matters"),
        ]).lower()
        targets=[x for x in re.findall(r"[0-9A-Za-z]{4,}", " ".join(scene.get("visual_targets") or []))[:5]]
        if targets:
            return " ".join(targets)
        return str(scene.get("editorial_point") or scene.get("intent") or "concrete b-roll for the spoken idea").strip()

    def avatar_companion_label(scene, spoken):
        targets=[str(x).strip() for x in (scene.get("visual_targets") or []) if str(x).strip()]
        for bad in ("presentador", "avatar", "espacio para captions", "tono prudente"):
            targets=[x for x in targets if bad not in x.lower()]
        if targets:
            return " + ".join(targets[:2])
        words=[w.upper() for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{5,}", spoken or "")[:2]]
        return " ".join(words) or "CONTEXTO"

    def resolve_avatar_companion(scene, spoken, idx, avatar_key, dur):
        clip=scene.get("clip", {}) or {}
        companion=clip.get("companion") if isinstance(clip.get("companion"), dict) else {}
        explicit=companion.get("source")
        label=avatar_companion_label(scene, spoken)
        if explicit:
            sources=[explicit]
        else:
            sources=[]
            if companion.get("asset"):
                sources.append("asset")
            # Escalera del mandato tambien para el companion del avatar (mitad
            # superior): clip_extractor (accion/persona real) antes que pexels e
            # image. El schema documenta este orden; antes props saltaba directo a
            # pexels. La cadena ya cae al siguiente source ante cualquier excepcion.
            sources.extend(["clip_extractor", "pexels", "image", "motion"])
        if "motion" not in sources:
            sources.append("motion")

        for source in sources:
            try:
                if source=="asset":
                    media=publish_user_asset(companion.get("asset") or clip.get("companion_asset"), "avatar_companion_user", idx)
                    record_asset("avatar_companion", media, provider="user", avatar_key=avatar_key, source="asset")
                    return {"media":media,"motion":companion.get("motion") or "static","prompt":"","source":"asset","label":label}
                if source=="clip_extractor":
                    query=sanitize_clip_extractor_query(avatar_companion_query(scene, spoken))
                    characteristics=companion.get("characteristics") or {}
                    model=companion.get("clip_model") or os.environ.get("CLIP_EXTRACTOR_MODEL", "gemma-local")
                    vllm_base_url=companion.get("vllm_base_url") or os.environ.get("CLIP_EXTRACTOR_VLLM_BASE_URL", "http://127.0.0.1:18100/v1")
                    max_clip_seconds=companion.get("max_clip_seconds") or round(max(1.5, dur))
                    sig=media_signature(
                        "avatar_companion_clip_extractor",
                        query=query,
                        model=model,
                        vllm_base_url=vllm_base_url,
                        max_clip_seconds=max_clip_seconds,
                        visual_targets=scene.get("visual_targets") or [],
                        visual_proof=scene.get("visual_proof") or "",
                        scene_index=idx,
                        avatar_key=avatar_key,
                        spoken_hash=short_hash(spoken),
                    )
                    dst=os.path.join(PUB, "avatar_companion_clip_extractor_%d.mp4"%idx)
                    name="media/avatar_companion_clip_extractor_%d.mp4"%idx
                    if not existing_media(dst, name, "REGEN_AVATAR_COMPANION", signature=sig):
                        if no_provider_calls():
                            raise RuntimeError("NO_PROVIDER_CALLS=1 y companion Clip Extractor no esta cacheado")
                        P.clip_extractor_clip(
                            query,
                            max(1.5, dur),
                            dst,
                            characteristics=characteristics,
                            model=model,
                            vllm_base_url=vllm_base_url,
                            max_clip_seconds=max_clip_seconds,
                        )
                        sidecar={}
                        try:
                            sidecar=json.load(open(dst+".clip_extractor.json",encoding="utf-8"))
                        except Exception:
                            sidecar={}
                        write_media_meta(
                            dst,
                            sig,
                            kind="avatar_companion",
                            provider="clip_extractor",
                            query=query,
                            characteristics=characteristics,
                            model=model,
                            vllm_base_url=vllm_base_url,
                            max_clip_seconds=max_clip_seconds,
                            visual_targets=scene.get("visual_targets") or [],
                            visual_proof=scene.get("visual_proof") or "",
                            clip_id=sidecar.get("clip_id"),
                            download_url=sidecar.get("download_url"),
                            base_url=sidecar.get("base_url"),
                            steps=sidecar.get("steps") or [],
                            avatar_key=avatar_key,
                            spoken_hash=short_hash(spoken),
                        )
                    record_asset("avatar_companion", name, provider="clip_extractor", signature=sig, avatar_key=avatar_key, query=query, source="clip_extractor")
                    return {"media":name,"motion":companion.get("motion") or "static","prompt":"","source":"clip_extractor","label":label}
                if source=="pexels":
                    query=avatar_companion_query(scene, spoken)
                    sig=media_signature(
                        "avatar_companion_pexels",
                        query=query,
                        visual_targets=scene.get("visual_targets") or [],
                        visual_proof=scene.get("visual_proof") or "",
                        scene_index=idx,
                        avatar_key=avatar_key,
                        spoken_hash=short_hash(spoken),
                    )
                    dst=os.path.join(PUB, "avatar_companion_%d.mp4"%idx)
                    name="media/avatar_companion_%d.mp4"%idx
                    if not existing_media(dst, name, "REGEN_AVATAR_COMPANION", signature=sig):
                        if no_provider_calls():
                            raise RuntimeError("NO_PROVIDER_CALLS=1 y companion Pexels no esta cacheado")
                        P.pexels_clip(query, max(1.5, dur), dst)
                        write_media_meta(dst, sig, kind="avatar_companion", provider="pexels", query=query, avatar_key=avatar_key, spoken_hash=short_hash(spoken))
                    record_asset("avatar_companion", name, provider="pexels", signature=sig, avatar_key=avatar_key, query=query, source="pexels")
                    return {"media":name,"motion":companion.get("motion") or "static","prompt":"","source":"pexels","label":label}
                if source=="image":
                    prompt=apply_locks(avatar_companion_prompt(scene, spoken), subject_lock, person_lock)
                    size=(companion.get("size") or clip.get("companion_size") or os.environ.get("CODEX_AVATAR_COMPANION_IMAGE_SIZE") or "1024x1024")
                    model=(companion.get("model") or clip.get("companion_model") or os.environ.get("CODEX_IMAGE_MODEL", "gpt-image-2"))
                    sig=media_signature(
                        "avatar_companion_image",
                        prompt=prompt,
                        model=model,
                        size=size,
                        scene_index=idx,
                        avatar_key=avatar_key,
                        spoken_hash=short_hash(spoken),
                    )
                    dst=os.path.join(PUB,"avatar_companion_%d.png"%idx)
                    name="media/avatar_companion_%d.png"%idx
                    if not existing_media(dst, name, "REGEN_AVATAR_COMPANION", signature=sig):
                        if no_provider_calls():
                            raise RuntimeError("NO_PROVIDER_CALLS=1 y companion image no esta cacheado")
                        P.image_asset(prompt, dst, model=model, size=size)
                        write_media_meta(dst, sig, kind="avatar_companion", provider=os.environ.get("IMAGE_PROVIDER","codex"), prompt=prompt, model=model, size=size, avatar_key=avatar_key, spoken_hash=short_hash(spoken))
                    record_asset("avatar_companion", name, provider=os.environ.get("IMAGE_PROVIDER","codex"), signature=sig, avatar_key=avatar_key, prompt=prompt, source="image")
                    return {"media":name,"motion":companion.get("motion") or "kenburns-in","prompt":prompt,"source":"image","label":label}
                if source=="motion":
                    record_asset("avatar_companion", "", provider="remotion", avatar_key=avatar_key, source="motion", label=label)
                    return {"media":"","motion":"motion_graphic","prompt":"","source":"motion","label":label}
            except Exception as e:
                if source=="asset":
                    raise
                print("  avatar companion %s fallo: %s -> pruebo siguiente prioridad"%(source, str(e)[:120]))
                continue
        return {"media":"","motion":"motion_graphic","prompt":"","source":"motion","label":label}

    SFX_PRIORITY={
        "ui-impact-soft": 90,
        "impact": 86,
        "sub-drop": 82,
        "riser": 78,
        "ui-page-swipe": 70,
        "ui-filter-pass": 66,
        "ui-filter-reject": 66,
        "ui-meter-fill": 58,
        "ui-line-draw": 54,
        "ui-card-pop": 50,
        "ui-check-tick": 46,
        "ui-callout-ping": 36,
        "pop": 34,
        "click": 30,
        "ui-soft-click": 24,
    }

    def _sfx_priority(ev):
        sid=ev.get("id")
        explicit=100 if not ev.get("auto") else 0
        return explicit + SFX_PRIORITY.get(sid, 40)

    def _dedupe_sfx(events, min_gap_ms=180):
        out=[]
        cleaned=[]
        for ev in events or []:
            sid=ev.get("id")
            if not sid:
                continue
            cleaned.append(ev)
        for ev in sorted(cleaned, key=lambda x:(int(x.get("atMs",0)), -_sfx_priority(x))):
            sid=ev.get("id")
            if sid=="none":
                out.append(ev)
                continue
            at=int(ev.get("atMs",0))
            conflicts=[
                x for x in out
                if x.get("id") and x.get("id")!="none"
                and abs(int(x.get("atMs",0))-at) <= min_gap_ms
            ]
            if not conflicts:
                out.append(ev)
                continue
            best=max(conflicts + [ev], key=lambda x:(_sfx_priority(x), -abs(int(x.get("atMs",0))-at)))
            if best is ev:
                out=[x for x in out if x not in conflicts]
                out.append(ev)
        return sorted(out, key=lambda x:int(x.get("atMs",0)))

    def _add_sfx(events, sid, at_ms, gain, total_ms):
        if not sid or sid=="none":
            return
        at=int(max(0,min(int(total_ms)-60,int(at_ms)))) if total_ms else int(max(0,at_ms))
        events.append({"id":sid,"atMs":at,"gain":gain,"auto":True})

    def derive_animation_sfx(overlays, existing, total_ms):
        """Derive quiet SFX for visible overlay sub-animations.

        Plan-authored SFX remain the main creative beats. These generated events
        cover internal animations that otherwise play silently: row reveals, line
        draws, meter fills and gate pass/fail states.
        """
        events=[dict(x) for x in (existing or [])]
        for o in overlays or []:
            comp=o.get("component")
            if comp not in SUPPORTED_OVERLAY_COMPONENTS:
                continue
            start=int(o.get("startMs",0))
            dur=max(1,int(o.get("durMs",0)))
            end=start+dur
            params=o.get("params") or {}
            items=params.get("items") or params.get("criteria") or []
            if not isinstance(items,list):
                items=[]
            item_ms=[int(x) for x in (o.get("itemMs") or []) if x is not None]
            def item_times(default_step=430):
                if item_ms:
                    return [max(start,min(end-120,int(x))) for x in item_ms]
                count=max(0,min(4,len(items)))
                return [start+420+i*default_step for i in range(count)]
            if comp=="ChapterDots":
                _add_sfx(events,"ui-page-swipe",start+70,0.85,total_ms)
                for at in item_times(360)[:3]:
                    _add_sfx(events,"ui-soft-click",at,0.55,total_ms)
            elif comp=="StepList":
                _add_sfx(events,"ui-card-pop",start+80,0.9,total_ms)
                for at in item_times(460):
                    _add_sfx(events,"ui-check-tick",at,0.85,total_ms)
            elif comp=="CausalMeter":
                _add_sfx(events,"ui-line-draw",start+220,0.95,total_ms)
                for at in item_times(430):
                    _add_sfx(events,"ui-check-tick",at,0.85,total_ms)
                _add_sfx(events,"ui-meter-fill",start+int(dur*0.62),1.05,total_ms)
            elif comp in ("StatRing","CountUp"):
                _add_sfx(events,"ui-meter-fill",start+160,1.05,total_ms)
            elif comp=="FocusPunch":
                _add_sfx(events,"ui-callout-ping",start+120,0.9,total_ms)
            elif comp=="SplitCompare":
                _add_sfx(events,"ui-card-pop",start+90,0.9,total_ms)
                if (params.get("verdict") or "") in ("left","right"):
                    _add_sfx(events,"ui-filter-pass",start+int(dur*0.62),1.0,total_ms)
            elif comp=="BigWordSequence":
                for at in item_times(600)[:5]:
                    _add_sfx(events,"ui-impact-soft",at,0.9,total_ms)
            elif comp in ("Annotation","ObjectCallout","LowerThird"):
                _add_sfx(events,"ui-callout-ping",start+80,0.75,total_ms)
            elif comp=="KeywordPop":
                _add_sfx(events,"pop",start+40,0.85,total_ms)
            elif comp=="StoryArcChart":
                _add_sfx(events,"ui-line-draw",start+180,0.95,total_ms)
        return _dedupe_sfx(events)

    def derive_pacing_sfx(existing, pacing_beats, total_ms):
        events=[dict(x) for x in (existing or [])]
        for beat in pacing_beats or []:
            if beat.get("semantic") is not True and not beat.get("action"):
                continue
            at=int(beat.get("atMs",0) or 0)
            if any(abs(int(x.get("atMs",0))-at) <= 160 for x in events if x.get("id") and x.get("id")!="none"):
                continue
            kind=str(beat.get("action") or beat.get("kind") or "")
            if kind in ("layout_swap", "new_media", "hook_interrupt", "layout_shift"):
                _add_sfx(events,"ui-page-swipe",at,0.72,total_ms)
            elif kind in ("crop_reframe", "zoom_punch", "reframe"):
                _add_sfx(events,"ui-card-pop",at,0.70,total_ms)
            elif kind in ("callout_target", "insert_card"):
                _add_sfx(events,"ui-callout-ping",at,0.75,total_ms)
            elif kind == "component_state":
                _add_sfx(events,"ui-soft-click",at,0.65,total_ms)
            else:
                _add_sfx(events,"ui-soft-click",at,0.55,total_ms)
        return _dedupe_sfx(events)

    # --- Escalera de medios en BUILD ---------------------------------------
    # ESCALERA CON VALIDACION VISUAL (mandato 2026-07-07): cada peldaño genera su
    # media y un juez de vision la MIRA antes de aceptarla (qa.media_fit_check).
    # No-apta (clip irrelevante, chroma verde, logo ajeno, tutorial ajeno) ->
    # baja al siguiente peldaño. Antes solo se descendia por fallo TECNICO del
    # proveedor y cualquier cosa que devolviera se colaba hasta el render
    # (caminadora para 'automation', hallado en corrida real). El veredicto se
    # persiste por firma en dst.fit.json: un asset aceptado no se re-juzga y uno
    # rechazado no se re-acepta en la siguiente corrida. image es el piso
    # (generada a spec con locks; la juzga props_qa).
    def _fit_state(dst, sig):
        try:
            d=json.load(open(dst+".fit.json",encoding="utf-8"))
            if d.get("signature")==sig:
                return bool(d.get("fit")), str(d.get("reason") or "")
        except Exception:
            pass
        return None, ""
    def _save_fit(dst, sig, fit, reason):
        try:
            json.dump({"signature":sig,"fit":bool(fit),"reason":str(reason)[:300]},
                      open(dst+".fit.json","w",encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    def _scene_spoken(s):
        return " ".join(w.get("word","") for w in al.get("words",[])
            if int(w.get("start_ms",0))>=s["fromMs"] and int(w.get("start_ms",0))<s["toMs"]).strip()
    def _gen_scene_pexels(idx, s):
        dst=os.path.join(PUB,"broll_%d.mp4"%idx); dur=max(1.5,(s["toMs"]-s["fromMs"])/1000.0)
        # pexels_query: variante en idioma-Pexels cuando el query principal esta
        # en idioma-YouTube (escena autorada para clip_extractor que descendio).
        query=s["clip"].get("pexels_query") or s["clip"].get("query","abstract")
        sig=media_signature("pexels", query=query, visual_targets=s.get("visual_targets") or [], visual_proof=s.get("visual_proof") or "")
        prev_fit, prev_reason=_fit_state(dst, sig)
        if prev_fit is False:
            raise RuntimeError("descartado por fit-check previo: %s"%prev_reason[:100])
        if not existing_media(dst, "media/broll_%d.mp4"%idx, "REGEN_PEXELS", signature=sig):
            P.pexels_clip(query,dur,dst)
            write_media_meta(dst, sig, kind="pexels", query=query, dur_ms=round(dur*1000), visual_targets=s.get("visual_targets") or [])
        record_asset("pexels", "media/broll_%d.mp4"%idx, provider="pexels", signature=sig, query=query)
        return "media/broll_%d.mp4"%idx, dst, sig
    def _gen_scene_image(idx, s, prompt=None):
        dst=os.path.join(PUB,"image_%d.png"%idx)
        prompt=apply_locks(prompt or s["clip"].get("prompt") or s["clip"].get("query"), subject_lock, person_lock)
        model=s["clip"].get("model") if s["clip"].get("source")=="image" else "gpt-image-2"
        model=model or os.environ.get("CODEX_IMAGE_MODEL", "gpt-image-2")
        size=s["clip"].get("size") or os.environ.get("CODEX_IMAGE_SIZE", "1024x1536")
        sig=media_signature("image", prompt=prompt or "", model=model, size=size, visual_targets=s.get("visual_targets") or [], visual_proof=s.get("visual_proof") or "")
        if not existing_media(dst, "media/image_%d.png"%idx, "REGEN_IMAGE", signature=sig):
            P.image_clip(prompt, dst, model=model)
            write_media_meta(dst, sig, kind="image", prompt=prompt or "", model=model, size=size, visual_targets=s.get("visual_targets") or [])
        record_asset("image", "media/image_%d.png"%idx, provider=os.environ.get("IMAGE_PROVIDER","codex"), signature=sig, prompt=prompt or "", model=model, fallback_from=s["clip"].get("source") if s["clip"].get("source")!="image" else None)
        return "media/image_%d.png"%idx, dst, sig
    def _gen_scene_clip_extractor(idx, s):
        dst=os.path.join(PUB,"broll_clip_extractor_%d.mp4"%idx); dur=max(1.5,(s["toMs"]-s["fromMs"])/1000.0)
        query=sanitize_clip_extractor_query(s["clip"].get("query","abstract"))
        characteristics=s["clip"].get("characteristics") or {}
        sig=media_signature(
            "clip_extractor",
            query=query,
            model=s["clip"].get("model") or os.environ.get("CLIP_EXTRACTOR_MODEL", "gemma-local"),
            vllm_base_url=s["clip"].get("vllm_base_url") or os.environ.get("CLIP_EXTRACTOR_VLLM_BASE_URL", "http://127.0.0.1:18100/v1"),
            max_clip_seconds=s["clip"].get("max_clip_seconds") or round(dur),
            visual_targets=s.get("visual_targets") or [],
            visual_proof=s.get("visual_proof") or "",
            dur_ms=round(dur*1000),
        )
        prev_fit, prev_reason=_fit_state(dst, sig)
        if prev_fit is False:
            raise RuntimeError("descartado por fit-check previo: %s"%prev_reason[:100])
        name="media/broll_clip_extractor_%d.mp4"%idx
        if not existing_media(dst, name, "REGEN_CLIP_EXTRACTOR", signature=sig):
            P.clip_extractor_clip(
                query,
                dur,
                dst,
                characteristics=characteristics,
                model=s["clip"].get("model"),
                vllm_base_url=s["clip"].get("vllm_base_url"),
                max_clip_seconds=s["clip"].get("max_clip_seconds"),
            )
            sidecar={}
            try:
                sidecar=json.load(open(dst+".clip_extractor.json",encoding="utf-8"))
            except Exception:
                sidecar={}
            write_media_meta(
                dst,
                sig,
                kind="clip_extractor",
                query=query,
                characteristics=characteristics,
                model=s["clip"].get("model") or os.environ.get("CLIP_EXTRACTOR_MODEL", "gemma-local"),
                vllm_base_url=s["clip"].get("vllm_base_url") or os.environ.get("CLIP_EXTRACTOR_VLLM_BASE_URL", "http://127.0.0.1:18100/v1"),
                max_clip_seconds=s["clip"].get("max_clip_seconds") or round(dur),
                dur_ms=round(dur*1000),
                visual_targets=s.get("visual_targets") or [],
                visual_proof=s.get("visual_proof") or "",
                clip_id=sidecar.get("clip_id"),
                download_url=sidecar.get("download_url"),
                base_url=sidecar.get("base_url"),
                steps=sidecar.get("steps") or [],
            )
        meta={}
        try:
            meta=json.load(open(media_meta_path(dst),encoding="utf-8"))
        except Exception:
            meta={}
        record_asset("clip_extractor", name, provider="clip_extractor", signature=sig, query=query, clip_id=meta.get("clip_id"))
        return name, dst, sig
    def _media_ladder(idx, s, start):
        """Baja la escalera desde `start` VALIDANDO cada resultado con vision.
        Devuelve (media, src_usada). Lanza si se agota (image tambien fallo)."""
        from engine import qa as _qa
        order=["clip_extractor","pexels","image"]
        rungs=order[order.index(start):] if start in order else ["image"]
        spoken=_scene_spoken(s)
        last_err=None
        for rung in rungs:
            try:
                if rung=="clip_extractor":
                    m,dst,sig=_gen_scene_clip_extractor(idx, s)
                elif rung=="pexels":
                    m,dst,sig=_gen_scene_pexels(idx, s)
                else:
                    m,_,_=_gen_scene_image(idx, s)
                    return m, "image"  # piso: generada a spec; la juzga props_qa
            except Exception as e:
                last_err=e
                if no_provider_calls():
                    raise SystemExit("%s scene %d fallo: %s"%(rung, idx, str(e)[:140]))
                print("  %s scene %d fallo: %s -> siguiente peldaño"%(rung, idx, str(e)[:100]))
                continue
            prev_fit,_=_fit_state(dst, sig)
            if prev_fit is True:
                return m, rung  # ya aceptado en una corrida previa (misma firma)
            fit, reason=_qa.media_fit_check(m, s, spoken=spoken)
            _save_fit(dst, sig, fit, reason)
            if fit:
                print("  %s scene %d APTO (%s)"%(rung, idx, reason[:80] or "ok"))
                return m, rung
            print("  %s scene %d NO APTO: %s -> siguiente peldaño"%(rung, idx, reason[:120]))
        raise RuntimeError("escalera agotada scene %d: %s"%(idx, str(last_err)[:120]))

    avatar_clip_reuse=avatar_clip_reuse_enabled()
    avatar_cache={}
    # Pre-flight de Kreado: si el reel tiene avatar y vamos a generar de verdad,
    # verifica que el backend responda ANTES de segmentar audio y llamar TTS por
    # escena. Falla temprano con mensaje accionable en vez de a mitad del loop.
    _needs_avatar=any(
        (sc.get("role")=="avatar" or (sc.get("clip") or {}).get("source")=="kreado")
        and not (sc.get("clip") or {}).get("asset")
        for sc in r["scenes"])
    if _needs_avatar and P.mode=="real" and not no_provider_calls():
        prov=(os.environ.get("AVATAR_PROVIDER","kreado") or "kreado").lower()
        if prov in ("kreado","kreado-ai","kreadoai") and not env_truthy("REUSE_AVATAR_CLIP"):
            try:
                from providers.kreado import KreadoService
                KreadoService().health()
            except Exception as e:
                raise SystemExit("Kreado backend no disponible (pre-flight): %s. Inicia el backend (npm start / neo start) o usa REUSE_AVATAR_CLIP=1 con clips cacheados." % str(e)[:200])
    scenes=[]
    for idx,s in enumerate(r["scenes"]):
        media=""; src=s["clip"]["source"]
        avatar_companion_media=""
        avatar_companion_prompt_text=""
        avatar_companion_motion="static"
        avatar_companion_source=""
        avatar_companion_label_text=""
        if s["role"]=="hook" and src=="google" and os.path.exists(os.path.join(WORK,"hero.mp4")):
            hero=os.path.join(WORK,"hero.mp4")
            shutil.copy(hero,os.path.join(PUB,"hook.mp4")); media="media/hook.mp4"
            hero_meta=hero+".meta.json"
            if os.path.exists(hero_meta):
                shutil.copy(hero_meta,os.path.join(PUB,"hook.mp4.meta.json"))
            try:
                hook_meta=json.load(open(os.path.join(PUB,"hook.mp4.meta.json"),encoding="utf-8"))
            except Exception:
                hook_meta={}
            record_asset("hook", media, provider="google", signature=hook_meta.get("signature"), model=hook_meta.get("model"), prompt=hook_meta.get("prompt"))
            poster=os.path.join(PUB,"hook_poster.png")
            rr=run(["ffmpeg","-y","-ss","1.450","-i",hero,"-frames:v","1",poster])
            if rr.returncode!=0 or not os.path.exists(poster):
                run(["ffmpeg","-y","-ss","0.450","-i",hero,"-frames:v","1",poster])
        elif s["role"]=="avatar" or src=="kreado":
            if s["clip"].get("asset"):
                media=s["clip"]["asset"]
                clip=s.get("clip", {}) or {}
                avatar_key=clip.get("avatar_key") or "default"
                dur=plan_resolve.avatar_gen_dur_s(s)  # respeta AVATAR_MAX_MS; sin cap = escena completa
                spoken=" ".join(w.get("word","") for w in al.get("words",[])
                    if int(w.get("start_ms",0))>=s["fromMs"] and int(w.get("start_ms",0))<s["toMs"]).strip()
                companion=resolve_avatar_companion(s, spoken, idx, avatar_key, dur)
                avatar_companion_media=companion.get("media","")
                avatar_companion_prompt_text=companion.get("prompt","")
                avatar_companion_motion=companion.get("motion","static")
                avatar_companion_source=companion.get("source","")
                avatar_companion_label_text=companion.get("label","")
            else:
                try:
                    clip=s.get("clip", {}) or {}
                    avatar_key=clip.get("avatar_key") or "default"
                    dur=plan_resolve.avatar_gen_dur_s(s)  # respeta AVATAR_MAX_MS; sin cap = escena completa
                    spoken=" ".join(w.get("word","") for w in al.get("words",[])
                        if int(w.get("start_ms",0))>=s["fromMs"] and int(w.get("start_ms",0))<s["toMs"]).strip()
                    runtime_provider=avatar_runtime_provider(clip.get("source"))
                    avatar_sig_fields={
                        "source":runtime_provider,
                        "avatar_key":avatar_key,
                        "prompt":clip.get("prompt") or "",
                        "model":video_model_for(clip.get("source"), avatar=True),
                        "resolution":video_resolution_for(avatar=True),
                        "aspect_ratio":avatar_aspect_ratio_for(clip.get("source")),
                        # dur en el fingerprint: sin esto, un clip cacheado de otra
                        # duracion se reutiliza y Remotion congela el ultimo frame
                        # (labios quietos con voz = "avatar montado"). Bucket 100ms.
                        "dur_ms":int(round(dur*1000/100.0))*100,
                    }
                    if avatar_signature_needs_spoken(clip.get("source")):
                        avatar_sig_fields["spoken_hash"]=short_hash(spoken)
                    sig=media_signature("avatar", **avatar_sig_fields)
                    can_reuse=avatar_clip_reuse and runtime_provider in ("kreado","kreado-ai","kreadoai")
                    if can_reuse and sig in avatar_cache:
                        media=avatar_cache[sig]
                    else:
                        dst=os.path.join(PUB,"avatar_%d.mp4"%idx)
                        if existing_media(dst, "media/avatar_%d.mp4"%idx, "REGEN_AVATAR", signature=sig):
                            media="media/avatar_%d.mp4"%idx
                            if can_reuse:
                                avatar_cache[sig]=media
                        else:
                            seg=os.path.join(WORK,"avatar_%d.wav"%idx)
                            audio=voice
                            if os.path.exists(voice):
                                run(["ffmpeg","-y","-ss","%.3f"%(s["fromMs"]/1000.0),"-t","%.3f"%dur,
                                     "-i",voice,"-ar","48000",seg])
                                if os.path.exists(seg): audio=seg
                            P.avatar_clip(audio,dur,dst,prompt=clip.get("prompt"),script_segment=spoken); media="media/avatar_%d.mp4"%idx
                            # Resolucion REAL que entrego el backend (diagnostico): Kreado
                            # no expone knob de resolucion; verificamos que salga 16:9 a la
                            # mayor resolucion disponible. El render usa objectFit:contain,
                            # asi que un no-16:9 no recorta la cara pero conviene saberlo.
                            av_w=av_h=0
                            try:
                                pr=run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height","-of","csv=p=0:s=x",dst])
                                dims=(pr.stdout or "").strip().split("x")
                                if len(dims)>=2:
                                    av_w,av_h=int(dims[0]),int(dims[1])
                                    ar=av_w/float(av_h or 1)
                                    flag="" if abs(ar-16/9.0)<0.02 else "  (NO es 16:9 exacto ar=%.3f; contain evita recorte pero revisa el backend)"%ar
                                    print("  avatar scene %d: %dx%d%s"%(idx,av_w,av_h,flag))
                            except Exception:
                                pass
                            write_media_meta(dst, sig, kind="avatar", avatar_key=avatar_key, provider=runtime_provider, prompt=clip.get("prompt") or "", spoken_hash=short_hash(spoken) if avatar_signature_needs_spoken(clip.get("source")) else "", dur_ms=round(dur*1000), model=avatar_sig_fields["model"], resolution=avatar_sig_fields["resolution"], aspect_ratio=avatar_sig_fields["aspect_ratio"], width=av_w, height=av_h)
                            if can_reuse:
                                avatar_cache[sig]=media
                        record_asset("avatar", media, provider=runtime_provider, signature=sig, avatar_key=avatar_key, aspect_ratio=avatar_sig_fields["aspect_ratio"], humanId=os.environ.get("KREADO_HUMAN_ID") if runtime_provider.startswith("kreado") else None)
                        companion=resolve_avatar_companion(s, spoken, idx, avatar_key, dur)
                        avatar_companion_media=companion.get("media","")
                        avatar_companion_prompt_text=companion.get("prompt","")
                        avatar_companion_motion=companion.get("motion","static")
                        avatar_companion_source=companion.get("source","")
                        avatar_companion_label_text=companion.get("label","")
                except Exception as e:
                    msg="avatar scene %d fallo: %s"%(idx,str(e)[:100])
                    if no_provider_calls() or (P.mode=="real" and not allow_asset_fallbacks()):
                        raise SystemExit(msg)
                    print("  %s -> fallback visual claro permitido"%msg)
        elif src=="asset":
            try:
                if engine_generated_clip_extractor_reference(s["clip"].get("asset")):
                    raise RuntimeError("clip_extractor no puede entrar como source=asset; usa source=clip_extractor y clip.query")
                media=publish_user_asset(s["clip"].get("asset"), "scene_asset", idx)
                record_asset("asset", media, provider="user", scene_index=idx, role=s.get("role"))
            except Exception as e:
                msg="asset scene %d fallo: %s"%(idx,str(e)[:120])
                if no_provider_calls() or (P.mode=="real" and not allow_asset_fallbacks()):
                    raise SystemExit(msg)
                print("  %s -> fallback visual claro permitido"%msg)
        elif src in ("pexels","clip_extractor"):
            # Escalera con validacion visual: genera -> juez mira -> apto o baja.
            try:
                media, src = _media_ladder(idx, s, src)
            except SystemExit:
                raise
            except Exception as e:
                if P.mode=="real" and not allow_asset_fallbacks():
                    raise SystemExit("escalera scene %d agotada: %s"%(idx,str(e)[:120]))
                print("  escalera scene %d agotada: %s -> fallback visual claro permitido"%(idx,str(e)[:100]))
        elif src in ("omni","seedance"):
            raise SystemExit("clip.source=%r es legacy y no se permite; usa google solo con generative_reason/why_real_media_failed o una fuente real" % src)
        elif src=="google":
            try:
                dst=os.path.join(PUB,"gen_%d.mp4"%idx); dur=max(1.5,(s["toMs"]-s["fromMs"])/1000.0)
                # Video GENERATIVO (omni/google): aplica los locks igual que la imagen
                # generada -- es generacion, mantiene producto Y protagonista consistentes.
                # (El stock real de clip_extractor/pexels no es generativo: ahi no aplica.)
                prompt=apply_locks(s["clip"].get("prompt") or s["clip"].get("query") or "vertical 9:16 cinematic supporting B-roll, no text, no logo", subject_lock, person_lock)
                sig=media_signature(
                    "video",
                    source=src,
                    prompt=prompt,
                    model=video_model_for(src),
                    resolution=video_resolution_for(),
                    visual_targets=s.get("visual_targets") or [],
                )
                if not existing_media(dst, "media/gen_%d.mp4"%idx, "REGEN_VIDEO", signature=sig):
                    P.video_clip("google", prompt, dur, dst)
                    write_media_meta(dst, sig, kind="video", source=src, prompt=prompt, dur_ms=round(dur*1000), model=video_model_for(src), resolution=video_resolution_for(), visual_targets=s.get("visual_targets") or [])
                media="media/gen_%d.mp4"%idx
                record_asset("video", media, provider=src, signature=sig, prompt=prompt)
            except Exception as e:
                msg="generative scene %d fallo: %s"%(idx,str(e)[:100])
                if no_provider_calls() or (P.mode=="real" and not allow_asset_fallbacks()):
                    raise SystemExit(msg)
                print("  %s -> fallback visual claro permitido"%msg)
        elif src=="image":
            if s["clip"].get("asset"):
                media=s["clip"]["asset"]
            else:
                try:
                    media,_,_=_gen_scene_image(idx, s)
                except Exception as e:
                    msg="image scene %d fallo: %s"%(idx,str(e)[:120])
                    if no_provider_calls() or (P.mode=="real" and not allow_asset_fallbacks()):
                        raise SystemExit(msg)
                    print("  %s -> fallback visual claro permitido"%msg)
        elif src=="none" and s["clip"].get("asset"): media=s["clip"]["asset"]
        scene_props={"role":s["role"],"source":src,"media":media,"fromMs":s["fromMs"],"toMs":s["toMs"],
                     "motion":s.get("motion","kenburns-in"),"transition_in":s.get("transition_in","fade")}
        for k in ("intent","visual_targets","max_duration_ms","layout","plate_purpose","visual_mode","visual_family","why_this_visual_not_other","editorial_point","why_it_matters","visual_proof","coverage_required","caption_position","avatar_layout","visualBeats","pacingBeats"):
            if k in s:
                scene_props[k]=s[k]
        if s.get("clip",{}).get("treatment"):
            scene_props["treatment"]=s["clip"]["treatment"]
        if s["role"]=="avatar" and s.get("clip",{}).get("avatar_key"):
            scene_props["avatar_key"]=s["clip"]["avatar_key"]
        if s["role"]=="avatar":
            scene_props["avatarCompanionMedia"]=avatar_companion_media
            scene_props["avatarCompanionMotion"]=avatar_companion_motion
            scene_props["avatarCompanionPrompt"]=avatar_companion_prompt_text
            scene_props["avatarCompanionSource"]=avatar_companion_source
            scene_props["avatarCompanionLabel"]=avatar_companion_label_text
        scenes.append(scene_props)
    if os.path.exists(voice):
        ins=["-i",voice]+(["-i",amb] if os.path.exists(amb) else [])
        pre="[0:a][1:a]amix=inputs=2:duration=longest," if os.path.exists(amb) else "[0:a]"
        af=(pre+
            "highpass=f=80,"
            "acompressor=threshold=-20dB:ratio=6:attack=5:release=80:makeup=8,"
            "loudnorm=I=-14:TP=-2:LRA=7,"
            "alimiter=limit=0.89:level=disabled,"
            "aformat=sample_rates=48000:channel_layouts=stereo[a]")
        audio_out=os.path.join(PUB,"audio.m4a")
        rr=run(["ffmpeg","-y"]+ins+["-filter_complex",af,"-map","[a]","-c:a","aac","-b:a","160k",audio_out])
        if rr.returncode!=0 or not os.path.exists(audio_out):
            raise SystemExit("audio master fallo: %s" % (rr.stderr or rr.stdout)[-500:])
        try:
            voice_meta=json.load(open(os.path.join(WORK,"voice.meta.json"),encoding="utf-8"))
        except Exception:
            voice_meta={}
        record_asset("audio", "media/audio.m4a", provider=voice_meta.get("provider_mode") or P.mode, signature=voice_meta.get("signature"))
    plate=os.path.join(PUB,"plate.mp4")
    fps_out=int(plan.get("meta",{}).get("fps",24) or 24)
    if any(sc.get("media")=="media/plate.mp4" for sc in scenes) and not os.path.exists(plate):
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0x16181d:s=1080x1920:d=6","-vf","format=yuv420p","-r",str(fps_out),plate])
    cta_props={k:v for k,v in (plan.get("cta",{}) or {}).items() if k not in ("anchor","visual_style")}
    cta_props["fromMs"]=r["ctaStartMs"]
    hook_props={"headline":plan["hook"]["headline"],"hookEndMs":scenes[0]["toMs"] if scenes else 2000}
    if scenes and scenes[0].get("source")=="google" and scenes[0].get("media")=="media/hook.mp4" and os.path.exists(os.path.join(PUB,"hook_poster.png")):
        hook_props["poster"]="media/hook_poster.png"
    visual_beats=pacing_utils.derive_visual_beats(scenes,r["overlays"],r["totalMs"])
    pacing_beats=pacing_utils.derive_pacing_beats(scenes,r["overlays"],r["totalMs"],include_auto=False)
    sfx_events=derive_animation_sfx(r["overlays"],r["sfx"],r["totalMs"])
    sfx_events=derive_pacing_sfx(sfx_events,visual_beats,r["totalMs"])
    asset_manifest_path=write_asset_manifest()
    qa_gates={"script":load_qa_gate("script"),"tts":load_qa_gate("tts"),"plan":load_qa_gate("plan")}
    require_qa_gates(qa_gates)
    props={"width":1080,"height":1920,"fps":fps_out,"totalMs":r["totalMs"],
     "providerMode":P.mode,
     "policies":{"avatar_policy":plan.get("meta",{}).get("avatar_policy","required"),
                 "media_policy":plan.get("meta",{}).get("media_policy","production"),
                 "media_min_scenes":int(plan.get("meta",{}).get("media_min_scenes",2) or 0),
                 "avatar_clip_reuse":bool(avatar_clip_reuse),
                 "render_policy":style.get("render_policy","declared_only"),
                 "media_fingerprints":True,
                 "asset_manifest":asset_manifest_path,
                 "qa_gates":qa_gates,
                 "no_provider_calls":no_provider_calls()},
     "brand":{"bg":hx(brand["bg"]),"fg":hx(brand["fg"]),"accent":hx(brand["accent"])},
     "style":style,
     "hook":hook_props,
     "captions":caps,"scenes":scenes,"overlays":r["overlays"],"visualBeats":visual_beats,"pacingBeats":pacing_beats,"sfx":sfx_events,
     "cta":cta_props,"audio":"media/audio.m4a"}
    json.dump(props,open(os.path.join(REM,"props.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)
    print("  props.json: %d scenes, %d caps, %d overlays, %d visual beats, %d legacy pacing beats, %d sfx"%(
        len(scenes),len(caps),len(r["overlays"]),len(visual_beats),len(pacing_beats),len(props["sfx"])))



if __name__ == "__main__":
    import sys as _sys
    build(_sys.argv[1], _sys.argv[2])
