import React from "react";
import {AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig, interpolate, spring} from "remotion";
import {THEME, hexA, fontFamily, C, isLightHex} from "../theme";
import {Scene, Overlay, VisualBeat, PacingBeat} from "../types";

export const cleanBeatText = (value?: string) => String(value || "")
  .replace(/\b(evaluacion)\b/gi, "evaluación")
  .trim();
export const visualBeatLabel = (beat: VisualBeat) => {
  const text = cleanBeatText(beat.label || beat.target || beat.semantic_delta || "");
  return text.length > 42 ? `${text.slice(0, 39).trim()}...` : text;
};
export const localBeatFrame = (beat: VisualBeat, scene: Scene, fps: number) =>
  Math.round(((beat.atMs || scene.fromMs) - scene.fromMs) / 1000 * fps);
export const scopedRootBeats = (beats: VisualBeat[] | undefined, scene: Scene, sceneIndex: number) =>
  (beats || []).filter((b) =>
    b.sceneIndex === sceneIndex ||
    (b.sceneIndex == null && b.atMs >= scene.fromMs && b.atMs < scene.toMs)
  );

export const SCENE_BEAT_BLOCKING_OVERLAYS = new Set([
  "KeywordPop", "StepList", "CausalMeter",
  "StatRing", "CountUp", "StoryArcChart", "LowerThird",
  "Annotation", "ObjectCallout", "ChapterDots",
  "FocusPunch", "SplitCompare", "BigWordSequence",
]);
export const overlayBlocksSceneBeat = (overlay: Overlay, beat: VisualBeat) => {
  const at = beat.atMs || 0;
  const start = overlay.startMs - 220;
  const end = overlay.startMs + overlay.durMs + 220;
  if (at < start || at > end) return false;
  if (!SCENE_BEAT_BLOCKING_OVERLAYS.has(String(overlay.component))) return false;
  if (overlay.component === "ObjectCallout" || overlay.component === "Annotation") {
    return beat.action === "callout_target" || beat.action === "insert_card";
  }
  return true;
};

export const SceneBeatCard: React.FC<{beat:VisualBeat;color:string;accent:string;bg:string;scene:Scene}> = ({beat,color,accent,bg,scene}) => {
  const f=useCurrentFrame(); const {fps,durationInFrames}=useVideoConfig();
  const light=isLightHex(bg);
  const p=spring({frame:f,fps,config:{damping:16,mass:0.62}});
  const out=interpolate(f,[Math.max(1,durationInFrames-8),durationInFrames],[1,0],C);
  const opacity=Math.min(1,p)*out;
  const action=beat.action || "callout_target";
  const label=visualBeatLabel(beat);
  if (!label) return null;
  // crop_reframe es un MOVIMIENTO DE CAMARA (surfaces.tsx Background lo reencuadra
  // via semanticX/Y segun target). NO debe dibujar tarjeta ni caja: hacerlo
  // mostraba en pantalla el target crudo como label de debug ('TOP', 'LEFT') mas
  // un recuadro verde -- el reel se veia sin terminar (hallado en render real del
  // reel en ingles, cuyos beats de pacing usaban targets direccionales). El
  // reframe se SIENTE, no se anota. Los callouts visibles son callout_target/
  // insert_card (que SI señalan algo en pantalla).
  if (action==="crop_reframe") return null;
  const target=String(beat.target || "").toLowerCase();
  const right = target.includes("right");
  const compact = action==="callout_target" || action==="component_state";
  const strong = action==="layout_swap" || action==="insert_card" || action==="new_media";
  const top = scene.role==="broll" ? (compact ? 260 : 330) : compact ? 220 : 360;
  const cardW = compact ? 360 : 640;
  const cardLeft = compact ? (right ? 620 : 82) : 220;
  const cardBg = light ? hexA(THEME.off,0.9) : hexA(THEME.panel,0.82);
  const semantic = cleanBeatText(beat.semantic_delta || "");
  return (
    <AbsoluteFill style={{pointerEvents:"none",opacity}}>
      {action==="crop_reframe" ? (
        <div style={{
          position:"absolute",
          left:right?592:86,
          top:scene.role==="broll"?470:430,
          width:402,
          height:402,
          borderRadius:28,
          border:`4px solid ${hexA(accent,0.7)}`,
          boxShadow:`0 0 0 12px ${hexA(accent,0.08)}, inset 0 0 42px ${hexA(accent,0.08)}`,
          transform:`scale(${0.92+0.08*p})`,
        }}/>
      ) : null}
      <div style={{
        position:"absolute",
        left:cardLeft,
        top,
        width:cardW,
        minHeight:compact?86:142,
        borderRadius:8,
        background:cardBg,
        border:`2px solid ${hexA(accent,strong?0.72:0.46)}`,
        boxShadow:light ? "0 18px 52px rgba(13,13,13,0.18)" : "0 22px 60px rgba(0,0,0,0.34)",
        padding:compact?"18px 22px":"24px 30px",
        boxSizing:"border-box",
        transform:`translateY(${(1-p)*22}px) scale(${0.98+0.02*p})`,
      }}>
        <div style={{display:"flex",alignItems:"center",gap:16}}>
          <div style={{width:compact?18:22,height:compact?18:22,borderRadius:999,background:accent,boxShadow:`0 0 18px ${hexA(accent,0.34)}`,flex:"0 0 auto"}}/>
          <div style={{fontFamily,fontWeight:800,fontSize:compact?30:42,lineHeight:1.02,color,textTransform:"uppercase",letterSpacing:0}}>
            {label}
          </div>
        </div>
        {!compact && semantic ? (
          <div style={{fontFamily,fontWeight:700,fontSize:26,lineHeight:1.12,color:hexA(color,0.66),marginTop:14,textTransform:"uppercase"}}>
            {semantic.length > 72 ? `${semantic.slice(0,69).trim()}...` : semantic}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const SceneBeatLayer: React.FC<{
  scene:Scene;
  sceneIndex:number;
  rootBeats?:VisualBeat[];
  overlays?:Overlay[];
  color:string;
  accent:string;
  bg:string;
  fps:number;
}> = ({scene,sceneIndex,rootBeats,overlays = [],color,accent,bg,fps}) => {
  const beats=(scene.visualBeats && scene.visualBeats.length ? scene.visualBeats : scopedRootBeats(rootBeats, scene, sceneIndex))
    .filter((b)=>b.atMs > scene.fromMs && b.atMs < scene.toMs)
    .filter((b)=>!overlays.some((o)=>overlayBlocksSceneBeat(o,b)));
  return (
    <>{beats.map((b,i)=>{
      const local=localBeatFrame(b,scene,fps);
      const from=Math.max(0,local-4);
      const dur=Math.max(16,Math.round(fps*(b.strength==="medium"?1.15:0.92)));
      return (
        <Sequence key={`scene-beat-${sceneIndex}-${i}-${b.atMs}`} from={from} durationInFrames={dur} name={`visual-beat-${b.action || "beat"}`}>
          <SceneBeatCard beat={b} color={color} accent={accent} bg={bg} scene={scene}/>
        </Sequence>
      );
    })}</>
  );
};

const PacingPulse: React.FC<{beat:PacingBeat;color:string;accent:string;bg:string}> = ({beat,color,accent,bg}) => {
  const f=useCurrentFrame(); const {durationInFrames}=useVideoConfig();
  const light=isLightHex(bg);
  const strength=beat.strength==="medium"?1:0.72;
  const opacity=interpolate(f,[0,2,Math.max(3,durationInFrames-4),durationInFrames],[0,0.86*strength,0.68*strength,0],C);
  const travel=interpolate(f,[0,durationInFrames],[-260,1120],C);
  const rail=interpolate(f,[0,6,durationInFrames],[0,1,1],C);
  const kind=beat.kind || "reframe";
  const isHook=kind==="hook_interrupt";
  const isFrame=kind==="reframe" || kind==="zoom_punch" || isHook;
  return (
    <AbsoluteFill style={{pointerEvents:"none",opacity}}>
      <AbsoluteFill style={{
        background:isHook
          ? `radial-gradient(circle at 50% 34%, ${hexA(accent,0.24)}, transparent 42%)`
          : `linear-gradient(180deg, transparent, ${hexA(accent, light ? 0.055 : 0.12)} 46%, transparent)`,
        mixBlendMode:light ? "multiply" : "screen",
      }}/>
      <div style={{
        position:"absolute",
        left:travel,
        top:-160,
        width:isHook?250:170,
        height:2240,
        transform:"skewX(-15deg)",
        background:`linear-gradient(90deg, transparent, ${hexA(accent,isHook?0.34:0.24)}, ${hexA("#FFFFFF",light?0.18:0.1)}, transparent)`,
        filter:"blur(0.4px)",
      }}/>
      <div style={{
        position:"absolute",
        left:70,
        right:70,
        top:isHook?138:206,
        height:4,
        transform:`scaleX(${rail})`,
        transformOrigin:"left center",
        background:`linear-gradient(90deg, ${hexA(accent,0.08)}, ${accent}, ${hexA(accent,0.08)})`,
        boxShadow:`0 0 20px ${hexA(accent,0.34)}`,
      }}/>
      <div style={{
        position:"absolute",
        left:52,
        top:isHook?112:180,
        width:88,
        height:88,
        borderTop:`5px solid ${hexA(accent,0.75)}`,
        borderLeft:`5px solid ${hexA(accent,0.75)}`,
        borderRadius:8,
        transform:`scale(${interpolate(f,[0,5,durationInFrames],[0.82,1,1.02],C)})`,
      }}/>
      {isFrame ? <div style={{
        position:"absolute",
        inset:34,
        border:`2px solid ${hexA(accent,0.16)}`,
        borderRadius:10,
        boxShadow:`inset 0 0 42px ${hexA(accent,0.08)}`,
      }}/> : null}
      <div style={{
        position:"absolute",
        right:58,
        top:isHook?138:206,
        width:46,
        height:46,
        borderRadius:999,
        background:hexA(accent,0.2),
        border:`2px solid ${hexA(color,light?0.22:0.34)}`,
      }}/>
    </AbsoluteFill>
  );
};

export const PacingBeatLayer: React.FC<{beats:PacingBeat[];brand:{fg:string;accent:string;bg:string};fps:number;totalMs:number}> = ({beats,brand,fps,totalMs}) => (
  <>{(beats||[]).filter((b)=>b.semantic === true && b.source !== "auto" && b.atMs > 0 && b.atMs < totalMs).map((b,i)=>{
    const dur=Math.round(fps*0.38);
    return (
      <Sequence key={`pacing-${i}-${b.atMs}`} from={Math.max(0,Math.round(b.atMs/1000*fps)-2)} durationInFrames={dur} name={`pacing-${b.kind || "beat"}`}>
        <PacingPulse beat={b} color={brand.fg} accent={brand.accent} bg={brand.bg}/>
      </Sequence>
    );
  })}</>
);
