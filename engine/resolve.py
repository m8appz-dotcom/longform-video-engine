#!/usr/bin/env python3
"""Resuelve un ReelPlan contra el word_alignment: cada anchor.phrase/at -> ms.
Salida: timeline resuelto (scenes con from/to, overlays con start/dur, sfx con at, cta/total)."""
import json, os, re, sys

from engine import _generated as GEN  # constante del cap del avatar (single source)


def avatar_cap_ms():
    """Tope duro (ms) por aparicion del avatar. 0 = SIN tope (mandato 2026-07-05:
    el avatar va en los mejores momentos, no solo en escenas cortas). Fuente:
    shared/core.json -> AVATAR_MAX_APPEARANCE_MS; override por env AVATAR_MAX_MS."""
    env = os.environ.get("AVATAR_MAX_MS")
    if env not in (None, ""):
        try:
            return int(env)
        except ValueError:
            pass
    return int(getattr(GEN, "AVATAR_MAX_APPEARANCE_MS", 0) or 0)


def avatar_gen_dur_s(scene):
    """Duracion (s) a generar/descargar para una escena de avatar, respetando el
    cap si hay uno. Minimo 0.5s. Sin cap: dura lo que dure la escena."""
    dur_s = (scene["toMs"] - scene["fromMs"]) / 1000.0
    cap = avatar_cap_ms()
    if cap > 0:
        dur_s = min(cap / 1000.0, dur_s)
    return max(0.5, dur_s)


def strip_accents(t):
    return (
        str(t)
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ü", "u")
        .replace("Á", "a").replace("É", "e").replace("Í", "i")
        .replace("Ó", "o").replace("Ú", "u").replace("Ü", "u")
    )

def norm(t):
    # Treat punctuation and hyphens as separators, not deletions. This keeps
    # anchors like a hyphenated code ("X-1") compatible with aligners that
    # return either one token ("X-1,") or two rough tokens ("X", "1").
    return re.sub(r"[^0-9a-zñ]+", " ", strip_accents(t).lower()).split()

def build_index(words):
    toks=[]
    for w in words:
        for t in norm(w["word"]):
            toks.append((t, int(w["start_ms"]), int(w["end_ms"])))
    return toks

def find_phrase(toks, phrase):
    pt=norm(phrase)
    if not pt: return None
    for i in range(len(toks)-len(pt)+1):
        if [toks[i+j][0] for j in range(len(pt))]==pt:
            return (toks[i][1], toks[i+len(pt)-1][2])
    return None

def resolve(plan, al):
    toks=build_index(al["words"]); dur=int(al["duration_ms"])
    missing=[]
    spoken_end=None
    cta_start=dur
    se=find_phrase(toks, plan["hook"]["spoken"])
    if se: spoken_end=se[1]
    def anchor_ms(a):
        if "at" in a:
            return {"start":0,"hook_end":spoken_end or 2000,"cta":cta_start,"end":dur}[a["at"]]
        r=find_phrase(toks, a["phrase"]);
        return r[0] if r else None
    def anchor_label(a):
        return a.get("phrase") or a.get("at") or "<anchor>"
    DEFAULT_DUR={"chart":4200,"stat":1900,"emphasis":1100,"label":2000,"annotation":1600,"quote":2200,"compare":2600,"chapter":1500,"list":4000}

    cta=plan.get("cta",{}) or {}
    cta_anchor=cta.get("anchor") if isinstance(cta.get("anchor"),dict) else None
    if cta_anchor:
        m=anchor_ms(cta_anchor)
        if m is None:
            missing.append("cta: %s"%anchor_label(cta_anchor))
        else:
            cta_start=m
    else:
        for phrase in (cta.get("button"), cta.get("text")):
            if not phrase:
                continue
            r=find_phrase(toks, phrase)
            if r:
                cta_start=r[0]
                break

    # escenas
    scenes=[]
    for sc in plan["scenes"]:
        ms=0 if sc["role"]=="hook" else anchor_ms(sc["anchor"])
        if ms is None:
            missing.append("scene/%s: %s"%(sc.get("role"), anchor_label(sc["anchor"])))
            continue
        resolved_beats=[]
        for i,b in enumerate(sc.get("visual_beats") or []):
            beat_anchor=b.get("anchor") or {}
            beat_ms=anchor_ms(beat_anchor)
            if beat_ms is None:
                missing.append("visual_beat/%s[%d]: %s"%(sc.get("role"), i, anchor_label(beat_anchor)))
                continue
            resolved_beats.append({
                "atMs":beat_ms,
                "action":b.get("action","callout_target"),
                "semantic_delta":b.get("semantic_delta",""),
                "target":b.get("target",""),
                "label":b.get("label",""),
                "strength":b.get("strength","soft"),
                "source":"explicit",
                "semantic":True,
            })
        legacy_beats=[]
        for i,b in enumerate(sc.get("pacing_beats") or []):
            beat_anchor=b.get("anchor") or {}
            beat_ms=anchor_ms(beat_anchor)
            if beat_ms is None:
                missing.append("legacy_pacing_beat/%s[%d]: %s"%(sc.get("role"), i, anchor_label(beat_anchor)))
                continue
            legacy_beats.append({
                "atMs":beat_ms,
                "kind":b.get("kind","reframe"),
                "strength":b.get("strength","soft"),
                "source":"legacy",
                "semantic":False,
                "cosmetic":True,
            })
        item={**sc,"fromMs":ms}
        if resolved_beats:
            item["visualBeats"]=resolved_beats
        if legacy_beats:
            item["pacingBeats"]=legacy_beats
        scenes.append(item)
    scenes.sort(key=lambda s:s["fromMs"])
    for i,s in enumerate(scenes):
        s["toMs"]=scenes[i+1]["fromMs"] if i+1<len(scenes) else cta_start
        max_scene=int(s.get("max_duration_ms") or 0)
        if max_scene and s["toMs"]-s["fromMs"]>max_scene:
            raise ValueError("scene/%s excede max_duration_ms: %dms > %dms"%(
                s.get("role"), s["toMs"]-s["fromMs"], max_scene))
    avatar_scenes=[s for s in scenes if s.get("role")=="avatar"]
    avatar_errors=[]
    if len(avatar_scenes)>2:
        avatar_errors.append("maximo 2 apariciones, recibidas %d"%len(avatar_scenes))
    cap_ms=avatar_cap_ms()  # 0 = sin tope duro (el avatar va en los mejores momentos)
    if cap_ms>0:
        for i,s in enumerate(avatar_scenes,1):
            dur_ms=s["toMs"]-s["fromMs"]
            if dur_ms>cap_ms:
                avatar_errors.append("aparicion %d dura %dms; maximo %dms"%(i,dur_ms,cap_ms))
    if avatar_errors:
        raise ValueError("avatar fuera de formato: " + "; ".join(avatar_errors))

    # overlays
    ov=[]
    for o in plan.get("overlays",[]):
        start=anchor_ms(o["anchor"])
        if start is None:
            missing.append("overlay/%s: %s"%(o.get("component"), anchor_label(o["anchor"])))
            continue
        ia=o.get("params",{}).get("item_anchors")
        if ia:
            ms=[]
            for p in ia:
                m=anchor_ms({"phrase":p})
                if m is None:
                    missing.append("item_anchor/%s: %s"%(o.get("component"), p))
                else:
                    ms.append(m)
            if ms:
                start=min([start]+ms)
                dur_ms=max((max(ms)-start)+1100, int(o.get("duration_ms") or 0))
            else:
                dur_ms=o.get("duration_ms") or DEFAULT_DUR["list"]
            item_ms=ms
        else:
            dur_ms=o.get("duration_ms") or DEFAULT_DUR.get(o["type"],1500); item_ms=None
        max_overlay=int(o.get("max_duration_ms") or 0)
        if max_overlay and dur_ms>max_overlay:
            raise ValueError("overlay/%s excede max_duration_ms: %dms > %dms"%(
                o.get("component"), dur_ms, max_overlay))
        # Un overlay informativo pertenece a la escena donde arranca. Si se deja
        # cruzar al siguiente scene, Remotion termina dibujando dos pantallas
        # explicativas una encima de otra.
        scene_end=None
        for sc in scenes:
            if int(sc["fromMs"]) <= int(start) < int(sc["toMs"]):
                scene_end=int(sc["toMs"])
                break
        if scene_end is not None and start + dur_ms > scene_end:
            dur_ms=max(1, scene_end-start)
        if item_ms:
            outside=[m for m in item_ms if int(m) < int(start) or int(m) >= int(start)+int(dur_ms)]
            if outside:
                raise ValueError("overlay/%s item_anchors fuera de su duracion tras recorte de escena: %s (overlay %d-%dms)"%(
                    o.get("component"), ",".join(str(x) for x in outside), start, start+dur_ms))
        ov_item={"type":o["type"],"component":o["component"],"toolbox":o.get("toolbox",[]),
                 "params":o.get("params",{}),"startMs":start,"durMs":dur_ms,"itemMs":item_ms}
        for k in ("rationale","safe_zone","max_duration_ms","blocks_captions","semantic_kind","placement","must_not_cover"):
            if k in o:
                ov_item[k]=o[k]
        ov.append(ov_item)

    # sfx
    sx=[]
    for x in plan.get("sfx",[]):
        at=anchor_ms(x["anchor"])
        if at is None:
            missing.append("sfx/%s: %s"%(x.get("id"), anchor_label(x["anchor"])))
            continue
        sx.append({"id":x["id"],"atMs":at,"gain":x.get("gain",0.5)})

    if missing:
        raise ValueError("anchors sin resolver tras alignment: " + "; ".join(missing))

    last_word_end=max((int(w.get("end_ms",0)) for w in al.get("words",[])), default=dur)
    outro_pad=max(0,int(os.environ.get("OUTRO_PAD_MS","80") or 0))
    base_total=min(dur,last_word_end+outro_pad)
    tail=max(0,int(os.environ.get("CTA_TAIL_MS","0") or 0))
    cta_min=max(0,int(os.environ.get("CTA_MIN_VISIBLE_MS","2500") or 0))
    total_ms=max(base_total+tail, cta_start+cta_min)
    for s in scenes:
        if s.get("layout")=="cta" or s.get("plate_purpose")=="cta_resource":
            if int(s.get("toMs",0)) <= int(s.get("fromMs",0)):
                s["toMs"]=total_ms
    return {"durationMs":dur,"ctaStartMs":cta_start,"totalMs":total_ms,
            "scenes":scenes,"overlays":ov,"sfx":sx}

if __name__=="__main__":
    plan=json.load(open(sys.argv[1] if len(sys.argv)>1 else "plan.json"))
    al=json.load(open(sys.argv[2] if len(sys.argv)>2 else "alignment.json"))
    r=resolve(plan,al); json.dump(r,open("resolved.json","w"),ensure_ascii=False,indent=1)
    print("dur %dms  cta@%dms  total %dms"%(r["durationMs"],r["ctaStartMs"],r["totalMs"]))
    print("ESCENAS:")
    for s in r["scenes"]: print("  %-6s %5d-%5d  %s"%(s["role"],s["fromMs"],s["toMs"],s["clip"].get("query") or s["clip"]["source"]))
    print("OVERLAYS:")
    for o in r["overlays"]: print("  %-10s @%5d +%4dms  %s"%(o["component"],o["startMs"],o["durMs"],o["params"].get("label") or o["params"].get("text") or o["params"].get("items") or o["params"].get("words") or ""))
    print("SFX:")
    for x in r["sfx"]: print("  %-9s @%5d"%(x["id"],x["atMs"]))
