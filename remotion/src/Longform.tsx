import React from "react";
import {AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import type {LongformProps, LongformShot, LongformTheme} from "./longform-types";
import {VerifiedEndScreen} from "./longform/VerifiedEndScreen";
import {MotionGraphics} from "./longform/MotionGraphics";

const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;
const short = (value: unknown, fallback = "") => {
  const clean = String(value || "").replace(/\s+/g, " ").trim();
  return clean || fallback;
};
const fit = (value:string, large:number, medium:number, small:number) => value.length > 36 ? small : value.length > 22 ? medium : large;
const displayWeight=(theme:LongformTheme)=>Number(theme.typography?.displayWeight||900);
const bodyWeight=(theme:LongformTheme)=>Number(theme.typography?.bodyWeight||700);
const labelWeight=(theme:LongformTheme)=>Number(theme.typography?.labelWeight||800);
const panelShadow=(theme:LongformTheme,fallback:string)=>theme.effects?.useShadows===false?"none":fallback;
const labelsUppercase=(theme:LongformTheme)=>theme.typography?.uppercaseLabels===false?"none":"uppercase";

const Media: React.FC<{shot:LongformShot;hook?:boolean}> = ({shot,hook=false}) => {
  const frame=useCurrentFrame(); const {fps}=useVideoConfig();
  const src=String(shot.source||"");
  if(!src) return <AbsoluteFill style={{background:"#000"}}/>;
  const style:React.CSSProperties={width:"100%",height:"100%",objectFit:"cover",objectPosition:shot.backgroundObjectPosition||"center"};
  if(shot.mediaType==="video") return <OffthreadVideo src={staticFile(src)} muted startFrom={Math.round((shot.sourceInMs||0)/1000*fps)} endAt={(shot.sourceOutMs||0)>(shot.sourceInMs||0)?Math.round((shot.sourceOutMs||0)/1000*fps):undefined} style={style}/>;
  const scale=hook?interpolate(frame,[0,90,220],[1.01,1.12,1.16],clamp):interpolate(frame,[0,180],[1.01,1.065],clamp);
  return <Img src={staticFile(src)} style={{...style,transform:`scale(${scale})`}}/>;
};

const protectedPosition = (shot:LongformShot):React.CSSProperties => {
  const zone=shot.motionSpec?.safeZone||"auto";
  if(zone==="right") return {right:64,top:64};
  if(zone==="bottom") return {left:64,bottom:64};
  if(zone==="top") return {left:64,top:64};
  if(zone==="left") return {left:64,top:64};
  return String(shot.backgroundObjectPosition||"").includes("left")?{right:64,top:64}:{left:64,top:64};
};

const MediaCallout:React.FC<{shot:LongformShot;theme:LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const {fps}=useVideoConfig();
  const p=spring({frame,fps,config:{damping:18,stiffness:120,mass:.8}});
  if(shot.suppressScreenCopy) return null;
  const items=(shot.evidenceOverlayItems||[]).slice(0,3).map((item)=>short(item)).filter(Boolean);
  const headline=short(shot.evidenceOverlayHeadline||shot.screenCopy);
  if(!headline&&!items.length) return null;
  return <div style={{position:"absolute",...protectedPosition(shot),width:Math.min(530,Math.max(360,headline.length*24)),maxWidth:"30%",background:`${theme.background}F2`,color:theme.text,border:`1px solid ${theme.hairline||theme.accent}`,borderLeft:`4px solid ${theme.accent}`,borderRadius:Number(theme.composition?.cardRadius||0),padding:"20px 24px",boxShadow:panelShadow(theme,`0 16px 34px ${theme.text}35`),fontFamily:theme.fontBody,opacity:p,transform:`translateY(${(1-p)*20}px)`}}>
    {headline?<div style={{fontFamily:theme.fontDisplay,fontSize:fit(headline,38,32,27),lineHeight:1,fontWeight:displayWeight(theme),letterSpacing:0,overflowWrap:"anywhere"}}>{headline}</div>:null}
    {items.length?<div style={{display:"grid",gap:9,marginTop:16}}>{items.map((item,index)=>{const q=interpolate(frame,[8+index*6,18+index*6],[0,1],clamp);return <div key={item+index} style={{display:"grid",gridTemplateColumns:"38px 1fr",alignItems:"center",gap:10,fontSize:22,fontWeight:bodyWeight(theme),textTransform:labelsUppercase(theme),opacity:q}}><span style={{color:theme.accent,fontFamily:theme.fontMono||theme.fontBody,fontWeight:labelWeight(theme),letterSpacing:0}}>0{index+1}</span><span>{item}</span></div>})}</div>:null}
  </div>;
};

const TextCard:React.FC<{shot:LongformShot;theme:LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const {fps}=useVideoConfig(); const p=spring({frame,fps,config:{damping:18,stiffness:115,mass:.8}});
  return <AbsoluteFill style={{background:theme.background,color:theme.text,fontFamily:theme.fontBody,display:"grid",placeItems:"center"}}>
    <div style={{width:1320,border:`1px solid ${theme.hairline || '#3b4b58'}`,borderRadius:12,padding:"44px 54px",opacity:p,transform:`translateY(${(1-p)*34}px)`}}>
      <div style={{fontFamily:theme.fontDisplay,fontSize:fit(short(shot.screenCopy,"PUNTO CLAVE"),76,64,52),lineHeight:1,fontWeight:displayWeight(theme),letterSpacing:0}}>{short(shot.screenCopy,"PUNTO CLAVE")}</div>
      {shot.subcopy?<div style={{fontSize:32,lineHeight:1.15,fontWeight:bodyWeight(theme),color:theme.body||theme.text,marginTop:20}}>{short(shot.subcopy)}</div>:null}
    </div>
  </AbsoluteFill>;
};

const AvatarFull:React.FC<{shot:LongformShot;theme:LongformTheme}> = ({shot,theme}) => {
  const frame=useCurrentFrame(); const p=interpolate(frame,[0,12],[0,1],clamp);
  return <AbsoluteFill style={{background:theme.background,padding:22}}>
    <div style={{position:"absolute",inset:22,overflow:"hidden",background:"#000",border:`5px solid ${theme.background}`,boxShadow:`inset 0 0 0 8px ${theme.accent}`}}><Media shot={shot}/><AbsoluteFill style={{boxShadow:"inset 0 -150px 120px -110px rgba(0,0,0,.7)"}}/></div>
    {shot.screenCopy?<div style={{position:"absolute",left:70,bottom:62,maxWidth:980,color:theme.background,fontFamily:theme.fontDisplay,fontSize:fit(short(shot.screenCopy),40,35,30),lineHeight:1.02,fontWeight:displayWeight(theme),letterSpacing:0,opacity:p,textShadow:theme.effects?.useShadows===false?"none":"0 3px 16px rgba(0,0,0,.9)"}}>{short(shot.screenCopy)}</div>:null}
  </AbsoluteFill>;
};

const ShotView:React.FC<{shot:LongformShot;props:LongformProps}> = ({shot,props}) => {
  if(shot.visualKind==="ui-card") return <MotionGraphics shot={shot} brand={props.brand} theme={props.theme} designProfile={props.designProfile}/>;
  if(shot.visualKind==="motion-card") return <TextCard shot={shot} theme={props.theme}/>;
  if(shot.visualKind==="avatar-full") return <AvatarFull shot={shot} theme={props.theme}/>;
  return <AbsoluteFill style={{background:props.theme.background,overflow:"hidden"}}><Media shot={shot} hook={shot.startMs===0}/><AbsoluteFill style={{background:props.theme.effects?.useGradients===false?"rgba(0,0,0,.08)":"linear-gradient(180deg,rgba(0,0,0,.03),transparent 62%,rgba(0,0,0,.22))"}}/><MediaCallout shot={shot} theme={props.theme}/></AbsoluteFill>;
};

export const Longform:React.FC<LongformProps> = (props) => {
  const {fps}=useVideoConfig(); const frame=useCurrentFrame();
  return <AbsoluteFill style={{background:props.theme.background}}>
    {props.audioSrc?<Audio src={staticFile(props.audioSrc)}/>:null}
    {props.musicBeds.map((bed,index)=><Sequence key={`music-${index}`} from={Math.round(bed.startMs/1000*fps)} durationInFrames={Math.max(1,Math.round((bed.endMs-bed.startMs)/1000*fps))}><Audio src={staticFile(bed.src)} loop volume={bed.volume}/></Sequence>)}
    {props.sfx.map((event,index)=><Sequence key={`sfx-${index}`} from={Math.round(event.startMs/1000*fps)}><Audio src={staticFile(event.src)} volume={event.volume}/></Sequence>)}
    {props.shots.map((shot)=><Sequence key={shot.shotId} from={Math.round(shot.startMs/1000*fps)} durationInFrames={Math.max(1,Math.round((shot.endMs-shot.startMs)/1000*fps))} premountFor={fps} name={shot.shotId}><ShotView shot={shot} props={props}/></Sequence>)}
    {props.endScreen?<Sequence style={{zIndex:1000}} from={Math.round(props.endScreen.startMs/1000*fps)} durationInFrames={Math.max(1,Math.round(props.endScreen.durationMs/1000*fps))} name="END-SCREEN-CTA"><VerifiedEndScreen endScreen={props.endScreen} theme={props.theme}/></Sequence>:null}
    {props.showProgress?<div style={{position:"absolute",left:0,bottom:0,height:6,width:`${interpolate(frame,[0,Math.max(1,props.durationMs/1000*fps)],[0,100],{...clamp})}%`,background:props.theme.accent}}/>:null}
  </AbsoluteFill>;
};
