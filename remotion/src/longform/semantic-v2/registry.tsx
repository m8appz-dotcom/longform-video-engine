import React from "react";
import {interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import type {LongformShot, LongformTheme} from "../../longform-types";

export type SemanticV2Props={shot:LongformShot;theme:LongformTheme};
const clamp={extrapolateLeft:"clamp",extrapolateRight:"clamp"} as const;
const clean=(value:unknown,fallback="")=>(String(value||fallback).replace(/\s+/g," ").trim());
const reveal=(frame:number,duration:number,start:number,end:number)=>interpolate(frame,[duration*start,duration*end],[0,1],clamp);
const semantic=(theme:LongformTheme,key:keyof NonNullable<LongformTheme["semanticColors"]>,fallback:string)=>theme.semanticColors?.[key]||fallback;
const displayWeight=(theme:LongformTheme)=>Number(theme.typography?.displayWeight||900);
const bodyWeight=(theme:LongformTheme)=>Number(theme.typography?.bodyWeight||700);

const EditorialProtocol:React.FC<SemanticV2Props>=({shot,theme})=>{
  if(!shot.backgroundSource) throw new Error(`${shot.shotId}: protocol-diagram requires literal backgroundSource`);
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig();
  const items=(shot.uiSpec?.items||["LUZ FIJA","DISTANCIA","POSTURA"]).slice(0,3);
  const values=(shot.uiSpec?.values||["45°","2,0 M","MISMA MARCA"]).slice(0,3);
  return <div data-qa-semantic-v2="editorial-protocol" style={{height:"100%",display:"grid",gridTemplateRows:"repeat(3,1fr)",gap:14}}>{items.map((item,index)=>{const q=reveal(frame,durationInFrames,.10+index*.12,.30+index*.12);return <div key={String(item)} style={{background:index===2?theme.accent:theme.surface,color:index===2?theme.background:theme.text,border:`1px solid ${theme.hairline||theme.accent}`,borderLeft:`4px solid ${index===2?theme.highlight:theme.accent}`,borderRadius:Number(theme.composition?.cardRadius||0),padding:"18px 22px",display:"grid",gridTemplateColumns:"54px 1fr",alignItems:"center",gap:14,opacity:q,transform:`translateX(${(1-q)*24}px)`}}><div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:24,fontWeight:bodyWeight(theme),letterSpacing:0,color:index===2?theme.highlight:theme.accent}}>0{index+1}</div><div><div style={{fontFamily:theme.fontDisplay,fontSize:25,lineHeight:1,fontWeight:displayWeight(theme),letterSpacing:0}}>{clean(item)}</div><div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:16,fontWeight:bodyWeight(theme),letterSpacing:0,marginTop:7,opacity:.76}}>{clean(values[index])}</div></div></div>})}</div>;
};

const AnatomyCutaway:React.FC<SemanticV2Props>=({shot,theme})=>{
  if(!shot.backgroundSource) throw new Error(`${shot.shotId}: anatomy semantic requires literal backgroundSource`);
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig();
  const items=(shot.uiSpec?.items||["PIEL","HINCHAZÓN","GRASA"]).slice(0,3);
  const values=(shot.uiSpec?.values||["SUPERFICIE","TEMPORAL","SUBCUTÁNEA"]).slice(0,3);
  const colors=[semantic(theme,"skinSurface","#D6A18A"),semantic(theme,"fluid",theme.accent),semantic(theme,"fat",theme.highlight)];
  return <div data-qa-semantic-v2="anatomy-legend" style={{height:"100%",display:"grid",gridTemplateRows:"repeat(3,1fr)",gap:14}}>{items.map((item,index)=>{const q=reveal(frame,durationInFrames,.05+index*.13,.30+index*.13);return <div key={String(item)} style={{display:"grid",gridTemplateColumns:"14px 1fr",gap:18,alignItems:"center",background:index===1?`${theme.accent}12`:theme.surface,padding:"18px 22px",opacity:q,transform:`translateX(${(1-q)*24}px)`}}>
      <div style={{height:"100%",minHeight:58,background:colors[index]}}/>
      <div><div style={{fontFamily:theme.fontDisplay,fontSize:27,lineHeight:1,fontWeight:displayWeight(theme)}}>{clean(item)}</div><div style={{fontSize:18,fontWeight:bodyWeight(theme),color:index===2?theme.highlight:theme.accent,marginTop:7}}>{clean(values[index])}</div></div>
    </div>})}</div>;
};

const ClaimEvidenceEditorial:React.FC<SemanticV2Props>=({shot,theme})=>{
  const frame=useCurrentFrame(); const {durationInFrames}=useVideoConfig();
  const values=(shot.uiSpec?.values||["PROMESA","EVIDENCIA","DECISIÓN"]).slice(0,3);
  return <div data-qa-semantic-v2="claim-evidence-editorial" style={{height:"100%",display:"grid",gridTemplateRows:"repeat(3,minmax(0,1fr))",gap:13}}>{values.map((value,index)=>{const q=reveal(frame,durationInFrames,.05+index*.13,.27+index*.13); const label=["PROMESA","EVIDENCIA","DECISIÓN"][index]; return <div key={String(value)} style={{position:"relative",background:index===2?theme.accent:index===0?`${theme.danger}13`:theme.surface,color:index===2?theme.background:theme.text,borderLeft:`10px solid ${index===0?theme.danger:index===1?theme.accent:theme.highlight}`,padding:"18px 24px",display:"grid",alignContent:"center",opacity:q,transform:`translateX(${(1-q)*30}px)`}}>
    <div style={{fontFamily:theme.fontMono||theme.fontBody,fontSize:14,fontWeight:bodyWeight(theme),letterSpacing:0,color:index===2?theme.highlight:index===0?theme.danger:theme.accent}}>{label}</div>
    <div style={{fontFamily:theme.fontDisplay,fontSize:String(value).length>24?25:31,lineHeight:1.02,fontWeight:displayWeight(theme),marginTop:8,textDecoration:index===0?"line-through":"none",textDecorationColor:theme.danger,textDecorationThickness:index===0?"4px":undefined}}>{clean(value)}</div>
  </div>})}</div>;
};

const registry:Record<string,React.FC<SemanticV2Props>>={
  "variant:protocol-diagram":EditorialProtocol,
  "variant:claim-evidence":ClaimEvidenceEditorial,
  "template:anatomy-explainer":AnatomyCutaway,
  "template:body-distinction":AnatomyCutaway,
};

export const semanticV2ComponentFor=(shot:LongformShot):React.FC<SemanticV2Props>|null=>{
  const variant=String(shot.uiSpec?.variant||"");
  const template=String(shot.uiSpec?.template||"");
  return registry[`variant:${variant}`]||registry[`template:${template}`]||null;
};

