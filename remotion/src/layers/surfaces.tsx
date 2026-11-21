import React from "react";
import {AbsoluteFill, Img, OffthreadVideo, useCurrentFrame, useVideoConfig, interpolate, spring} from "remotion";
import {THEME, hexA, fontFamily, C, isLightHex, resolveSrc, isVideo, DottedTexture} from "../theme";
import {PANEL, OVERLAY_ROW_PX} from "../generated";
import {ReelProps, Scene, Overlay, VisualBeat} from "../types";
import {localBeatFrame} from "./beats";

// Tratamiento visual del media de una escena (clip.treatment). Solo estilo: no
// agrega ni inventa contenido, por eso es compatible con declared_only.
export const MediaTreatment: React.FC<{treatment?: string; accent: string}> = ({treatment, accent}) => {
  if (!treatment || treatment === "none") return null;
  if (treatment === "vignette") return (
    <AbsoluteFill style={{background: "radial-gradient(78% 62% at 50% 44%, transparent 58%, rgba(0,0,0,0.46) 100%)"}}/>
  );
  if (treatment === "spotlight") return (
    <AbsoluteFill style={{background: "radial-gradient(52% 38% at 50% 42%, transparent 30%, rgba(0,0,0,0.62) 92%)"}}/>
  );
  if (treatment === "duotone_brand") return (
    <>
      <AbsoluteFill style={{background: accent, mixBlendMode: "color", opacity: 0.75}}/>
      <AbsoluteFill style={{background: "linear-gradient(180deg, rgba(0,0,0,0.16), rgba(0,0,0,0.30))", mixBlendMode: "multiply"}}/>
    </>
  );
  return null;
};

export const Background: React.FC<{
  media?: string;
  motion?: string;
  color: string;
  fg?: string;
  texture?: NonNullable<ReelProps["style"]>["texture"];
  startFromFrames?: number;
  scene?: Scene;
  visualBeats?: VisualBeat[];
  accent?: string;
}> = ({media, motion, color, fg = "#ffffff", texture = "subtle", startFromFrames = 0, scene, visualBeats = [], accent}) => {
  const frame = useCurrentFrame(); const {durationInFrames,fps} = useVideoConfig();
  const light = isLightHex(color);
  if (!media) return (
    <AbsoluteFill style={{background: light ? `linear-gradient(180deg,${THEME.cream},${THEME.off})` : `linear-gradient(160deg,${hexA(color,0.92)},${color} 78%)`}}>
      {texture !== "none" ? <DottedTexture color={light ? THEME.ink : fg} opacity={texture === "dotted" ? 0.08 : 0.035}/> : null}
    </AbsoluteFill>
  );
  const z = motion === "static" ? 1 : interpolate(frame,[0,durationInFrames],motion==="kenburns-out"?[1.12,1]:[1,1.12],C);
  const px = motion==="pan-left"?interpolate(frame,[0,durationInFrames],[40,-40],C):motion==="pan-right"?interpolate(frame,[0,durationInFrames],[-40,40],C):0;
  const cropBeats = visualBeats.filter((b)=>b.action==="crop_reframe" && scene);
  const activeCrop = cropBeats
    .map((b)=>({beat:b, local: scene ? localBeatFrame(b, scene, fps) : 0}))
    .filter((b)=>frame >= b.local - 4)
    .sort((a,b)=>b.local-a.local)[0];
  const cropProgress = activeCrop ? interpolate(frame,[activeCrop.local-4,activeCrop.local+12],[0,1],C) : 0;
  const target = String(activeCrop?.beat.target || "").toLowerCase();
  const semanticZoom = activeCrop ? interpolate(cropProgress,[0,1],[1,activeCrop.beat.strength==="medium"?1.18:1.12],C) : 1;
  const semanticX = activeCrop ? interpolate(cropProgress,[0,1],[0,
    target.includes("left") ? 64 :
    target.includes("right") ? -64 : 0
  ],C) : 0;
  const semanticY = activeCrop ? interpolate(cropProgress,[0,1],[0,
    target.includes("top") || target.includes("superior") ? 54 :
    target.includes("bottom") || target.includes("inferior") ? -72 :
    target.includes("dentro") || target.includes("intern") ? -42 : 0
  ],C) : 0;
  return (
    <AbsoluteFill style={{backgroundColor: color, overflow:"hidden"}}>
      {isVideo(media)
        ? <OffthreadVideo src={resolveSrc(media)} muted startFrom={startFromFrames} style={{width:"100%",height:"100%",objectFit:"cover",transform:`scale(${z*semanticZoom}) translate(${px+semanticX}px, ${semanticY}px)`}} />
        : <Img src={resolveSrc(media)} style={{width:"100%",height:"100%",objectFit:"cover",transform:`scale(${z*semanticZoom}) translate(${px+semanticX}px, ${semanticY}px)`}} />}
      <MediaTreatment treatment={scene?.treatment} accent={accent || fg}/>
      <AbsoluteFill style={{background:light
        ? `linear-gradient(180deg,rgba(255,255,255,0.04),${hexA(THEME.cream,0.16)})`
        : `linear-gradient(180deg,${hexA(fg,0.055)},${hexA(color,0.14)})`}} />
      {texture === "dotted" ? <DottedTexture color={light ? THEME.ink : fg} opacity={0.04}/> : null}
    </AbsoluteFill>
  );
};

export const FramedMedia: React.FC<{
  media?: string;
  color: string;
  accent: string;
  bg: string;
  motion?: string;
  startFromFrames?: number;
  objectPosition?: string;
  objectFit?: "cover" | "contain";
  fallbackLabel?: string;
  lift?: number;
}> = ({media, color, accent, bg, motion = "static", startFromFrames = 0, objectPosition = "center center", objectFit = "cover", fallbackLabel, lift = 0}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const light = isLightHex(bg);
  const z = motion === "static"
    ? 1
    : interpolate(frame, [0, durationInFrames], motion === "kenburns-out" ? [1.08, 1] : [1, 1.08], C);
  const y = lift ? interpolate(frame, [0, durationInFrames], [lift, -lift], C) : 0;
  const p = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], C);
  if (!media) {
    const sweep = interpolate(frame, [0, Math.max(1, durationInFrames * 0.7)], [0, 1], C);
    const chipLabels = (fallbackLabel || "").split(/\s*\+\s*|\s{2,}/).filter(Boolean).slice(0, 3);
    return (
      <AbsoluteFill style={{
        background: light
          ? `linear-gradient(135deg,${THEME.off},${THEME.cream})`
          : `radial-gradient(circle at 50% 36%, ${hexA(accent,0.18)}, ${bg} 70%)`,
        alignItems: "center",
        justifyContent: "center",
      }}>
        <DottedTexture color={light ? THEME.ink : color} opacity={light ? 0.035 : 0.08}/>
        <div style={{
          position: "absolute",
          left: 94,
          right: 94,
          top: 178,
          height: 462,
          borderRadius: 18,
          border: `2px solid ${hexA(accent,0.28)}`,
          background: hexA(light ? THEME.panel : color, light ? 0.72 : 0.10),
          boxShadow: `0 24px 80px ${hexA(accent,0.14)}`,
          overflow: "hidden",
          transform: `scale(${0.985 + p * 0.015})`,
        }}/>
        <div style={{position:"absolute",left:150,top:242,width:780,height:3,background:hexA(accent,0.18)}}/>
        <div style={{position:"absolute",left:150,top:242,width:780*sweep,height:7,borderRadius:7,background:hexA(accent,0.78)}}/>
        {chipLabels.map((label, i)=> {
          const enter = interpolate(frame, [8 + i * 8, 22 + i * 8], [0, 1], C);
          return (
            <div key={label + i} style={{
              position: "absolute",
              left: 168 + i * 32,
              right: 168 - i * 32,
              top: 314 + i * 92,
              minHeight: 68,
              borderRadius: 16,
              border: `2px solid ${hexA(accent,0.18 + i * 0.04)}`,
              background: hexA(THEME.panel, light ? 0.84 : 0.18),
              color: light ? THEME.ink : color,
              fontFamily,
              fontWeight: 800,
              fontSize: 30,
              textTransform: "uppercase",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: `0 18px 46px ${hexA(accent,0.10)}`,
              opacity: enter,
              transform: `translateY(${(1-enter)*18}px)`,
            }}>{label}</div>
          );
        })}
        {fallbackLabel ? (
          <div style={{
            position: "absolute",
            bottom: 44,
            left: 42,
            right: 42,
            fontFamily,
            fontWeight: 800,
            fontSize: 26,
            color: hexA(color,0.68),
            textAlign: "center",
            textTransform: "uppercase",
          }}>{fallbackLabel}</div>
        ) : null}
      </AbsoluteFill>
    );
  }
  const mediaStyle: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit,
    objectPosition,
    // Ken Burns (scale) sobre objectFit:contain descubriria bandas: solo escala
    // cuando el media cubre (cover). Con contain el clip se muestra completo, sin
    // recorte y sin zoom -- exactamente lo que exige el avatar 16:9.
    scale: objectFit === "contain" ? 1 : z,
    translate: `0px ${objectFit === "contain" ? 0 : y}px`,
    filter: "brightness(1.05) contrast(1.04) saturate(1.04)",
  };
  return (
    <AbsoluteFill style={{backgroundColor: bg, overflow: "hidden"}}>
      {isVideo(media)
        ? <OffthreadVideo src={resolveSrc(media)} muted startFrom={startFromFrames} style={mediaStyle}/>
        : <Img src={resolveSrc(media)} style={mediaStyle}/>}
      <AbsoluteFill style={{background: light
        ? "linear-gradient(180deg,rgba(255,255,255,0.02),rgba(240,237,230,0.10))"
        : "linear-gradient(180deg,rgba(0,0,0,0.02),rgba(0,0,0,0.14))"}}/>
    </AbsoluteFill>
  );
};

export const Fade: React.FC<{durationInFrames:number;index:number;transition?: string;children:React.ReactNode}> = ({durationInFrames,index,transition,children}) => {
  const f=useCurrentFrame();
  const mode=(transition || "fade").toLowerCase();
  if (mode === "cut" || durationInFrames < 18) {
    return <AbsoluteFill>{children}</AbsoluteFill>;
  }
  if (mode === "slide") {
    const dir=index%2===0?1:-1;
    const x=interpolate(f,[0,8,durationInFrames-8,durationInFrames],[72*dir,0,0,-48*dir],C);
    return <AbsoluteFill style={{transform:`translateX(${x}px)`}}>{children}</AbsoluteFill>;
  }
  // Transiciones expresivas (vocabulario curado; el validador limita a 3 por reel
  // y exige transition_reason): punch_in = zoom seco hacia el contenido entrante;
  // whip = barrido rapido con blur direccional.
  if (mode === "punch_in") {
    const z=interpolate(f,[0,9],[1.22,1],C);
    const op=interpolate(f,[0,4],[0.35,1],C);
    return <AbsoluteFill style={{opacity:op,transform:`scale(${z})`}}>{children}</AbsoluteFill>;
  }
  if (mode === "whip") {
    const dir=index%2===0?1:-1;
    const x=interpolate(f,[0,7],[340*dir,0],C);
    const blur=interpolate(f,[0,7],[18,0],C);
    return <AbsoluteFill style={{transform:`translateX(${x}px)`,filter:`blur(${Math.max(0,blur)}px)`}}>{children}</AbsoluteFill>;
  }
  const o=interpolate(f,[0,7,durationInFrames-7,durationInFrames],[0,1,1,0],C);
  if (mode === "wipe" || mode === "clockwipe") {
    const inset=interpolate(f,[0,10],[100,0],C);
    return <AbsoluteFill style={{opacity:o,clipPath:`inset(0 ${inset}% 0 0)`}}>{children}</AbsoluteFill>;
  }
  const dir=index%2===0?1:-1;
  const x=mode === "fade" ? 0 : interpolate(f,[0,8,durationInFrames-8,durationInFrames],[60*dir,0,0,-40*dir],C);
  return <AbsoluteFill style={{opacity:o,transform:`translateX(${x}px)`}}>{children}</AbsoluteFill>;
};

export const HookText: React.FC<{text:string;color:string;accent:string;bg:string;zone?: NonNullable<ReelProps["style"]>["hook_text_zone"]}> = ({text,color,accent,bg,zone = "top_clean"}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const lightBg=isLightHex(bg);
  const words=text.split(/\s+/).filter(Boolean);
  const cleanZone = zone === "auto" ? "top_clean" : zone;
  const area: React.CSSProperties = cleanZone === "bottom_clean"
    ? {justifyContent:"flex-end",padding:"0 78px 500px"}
    : cleanZone === "center_clean"
      ? {justifyContent:"center",padding:"0 78px"}
      : {justifyContent:"flex-start",padding:"158px 78px 0"};
  const textLen=text.replace(/\s+/g,"").length;
  const fs=Math.max(50,Math.min(82,86-Math.max(0,textLen-18)*1.15));
  return (
    <AbsoluteFill style={{alignItems:"center",...area}}>
      {cleanZone==="top_clean" ? (
        <div style={{
          position:"absolute",
          left:42,
          right:42,
          top:112,
          height:240,
          borderRadius:14,
          background:lightBg ? hexA(THEME.cream,0.78) : "rgba(10,10,10,0.58)",
          boxShadow:lightBg ? "0 18px 56px rgba(13,13,13,0.13)" : "0 18px 62px rgba(0,0,0,0.42)",
          backdropFilter:"blur(7px)",
        }}/>
      ) : null}
      <div style={{
        display:"flex",
        flexWrap:"wrap",
        justifyContent:"center",
        gap:"6px 18px",
        maxWidth:914,
        padding:"24px 34px 27px",
        borderRadius:8,
        background:lightBg ? hexA(THEME.off,0.86) : "rgba(10,10,10,0.68)",
        border:`1px solid ${hexA(lightBg ? color : accent, lightBg ? 0.12 : 0.24)}`,
        boxShadow:lightBg ? "0 20px 70px rgba(13,13,13,0.18)" : "0 22px 70px rgba(0,0,0,0.48)",
        backdropFilter:"blur(5px)",
      }}>
        {words.map((w,i)=>{const raw=spring({frame:f-i*2,fps,config:{damping:14,mass:0.5}}); const s=Math.max(raw,0.88);
          const isAccent=i===words.length-1 || w.length>=8;
          return <span key={i} style={{fontFamily,fontWeight:800,fontSize:fs,lineHeight:1.03,
            color:w.length>=7?accent:color,textTransform:"uppercase",opacity:s,transform:`translateY(${(1-s)*26}px)`,
            textShadow:lightBg ? "0 1px 0 rgba(255,255,255,0.82)" : "0 5px 18px rgba(0,0,0,0.85)",
            display:"inline-block"}}>{isAccent ? <span style={{color:accent}}>{w}</span> : w}</span>;})}
      </div>
    </AbsoluteFill>
  );
};

// ChapterDots sacado de esta lista: solo pinta un pill pequeno centrado, no un
// fondo propio -- excluirlo dejaba la escena en cream plano (hallado en
// render real, escena "revisa tres cosas" con ~90% del frame vacio).
const FULL_FRAME_OVERLAY_COMPONENTS = new Set([
  "CausalMeter", "StoryArcChart",
]);

export const shouldRenderPlateSurface = (scene: Scene, overlays: Overlay[], declaredOnly = true) => {
  const plateLike = scene.role === "plate" || (scene.role === "hook" && !scene.media && scene.source === "none");
  if (scene.media || !plateLike || scene.layout === "cta") return false;
  if (declaredOnly && (!scene.plate_purpose || scene.plate_purpose === "none")) return false;
  // Antes: false aqui dejaba estas escenas SIN fondo alguno (cream plano),
  // hallado en render real como aire muerto severo. Ahora rendereamos el
  // ambiente (textura+glow) via PlateSurface; el panel/caja se sigue
  // omitiendo para estas dos variantes (ver purpose==="none" mas abajo).
  if (overlays.some((o)=>FULL_FRAME_OVERLAY_COMPONENTS.has(String(o.component)))) return false;
  // SplitCompare vertical (DepthDiagram) es un visual full-frame autosuficiente:
  // el panel del plate detras solo lo ensucia (dos cajas superpuestas).
  if (overlays.some((o)=>String(o.component)==="SplitCompare" && (o as any).params?.orientation==="vertical")) return false;
  return true;
};

export const HookPoster: React.FC<{poster?: string}> = ({poster}) => {
  const f=useCurrentFrame();
  if (!poster || f > 10) return null;
  const opacity=interpolate(f,[0,10],[1,0],C);
  return (
    <AbsoluteFill style={{opacity,pointerEvents:"none"}}>
      <Img src={resolveSrc(poster)} style={{width:"100%",height:"100%",objectFit:"cover"}}/>
    </AbsoluteFill>
  );
};

export const platePurposeFor = (scene: Scene, overlays: Overlay[], declaredOnly = true) => {
  if (scene.plate_purpose && scene.plate_purpose !== "none") return scene.plate_purpose;
  if (declaredOnly) return "none";
  if (scene.layout === "cta") return "cta_resource";
  if (overlays.some((o)=>o.component==="StatRing"||o.component==="CountUp")) return "stat_card";
  if (overlays.some((o)=>o.component==="StepList")) return "rule_checklist";
  return "decision_card";
};

// Altura estimada por fila de los overlays de lista (geometria compartida via
// generated.ts: OVERLAY_ROW_PX, espejo de validate_props).
export const plateContentEstimate = (overlays: Overlay[]): number =>
  Math.max(0, ...overlays.map((o) => {
    const row = OVERLAY_ROW_PX[String(o.component)] || 0;
    const items = (o.params?.items || o.params?.labels || []) as unknown[];
    return row && Array.isArray(items) ? items.length * row : 0;
  }));

export const PlateSurface: React.FC<{color:string;accent:string;bg:string;scene:Scene;overlays:Overlay[];declaredOnly?:boolean;laneBottom?:number;laneTop?:number}> = ({color,accent,bg,scene,overlays,declaredOnly=true,laneBottom=570,laneTop=0}) => {
  const f=useCurrentFrame();
  const {fps}=useVideoConfig();
  const light=isLightHex(bg);
  const purpose=platePurposeFor(scene,overlays,declaredOnly);
  if (purpose==="none") return null;
  const sweep=interpolate(f,[0,52],[0,1],C);
  // El panel abraza su contenido y se centra en la zona libre sobre la caption lane
  // de ESTA escena (nada de caja fija 936x990): sin aire muerto dentro del panel y
  // sin invadir jamas la banda del caption. El centro optico coincide con el centro
  // de flex que usan los overlays (paddingTop=laneTop, paddingBottom=laneBottom).
  const freeCenter=(laneTop+1920-laneBottom)/2;
  const est=plateContentEstimate(overlays);
  // Antes: sin items de lista (est=0) caia al fallback 990 -- el TAMANO MAXIMO,
  // exactamente al reves de lo que necesita una escena con solo un LowerThird/
  // StatRing/BigWordSequence suelto. Hallado en render real: panel gigante
  // envolviendo un solo rotulo pequeno. Sin lista, el panel abraza un tamano
  // modesto (cabe LowerThird+StatRing) en vez del maximo pensado para listas.
  const sparseH=440;
  const minH=est ? PANEL.min_height : Math.min(PANEL.min_height, sparseH);
  const panelH=Math.max(minH,Math.min(est ? est+PANEL.content_padding : sparseH, 1920-laneBottom-40-Math.max(PANEL.top_margin,laneTop)));
  const panelTop=Math.max(Math.max(PANEL.top_margin,laneTop),Math.round(freeCenter-panelH/2));
  // Superficie PURA: fondo, textura, glow y panel. NO dibuja tarjetas, anillos,
  // barras, cajas ni valores por su cuenta. TODO el contenido informativo lo
  // componen los overlays declarados (StepList/StatRing/CausalMeter/etc.) que
  // se colocan encima. Sin plate_purpose declarado no se renderiza (return null).
  return (
    <AbsoluteFill style={{pointerEvents:"none",overflow:"hidden",background:light ? "transparent" : hexA(color,0.045)}}>
      <DottedTexture color={light ? THEME.ink : color} opacity={light ? 0.024 : 0.075}/>
      {/* Glow tenue: a 0.42/0.50 el accent rojo se leia como mancha/render sucio
          (hallado en revision humana del reel de cremas). Acoplado al umbral
          luma_std de bright_empty en engine/visual_qa.py: si se cambia uno,
          cambiar el otro o se reabre la oscilacion glow<->QA. */}
      <div style={{position:"absolute",inset:0,background:light
        ? `radial-gradient(72% 46% at 50% 32%, ${hexA(accent,0.10)}, transparent 72%)`
        : `radial-gradient(72% 46% at 50% 32%, ${hexA(accent,0.14)}, transparent 72%)`}}/>
      <div style={{position:"absolute",left:72,top:panelTop,width:936,height:panelH,borderRadius:22,border:`2px solid ${light ? hexA(color,0.22) : hexA(color,0.3)}`,
        background:light ? `linear-gradient(180deg,${hexA(THEME.off,0.62)},${hexA(THEME.cream,0.22)})` : `linear-gradient(180deg,${hexA(THEME.panel,0.58)},${hexA(bg,0.14)})`}}/>
      <div style={{position:"absolute",left:112,top:panelTop+panelH-86,width:760*sweep,height:8,borderRadius:8,background:accent,opacity:0.62}}/>
    </AbsoluteFill>
  );
};

export const HookSpectacle: React.FC<{color:string;accent:string;label?:string}> = ({color,accent,label}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const draw=interpolate(f,[0,Math.round(fps*1.4)],[0,1],C);
  const boom=spring({frame:f-4,fps,config:{damping:13,mass:0.7}});
  const orb=interpolate(f,[0,Math.round(fps*2.6)],[0,1],C);
  return (
    <AbsoluteFill style={{pointerEvents:"none"}}>
      <AbsoluteFill style={{background:`radial-gradient(54% 34% at 50% 52%, ${hexA(THEME.purple,0.16)}, transparent 72%)`}}/>
      <svg width="1080" height="1200" viewBox="0 0 1080 1200" style={{position:"absolute",top:360,left:0,overflow:"visible",opacity:0.96}}>
        <defs>
          <filter id="hookGlow"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <linearGradient id="hookLine" x1="0" x2="1"><stop offset="0%" stopColor={THEME.yellow}/><stop offset="55%" stopColor={THEME.magenta}/><stop offset="100%" stopColor={THEME.purple}/></linearGradient>
        </defs>
        {[0,1,2,3].map(i=>(
          <ellipse key={i} cx="540" cy={430+i*64} rx={130+i*95} ry={42+i*14}
            fill="none" stroke={hexA(color,0.08+i*0.04)} strokeWidth="3"
            strokeDasharray={`${90+i*26} ${28+i*8}`} transform={`rotate(${(f*0.18+i*7)%360} 540 ${430+i*64})`}/>
        ))}
        <path d="M 118 690 C 260 460, 396 384, 540 344 C 696 388, 838 470, 962 690"
          fill="none" stroke="url(#hookLine)" strokeWidth="12" strokeLinecap="round"
          strokeDasharray="1400" strokeDashoffset={1400*(1-draw)} filter="url(#hookGlow)"/>
        {[0,1,2,3,4,5,6,7,8,9,10,11].map((i)=>{
          const x=180+(i%6)*144; const y=500+Math.floor(i/6)*150;
          const s=spring({frame:f-i*2,fps,config:{damping:12,mass:0.6}});
          return <g key={i} opacity={s} transform={`translate(${x} ${y}) scale(${0.75+0.25*s})`}>
            <rect x="-42" y="-42" width="84" height="84" rx="18" fill={hexA(i%3===0?THEME.yellow:i%3===1?THEME.purple:THEME.red,0.22)} stroke={hexA(color,0.25)}/>
            <circle cx="0" cy="0" r={12+6*Math.sin((f+i*8)/8)} fill={i%3===0?THEME.yellow:i%3===1?THEME.purple:THEME.red}/>
          </g>;
        })}
        <circle cx={540+Math.sin(f/18)*190} cy={390+Math.cos(f/16)*42} r={18+14*orb}
          fill={accent} filter="url(#hookGlow)" opacity={0.82}/>
        {label ? <text x="540" y="792" textAnchor="middle" fill={hexA(color,0.7)} fontFamily={fontFamily} fontSize="26" fontWeight="800">{label}</text> : null}
      </svg>
      <div style={{position:"absolute",left:104,top:728,width:872,height:2,background:`linear-gradient(90deg,transparent,${hexA(accent,0.65)},transparent)`,transform:`scaleX(${0.3+0.7*boom})`}}/>
    </AbsoluteFill>
  );
};
