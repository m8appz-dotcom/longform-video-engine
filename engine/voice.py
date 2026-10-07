#!/usr/bin/env python3
"""Etapa de voz+props del pipeline v2: valida plan, TTS, alignment, hook visual y props_build.

Port de run_plan.py v1 con llamadas in-process (sin subprocess a scripts) y config central."""
import hashlib, os, sys, json, re, shutil, subprocess
from engine.config import ROOT, WORK_DIR as WORK, ensure_dirs
ensure_dirs()
from engine import media_tools
from providers.core import get_providers
from engine.aligner import get_aligner
def allow_asset_fallbacks():
    return os.environ.get("ALLOW_ASSET_FALLBACKS","").lower() in ("1","true","yes")
def enable_ambient_bed():
    return os.environ.get("ENABLE_AMBIENT_BED","").lower() in ("1","true","yes")
def enable_voice_tighten(mode):
    raw=os.environ.get("ENABLE_VOICE_TIGHTEN")
    if raw is not None:
        return raw.lower() in ("1","true","yes")
    return False
def reuse_google_video_clips():
    return os.environ.get("REUSE_OMNI_VIDEO_CLIPS","").lower() in ("1","true","yes","on")
def env_truthy(name):
    return os.environ.get(name,"").lower() in ("1","true","yes","on")
def media_meta_path(path):
    return path + ".meta.json"
def media_signature(kind, **fields):
    raw=json.dumps({"kind":kind, **fields}, ensure_ascii=False, sort_keys=True, separators=(",",":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
def write_media_meta(path, signature, **fields):
    if not signature:
        return
    meta={"signature":signature, "fingerprint_version":2, **fields}
    with open(media_meta_path(path),"w",encoding="utf-8") as f:
        json.dump(meta,f,ensure_ascii=False,indent=1)
def load_media_meta(path):
    try:
        return json.load(open(media_meta_path(path),encoding="utf-8"))
    except Exception:
        return {}
def write_tts_meta(signature, **fields):
    meta={"signature":signature, "fingerprint_version":2, **fields}
    with open(os.path.join(WORK,"voice.meta.json"),"w",encoding="utf-8") as f:
        json.dump(meta,f,ensure_ascii=False,indent=1)
def load_tts_meta():
    try:
        return json.load(open(os.path.join(WORK,"voice.meta.json"),encoding="utf-8"))
    except Exception:
        return {}
def clean_generated_work(preserve_tts=False):
    preserve=set()
    if preserve_tts:
        preserve.update(("voice.wav","voice.align.json","word_alignment.json","voice.meta.json","voice.wav.meta.json"))
    for name in os.listdir(WORK):
        if name in preserve:
            continue
        if name in ("voice.wav", "voice.align.json", "word_alignment.json", "voice.meta.json", "voice.wav.meta.json", "ambient.wav", "hero.mp4", "voice.tight.wav", "voice.tempo.wav", "voice_tighten_concat.txt") or name.startswith("avatar_"):
            path=os.path.join(WORK,name)
            if os.path.isfile(path):
                try: os.remove(path)
                except OSError: pass
    parts=os.path.join(WORK,"voice_tighten_parts")
    if os.path.isdir(parts):
        shutil.rmtree(parts, ignore_errors=True)
def run(args):
    return media_tools.run(args,capture_output=True,text=True)
def validate_script_quality(plan_path):
    from engine import script_audit
    rc = script_audit.run_for(plan_path)
    if rc:
        raise SystemExit("script audit fallo (calidad deterministica del guion)")


def validate_ai_script(plan_path):
    from engine import qa
    report = qa.run_stage("script", plan_path)
    if not report.get("ok"):
        raise SystemExit("AI QA script fallo: score=%s" % report.get("score"))


def validate_ai_plan(plan_path):
    from engine import qa
    report = qa.run_stage("plan", plan_path)
    if not report.get("ok"):
        raise SystemExit("AI QA plan fallo: score=%s" % report.get("score"))


def validate_ai_tts(voice_path, alignment_path, plan_path):
    from engine import qa
    report = qa.run_stage("tts", voice_path, alignment_path, plan_path)
    if not report.get("ok"):
        raise SystemExit("AI QA tts fallo: score=%s" % report.get("score"))


def tts_signature(script, words, dur, provider_mode, aligner):
    fields={
        "script":script,
        "words":words,
        "dur_ms":round(float(dur)*1000),
        "provider_mode":provider_mode,
        "aligner":os.environ.get("ALIGNER","elevenlabs").lower() if provider_mode=="real" else "mock",
        "voice_id":os.environ.get("ELEVENLABS_VOICE_ID","") if provider_mode=="real" else "mock",
        "tts_model":os.environ.get("ELEVENLABS_MODEL","eleven_multilingual_v2") if provider_mode=="real" else "mock",
        "eleven_speed":os.environ.get("ELEVENLABS_SPEED","0.98") if provider_mode=="real" else "",
        "eleven_stability":os.environ.get("ELEVENLABS_STABILITY","0.68"),
        "eleven_similarity":os.environ.get("ELEVENLABS_SIMILARITY","0.84"),
        "eleven_style":os.environ.get("ELEVENLABS_STYLE","0.12"),
        "eleven_speaker_boost":os.environ.get("ELEVENLABS_USE_SPEAKER_BOOST","1"),
        "voice_atempo":os.environ.get("VOICE_ATEMPO","1.0"),
        "enable_voice_tighten":str(enable_voice_tighten(provider_mode)),
        "voice_tighten_min_ms":os.environ.get("VOICE_TIGHTEN_MIN_MS","240"),
        "voice_tighten_keep_ms":os.environ.get("VOICE_TIGHTEN_KEEP_MS","160"),
        "voice_tighten_threshold_db":os.environ.get("VOICE_TIGHTEN_THRESHOLD_DB","-35"),
        "aligner_mode":getattr(aligner,"mode","unknown"),
    }
    return media_signature("tts", **fields)
def tts_cache_valid(signature, provider_mode):
    voice_path=os.path.join(WORK,"voice.wav")
    word_path=os.path.join(WORK,"word_alignment.json")
    if not os.path.exists(voice_path) or not os.path.exists(word_path):
        return False
    if provider_mode=="real" and os.environ.get("ALIGNER","elevenlabs").lower()!="whisperx":
        if not os.path.exists(os.path.join(WORK,"voice.align.json")):
            return False
    meta=load_tts_meta()
    return meta.get("signature")==signature
def hook_signature(hook_visual):
    dur=float(os.environ.get("GOOGLE_HOOK_SECONDS","2.5") or 2.5)
    return media_signature(
        "hook",
        provider=hook_visual.get("provider"),
        prompt=hook_visual.get("prompt",""),
        model=os.environ.get("OMNI_VIDEO_MODEL","gemini-omni-flash-preview"),
        aspect_ratio=os.environ.get("OMNI_VIDEO_ASPECT_RATIO","9:16"),
        delivery=os.environ.get("OMNI_VIDEO_DELIVERY","uri"),
        dur_ms=round(dur*1000),
    )
def hook_cache_ok(path, signature):
    if not os.path.exists(path) or os.path.getsize(path) < int(os.environ.get("MIN_VIDEO_BYTES","120000") or 120000):
        return False
    meta=load_media_meta(path)
    if not meta:
        # One-time migration for legacy cached hooks that predate fingerprints.
        write_media_meta(path, signature, kind="hook", legacy_adopted=True)
        return True
    return meta.get("signature")==signature
def probe_duration(path):
    rr=run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",path])
    try:
        return float((rr.stdout or "").strip())
    except ValueError:
        return 0.0
def detect_silences(path, min_s, threshold_db):
    noise="%sdB"%str(threshold_db).replace("dB","")
    rr=run(["ffmpeg","-hide_banner","-nostats","-i",path,"-af","silencedetect=noise=%s:d=%.3f"%(noise,min_s),"-f","null","-"])
    text=(rr.stderr or "")+"\n"+(rr.stdout or "")
    out=[]; start=None
    for line in text.splitlines():
        m=re.search(r"silence_start:\s*([0-9.]+)",line)
        if m:
            start=float(m.group(1)); continue
        m=re.search(r"silence_end:\s*([0-9.]+)",line)
        if m and start is not None:
            end=float(m.group(1))
            if end>start:
                out.append((start,end))
            start=None
    dur=probe_duration(path)
    if start is not None and dur>start:
        out.append((start,dur))
    return out
def shifted_time(t, cuts):
    removed=0.0
    for a,b in cuts:
        if t<=a:
            break
        removed += max(0.0, min(t,b)-a)
    return max(0.0, t-removed)
def rewrite_alignment_sidecar(sidecar, cuts, tempo):
    if not os.path.exists(sidecar):
        return
    data=json.load(open(sidecar,encoding="utf-8"))
    for key in ("character_start_times_seconds","character_end_times_seconds"):
        vals=data.get(key)
        if isinstance(vals,list):
            data[key]=[shifted_time(float(v),cuts)/tempo for v in vals]
    open(sidecar,"w",encoding="utf-8").write(json.dumps(data,ensure_ascii=False))
def tighten_voice(path, mode):
    if not enable_voice_tighten(mode) or not os.path.exists(path):
        return
    min_s=float(os.environ.get("VOICE_TIGHTEN_MIN_MS","240"))/1000.0
    keep_s=float(os.environ.get("VOICE_TIGHTEN_KEEP_MS","160"))/1000.0
    threshold=os.environ.get("VOICE_TIGHTEN_THRESHOLD_DB","-35")
    tempo=float(os.environ.get("VOICE_ATEMPO","1.0"))
    dur=probe_duration(path)
    silences=detect_silences(path,min_s,threshold)
    cuts=[]; intervals=[]; cursor=0.0
    for a,b in silences:
        a=max(0.0,min(dur,a)); b=max(0.0,min(dur,b))
        cut_start=a+keep_s
        if b-cut_start < 0.025:
            continue
        if cut_start>cursor:
            intervals.append((cursor,cut_start))
        cuts.append((cut_start,b))
        cursor=b
    if cursor<dur:
        intervals.append((cursor,dur))
    current=path
    if cuts and intervals:
        parts=os.path.join(WORK,"voice_tighten_parts"); os.makedirs(parts,exist_ok=True)
        list_path=os.path.join(WORK,"voice_tighten_concat.txt")
        with open(list_path,"w",encoding="utf-8") as f:
            for i,(a,b) in enumerate(intervals):
                seg=os.path.join(parts,"seg_%03d.wav"%i)
                rr=run(["ffmpeg","-y","-ss","%.3f"%a,"-t","%.3f"%(b-a),"-i",path,"-ar","48000","-c:a","pcm_s16le",seg])
                if rr.returncode!=0:
                    print("  voice tighten: no pude cortar segmento; continuo sin recorte")
                    return
                f.write("file '%s'\n"%seg.replace("'","'\\''"))
        merged=os.path.join(WORK,"voice.tight.wav")
        rr=run(["ffmpeg","-y","-f","concat","-safe","0","-i",list_path,"-ar","48000","-c:a","pcm_s16le",merged])
        if rr.returncode!=0 or not os.path.exists(merged):
            print("  voice tighten: concat fallo; continuo sin recorte")
            return
        current=merged
    if tempo and abs(tempo-1.0)>0.001:
        tempo_out=os.path.join(WORK,"voice.tempo.wav")
        rr=run(["ffmpeg","-y","-i",current,"-filter:a","atempo=%.4f"%tempo,"-ar","48000",tempo_out])
        if rr.returncode==0 and os.path.exists(tempo_out):
            current=tempo_out
        else:
            tempo=1.0
            print("  voice tighten: atempo fallo; continuo sin tempo")
    if current!=path:
        shutil.copyfile(current,path)
        rewrite_alignment_sidecar(os.path.splitext(path)[0]+".align.json",cuts,tempo or 1.0)
        removed=sum(b-a for a,b in cuts)
        print("  voice tighten: recorte %.0f ms, tempo %.2fx"%(removed*1000,tempo or 1.0))
def main(plan_path):
    from engine import validate_plan as _vp
    if _vp.main(plan_path):
        raise SystemExit("ReelPlan invalido")
    validate_script_quality(plan_path)
    validate_ai_script(plan_path)
    plan=json.load(open(plan_path,encoding="utf-8")); script=plan["script"]
    words=[w for w in re.split(r"\s+",script.strip()) if w]
    P=get_providers(1080,1920); AL=get_aligner()
    default_word_seconds = 0.30 if P.mode == "mock" else 0.42
    word_seconds = float(os.environ.get("REEL_WORD_SECONDS", default_word_seconds))
    dur=len(words)*word_seconds+0.6
    voice_path=os.path.join(WORK,"voice.wav")
    word_alignment_path=os.path.join(WORK,"word_alignment.json")
    tts_sig=tts_signature(script, words, dur, P.mode, AL)
    reuse_tts=env_truthy("REUSE_TTS") and not env_truthy("REGEN_TTS")
    tts_cached=reuse_tts and tts_cache_valid(tts_sig, P.mode)
    clean_generated_work(preserve_tts=tts_cached)
    if tts_cached:
        wa=json.load(open(word_alignment_path,encoding="utf-8"))
        print("  voz: cache TTS reutilizado (%d palabras, %s)"%(len(words), P.mode))
    else:
        if env_truthy("NO_PROVIDER_CALLS"):
            raise SystemExit("NO_PROVIDER_CALLS=1 y cache TTS invalido o ausente; no llamo TTS")
        P.tts_voiceover(script,dur,voice_path); print("  voz: %d palabras (%s)"%(len(words), P.mode))
        tighten_voice(voice_path, P.mode)
        wa=AL.align(voice_path,words)
        json.dump(wa,open(word_alignment_path,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
        write_tts_meta(
            tts_sig,
            kind="tts",
            words=len(words),
            provider_mode=P.mode,
            aligner=os.environ.get("ALIGNER","elevenlabs") if P.mode=="real" else "mock",
            dur_ms=round(dur*1000),
        )
    validate_ai_tts(voice_path, word_alignment_path, plan_path)
    validate_ai_plan(plan_path)
    amb_path=os.path.join(WORK,"ambient.wav")
    if enable_ambient_bed():
        try: P.ambient_bed(dur,amb_path)
        except Exception: pass
    elif os.path.exists(amb_path):
        os.remove(amb_path)
    print("  alignment: %d palabras, %d ms"%(len(wa["words"]),wa["duration_ms"]))
    first_scene=(plan.get("scenes") or [{}])[0]
    first_clip=(first_scene.get("clip") or {}) if isinstance(first_scene, dict) else {}
    hv=plan["hook"].get("visual",{})
    hook_uses_google=first_scene.get("role")=="hook" and first_clip.get("source")=="google"
    if hook_uses_google:
        hv={**hv, "provider":"google", "prompt": first_clip.get("prompt") or hv.get("prompt","")}
        try:
            cached_hook=os.path.join(ROOT,"remotion","public","media","hook.mp4")
            hook_sig=hook_signature(hv)
            hook_dur=float(os.environ.get("GOOGLE_HOOK_SECONDS","2.5") or 2.5)
            if reuse_google_video_clips() and not env_truthy("REGEN_HOOK"):
                if not hook_cache_ok(cached_hook, hook_sig):
                    raise RuntimeError("REUSE_OMNI_VIDEO_CLIPS=1 pero no hay media/hook.mp4 con fingerprint valido para reutilizar")
                shutil.copyfile(cached_hook, os.path.join(WORK,"hero.mp4"))
                meta_src=media_meta_path(cached_hook)
                if os.path.exists(meta_src):
                    shutil.copyfile(meta_src, media_meta_path(os.path.join(WORK,"hero.mp4")))
                print("  hook: google reutilizado desde media/hook.mp4")
            else:
                if env_truthy("NO_PROVIDER_CALLS"):
                    raise RuntimeError("NO_PROVIDER_CALLS=1 y hook cache no fue reutilizado; no llamo Google")
                P.video_clip("google", hv.get("prompt",""), hook_dur, os.path.join(WORK,"hero.mp4"))
                write_media_meta(
                    os.path.join(WORK,"hero.mp4"),
                    hook_sig,
                    kind="hook",
                    provider="google",
                    prompt=hv.get("prompt",""),
                    model=os.environ.get("OMNI_VIDEO_MODEL","gemini-omni-flash-preview"),
                    aspect_ratio=os.environ.get("OMNI_VIDEO_ASPECT_RATIO","9:16"),
                    delivery=os.environ.get("OMNI_VIDEO_DELIVERY","uri"),
                    dur_ms=round(hook_dur*1000),
                )
                print("  hook: %s ok" % hv.get("provider"))
        except Exception as e:
            msg="hook %s fallo: %s"%(hv.get("provider"),str(e)[:100])
            if P.mode=="real" and not allow_asset_fallbacks():
                raise RuntimeError(msg)
            print("  %s -> fallback permitido"%msg)
    from engine import props_build as _pb
    _pb.build(plan_path, os.path.join(WORK, "word_alignment.json"))
    print("OK: work/ + remotion/props.json listos")
if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv)>1 else os.path.join(ROOT,"contracts","reel_plan.example.json"))
