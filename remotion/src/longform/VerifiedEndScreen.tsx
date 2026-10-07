import React from "react";
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import type {LongformEndScreen, LongformTheme} from "../longform-types";

const clamp={extrapolateLeft:"clamp",extrapolateRight:"clamp"} as const;
const displayWeight=(theme:LongformTheme)=>Number(theme.typography?.displayWeight||900);
const labelWeight=(theme:LongformTheme)=>Number(theme.typography?.labelWeight||800);
const panelShadow=(theme:LongformTheme,fallback:string)=>theme.effects?.useShadows===false?"none":fallback;
export const VerifiedEndScreen:React.FC<{endScreen:LongformEndScreen;theme:LongformTheme}> = ({endScreen,theme}) => {
  const frame=useCurrentFrame(); const {durationInFrames,width,height}=useVideoConfig();
  const scale=Math.min(width/1920,height/1080);
  const u=(value:number)=>Math.round(value*scale);
  const p=interpolate(frame,[0,Math.min(18,durationInFrames*.25)],[0,1],clamp);
  const line=interpolate(frame,[4,Math.min(42,durationInFrames*.55)],[0,1],clamp);
  const hasThumbnail=Boolean(endScreen.thumbnailSrc);
  const titleSize=endScreen.targetVideoTitle.length>54?u(52):endScreen.targetVideoTitle.length>34?u(60):u(68);
  return <AbsoluteFill style={{zIndex:1000,background:theme.background,color:theme.text,fontFamily:theme.fontBody,padding:`${u(84)}px ${u(98)}px`,overflow:"hidden"}}>
    <div style={{height:u(11),width:u(220),background:theme.accent,transformOrigin:"left",transform:`scaleX(${line})`}}/>
    <div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:u(22),fontWeight:labelWeight(theme),letterSpacing:0,color:theme.accent,marginTop:u(24)}}>SIGUIENTE VIDEO</div>
    <div style={{display:"grid",gridTemplateColumns:hasThumbnail?".92fr 1.08fr":"1fr",gap:u(62),alignItems:"center",marginTop:u(30),height:u(690)}}>
      <div style={{alignSelf:"center",opacity:p,transform:`translateX(${(1-p)*-u(30)}px)`}}>
        <div style={{fontFamily:theme.fontDisplay,fontSize:titleSize,lineHeight:1.01,fontWeight:displayWeight(theme),letterSpacing:0,maxWidth:u(820),overflowWrap:"break-word"}}>{endScreen.targetVideoTitle}</div>
        <div style={{display:"flex",alignItems:"center",gap:u(18),marginTop:u(42),fontFamily:theme.fontMono||theme.fontBody,fontSize:u(20),fontWeight:labelWeight(theme),letterSpacing:0,color:theme.body||theme.accent}}><span style={{display:"block",width:u(72),height:u(2),background:theme.highlight,transformOrigin:"left",transform:`scaleX(${line})`}}/>CONTINÚA CON EL SIGUIENTE PASO</div>
      </div>
      {hasThumbnail?<div data-qa-verified-thumbnail="true" style={{position:"relative",aspectRatio:"16 / 9",background:theme.text,boxShadow:panelShadow(theme,`0 ${u(24)}px ${u(58)}px ${theme.text}30`),opacity:p,transform:`translateX(${(1-p)*u(34)}px) scale(${.97+.03*p})`,overflow:"hidden",border:`1px solid ${theme.hairline||theme.highlight}`,borderTop:`${u(4)}px solid ${theme.highlight}`,borderRadius:Number(theme.composition?.cardRadius||0)}}>
        <Img src={staticFile(String(endScreen.thumbnailSrc))} style={{width:"100%",height:"100%",objectFit:"cover"}}/>
        <div style={{position:"absolute",left:u(24),bottom:u(22),background:`${theme.text}E8`,color:theme.background,border:`1px solid ${theme.hairline||theme.background}`,borderRadius:9999,padding:`${u(12)}px ${u(18)}px`,fontFamily:theme.fontDisplay,fontSize:u(22),fontWeight:displayWeight(theme),letterSpacing:0}}>MÍRALO AHORA&nbsp; →</div>
      </div>:<div style={{height:u(320),background:theme.surface,color:theme.text,border:`1px solid ${theme.hairline||theme.highlight}`,borderTop:`${u(4)}px solid ${theme.highlight}`,borderRadius:Number(theme.composition?.cardRadius||0),display:"grid",placeItems:"center",fontFamily:theme.fontDisplay,fontSize:u(38),lineHeight:1.05,fontWeight:displayWeight(theme),letterSpacing:0,textAlign:"center",padding:u(42),opacity:p}}>MÍRALO AHORA&nbsp; →</div>}
    </div>
  </AbsoluteFill>;
};
