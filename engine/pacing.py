"""Shared pacing helpers for short-form reel timelines.

Only scene cuts, meaningful overlay reveals and semantic visual beats count as
visual change. Synthetic sweeps/reframes may still be generated for legacy
compatibility, but they are cosmetic and never satisfy the Reels pacing gate.
"""

from __future__ import annotations

LONG_SCENE_MS = 3200
FAST_GAP_MS = 1400
# Antes 3000ms para escenas cortas (<LONG_SCENE_MS) -- mas laxo que FAST_GAP_MS
# pese a aplicar a escenas MAS cortas, con menos tiempo para llenar. Dejaba
# pasar escenas practicamente enteras vacias (encontrado en render real:
# panel/ChapterDots sin nada mas, ~90% del frame muerto, el gate numerico
# no lo vio porque 3000ms > duracion de la escena).
DEFAULT_GAP_MS = 1400
HOOK_INTERRUPT_MS = 1500
CTA_MIN_MS = 2500
CTA_MAX_MS = 4200
SCENE_HARD_MAX_MS = 8200
DEDUP_MS = 120

SEMANTIC_ACTIONS = {
    "new_media",
    "crop_reframe",
    "component_state",
    "layout_swap",
    "callout_target",
    "insert_card",
}
COSMETIC_KINDS = {
    "accent_wipe",
    "reframe",
    "zoom_punch",
    "focus_pulse",
    "layout_shift",
    "callout_pulse",
}


def _ms(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def is_cta_scene(scene):
    return scene.get("layout") == "cta" or scene.get("plate_purpose") == "cta_resource"


def _event(at_ms, kind, source, scene_index=None, strength="soft", **extra):
    ev = {
        "atMs": _ms(at_ms),
        "kind": kind,
        "source": source,
        "sceneIndex": scene_index,
        "strength": strength,
    }
    ev.update({k: v for k, v in extra.items() if v not in (None, "")})
    return ev


def _dedupe(events, window_ms=DEDUP_MS):
    out = []
    for ev in sorted(events, key=lambda x: (_ms(x.get("atMs")), str(x.get("kind") or x.get("action") or ""))):
        at = _ms(ev.get("atMs"))
        signature = (ev.get("kind") or ev.get("action") or "", ev.get("source") or "")
        if any(
            abs(_ms(prev.get("atMs")) - at) <= window_ms
            and (prev.get("kind") or prev.get("action") or "", prev.get("source") or "") == signature
            for prev in out
        ):
            continue
        out.append(ev)
    return out


def is_semantic_beat(beat):
    if not isinstance(beat, dict):
        return False
    if beat.get("semantic") is True:
        return True
    return beat.get("action") in SEMANTIC_ACTIONS


def explicit_visual_beats(scenes):
    beats = []
    for idx, scene in enumerate(scenes or []):
        raw = scene.get("visualBeats") or scene.get("visual_beats") or []
        if not isinstance(raw, list):
            continue
        for beat in raw:
            if not isinstance(beat, dict):
                continue
            at = beat.get("atMs")
            if at is None:
                continue
            action = beat.get("action") or "callout_target"
            beats.append(_event(
                at,
                action,
                beat.get("source") or "explicit",
                idx,
                beat.get("strength") or "medium",
                action=action,
                semantic=True,
                semantic_delta=beat.get("semantic_delta"),
                target=beat.get("target"),
                label=beat.get("label"),
            ))
    return _dedupe(beats)


def explicit_scene_beats(scenes):
    """Legacy pacing beats.

    These are kept only so old resolved files can still be inspected. They do
    not count as semantic unless explicitly marked with semantic=true.
    """
    beats = []
    for idx, scene in enumerate(scenes or []):
        raw = scene.get("pacingBeats") or scene.get("pacing_beats") or []
        if not isinstance(raw, list):
            continue
        for beat in raw:
            if not isinstance(beat, dict):
                continue
            at = beat.get("atMs")
            if at is None:
                continue
            semantic = is_semantic_beat(beat)
            beats.append(_event(
                at,
                beat.get("kind") or beat.get("action") or "reframe",
                beat.get("source") or "legacy",
                idx,
                beat.get("strength") or "medium",
                action=beat.get("action"),
                semantic=semantic,
                cosmetic=not semantic,
            ))
    return _dedupe(beats)


def overlay_visual_events(overlays):
    events = []
    for overlay in overlays or []:
        comp = overlay.get("component")
        start = _ms(overlay.get("startMs"))
        dur = max(1, _ms(overlay.get("durMs"), 1))
        end = start + dur
        events.append(_event(start, "overlay_reveal", "overlay", semantic=True))
        item_ms = [_ms(x) for x in overlay.get("itemMs") or [] if x is not None]
        params = overlay.get("params") or {}
        items = params.get("items") or params.get("criteria") or params.get("labels") or []
        if not isinstance(items, list):
            items = []

        def fallback_items(step=430):
            count = max(0, min(4, len(items)))
            return [start + 420 + i * step for i in range(count)]

        if comp in ("StepList", "CausalMeter", "ChapterDots"):
            for at in (item_ms or fallback_items()):
                if start < at < end:
                    events.append(_event(at, "item_reveal", "overlay", semantic=True))
        if comp in ("CausalMeter", "StoryArcChart"):
            events.append(_event(min(end - 80, start + min(760, max(360, dur // 2))), "line_draw", "overlay", semantic=True))
        if comp in ("CausalMeter", "StatRing", "CountUp"):
            events.append(_event(min(end - 80, start + int(dur * 0.62)), "meter_fill", "overlay", semantic=True))
    return _dedupe(events)


def natural_events(scenes, overlays, total_ms, include_scene_visual=True):
    events = []
    for idx, scene in enumerate(scenes or []):
        start = _ms(scene.get("fromMs"))
        events.append(_event(start, "scene_cut", "scene", idx, "medium", semantic=True))
    events.extend(overlay_visual_events(overlays))
    if include_scene_visual:
        events.extend(explicit_visual_beats(scenes))
    events.append(_event(_ms(total_ms), "end", "timeline", semantic=True))
    return _dedupe([ev for ev in events if 0 <= _ms(ev.get("atMs")) <= _ms(total_ms)])


def _auto_kind(scene):
    if scene.get("role") == "hook":
        return "hook_interrupt"
    if scene.get("role") == "avatar":
        return "focus_pulse"
    if scene.get("role") == "plate" or (scene.get("source") or "") == "none":
        return "accent_wipe"
    return "reframe"


def derive_visual_beats(scenes, overlays=None, total_ms=0):
    del overlays
    beats = explicit_visual_beats(scenes)
    if total_ms:
        beats = [b for b in beats if 0 <= _ms(b.get("atMs")) <= _ms(total_ms)]
    return _dedupe(beats)


def derive_pacing_beats(scenes, overlays, total_ms, include_auto=True):
    """Return legacy cosmetic beats for rendering/debugging only.

    The returned beats must not be used to satisfy QA pacing. Use
    derive_visual_beats() for semantic events.
    """
    extras = explicit_scene_beats(scenes)
    if not include_auto:
        return _dedupe(extras)

    events = natural_events(scenes, overlays, total_ms, include_scene_visual=True)
    for idx, scene in enumerate(scenes or []):
        if is_cta_scene(scene):
            continue
        start = _ms(scene.get("fromMs"))
        end = _ms(scene.get("toMs"))
        dur = end - start
        if dur <= 0:
            continue
        gap_limit = FAST_GAP_MS if dur > LONG_SCENE_MS or scene.get("role") == "hook" else DEFAULT_GAP_MS
        local = sorted(set(
            _ms(ev.get("atMs"))
            for ev in events
            if start <= _ms(ev.get("atMs")) <= end
        ) | {start, end})
        cursor = start
        for at in local[1:]:
            while at - cursor > gap_limit:
                beat_at = min(at - 260, cursor + min(1400, gap_limit))
                if beat_at <= cursor + 240:
                    break
                beat = _event(
                    beat_at,
                    _auto_kind(scene),
                    "auto",
                    idx,
                    "soft",
                    semantic=False,
                    cosmetic=True,
                )
                extras.append(beat)
                events.append(beat)
                cursor = beat_at
            cursor = max(cursor, at)
    return _dedupe(extras)


def _root_visual_beats(props):
    beats = []
    for beat in props.get("visualBeats") or []:
        if not isinstance(beat, dict) or beat.get("atMs") is None:
            continue
        action = beat.get("action") or "callout_target"
        beats.append(_event(
            beat.get("atMs"),
            action,
            beat.get("source") or "props",
            beat.get("sceneIndex"),
            beat.get("strength") or "medium",
            action=action,
            semantic=True,
            semantic_delta=beat.get("semantic_delta"),
            target=beat.get("target"),
            label=beat.get("label"),
        ))
    return _dedupe(beats)


def _scene_events(scene, all_events):
    start = _ms(scene.get("fromMs"))
    end = _ms(scene.get("toMs"))
    vals = sorted(set(
        _ms(ev.get("atMs"))
        for ev in all_events
        if start <= _ms(ev.get("atMs")) <= end
    ) | {start, end})
    return vals


def pacing_report(props):
    scenes = props.get("scenes") or []
    overlays = props.get("overlays") or []
    total_ms = _ms(props.get("totalMs"))
    root_visual = _root_visual_beats(props)
    scene_visual = explicit_visual_beats(scenes)
    semantic_beats = _dedupe(root_visual + scene_visual)
    legacy = []
    for b in props.get("pacingBeats") or []:
        if not isinstance(b, dict):
            continue
        ev = _event(
            b.get("atMs"),
            b.get("kind") or b.get("action") or "reframe",
            b.get("source") or "props",
            b.get("sceneIndex"),
            b.get("strength") or "soft",
            action=b.get("action"),
            semantic=is_semantic_beat(b),
            cosmetic=not is_semantic_beat(b),
        )
        legacy.append(ev)
    semantic_legacy = [b for b in legacy if b.get("semantic") is True]
    cosmetic = [b for b in legacy if b.get("semantic") is not True]
    all_events = natural_events(scenes, overlays, total_ms, include_scene_visual=False) + semantic_beats + semantic_legacy
    all_events = _dedupe(all_events)
    scene_reports = []
    errors = []
    for idx, scene in enumerate(scenes):
        start = _ms(scene.get("fromMs"))
        end = _ms(scene.get("toMs"))
        dur = end - start
        role = scene.get("role")
        layout = scene.get("layout")
        if dur <= 0:
            continue
        events = _scene_events(scene, all_events)
        gaps = [b - a for a, b in zip(events, events[1:])]
        max_gap = max(gaps) if gaps else dur
        cosmetic_here = [
            b for b in cosmetic
            if start < _ms(b.get("atMs")) < end
        ]
        semantic_here = [
            b for b in semantic_beats + semantic_legacy
            if start < _ms(b.get("atMs")) < end
        ]
        if is_cta_scene(scene):
            limit = CTA_MAX_MS
            if dur < CTA_MIN_MS:
                errors.append("pacing: CTA visible %dms; minimo %dms" % (dur, CTA_MIN_MS))
            if dur > CTA_MAX_MS:
                errors.append("pacing: CTA visible %dms; maximo %dms para no cerrar lento" % (dur, CTA_MAX_MS))
        else:
            # v2: la media EN MOVIMIENTO (clip/foto con motion) cuenta como evento
            # visual continuo: el timer de 1400ms fabricaba beats de relleno sobre
            # clips de accion (que el juez luego marcaba redundantes). El gap corto
            # queda SOLO para plates/texto; una escena media tolera hasta 3200ms
            # entre beats declarados (y >3200ms sigue exigiendo un beat semantico).
            media_backed = (scene.get("source") or (scene.get("clip") or {}).get("source")) in (
                "asset", "pexels", "clip_extractor", "image", "google", "kreado")
            limit = LONG_SCENE_MS if media_backed else (FAST_GAP_MS if dur > LONG_SCENE_MS or role == "hook" else DEFAULT_GAP_MS)
            if dur > SCENE_HARD_MAX_MS:
                errors.append("pacing: scene[%d]/%s dura %dms; divide el beat narrativo" % (idx, role, dur))
            if max_gap > limit:
                msg = "pacing: scene[%d]/%s tiene gap visual semantico de %dms; maximo %dms" % (
                    idx, role, max_gap, limit)
                if cosmetic_here:
                    msg += " (hay %d pacingBeats cosmeticos que no cuentan; usa visual_beats, overlay real o split)" % len(cosmetic_here)
                errors.append(msg)
            if dur > LONG_SCENE_MS and not semantic_here:
                has_overlay_inside = any(
                    start < _ms(ev.get("atMs")) < end and ev.get("source") == "overlay"
                    for ev in all_events
                )
                if not has_overlay_inside:
                    errors.append("pacing: scene[%d]/%s dura %dms sin visual_beats semanticos; divide o agrega cambios reales de contenido" % (
                        idx, role, dur))
            if role == "hook":
                early = [x for x in events if start < x <= start + HOOK_INTERRUPT_MS]
                if not early:
                    errors.append("pacing: hook sin pattern interrupt visual antes de %dms" % HOOK_INTERRUPT_MS)
        scene_reports.append({
            "index": idx,
            "role": role,
            "layout": layout,
            "fromMs": start,
            "toMs": end,
            "durMs": dur,
            "events": events,
            "semanticBeats": len(semantic_here),
            "cosmeticBeatsIgnored": len(cosmetic_here),
            "maxGapMs": max_gap,
            "limitMs": limit,
        })
    semantic_count = len(semantic_beats) + len(semantic_legacy)
    cosmetic_count = len(cosmetic)
    worst_gap = max((s["maxGapMs"] for s in scene_reports), default=0)
    return {
        "ok": not errors,
        "detail": "%d semantic visual beats, %d cosmetic ignored, worst semantic gap %.2fs" % (
            semantic_count, cosmetic_count, worst_gap / 1000.0),
        "errors": errors,
        "scenes": scene_reports,
        "beat_count": semantic_count,
        "cosmetic_count": cosmetic_count,
        "worst_gap_ms": worst_gap,
    }


def compact_report_line(report):
    if report.get("ok"):
        return report.get("detail") or "pacing ok"
    return "; ".join(report.get("errors") or [])[:500]
