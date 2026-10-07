import React from "react";
import {AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {THEME, hexA, hx, isLightHex, resolveSrc, resolveStyleVars, ensureReelFonts, C} from "./theme";
import {COMPONENTS, COMPONENT_ALIASES, SFX_MAX_GAIN, AVATAR_CAPTION_BAND_H, AVATAR_H} from "./generated";
import {ReelProps, Scene, Overlay, Sfx} from "./types";
import {
  StoryArcChart, StatRing, StepList, CausalMeter, KeywordPop, LowerThird,
  ChapterDots, ObjectCallout, Annotation, FocusPunch, SplitCompare, BigWordSequence,
} from "./components/overlays";
import {Background, Fade, PlateSurface, shouldRenderPlateSurface, HookText, HookSpectacle, HookPoster} from "./layers/surfaces";
import {CaptionLayer, sceneCaptionPos, laneFor} from "./layers/captions";
import {AvatarLayer} from "./layers/avatar";
import {SceneBeatLayer, PacingBeatLayer, scopedRootBeats} from "./layers/beats";
import {Cta} from "./layers/cta";

// Registro unico: un componente es valido si esta en shared/core.json (via generated.ts).
const componentId = (c: string) => COMPONENT_ALIASES[c] || c;
const isKnownComponent = (c: string) => (COMPONENTS as readonly string[]).includes(componentId(c)) || (COMPONENTS as readonly string[]).includes(c);

const renderPolicyFor = (props: ReelProps) =>
  String(props.policies?.render_policy || props.style?.render_policy || "declared_only");

const hasList = (value: any, min = 1) => Array.isArray(value) && value.length >= min;
const hasText = (value: any) => value !== undefined && value !== null && String(value).trim().length > 0;
const hasDeclaredOverlayContent = (component: string, params: any) => {
  const p = params || {};
  if (component === "StoryArcChart") return hasList(p.points, 2);
  if (component === "StatRing" || component === "CountUp") return hasText(p.value);
  if (component === "StepList") return hasList(p.items);
  if (component === "CausalMeter") return hasList(p.items);
  if (component === "ObjectCallout" || component === "Annotation") return hasText(p.label);
  if (component === "KeywordPop") return hasList(p.words);
  if (component === "LowerThird") return hasText(p.text);
  if (component === "ChapterDots") return hasList(p.labels);
  if (component === "FocusPunch") return hasText(p.target_x) && hasText(p.target_y);
  if (component === "SplitCompare") return hasText(p.left_label) && hasText(p.right_label);
  if (component === "BigWordSequence") return hasList(p.words, 2);
  return true;
};

// Escena liderada por un grafico de texto (plate sin media): su overlay ES el
// mensaje y el caption cede a subtitulo. Ahi la reserva vertical grande del
// caption (~570px) empujaba el contenido a ~35% de altura, dejando la mitad
// inferior muerta entre el grafico y el caption (top-heavy, hallado en render).
// Bajamos la reserva de CENTRADO (no la del caption) para que el contenido caiga
// al centro optico (~45%) y forme un bloque cohesivo con el caption; el aire de
// arriba pasa a ser respiro intencional. 180 despeja incluso el diagrama vertical.
const isGraphicLedScene = (sc?: Scene): boolean => !!sc && sc.role === "plate"
  && ((sc.source === "none") || !sc.media) && sc.plate_purpose !== "cta_resource";
const PLATE_CENTER_PB = 180;

// Mandato del dueño: mitad inferior SIEMPRE es el avatar 16:9, sin excepcion.
// Los overlays declarados que antes anclaban a estas escenas (StatRing,
// SplitCompare, LowerThird, KeywordPop...) no saben de esta banda -- sin este
// reserve, un StatRing/LowerThird "safe_lower" cae directo sobre la cara.
const isAvatarScene = (sc?: Scene): boolean => !!sc && sc.role === "avatar";
const AVATAR_RESERVE_PB = AVATAR_CAPTION_BAND_H + AVATAR_H; // 960: todo lo que no sea companion

const OverlayLayer: React.FC<{overlays: Overlay[]; brand: any; fps: number; declaredOnly?: boolean; style?: ReelProps["style"]; scenes?: Scene[]}> =
({overlays, brand, fps, declaredOnly = true, style, scenes}) => {
  const fr = (ms: number) => Math.round(ms / 1000 * fps);
  return (<>{overlays.map((o, i) => {
    const lane = laneFor(sceneCaptionPos(scenes, o.startMs + 1, style));
    const ovScene = scenes?.find((s) => o.startMs >= s.fromMs && o.startMs < s.toMs);
    const avatarScene = isAvatarScene(ovScene);
    const plateCenterPb = avatarScene ? AVATAR_RESERVE_PB : (isGraphicLedScene(ovScene) ? Math.min(lane.pb, PLATE_CENTER_PB) : lane.pb);
    const onMedia = !!(ovScene && ovScene.media && ovScene.source !== "none");
    // Hold anti-frame-muerto: en plates, si tras este overlay queda un hueco corto
    // (<=700ms) hasta el siguiente overlay o el fin de escena, la Sequence se
    // extiende para abutar (el fade-out se corre, el plate nunca queda vacio).
    // Solo visual: el contrato de props no se muta. Acoplado a max_gap_ms=300 en
    // engine/visual_qa.py (plate_coverage_errors).
    let effDurMs = o.durMs;
    if (ovScene && isGraphicLedScene(ovScene)) {
      const end = o.startMs + o.durMs;
      let target = ovScene.toMs;
      for (const o2 of overlays) {
        if (o2 !== o && o2.startMs >= end && o2.startMs < target) target = o2.startMs;
      }
      const gap = target - end;
      if (gap > 0 && gap <= 700) effDurMs = target - o.startMs;
    }
    const from = fr(o.startMs); const dur = Math.max(1, fr(effDurMs));
    const p = o.params || {}; const common = {color: brand.fg, accent: brand.accent, bg: brand.bg};
    const component = String(o.component || "");
    if (!isKnownComponent(component)) return null;
    if (declaredOnly && !hasDeclaredOverlayContent(component, p)) return null;
    let el: React.ReactNode = null;
    if (o.component === "StoryArcChart") el = <StoryArcChart {...common} {...p} laneTop={lane.pt} showSeventyLine={p.showSeventyLine ?? p.show_seventy_line ?? false}/>;
    else if (o.component === "StatRing" || o.component === "CountUp") el = <StatRing {...common} laneBottom={plateCenterPb} laneTop={lane.pt} value={p.value} suffix={p.suffix} label={p.label} from={p.from} fitMode={p.fit_mode}/>;
    else if (o.component === "StepList") { const offs = (o.itemMs || []).map((m) => m - o.startMs); el = <StepList {...common} laneBottom={plateCenterPb} laneTop={lane.pt} items={p.items} offsets={offs} variant={p.variant} placement={o.placement} futureReveal={p.future_reveal} durMs={o.durMs}/>; }
    else if (o.component === "CausalMeter") { const offs = (o.itemMs || []).map((m) => m - o.startMs); el = <CausalMeter {...common} {...p} offsets={offs}/>; }
    else if (o.component === "ObjectCallout") el = <ObjectCallout {...common} {...p}/>;
    else if (o.component === "KeywordPop") el = <KeywordPop {...common} placement={avatarScene ? "safe_top" : o.placement} mustNotCover={o.must_not_cover || []} words={p.words || []} onMedia={onMedia}/>;
    else if (o.component === "LowerThird") el = <LowerThird {...common} placement={avatarScene ? "safe_top" : o.placement} mustNotCover={o.must_not_cover || []} text={p.text} sub={p.sub} subSource={p.sub_source} onMedia={onMedia}/>;
    else if (o.component === "ChapterDots") el = <ChapterDots {...common} laneBottom={plateCenterPb} laneTop={lane.pt} title={p.title} labels={p.labels} activeIndex={p.activeIndex} highlightUntil={p.highlightUntil}/>;
    else if (o.component === "FocusPunch") el = <FocusPunch {...common} {...p}/>;
    else if (o.component === "SplitCompare") el = <SplitCompare {...common} {...p} laneBottom={plateCenterPb} laneTop={lane.pt} durMs={o.durMs} onMedia={onMedia}/>;
    else if (o.component === "BigWordSequence") { const offs = (o.itemMs || []).map((m) => m - o.startMs); el = <BigWordSequence {...common} words={p.words} offsets={offs} laneBottom={plateCenterPb} laneTop={lane.pt}/>; }
    else if (o.component === "Annotation") el = <Annotation {...common} label={p.label}/>;
    if (!el) return null;
    return <Sequence key={i} from={from} durationInFrames={dur} name={o.component}>{el}</Sequence>;
  })}</>);
};

const ProgressBar: React.FC<{accent: string; mode?: NonNullable<ReelProps["style"]>["progress_bar"]}> = ({accent, mode = "none"}) => {
  if (mode === "none") return null;
  const f = useCurrentFrame(); const {durationInFrames} = useVideoConfig();
  const w = interpolate(f, [0, durationInFrames], [0, 100], C);
  const c = mode === "warning" ? THEME.yellow : accent;
  return <AbsoluteFill style={{justifyContent: "flex-end"}}><div style={{height: 8, width: `${w}%`, backgroundColor: c, boxShadow: `0 0 16px ${c}`}}/></AbsoluteFill>;
};

// Duracion visual de cada SFX en frames (solo render); los caps de gain vienen
// de shared/core.json via generated.ts.
const SFX_DUR: Record<string, number> = {
  click: 24, pop: 30, impact: 38, whoosh: 42, "swoosh-up": 42, "sub-drop": 54, riser: 62,
  "ui-soft-click": 18, "ui-card-pop": 28, "ui-check-tick": 22, "ui-line-draw": 34,
  "ui-meter-fill": 42, "ui-filter-pass": 38, "ui-filter-reject": 30, "ui-callout-ping": 24,
  "ui-page-swipe": 34, "ui-impact-soft": 34,
};

const SfxAudio: React.FC<{s: Sfx; durationInFrames: number}> = ({s, durationInFrames}) => {
  const cap = SFX_MAX_GAIN[s.id] ?? 0.18;
  const gain = Math.min(Math.max(s.gain ?? cap, 0), cap);
  return (
    <Audio
      src={staticFile("sfx/" + s.id + ".wav")}
      volume={(frame) => {
        const fadeIn = interpolate(frame, [0, 2], [0, 1], C);
        const fadeOut = interpolate(frame, [Math.max(3, durationInFrames - 4), durationInFrames], [1, 0], C);
        return gain * Math.min(fadeIn, fadeOut);
      }}
    />
  );
};

const SfxLayer: React.FC<{sfx: Sfx[]; fps: number}> = ({sfx, fps}) => (
  <>{sfx.filter((s) => s.id && s.id !== "none").map((s, i) => {
    const dur = SFX_DUR[s.id] ?? 36;
    return (
      <Sequence key={`${s.id}-${i}`} from={Math.max(0, Math.round(s.atMs / 1000 * fps) - 1)} durationInFrames={dur} name={"sfx-" + s.id}>
        <SfxAudio s={s} durationInFrames={dur}/>
      </Sequence>
    );
  })}</>
);

export const Reel: React.FC<ReelProps> = (props) => {
  ensureReelFonts();
  const {fps} = useVideoConfig(); const f = (ms: number) => Math.round(ms / 1000 * fps);
  const ctaMs = props.cta ? props.cta.fromMs : props.totalMs;
  const hookEndMs = props.hook?.hookEndMs ?? (props.scenes[0]?.toMs || 0);
  const overlays = props.overlays || [];
  const blocks = overlays.filter((o) => o.blocks_captions === true).map((o) => [o.startMs, o.startMs + o.durMs]);
  const avatarWindows = props.scenes.filter((s) => s.role === "avatar").map((s) => [s.fromMs, s.toMs]);
  const palette = props.style?.palette || {};
  const brand = {
    bg: hx(palette.bg, props.brand.bg),
    fg: hx(palette.fg, props.brand.fg),
    accent: hx(palette.accent, props.brand.accent),
  };
  const lightTheme = props.style?.base_theme === "light" || isLightHex(brand.bg);
  const declaredOnly = renderPolicyFor(props) === "declared_only" || true;
  const hookOverlay = props.style?.hook_overlay || "none";
  const texture = props.style?.texture || "subtle";
  const rootStyle = {backgroundColor: brand.bg, ...resolveStyleVars(props)} as React.CSSProperties;
  return (
    <AbsoluteFill style={rootStyle}>
      {props.audio ? <Audio src={resolveSrc(props.audio)}/> : null}
      <AbsoluteFill style={{background: lightTheme ? `linear-gradient(180deg,${THEME.cream},${THEME.off})` : `linear-gradient(160deg,${THEME.panel},${brand.bg} 82%)`}}/>

      {props.scenes.map((sc, i) => {
        const dur = Math.max(1, f(sc.toMs - sc.fromMs));
        const sceneOverlays = overlays.filter((o) => o.startMs < sc.toMs && o.startMs + o.durMs > sc.fromMs);
        const sceneBeats = sc.visualBeats && sc.visualBeats.length ? sc.visualBeats : scopedRootBeats(props.visualBeats, sc, i);
        const lane = laneFor(sceneCaptionPos(props.scenes, sc.fromMs + 1, props.style));
        return (
          <Sequence key={i} from={f(sc.fromMs)} durationInFrames={dur} name={sc.role}>
            <Fade durationInFrames={dur} index={i} transition={sc.transition_in}>
              {sc.role === "avatar" ? (
                <Background motion="static" color={brand.bg} fg={brand.fg} texture={texture} scene={sc} visualBeats={sceneBeats}/>
              ) : (
                <Background media={lightTheme && sc.media === "media/plate.mp4" ? undefined : sc.media} motion={sc.motion} color={brand.bg} fg={brand.fg} accent={brand.accent} texture={texture} startFromFrames={sc.role === "hook" ? Math.round(fps * 1.45) : 0} scene={sc} visualBeats={sceneBeats}/>
              )}
            </Fade>
            {shouldRenderPlateSurface(sc, sceneOverlays, declaredOnly) ? <PlateSurface color={brand.fg} accent={brand.accent} bg={brand.bg} scene={sc} overlays={sceneOverlays} declaredOnly={declaredOnly} laneBottom={isGraphicLedScene(sc) ? Math.min(lane.pb, PLATE_CENTER_PB) : lane.pb} laneTop={lane.pt}/> : null}
            {sc.role === "hook" && hookOverlay === "spectacle" ? <HookSpectacle color={brand.fg} accent={brand.accent} label={props.style?.hook_label}/> : null}
            <SceneBeatLayer scene={sc} sceneIndex={i} rootBeats={props.visualBeats} overlays={sceneOverlays} color={brand.fg} accent={brand.accent} bg={brand.bg} fps={fps}/>
            {sc.role === "hook" ? <HookPoster poster={props.hook?.poster}/> : null}
            {sc.role === "hook" && props.hook?.headline ? <HookText text={props.hook.headline} color={brand.fg} accent={brand.accent} bg={brand.bg} zone={props.style?.hook_text_zone}/> : null}
          </Sequence>
        );
      })}

      {/* AvatarLayer ANTES que OverlayLayer: AvatarSplitFrame pinta un fondo
          full-frame (companion + banda avatar); si va despues, tapa por completo
          los overlays declarados (StatRing/LowerThird/SplitCompare) anclados a
          esa escena -- hallado al verificar la banda del avatar con overlays reales. */}
      <AvatarLayer scenes={props.scenes} color={brand.fg} accent={brand.accent} bg={brand.bg} fps={fps}/>
      <OverlayLayer overlays={overlays} brand={brand} fps={fps} declaredOnly={declaredOnly} style={props.style} scenes={props.scenes}/>
      <PacingBeatLayer beats={props.pacingBeats || []} brand={brand} fps={fps} totalMs={props.totalMs}/>
      <CaptionLayer captions={props.captions} color={brand.fg} accent={brand.accent} ctaMs={ctaMs} hookEndMs={hookEndMs} blocks={blocks} avatarWindows={avatarWindows} style={props.style} scenes={props.scenes}/>

      {props.cta ? (
        <Sequence from={f(props.cta.fromMs)} durationInFrames={Math.max(1, f(props.totalMs - props.cta.fromMs))} name="cta">
          <Cta {...props.cta} color={brand.fg} accent={brand.accent} bg={brand.bg}/>
        </Sequence>
      ) : null}

      <ProgressBar accent={brand.accent} mode={props.style?.progress_bar || "none"}/>
      <SfxLayer sfx={props.sfx || []} fps={fps}/>
    </AbsoluteFill>
  );
};
