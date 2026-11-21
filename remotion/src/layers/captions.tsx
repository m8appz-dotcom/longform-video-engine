import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, spring} from "remotion";
import {THEME, hexA, fontFamily, C} from "../theme";
import {
  CAPTION_PAD_BOTTOM,
  CAPTION_PAD_TOP_WHEN_TOP,
  captionLaneReservePx,
  captionLaneReserveTopPx,
  AVATAR_COMPANION_H,
  AVATAR_CAPTION_BAND_H,
} from "../generated";
import {ReelProps, Caption, Scene} from "../types";

export const captionSize = (word: string, mode: string) => {
  if (mode === "minimal") return 54;
  const len = word.length;
  if (len <= 5) return 92;
  if (len <= 9) return 82;
  if (len <= 13) return 70;
  return 58;
};
const CAPTION_STOPWORDS = new Set([
  "a", "al", "de", "del", "el", "la", "los", "las", "un", "una", "unos", "unas",
  "y", "o", "que", "con", "por", "para", "en", "es", "son", "si", "se", "te",
  "tu", "tus", "mi", "mis", "lo", "le", "les", "como", "pero",
  "contra",
]);
const captionToken = (word: string) => word.toLowerCase()
  .replace(/[áàä]/g, "a").replace(/[éèë]/g, "e").replace(/[íìï]/g, "i")
  .replace(/[óòö]/g, "o").replace(/[úùü]/g, "u").replace(/ñ/g, "n")
  .replace(/[^a-z0-9]/g, "");
export const isCaptionStopword = (word: string) => CAPTION_STOPWORDS.has(captionToken(word));

// Posicion efectiva del caption en un instante: override por escena > style global.
export const sceneCaptionPos = (scenes: Scene[] | undefined, ms: number, style?: ReelProps["style"]) =>
  scenes?.find((s) => ms >= s.fromMs && ms < s.toMs)?.caption_position || style?.caption_position || "center_low";

// Reserva vertical para que NINGUN overlay se monte sobre el caption. Cada overlay
// del area principal se centra/posiciona solo en la zona libre de SU escena.
// La geometria viene de generated.ts (compartida con el validador).
export const laneFor = (pos?: string): {pb: number; pt: number} => ({
  pb: captionLaneReservePx(pos),
  pt: captionLaneReserveTopPx(pos),
});

export const CaptionLayer: React.FC<{captions:Caption[];color:string;accent:string;ctaMs:number;hookEndMs:number;blocks:number[][];avatarWindows:number[][];style?:ReelProps["style"];scenes?:Scene[]}> =
({captions,color,accent,ctaMs,hookEndMs,blocks,avatarWindows,style,scenes}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig(); const t=(f/fps)*1000;
  const mode = style?.caption_style || "word_pop";
  if(mode==="none"||!captions.length||t>=ctaMs||t<hookEndMs) return null;
  for(const [a,b] of blocks){ if(t>=a&&t<b) return null; }
  let idx=0; for(let i=0;i<captions.length;i++){ if(captions[i].startMs<=t) idx=i; else break; }
  const active=captions[idx]; const local=((t-active.startMs)/1000)*fps;
  const pop=spring({frame:local,fps,config:{damping:12,mass:0.6}});
  const up=interpolate(local,[0,8],[34,0],C); const lineW=interpolate(local,[2,12],[0,100],C);
  const inAvatar=avatarWindows.some(([a,b])=>t>=a&&t<b);
  const light=style?.base_theme==="light";
  const position = sceneCaptionPos(scenes, active.startMs, style);
  // Escena "liderada por grafico": plate/diagrama sin media, donde un overlay de
  // texto (BigWordSequence/ChapterDots/SplitCompare/StepList) YA es el mensaje
  // dominante. Ahi un caption word-pop grande y en caja crea DOS focos del mismo
  // peso compitiendo (hallado en render real: 'REVISA'/'TRES'/'MEJORAR' sueltos
  // sobre el grafico). En esas escenas el caption cede a subtitulo de apoyo.
  const activeScene = scenes?.find((s) => active.startMs >= s.fromMs && active.startMs < s.toMs);
  const graphicLed = !!activeScene && activeScene.role === "plate"
    && (activeScene.source === "none" || !activeScene.media)
    && activeScene.plate_purpose !== "cta_resource";
  const avatarCaptionLane = inAvatar;
  const policy = style?.caption_emphasis_policy || "smart_stopwords";
  // Fusion anti-huerfana: una stopword NUNCA ocupa la pantalla sola ("DE"/"EN"/"LA"
  // gigantes, hallado en revision humana del reel de cremas). Si la palabra activa
  // es stopword, se muestra fusionada con la(s) siguiente(s) hasta la primera
  // palabra plena (max 3, ventana 1100ms); la stopword queda atenuada DENTRO del
  // mismo box. El contrato de captions (timing por palabra) no se muta.
  let content = [active];
  if (policy !== "all_equal" && isCaptionStopword(active.word)) {
    const fused = [active];
    for (let j = idx + 1; j < captions.length && fused.length < 3; j++) {
      if (captions[j].startMs - active.startMs > 1100) break;
      fused.push(captions[j]);
      if (!isCaptionStopword(captions[j].word)) break;
    }
    if (fused.length === 1 && idx > 0) fused.unshift(captions[idx - 1]);
    content = fused;
  }
  const fusedPhrase = content.length > 1;
  const stopword = !fusedPhrase && policy !== "all_equal" && isCaptionStopword(active.word);
  const softStopword = policy === "smart_stopwords" && stopword;
  const tinyStopword = policy === "minimal_stopwords" && stopword;
  const displayText = content.map((c) => c.word).join(" ");
  const readability = style?.caption_readability_mode || "adaptive_boxed";
  const forceReadableBox = readability === "adaptive_boxed" || readability === "high_contrast_boxed";
  const boxedCaption = mode==="boxed" || avatarCaptionLane || forceReadableBox || light;
  const captionPanel = forceReadableBox ? hexA(THEME.off, stopword ? 0.9 : 0.96) : hexA(light ? THEME.cream : THEME.panel, stopword ? 0.66 : avatarCaptionLane ? 0.92 : light ? 0.78 : 0.86);
  const captionInk = forceReadableBox ? THEME.ink : color;
  // Ventana de avatar: el caption vive en la FRANJA entre el companion (arriba) y
  // el avatar 16:9 (abajo) -- nunca sobre la cara. Anclado con flex-start +
  // paddingTop a la banda, usando la MISMA geometria que avatar.tsx (generated).
  const avatarBandTop = AVATAR_COMPANION_H + Math.max(24, Math.round((AVATAR_CAPTION_BAND_H - 170) / 2));
  const padBottom=avatarCaptionLane ? 0 : (CAPTION_PAD_BOTTOM[position] ?? CAPTION_PAD_BOTTOM["center_low"]);
  const padTop=avatarCaptionLane ? avatarBandTop : position==="top" ? CAPTION_PAD_TOP_WHEN_TOP : 0;
  const justify=avatarCaptionLane ? "flex-start" : position==="top" ? "flex-start" : "flex-end";
  const baseFontSize=stopword ? Math.min(captionSize(active.word, mode), tinyStopword ? 42 : 54) : captionSize(fusedPhrase ? displayText : active.word, mode);
  const fontSize=avatarCaptionLane ? Math.min(baseFontSize, stopword ? 46 : 76)
    : graphicLed ? Math.min(baseFontSize, stopword ? 38 : 54)  // subtitulo, no heroe
    : baseFontSize;
  return (
    <AbsoluteFill style={{justifyContent:justify,alignItems:"center",paddingBottom:avatarCaptionLane?0:position==="top"?0:padBottom,paddingTop:padTop}}>
      {!light && !avatarCaptionLane ? <AbsoluteFill style={{background:`radial-gradient(46% 14% at 50% 68%,rgba(0,0,0,0.42),transparent 72%)`}}/> : null}
      <div style={{
        transform:`translateY(${up}px) scale(${0.95+0.05*pop})`,
        opacity:(0.62+0.38*pop)*(graphicLed ? 0.9 : 1),
        textAlign:"center",
        maxWidth: avatarCaptionLane ? (stopword ? 560 : 760) : stopword ? 580 : mode==="boxed" ? 900 : 860,
        background: boxedCaption ? captionPanel : "transparent",
        border: boxedCaption ? `2px solid ${hexA(accent,stopword ? 0.12 : avatarCaptionLane ? 0.26 : 0.34)}` : "none",
        borderRadius: boxedCaption ? (stopword ? 14 : 18) : 0,
        padding: boxedCaption ? (stopword ? "9px 17px" : avatarCaptionLane ? "13px 24px" : "15px 27px 17px") : "0 26px",
        boxShadow: boxedCaption ? (stopword ? "0 10px 28px rgba(0,0,0,0.16)" : avatarCaptionLane ? "0 16px 42px rgba(0,0,0,0.18)" : "0 20px 60px rgba(0,0,0,0.34)") : "none",
        backdropFilter: boxedCaption ? "blur(2px)" : "none",
      }}>
        <div style={{fontFamily,fontWeight:softStopword ? 700 : 800,fontSize,textTransform:"uppercase",color:captionInk,
          textShadow:forceReadableBox?"0 1px 0 rgba(255,255,255,0.74)":light?"0 1px 0 rgba(255,255,255,0.7)":mode==="minimal"?"0 4px 14px rgba(0,0,0,0.78)":"0 7px 20px rgba(0,0,0,0.88),0 3px 0 rgba(0,0,0,0.68)",lineHeight:1.02}}>
          {content.map((c,i)=>{
            const spanStop = policy !== "all_equal" && isCaptionStopword(c.word);
            return (
            <span key={`${c.startMs}-${i}`} style={{
              color:spanStop ? hexA(forceReadableBox ? THEME.ink : light ? THEME.ink : color, tinyStopword ? 0.62 : 0.72) : c.startMs===active.startMs ? (mode==="word_pop" ? (forceReadableBox || light ? THEME.ink : color) : accent) : captionInk,
              marginRight:i<content.length-1?18:0,
              display:"inline-block",
            }}>{c.word}</span>
          );})}
        </div>
        {style?.caption_decoration==="underline" ? <div style={{height:6,width:`${lineW}%`,margin:"10px auto 0",backgroundColor:accent,borderRadius:6,boxShadow:`0 0 14px ${hexA(accent,0.48)}`}}/> : null}
      </div>
    </AbsoluteFill>
  );
};
