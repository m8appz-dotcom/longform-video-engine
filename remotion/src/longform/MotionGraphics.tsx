import React from "react";
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {ThreeCanvas} from "@remotion/three";
import type {LongformDesignProfile, LongformProps, LongformShot, LongformTheme} from "../longform-types";
import {semanticV2ComponentFor} from "./semantic-v2/registry";

const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;
const words = (value: unknown, fallback = "PUNTO CLAVE") => {
  const clean = String(value || "").replace(/\s+/g, " ").trim();
  return clean || fallback;
};
const fit = (value: string, large: number, medium: number, small: number) => value.length > 34 ? small : value.length > 20 ? medium : large;

const progressAt = (frame: number, duration: number, start = 0.05, end = 0.44) =>
  interpolate(frame, [duration * start, duration * end], [0, 1], clamp);

const numericToken = (value: unknown, fallback: number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const semanticColor = (theme: LongformTheme, key: keyof NonNullable<LongformTheme["semanticColors"]>, fallback: string) =>
  theme.semanticColors?.[key] || fallback;
const displayWeight = (theme: LongformTheme) => Number(theme.typography?.displayWeight || 900);
const bodyWeight = (theme: LongformTheme) => Number(theme.typography?.bodyWeight || 700);
const panelShadow = (theme: LongformTheme, fallback: string) => theme.effects?.useShadows === false ? "none" : fallback;

const Shell: React.FC<{shot: LongformShot; theme: LongformTheme; designProfile?: LongformDesignProfile; children: React.ReactNode}> = ({shot, theme, designProfile, children}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const motion = designProfile?.motion || theme.motion || {};
  const configuredFrames=numericToken(motion.transitionFrames,14);
  const inP = interpolate(frame, [0, Math.min(Math.max(8,configuredFrames), durationInFrames * 0.22)], [0, 1], clamp);
  const hasBackground = Boolean(shot.backgroundSource);
  const evidenceHybrid = hasBackground && Boolean(shot.evidenceMustRemainDominant !== false);
  const overlayOwnedByMotion = shot.textOwner === "remotion";
  const fullBleedHybrid = (shot.uiSpec?.template === "comparison" && shot.uiSpec?.variant !== "claim-evidence") || shot.uiSpec?.variant === "safety-sequence";
  const splitHybrid = evidenceHybrid && !fullBleedHybrid;
  const composition = designProfile?.composition || theme.composition || {};
  const edge = numericToken(composition.edgePadding, 86);
  const panelGap = numericToken(composition.panelGap, 46);
  const radius = Math.min(8, numericToken(composition.cardRadius, 0));
  const splitRatio = Math.max(.38, Math.min(.62, numericToken(composition.splitRatio, .5)));
  const splitPct = `${Math.round(splitRatio * 10000) / 100}%`;
  const pattern=shot.motionPattern||"technical-reveal";
  const intensity = Math.max(.2, Math.min(1.2, numericToken(motion.intensity, .5)));
  const travel = 12 + intensity * 28;
  const profileEntrance = String(motion.entrance || "rise");
  const semanticTransform=pattern==="layer-build"?`translateY(${(1-inP)*travel}px)`:pattern==="evidence-scan"?`translateX(${(1-inP)*travel}px)`:pattern==="editorial-split"?`translateX(${(1-inP)*-travel}px)`:pattern==="focus-pull"?`scale(${1+.045*intensity*(1-inP)})`:`translateY(${(1-inP)*travel*.65}px)`;
  const profileTransform=profileEntrance==="slide"?`translateX(${(1-inP)*travel*.25}px)`:profileEntrance==="scale"?`scale(${.985+.015*inP})`:`translateY(${(1-inP)*travel*.18}px)`;
  const motionTransform=`${semanticTransform} ${profileTransform}`;
  return <AbsoluteFill data-qa-shot={shot.shotId} data-qa-strategy={shot.visualStrategy || (hasBackground ? "hybrid" : "motion")} style={{background: theme.background, color: theme.text, fontFamily: theme.fontBody, overflow: "hidden"}}>
    {hasBackground ? <Img data-qa-evidence="background" src={staticFile(String(shot.backgroundSource))} style={{position:"absolute",left:0,top:0,width:splitHybrid?splitPct:"100%",height:"100%",objectFit:"cover",objectPosition:shot.backgroundObjectPosition||"center"}}/> : null}
    {splitHybrid ? <div style={{position:"absolute",left:splitPct,right:0,top:0,bottom:0,background:theme.background,borderLeft:`${Math.max(4,panelGap/10)}px solid ${theme.accent}`}}/> : null}
    {hasBackground && !splitHybrid ? <AbsoluteFill style={{background:theme.effects?.useGradients===false?`${theme.background}18`:`linear-gradient(180deg,${theme.background}B0 0%,${theme.background}12 25%,transparent 65%,${theme.text}20 100%)`}}/> : null}
    <div data-qa-text-owner={overlayOwnedByMotion?"remotion":"none"} style={{position:"absolute",left:splitHybrid?`calc(${splitPct} + ${panelGap}px)`:evidenceHybrid?42:edge,right:splitHybrid?edge:undefined,top:evidenceHybrid?34:70,maxWidth:splitHybrid?`calc(${100-splitRatio*100}% - ${panelGap+edge}px)`:evidenceHybrid?620:1420,background:evidenceHybrid&&!splitHybrid?`${theme.background}EC`:"transparent",borderRadius:radius,padding:evidenceHybrid&&!splitHybrid?"12px 18px 14px":0,opacity:inP,transform:`translateY(${(1-inP)*travel*.6}px)`,zIndex:3}}>
      <div style={{height:evidenceHybrid?6:10,width:evidenceHybrid?90:150,background:theme.accent,transformOrigin:"left",transform:`scaleX(${inP})`}}/>
      <div data-qa-headline="true" style={{fontFamily:theme.fontDisplay,fontSize:evidenceHybrid?fit(words(shot.uiSpec?.headline||shot.screenCopy),44,38,32):fit(words(shot.uiSpec?.headline||shot.screenCopy),78,58,48),lineHeight:1,fontWeight:displayWeight(theme),letterSpacing:0,marginTop:evidenceHybrid?10:22,overflowWrap:"break-word"}}>{words(shot.uiSpec?.headline||shot.screenCopy)}</div>
      {!evidenceHybrid&&shot.uiSpec?.subcopy?<div data-qa-subcopy="true" style={{fontSize:30,lineHeight:1.15,fontWeight:bodyWeight(theme),marginTop:16,maxWidth:760}}>{words(shot.uiSpec.subcopy,"")}</div>:null}
    </div>
    <div data-qa-evidence-zone={shot.evidenceZone||"full"} data-qa-motion-pattern={pattern} data-qa-profile-entrance={profileEntrance} style={{position:"absolute",left:splitHybrid?`calc(${splitPct} + ${panelGap}px)`:evidenceHybrid?0:edge,right:splitHybrid?edge:evidenceHybrid?0:edge,top:splitHybrid?235:evidenceHybrid?0:245,bottom:splitHybrid?70:evidenceHybrid?0:70,opacity:inP,transform:motionTransform,transformOrigin:"center"}}>{children}</div>
  </AbsoluteFill>;
};

const Comparison: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot, theme}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const p = progressAt(frame, durationInFrames, .05, .38);
  const items = (shot.uiSpec?.items || []).slice(0, 2);
  const values = (shot.uiSpec?.values || []).slice(0, 2);
  const labels = [words(items[0] || values[0], "ESTADO INICIAL"), words(items[1] || values[1], "ESTADO FINAL")];
  if (shot.backgroundSource) {
    const hybridItems=(shot.uiSpec?.items||[]).slice(0,4);
    const hybridValues=(shot.uiSpec?.values||[]).slice(0,4);
    if (shot.reuseLeftPanel) {
      return <div style={{position:"absolute",inset:0,display:"grid",gridTemplateColumns:"1fr 1fr",overflow:"hidden"}}>
        {[0,1].map((panel)=><div key={panel} style={{position:"relative",overflow:"hidden",borderRight:panel===0?`6px solid ${theme.background}`:undefined}}>
          <Img src={staticFile(String(shot.backgroundSource))} style={{position:"absolute",left:0,top:0,width:"200%",height:"100%",objectFit:"cover",maxWidth:"none"}}/>
          <AbsoluteFill style={{background:panel===0?"rgba(30,22,18,.05)":shot.surfaceSheenRight?`linear-gradient(112deg,transparent 20%,${theme.surface}45 47%,rgba(255,255,255,.34) 54%,transparent 68%)`:"transparent",opacity:panel===0?.38:.32+.28*p,transform:panel===1?`translateX(${(1-p)*-10}%)`:undefined}}/>
          <div style={{position:"absolute",left:18,right:18,bottom:22,minHeight:78,background:panel===1?`${theme.accent}EE`:`${theme.background}EE`,color:panel===1?theme.background:theme.text,border:`1px solid ${theme.hairline||theme.accent}`,borderTop:`4px solid ${panel===1?theme.highlight:theme.accent}`,borderRadius:Number(theme.composition?.cardRadius||0),padding:"12px 16px",boxShadow:panelShadow(theme,`0 8px 20px ${theme.text}22`),opacity:p}}>
            <div style={{fontFamily:theme.fontDisplay,fontSize:fit(words(hybridItems[panel]||labels[panel]),27,24,20),lineHeight:1,fontWeight:displayWeight(theme)}}>{words(hybridItems[panel]||labels[panel])}</div>
            {hybridValues[panel]?<div style={{fontSize:16,lineHeight:1,fontWeight:bodyWeight(theme),marginTop:7,opacity:.82}}>{words(hybridValues[panel],"")}</div>:null}
          </div>
        </div>)}
      </div>;
    }
    return <div style={{position:"absolute",left:34,right:34,bottom:24,display:"grid",gridTemplateColumns:`repeat(${Math.max(1,hybridItems.length)},minmax(0,1fr))`,gap:12,alignItems:"end"}}>{hybridItems.map((item,index)=>{
      const q=interpolate(p,[index/Math.max(1,hybridItems.length),Math.min(1,(index+1)/Math.max(1,hybridItems.length))],[0,1],clamp);
      const label=words(item);
      return <div key={label+index} style={{minHeight:78,background:index===hybridItems.length-1?`${theme.accent}EE`:`${theme.background}EE`,color:index===hybridItems.length-1?theme.background:theme.text,border:`1px solid ${theme.hairline||theme.accent}`,borderTop:`4px solid ${index===hybridItems.length-1?theme.highlight:theme.accent}`,borderRadius:Number(theme.composition?.cardRadius||0),padding:"12px 16px",boxShadow:panelShadow(theme,`0 8px 20px ${theme.text}22`),opacity:q,transform:`translateY(${(1-q)*16}px)`}}><div style={{fontFamily:theme.fontDisplay,fontSize:fit(label,27,24,20),lineHeight:1,fontWeight:displayWeight(theme)}}>{label}</div>{hybridValues[index]?<div style={{fontSize:16,lineHeight:1,fontWeight:bodyWeight(theme),marginTop:7,opacity:.82}}>{words(hybridValues[index],"")}</div>:null}</div>;
    })}</div>;
  }
  return <div style={{height: "100%", display: "grid", gridTemplateColumns: "1fr 120px 1fr", alignItems: "center", gap: 28}}>
    {labels.map((label, index) => <React.Fragment key={label + index}>
      {index === 1 ? <div style={{fontSize: 82, fontWeight: displayWeight(theme), color: theme.accent, opacity: p, transform: `translateX(${(1-p)*-24}px)`}}>→</div> : null}
      <div style={{minHeight: 330, padding: "42px", display: "flex", flexDirection: "column", justifyContent: "space-between", background: index ? theme.accent : theme.text, color: index ? theme.surface : theme.background, borderTop: `12px solid ${index ? theme.highlight : theme.accent}`, opacity: p, transform: `translateX(${(1-p)*(index ? 70 : -70)}px)`}}>
        <div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:18,fontWeight:bodyWeight(theme),letterSpacing:0,color: theme.highlight}}>0{index+1}</div>
        <div>
          <div style={{fontFamily: theme.fontDisplay, fontSize: fit(label, 54, 46, 38), lineHeight: 1.02, fontWeight: displayWeight(theme)}}>{label}</div>
          {values[index] ? <div style={{fontSize: 25, lineHeight: 1.1, fontWeight: bodyWeight(theme), marginTop: 18, opacity: .86}}>{words(values[index], "")}</div> : null}
        </div>
      </div>
    </React.Fragment>)}
  </div>;
};

const Timeline: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot, theme}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const p = progressAt(frame, durationInFrames, .05, .42);
  const items = (shot.uiSpec?.items?.length ? shot.uiSpec.items : ["INICIO", "CAMBIO", "RESULTADO"]).slice(0, 4).map((item) => words(item));
  const values = (shot.uiSpec?.values || []).slice(0, 4).map((item) => words(item, ""));
  return <div style={{height: "100%", display: "flex", alignItems: "center", position: "relative"}}>
    <div style={{position: "absolute", left: 40, right: 40, top: "46%", height: 9, background: `${theme.text}25`}}/>
    <div style={{position: "absolute", left: 40, width: `calc((100% - 80px) * ${p})`, top: "46%", height: 9, background: theme.accent}}/>
    <div style={{width: "100%", display: "grid", gridTemplateColumns: `repeat(${items.length},1fr)`, gap: 18}}>{items.map((item, index) => {
      const reveal = interpolate(p, [index/items.length, Math.min(1,(index+1)/items.length)], [0, 1], clamp);
      return <div key={item+index} style={{display: "grid", justifyItems: "center", gap: 24, opacity: reveal}}>
        <div style={{width: 76, height: 76, borderRadius: "50%", background: index === items.length-1 ? theme.highlight : theme.accent, border: `12px solid ${theme.background}`, boxShadow: `0 0 0 5px ${theme.text}`}}/>
        <div style={{fontFamily: theme.fontDisplay, fontSize: fit(item, 32, 28, 23), lineHeight: 1.02, fontWeight: displayWeight(theme), textAlign: "center", maxWidth: 300}}>{item}</div>
        {values[index] ? <div style={{fontSize: 21, lineHeight: 1.05, fontWeight: bodyWeight(theme), textAlign: "center", maxWidth: 280, color: theme.accent}}>{values[index]}</div> : null}
      </div>;
    })}</div>
  </div>;
};

const ConceptFlow: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot, theme}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const p = progressAt(frame, durationInFrames, .05, .42);
  const items = (shot.uiSpec?.items?.length ? shot.uiSpec.items : [shot.uiSpec?.headline || shot.screenCopy || "CONCEPTO"]).slice(0, 4).map((item) => words(item));
  const values = (shot.uiSpec?.values || []).slice(0, 4).map((item) => words(item, ""));
  return <div style={{height:"100%",display:"grid",gridTemplateColumns:`repeat(${Math.max(1,items.length)},minmax(0,1fr))`,gap:72,alignItems:"center",padding:"50px 12px"}}>{items.map((item,index)=>{
    const q=interpolate(p,[index/items.length,Math.min(1,(index+1)/items.length)],[0,1],clamp);
    return <div key={item+index} style={{minHeight:220,position:"relative",background:index===items.length-1?theme.accent:theme.surface,border:`1px solid ${theme.hairline||theme.accent}`,borderTop:`4px solid ${index===items.length-1?theme.highlight:theme.accent}`,borderRadius:Number(theme.composition?.cardRadius||0),padding:"30px",display:"grid",alignContent:"center",opacity:q,transform:`translateY(${(1-q)*24}px)`}}><div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:18,fontWeight:bodyWeight(theme),letterSpacing:0,color:index===items.length-1?theme.highlight:theme.accent}}>0{index+1}</div><div style={{fontFamily:theme.fontDisplay,fontSize:fit(item,36,31,25),lineHeight:1,fontWeight:displayWeight(theme),letterSpacing:0,color:index===items.length-1?theme.background:theme.text,marginTop:18}}>{item}</div>{values[index]?<div style={{fontSize:19,lineHeight:1.08,fontWeight:bodyWeight(theme),marginTop:12,color:index===items.length-1?theme.background:theme.accent}}>{values[index]}</div>:null}{index<items.length-1?<div style={{position:"absolute",right:-58,top:"50%",width:44,height:2,background:theme.highlight,transform:`scaleX(${q})`,transformOrigin:"left"}}><div style={{position:"absolute",right:-2,top:-9,width:0,height:0,borderTop:"10px solid transparent",borderBottom:"10px solid transparent",borderLeft:`14px solid ${theme.highlight}`}}/></div>:null}</div>;
  })}</div>;
};

const Magnifier: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot, theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig(); const p=progressAt(frame,durationInFrames,.05,.42);
  const items=(shot.uiSpec?.items||[]).slice(0,3).map((item)=>words(item));
  return <div style={{height:"100%",display:"grid",gridTemplateColumns:".9fr 1.1fr",gap:60,alignItems:"center"}}>
    <div style={{height:430,position:"relative",pointerEvents:"none"}}><div style={{position:"absolute",left:72,top:70,width:275,height:275,borderRadius:"50%",border:`12px solid ${theme.highlight}`,boxShadow:`0 0 0 999px ${theme.background}0`,transform:`translate(${(1-p)*-100}px,${(1-p)*54}px) scale(${.92+.08*p})`}}/><div style={{position:"absolute",left:315,top:322,width:150,height:18,background:theme.highlight,transform:`rotate(45deg) scaleX(${p})`,transformOrigin:"left"}}/></div>
    <div style={{display:"grid",gap:18}}>{(items.length?items:["PROMESA","USO","LÍMITE"]).map((item,index)=>{const q=interpolate(p,[index*.18,Math.min(1,index*.18+.35)],[0,1],clamp);return <div key={item+index} style={{minHeight:105,background:index===0?theme.text:theme.surface,color:index===0?theme.background:theme.text,borderLeft:`12px solid ${index===0?theme.highlight:theme.accent}`,padding:"22px 28px",fontFamily:theme.fontDisplay,fontSize:fit(item,38,33,28),lineHeight:1.02,fontWeight:displayWeight(theme),display:"flex",alignItems:"center",opacity:q,transform:`translateX(${(1-q)*30}px)`}}>{item}</div>})}</div>
  </div>;
};

const ProtocolFrame: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot, theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig(); const p=progressAt(frame,durationInFrames,.04,.40);
  const items=(shot.uiSpec?.items||["LUZ FIJA","DISTANCIA","POSTURA"]).slice(0,4).map((item)=>words(item));
  const values=(shot.uiSpec?.values||["45°","2,0 M","MISMA MARCA"]).slice(0,4).map((item)=>words(item,""));
  return <div style={{height:"100%",display:"grid",gridTemplateColumns:"1.3fr .7fr",gap:42,alignItems:"center"}}>
    <div data-qa-semantic="camera-protocol" style={{height:460,position:"relative",background:theme.text,border:`1px solid ${theme.hairline||theme.surface}`,borderRadius:Number(theme.composition?.cardRadius||0),boxShadow:panelShadow(theme,`0 22px 50px ${theme.text}28`),overflow:"hidden"}}>
      <div style={{position:"absolute",left:90,top:116,width:142,height:94,borderRadius:8,background:theme.surface,border:`6px solid ${theme.accent}`,opacity:p}}>
        <div style={{position:"absolute",right:18,top:17,width:50,height:50,borderRadius:"50%",border:`8px solid ${theme.text}`}}/>
        <div style={{position:"absolute",left:20,top:-26,width:64,height:28,background:theme.surface,border:`5px solid ${theme.accent}`}}/>
      </div>
      <div style={{position:"absolute",left:155,top:210,width:8,height:142,background:theme.surface,transform:`scaleY(${p})`,transformOrigin:"top"}}/>
      <div style={{position:"absolute",left:159,top:332,width:8,height:118,background:theme.surface,transform:"rotate(24deg)",transformOrigin:"top"}}/><div style={{position:"absolute",left:159,top:332,width:8,height:118,background:theme.surface,transform:"rotate(-24deg)",transformOrigin:"top"}}/>
      <div style={{position:"absolute",left:330,top:104,width:220,height:165,clipPath:"polygon(0 38%,100% 0,100% 100%,0 62%)",background:`${theme.highlight}55`,opacity:p}}/>
      <div style={{position:"absolute",right:168,top:80,width:78,height:78,borderRadius:"50%",background:theme.highlight,border:`6px solid ${theme.surface}`,opacity:p}}/>
      <div style={{position:"absolute",right:126,top:154,width:164,height:194,borderRadius:"72px 72px 20px 20px",background:theme.accent,border:`6px solid ${theme.surface}`,opacity:p}}/>
      <div style={{position:"absolute",left:248,right:238,bottom:70,height:5,background:theme.highlight,transform:`scaleX(${p})`,transformOrigin:"left"}}/>
      <div style={{position:"absolute",left:342,bottom:36,color:theme.surface,fontSize:20,fontWeight:displayWeight(theme)}}>2,0 M · MISMO PUNTO</div>
      <div style={{position:"absolute",right:62,top:52,color:theme.surface,fontSize:20,fontWeight:displayWeight(theme)}}>SUJETO CENTRADO</div>
    </div>
    <div style={{display:"grid",gap:16}}>{items.map((item,index)=>{const q=interpolate(p,[index*.16,Math.min(1,index*.16+.3)],[0,1],clamp);return <div key={item+index} style={{background:index===items.length-1?theme.accent:theme.surface,borderLeft:`10px solid ${index===items.length-1?theme.highlight:theme.accent}`,padding:"20px 24px",opacity:q,transform:`translateX(${(1-q)*28}px)`}}><div style={{fontFamily:theme.fontDisplay,fontSize:27,fontWeight:displayWeight(theme),color:index===items.length-1?theme.background:theme.text}}>{item}</div>{values[index]?<div style={{fontSize:20,fontWeight:bodyWeight(theme),marginTop:7,color:index===items.length-1?theme.background:theme.accent}}>{values[index]}</div>:null}</div>})}</div>
  </div>;
};

const AnatomyCrossSection: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig(); const p=progressAt(frame,durationInFrames,.04,.40);
  const items=(shot.uiSpec?.items||["CREMA","PIEL","GRASA SUBCUTÁNEA"]).slice(0,3).map((item)=>words(item));
  const values=(shot.uiSpec?.values||["SUPERFICIE","BARRERA","SIN CAMBIO"]).slice(0,3).map((item)=>words(item,""));
  return <div style={{height:"100%",display:"grid",gridTemplateColumns:"1.15fr .85fr",gap:54,alignItems:"center"}}>
    <div style={{height:470,position:"relative",border:`1px solid ${theme.hairline||theme.text}`,borderRadius:Number(theme.composition?.cardRadius||0),background:theme.surface,overflow:"hidden",boxShadow:panelShadow(theme,`0 22px 45px ${theme.text}20`)}}>
      <div style={{position:"absolute",left:0,right:0,top:18,height:42,background:theme.surface,borderBottom:`5px solid ${theme.text}`,transform:`scaleX(${p})`,transformOrigin:"left"}}/>
      <div style={{position:"absolute",left:0,right:0,top:64,height:108,background:semanticColor(theme,"skinSurface","#D6A18A"),borderBottom:`5px solid ${theme.text}`,opacity:p}}/>
      <div style={{position:"absolute",left:0,right:0,top:177,height:118,background:semanticColor(theme,"skinDeep","#B97562"),borderBottom:`5px solid ${theme.text}`,opacity:p}}/>
      <div style={{position:"absolute",left:0,right:0,top:300,bottom:0,background:semanticColor(theme,"fat","#D2A548"),opacity:p}}/>
      {Array.from({length:8}).map((_,index)=>{const x=38+(index%4)*172; const y=325+Math.floor(index/4)*72; return <div key={index} style={{position:"absolute",left:x,top:y,width:122,height:64,borderRadius:"50%",background:index%2?theme.highlight:semanticColor(theme,"fat","#D2A548"),border:`4px solid ${theme.text}`,transform:`scale(${.55+.45*p})`,opacity:p}}/>})}
      <div style={{position:"absolute",left:44,top:4,fontSize:22,fontWeight:displayWeight(theme),color:theme.accent}}>CAPA TÓPICA</div>
      <div style={{position:"absolute",left:44,top:110,fontSize:25,fontWeight:displayWeight(theme)}}>BARRERA CUTÁNEA</div>
      <div style={{position:"absolute",left:44,top:225,fontSize:25,fontWeight:displayWeight(theme)}}>DERMIS</div>
      <div style={{position:"absolute",left:44,bottom:28,fontSize:25,fontWeight:displayWeight(theme)}}>TEJIDO SUBCUTÁNEO</div>
    </div>
    <div style={{display:"grid",gap:18}}>{items.map((item,index)=>{const q=interpolate(p,[index*.16,Math.min(1,index*.16+.3)],[0,1],clamp);return <div key={item+index} style={{padding:"22px 26px",background:index===2?theme.text:theme.surface,color:index===2?theme.background:theme.text,borderLeft:`10px solid ${index===2?theme.highlight:theme.accent}`,opacity:q,transform:`translateX(${(1-q)*28}px)`}}><div style={{fontFamily:theme.fontDisplay,fontSize:fit(item,31,27,23),fontWeight:displayWeight(theme)}}>{item}</div>{values[index]?<div style={{fontSize:20,fontWeight:bodyWeight(theme),marginTop:8,color:index===2?theme.highlight:theme.accent}}>{values[index]}</div>:null}</div>})}</div>
  </div>;
};

const BodyDistinction: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig(); const p=progressAt(frame,durationInFrames,.04,.40);
  const items=(shot.uiSpec?.items||["PIEL","HINCHAZÓN","GRASA"]).slice(0,3).map((item)=>words(item));
  const values=(shot.uiSpec?.values||["SUPERFICIE","TEMPORAL","SUBCUTÁNEA"]).slice(0,3).map((item)=>words(item,""));
  return <div data-qa-semantic="skin-swelling-fat" style={{height:"100%",display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:28,alignItems:"center"}}>{items.map((item,index)=>{const q=interpolate(p,[index*.15,Math.min(1,index*.15+.34)],[0,1],clamp);return <div key={item+index} style={{height:430,background:index===1?theme.accent:theme.surface,color:index===1?theme.background:theme.text,borderTop:`10px solid ${index===2?theme.highlight:theme.accent}`,padding:"26px",display:"grid",gridTemplateRows:"1fr auto",gap:18,opacity:q,transform:`translateY(${(1-q)*30}px)`}}>
    <div style={{position:"relative",display:"grid",placeItems:"center",overflow:"hidden"}}>
      {index===0?<div style={{width:"82%",height:210,position:"relative"}}><div style={{position:"absolute",left:0,right:0,top:30,height:24,background:semanticColor(theme,"skinSurface","#D6A18A"),border:`4px solid ${theme.text}`}}/><div style={{position:"absolute",left:0,right:0,top:58,height:62,background:semanticColor(theme,"tissue","#C98C75"),borderLeft:`4px solid ${theme.text}`,borderRight:`4px solid ${theme.text}`,borderBottom:`4px solid ${theme.text}`}}/><div style={{position:"absolute",left:0,right:0,top:124,height:72,background:semanticColor(theme,"skinDeep","#B97562"),border:`4px solid ${theme.text}`}}/><div style={{position:"absolute",left:42,right:42,top:8,height:10,background:theme.highlight,transform:`scaleX(${p})`}}/></div>:null}
      {index===1?<div style={{width:"82%",height:220,position:"relative"}}><div style={{position:"absolute",left:20,right:20,top:24,height:28,background:semanticColor(theme,"skinSurface","#D6A18A"),border:`4px solid ${theme.background}`}}/><div style={{position:"absolute",left:12,right:12,top:56,height:112,borderRadius:"22px 22px 46% 46%",background:semanticColor(theme,"fluid","#6F9FA3"),border:`5px solid ${theme.background}`,transform:`scaleX(${.86+.14*Math.sin(frame/8)})`}}/><div style={{position:"absolute",left:0,top:94,fontSize:52,fontWeight:displayWeight(theme)}}>←</div><div style={{position:"absolute",right:0,top:94,fontSize:52,fontWeight:displayWeight(theme)}}>→</div><div style={{position:"absolute",left:45,right:45,bottom:18,textAlign:"center",fontSize:18,fontWeight:displayWeight(theme)}}>VOLUMEN TEMPORAL</div></div>:null}
      {index===2?<div style={{width:"86%",height:224,position:"relative",background:semanticColor(theme,"skinDeep","#B97562"),border:`4px solid ${theme.text}`,padding:"74px 18px 16px"}}><div style={{position:"absolute",left:0,right:0,top:0,height:34,background:semanticColor(theme,"skinSurface","#D6A18A"),borderBottom:`4px solid ${theme.text}`}}><span style={{position:"absolute",left:14,top:4,fontSize:15,fontWeight:displayWeight(theme)}}>PIEL</span></div><div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:7}}>{Array.from({length:12}).map((_,i)=><div key={i} style={{height:46,borderRadius:"48% 52% 44% 56%",background:i%2?semanticColor(theme,"fat","#D2A548"):theme.highlight,border:`3px solid ${theme.text}`,transform:`scale(${.72+.28*p})`}}/>)}</div></div>:null}
    </div>
    <div><div style={{fontFamily:theme.fontDisplay,fontSize:fit(item,34,29,25),fontWeight:displayWeight(theme)}}>{item}</div>{values[index]?<div style={{fontSize:21,fontWeight:bodyWeight(theme),marginTop:8,color:index===1?theme.background:theme.accent}}>{values[index]}</div>:null}</div>
  </div>})}</div>;
};

const ClaimDecision: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig(); const p=progressAt(frame,durationInFrames,.04,.40);
  const values=(shot.uiSpec?.values||["REDUCE CENTÍMETROS","NO REDUCE GRASA","NO COMPRES"]).slice(0,3).map((item)=>words(item,""));
  if(shot.backgroundSource) return <div style={{height:"100%",display:"grid",gridTemplateRows:"repeat(3,minmax(0,1fr))",gap:14,alignContent:"center"}}>
    <div style={{position:"relative",background:`${theme.text}14`,border:`1px solid ${theme.hairline||theme.danger}`,borderLeft:`4px solid ${theme.danger}`,borderRadius:Number(theme.composition?.cardRadius||0),padding:"18px 24px",display:"grid",alignContent:"center",opacity:p}}><div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:14,fontWeight:bodyWeight(theme),letterSpacing:0,color:theme.danger}}>PROMESA</div><div style={{fontFamily:theme.fontDisplay,fontSize:fit(values[0],32,27,23),lineHeight:1,fontWeight:displayWeight(theme),letterSpacing:0,marginTop:8}}>{values[0]}</div><div style={{position:"absolute",left:20,right:20,top:"58%",height:4,background:theme.danger,transform:`rotate(-3deg) scaleX(${p})`,transformOrigin:"left"}}/></div>
    <div style={{background:theme.surface,border:`1px solid ${theme.hairline||theme.accent}`,borderLeft:`4px solid ${theme.accent}`,borderRadius:Number(theme.composition?.cardRadius||0),padding:"18px 24px",display:"grid",alignContent:"center",opacity:p,transform:`translateX(${(1-p)*22}px)`}}><div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:14,fontWeight:bodyWeight(theme),letterSpacing:0,color:theme.accent}}>EVIDENCIA</div><div style={{fontFamily:theme.fontDisplay,fontSize:fit(values[1],32,27,23),lineHeight:1,fontWeight:displayWeight(theme),letterSpacing:0,marginTop:8}}>{values[1]}</div></div>
    <div style={{background:theme.accent,color:theme.background,border:`1px solid ${theme.hairline||theme.highlight}`,borderLeft:`4px solid ${theme.highlight}`,borderRadius:Number(theme.composition?.cardRadius||0),padding:"18px 24px",display:"grid",gridTemplateColumns:"48px 1fr",alignItems:"center",gap:10,opacity:p,transform:`translateX(${(1-p)*22}px)`}}><div style={{fontSize:32,fontWeight:displayWeight(theme)}}>✓</div><div><div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:14,fontWeight:bodyWeight(theme),letterSpacing:0,color:theme.highlight}}>DECISIÓN</div><div style={{fontFamily:theme.fontDisplay,fontSize:fit(values[2],32,27,23),lineHeight:1,fontWeight:displayWeight(theme),letterSpacing:0,marginTop:8}}>{values[2]}</div></div></div>
  </div>;
  return <div style={{height:"100%",display:"grid",gridTemplateColumns:".9fr 1.1fr",gap:46,alignItems:"center"}}>
    <div style={{height:390,background:theme.text,color:theme.background,padding:"40px",display:"grid",alignContent:"center",position:"relative",opacity:interpolate(p,[0,.65],[1,.48],clamp),transform:`scale(${1-.06*p})`}}>
      <div style={{fontSize:22,fontWeight:displayWeight(theme),color:theme.highlight}}>CLAIM EXAGERADO</div><div style={{fontFamily:theme.fontDisplay,fontSize:fit(values[0],58,49,40),lineHeight:1,fontWeight:displayWeight(theme),marginTop:24}}>{values[0]}</div>
      <div style={{position:"absolute",left:34,right:34,top:"52%",height:15,background:theme.danger,transform:`rotate(-7deg) scaleX(${p})`,transformOrigin:"left"}}/>
    </div>
    <div style={{display:"grid",gap:18}}>
      <div style={{fontSize:22,fontWeight:displayWeight(theme),color:theme.accent}}>EVIDENCIA MEDIDA</div>
      <div style={{padding:"30px 34px",background:theme.surface,borderLeft:`12px solid ${theme.accent}`,fontFamily:theme.fontDisplay,fontSize:fit(values[1],42,36,30),fontWeight:displayWeight(theme),opacity:p,transform:`translateX(${(1-p)*32}px)`}}>{values[1]}</div>
      <div style={{padding:"34px",background:theme.accent,color:theme.background,borderLeft:`12px solid ${theme.highlight}`,fontFamily:theme.fontDisplay,fontSize:fit(values[2],52,44,36),fontWeight:displayWeight(theme),opacity:p,transform:`scale(${.88+.12*p})`}}>✓ {values[2]}</div>
    </div>
  </div>;
};

const SafetySequence: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig(); const p=progressAt(frame,durationInFrames,.04,.40);
  const items=(shot.uiSpec?.items||["APLICA","OBSERVA","IRRITA","SUSPENDE"]).slice(0,4).map((item)=>words(item));
  const values=(shot.uiSpec?.values||["USO","REVISA","ROJEZ","APARTA"]).slice(0,4).map((item)=>words(item,""));
  const icon=(index:number,q:number)=>{
    if(index===0)return <div style={{width:66,height:44,border:`5px solid ${theme.text}`,borderRadius:"8px 8px 18px 18px",position:"relative"}}><div style={{position:"absolute",left:23,top:-22,width:18,height:18,borderRadius:"50%",background:theme.surface,border:`4px solid ${theme.accent}`,transform:`scale(${.7+.3*q})`}}/></div>;
    if(index===1)return <div style={{width:74,height:42,border:`6px solid ${theme.text}`,borderRadius:"50%",display:"grid",placeItems:"center"}}><div style={{width:20,height:20,borderRadius:"50%",background:theme.accent,transform:`scale(${.7+.3*q})`}}/></div>;
    if(index===2)return <div style={{width:62,height:62,borderRadius:"50%",background:`${theme.danger}55`,border:`6px solid ${theme.danger}`,boxShadow:`0 0 0 ${12*q}px ${theme.danger}22`}}/>;
    return <div style={{width:76,height:58,position:"relative"}}><div style={{position:"absolute",left:0,top:14,width:42,height:38,border:`5px solid ${theme.text}`,borderRadius:8}}/><div style={{position:"absolute",right:0,top:22,fontSize:42,fontWeight:displayWeight(theme),color:theme.highlight,transform:`translateX(${(1-q)*-18}px)`}}>→</div></div>;
  };
  return <div style={{height:"100%",display:"flex",alignItems:"end",paddingBottom:18}}><div style={{width:"100%",display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,background:`${theme.background}D8`,padding:12,borderTop:`5px solid ${theme.text}`}}>{items.map((item,index)=>{const q=interpolate(p,[index*.15,Math.min(1,index*.15+.28)],[0,1],clamp);return <div key={item+index} style={{minHeight:112,background:index===3?`${theme.danger}F0`:`${theme.surface}F0`,color:index===3?theme.background:theme.text,borderTop:`6px solid ${index===2?theme.danger:index===3?theme.highlight:theme.accent}`,padding:"12px 16px",display:"grid",gridTemplateColumns:"82px 1fr",alignItems:"center",gap:10,opacity:q,transform:`translateY(${(1-q)*18}px)`}}>{icon(index,q)}<div><div style={{fontFamily:theme.fontDisplay,fontSize:fit(item,27,24,21),fontWeight:displayWeight(theme)}}>{item}</div>{values[index]?<div style={{fontSize:15,fontWeight:bodyWeight(theme),marginTop:5}}>{values[index]}</div>:null}</div></div>})}</div></div>;
};

const AdvancedField: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig(); const p=progressAt(frame,durationInFrames,.04,.9);
  const items=(shot.uiSpec?.items?.length?shot.uiSpec.items:["SEÑAL","CAMBIO","RESULTADO"]).slice(0,3).map((item)=>words(item));
  return <div style={{height:"100%",position:"relative",display:"grid",placeItems:"center",perspective:1100}}>
    <div style={{width:1040,height:420,position:"relative",transformStyle:"preserve-3d",transform:`rotateX(${58-8*p}deg) rotateZ(${-14+10*p}deg)`}}>{items.map((item,index)=>{const q=interpolate(p,[index*.18,Math.min(1,index*.18+.45)],[0,1],clamp);return <div key={item+index} style={{position:"absolute",left:110+index*260,top:100+index*22,width:280,height:180,background:index===2?theme.highlight:index===1?theme.accent:theme.text,color:index===0?theme.background:theme.text,border:`1px solid ${theme.hairline||theme.surface}`,borderRadius:Number(theme.composition?.cardRadius||0),boxShadow:panelShadow(theme,`0 30px 55px ${theme.text}35`),display:"grid",placeItems:"center",fontFamily:theme.fontDisplay,fontSize:29,fontWeight:displayWeight(theme),opacity:q,transform:`translate3d(0,${(1-q)*80}px,${index*70*q}px)`}}>{item}</div>})}</div>
  </div>;
};

const ThreeField: React.FC<{shot: LongformShot; theme: LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig();
  const p=progressAt(frame,durationInFrames,.04,.88);
  const rotation=(p-.5)*.5;
  const labels=(shot.uiSpec?.items?.length?shot.uiSpec.items:["ESTADO A","TRANSICIÓN","ESTADO B"]).slice(0,3).map((item)=>words(item));
  return <div style={{height:"100%",position:"relative"}}>
    <ThreeCanvas width={1660} height={690} camera={{position:[0,1.4,8.2],fov:42}} style={{position:"absolute",inset:0}}>
      <ambientLight intensity={1.7}/><directionalLight position={[4,6,5]} intensity={2.3}/>
      <group rotation={[.12,rotation,0]} position={[0,-.25,0]}>
        {[-1,0,1].map((slot,index)=>{
          const q=interpolate(p,[index*.2,Math.min(1,index*.2+.38)],[0,1],clamp);
          const color=[theme.text,theme.accent,theme.highlight][index];
          return <group key={slot} position={[slot*2.45,(q-1)*1.3,index*.18]}>
            <mesh><boxGeometry args={[2.05,1.35,.32]}/><meshStandardMaterial color={color} roughness={.46} metalness={.08}/></mesh>
            <mesh position={[0,-.9,0]} scale={[q,1,1]}><boxGeometry args={[1.8,.08,.08]}/><meshStandardMaterial color={theme.surface}/></mesh>
          </group>;
        })}
      </group>
    </ThreeCanvas>
    <div style={{position:"absolute",left:150,right:150,bottom:42,display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:50}}>{labels.map((label,index)=><div key={label+index} style={{fontFamily:theme.fontDisplay,fontSize:27,fontWeight:displayWeight(theme),textAlign:"center",color:index===1?theme.accent:theme.text}}>{label}</div>)}</div>
  </div>;
};

export const MotionGraphics: React.FC<{shot:LongformShot;brand:LongformProps["brand"];theme:LongformTheme;designProfile?:LongformDesignProfile}> = ({shot,brand,theme,designProfile}) => {
  const resolved: LongformTheme = theme || {background:brand.cream,surface:"#FFFFFF",text:brand.ink,accent:brand.teal,highlight:brand.gold,danger:brand.red,fontDisplay:brand.fontDisplay||'"Inter", Arial, sans-serif',fontBody:brand.fontBody||'"Inter", Arial, sans-serif'};
  const primitive=shot.motionSpec?.visualPrimitive || (shot.uiSpec?.template==="comparison"?"comparison":shot.uiSpec?.template==="timeline"?"timeline":shot.uiSpec?.template==="product-label"?"magnifier":"diagram");
  let body:React.ReactNode;
  const SemanticV2=shot.rendererVersion==="semantic-v2"?semanticV2ComponentFor(shot):null;
  if(SemanticV2) body=<SemanticV2 shot={shot} theme={resolved}/>;
  else if(shot.uiSpec?.variant==="protocol-diagram") body=<ProtocolFrame shot={shot} theme={resolved}/>;
  else if(shot.uiSpec?.variant==="claim-evidence") body=<ClaimDecision shot={shot} theme={resolved}/>;
  else if(shot.uiSpec?.variant==="safety-sequence") body=<SafetySequence shot={shot} theme={resolved}/>;
  else if(shot.uiSpec?.template==="body-distinction") body=<BodyDistinction shot={shot} theme={resolved}/>;
  else if(shot.uiSpec?.template==="anatomy-explainer") body=<AnatomyCrossSection shot={shot} theme={resolved}/>;
  else if(primitive==="comparison"||shot.uiSpec?.template==="comparison") body=<Comparison shot={shot} theme={resolved}/>;
  else if(primitive==="timeline"||primitive==="process"||["process-steps","procedure","safety-sequence"].includes(String(shot.uiSpec?.template||""))) body=<Timeline shot={shot} theme={resolved}/>;
  else if(primitive==="magnifier"||["product-label","product-inspection"].includes(String(shot.uiSpec?.template||""))) body=<Magnifier shot={shot} theme={resolved}/>;
  else if(primitive==="three_scene") body=<ThreeField shot={shot} theme={resolved}/>;
  else if(primitive==="particles") body=<AdvancedField shot={shot} theme={resolved}/>;
  else if(["concept","mechanism","evaluation-dashboard"].includes(String(shot.uiSpec?.template||""))||primitive==="editorial"||primitive==="diagram"||primitive==="chart") body=<ConceptFlow shot={shot} theme={resolved}/>;
  else throw new Error(`Unsupported semantic motion graphic: ${shot.shotId} template=${shot.uiSpec?.template||""} primitive=${primitive}`);
  return <Shell shot={shot} theme={resolved} designProfile={designProfile}>{body}</Shell>;
};

