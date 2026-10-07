import React from "react";
import {AbsoluteFill, Img, useCurrentFrame, useVideoConfig, interpolate, spring} from "remotion";
import {THEME, hexA, fontFamily, C, isLightHex, resolveSrc, DottedTexture} from "../theme";
import {captionSize} from "../layers/captions";

// ---------- OVERLAYS con significado ----------
export const StoryArcChart: React.FC<any> = ({
  title = "",
  variant = "modern",
  points,
  labels,
  yLabel = "",
  xLabel = "",
  highlightUntil,
  badge,
  footerBars = true,
  showSeventyLine = false,
  color,
  bg,
  laneTop = 0,
}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const traditional = variant === "traditional";
  const light = isLightHex(bg);
  const lineColor = traditional ? THEME.yellow : THEME.purple;
  const glowColor = traditional ? THEME.yellow : THEME.magenta;
  // Nunca inventa la serie: sin points declarados (>=2) no se renderiza.
  if (!Array.isArray(points) || points.length < 2) return null;
  const vals = points.map((p:number)=>Math.max(0,Math.min(100,Number(p))));
  const labs = Array.isArray(labels) && labels.length ? labels.map((x:any)=>String(x)) : [];
  const W=820, H=430, X=96, Y=222;
  const coords = vals.map((v:number,i:number) => {
    const x = X + (vals.length === 1 ? 0 : (i/(vals.length-1))*W);
    const y = Y + H - (v/100)*H;
    return [x,y] as const;
  });
  const path = coords.map(([x,y],i)=>`${i===0?"M":"L"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const draw = interpolate(f,[0,Math.round(fps*1.05)],[0,1],C);
  const dash = 2200;
  const hi = typeof highlightUntil === "number" ? Math.max(0, Math.min(coords.length-1, highlightUntil)) : coords.length-1;
  const hiPath = coords.slice(0,hi+1).map(([x,y],i)=>`${i===0?"M":"L"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const pulse = 0.72 + 0.28*Math.sin(f/4);
  const headline = String(title).split(/\s+/).filter(Boolean);
  return (
    <AbsoluteFill style={{pointerEvents:"none",background:light ? `linear-gradient(180deg,${THEME.cream},${THEME.off})` : `linear-gradient(180deg,${hexA(bg,0.96)},${hexA(bg,0.88)} 82%,${hexA(bg,0.12)} 100%)`}}>
      <DottedTexture color={light ? THEME.ink : color} opacity={light ? 0.035 : 0.12}/>
      <AbsoluteFill style={{justifyContent:"flex-start",alignItems:"center",paddingTop:Math.max(96,laneTop)}}>
        <div style={{fontFamily,fontWeight:800,fontSize:58,lineHeight:1.02,color,textAlign:"center",textShadow:light ? "none" : "0 8px 22px rgba(0,0,0,0.65)"}}>
          {headline.map((w:string,i:number)=>(
            <span key={i} style={{marginRight:14,color}}>{w}</span>
          ))}
        </div>
        {badge ? (
          <div style={{
            marginTop:22,
            fontFamily,
            fontWeight:800,
            fontSize:30,
            color:traditional ? (light ? THEME.ink : "#fff") : THEME.ink,
            background:traditional ? THEME.yellow : THEME.yellow,
            padding:"10px 22px",
            borderRadius:8,
            boxShadow:`0 0 28px ${hexA(THEME.yellow,0.28)}`,
            textTransform:"uppercase",
          }}>{badge}</div>
        ) : null}
      </AbsoluteFill>
      <svg width="1080" height="1040" viewBox="0 0 1080 1040" style={{position:"absolute",top:196,left:0,overflow:"visible"}}>
        <defs>
          <filter id={`storyGlow-${variant}`}>
            <feGaussianBlur stdDeviation="7" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <linearGradient id={`storyLine-${variant}`} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor={lineColor}/>
            <stop offset="100%" stopColor={traditional ? THEME.green : THEME.magenta}/>
          </linearGradient>
        </defs>
        {[0,1,2,3].map(i=>(
          <line key={i} x1={X} y1={Y+i*(H/4)} x2={X+W} y2={Y+i*(H/4)}
            stroke={hexA(color,0.1)} strokeWidth="2"/>
        ))}
        <line x1={X} y1={Y} x2={X} y2={Y+H} stroke={hexA(color,0.58)} strokeWidth="4"/>
        <line x1={X} y1={Y+H} x2={X+W} y2={Y+H} stroke={hexA(color,0.58)} strokeWidth="4"/>
        {yLabel ? <text x={X-50} y={Y+H/2} fill={hexA(color,0.72)} fontFamily={fontFamily} fontSize="22" fontWeight="800" transform={`rotate(-90 ${X-50} ${Y+H/2})`} textAnchor="middle">{yLabel}</text> : null}
        {xLabel ? <text x={X+W/2} y={Y+H+56} fill={hexA(color,0.72)} fontFamily={fontFamily} fontSize="22" fontWeight="800" textAnchor="middle">{xLabel}</text> : null}
        {!traditional && showSeventyLine ? <line x1={X} y1={Y+H-(70/100)*H} x2={X+W} y2={Y+H-(70/100)*H} stroke={hexA(THEME.yellow,0.34)} strokeDasharray="10 12" strokeWidth="4"/> : null}
        {!traditional && showSeventyLine ? <text x={X+16} y={Y+H-(70/100)*H-18} fill={THEME.yellow} fontFamily={fontFamily} fontSize="28" fontWeight="800">70/100</text> : null}
        <path d={path} fill="none" stroke={hexA(color,0.18)} strokeWidth="12" strokeLinecap="round" strokeLinejoin="round"/>
        <path d={path} fill="none" stroke={`url(#storyLine-${variant})`} strokeWidth="10" strokeLinecap="round" strokeLinejoin="round"
          strokeDasharray={dash} strokeDashoffset={dash*(1-draw)} opacity={0.36} filter={`url(#storyGlow-${variant})`}/>
        <path d={hiPath} fill="none" stroke={`url(#storyLine-${variant})`} strokeWidth="14" strokeLinecap="round" strokeLinejoin="round"
          strokeDasharray={dash} strokeDashoffset={dash*(1-draw)} opacity={pulse} filter={`url(#storyGlow-${variant})`}/>
        {coords.map(([x,y],i)=>(
          <circle key={i} cx={x} cy={y} r={f>i*5 ? (i<=hi ? 10+6*pulse : 8) : 0}
            fill={i<=hi ? lineColor : color} opacity={f>i*5 ? 1 : 0} filter={`url(#storyGlow-${variant})`}/>
        ))}
        {labs.slice(0, Math.min(labs.length, coords.length)).map((lab:string,i:number)=>{
          if(!coords[i] || f < 10+i*6) return null;
          const [x,y]=coords[i];
          const w = Math.max(118, Math.min(230, String(lab).length*13+44));
          const lx = Math.max(58, Math.min(1080-w-42, x + (i%2===0 ? 18 : -w-18)));
          const ly = Math.max(88, y - (traditional ? 54 : 70));
          return (
            <g key={i}>
              <path d={`M ${x} ${y-10} L ${lx+w/2} ${ly+38}`} stroke={hexA(color,0.32)} strokeWidth="2"/>
              <rect x={lx} y={ly} width={w} height="44" rx="8" fill={hexA(THEME.panel,0.92)} stroke={hexA(i<=hi?lineColor:color,0.62)}/>
              <text x={lx+w/2} y={ly+29} fill={i<=hi?color:hexA(color,0.76)} fontFamily={fontFamily} fontSize="21" fontWeight="800" textAnchor="middle">{lab}</text>
            </g>
          );
        })}
        {footerBars !== false ? vals.slice(0,-1).map((_,i)=>{
          const bw = W/(vals.length-1)-12;
          const active = !traditional && i <= hi;
          return <rect key={i} x={X+i*(W/(vals.length-1))+6} y={Y+H+86} width={Math.max(28,bw)} height={active?14:9} rx="4"
            fill={active ? THEME.yellow : hexA(THEME.yellow, traditional ? 0.14 : 0.28)}
            opacity={f>12+i*4?1:0} style={{filter:active?`drop-shadow(0 0 10px ${hexA(THEME.yellow,0.65)})`:undefined}}/>;
        }) : null}
      </svg>
    </AbsoluteFill>
  );
};

export const StatRing: React.FC<any> = ({value,suffix,label,fitMode,from,color,accent,laneBottom=0,laneTop=0}) => {
  const f=useCurrentFrame(); const {fps,durationInFrames}=useVideoConfig();
  const shortBeat=durationInFrames <= Math.round(fps*1.15);
  const p=shortBeat ? interpolate(f,[0,5],[0.82,1],C) : spring({frame:f,fps,config:{damping:14}});
  const numeric=Number(value ?? 0);
  const start=Number(from ?? 0);
  const n=shortBeat ? numeric : Math.round(interpolate(f,[0,Math.round(fps*0.8)],[start,numeric],C));
  const suffixText=String(suffix || "");
  const suffixClean=suffixText.trim();
  const wide=fitMode==="responsive" || fitMode==="compact" || `${n}${suffixClean}`.length>=4;
  const compact=fitMode==="compact";
  const denomMatch=suffixClean.match(/^\/(\d+)/);
  const denom=denomMatch ? Number(denomMatch[1]) : 100;
  const ratio=denomMatch ? numeric/Math.max(1,denom) : numeric/100;
  const R=178,CIRC=2*Math.PI*R; const fill=interpolate(f,[0,shortBeat?6:Math.round(fps*0.9)],[shortBeat?0.22:0,Math.min(1,Math.max(0,ratio))],C);
  const numberFont=compact ? 126 : wide ? 132 : 154;
  const suffixFont=compact ? 66 : suffixClean.length>=3 ? 64 : 82;
  return (
    <AbsoluteFill style={{justifyContent:"center",alignItems:"center",paddingBottom:Math.max(390,laneBottom),paddingTop:laneTop}}>
      <div style={{position:"relative",width:500,height:500,transform:`scale(${0.72+0.28*p})`,opacity:p}}>
        <svg width="500" height="500" style={{position:"absolute",inset:0}}>
          <circle cx="250" cy="250" r={R} stroke={hexA(color,0.12)} strokeWidth="20" fill="none"/>
          <circle cx="250" cy="250" r={R} stroke={accent} strokeWidth="20" fill="none" strokeLinecap="round"
            strokeDasharray={CIRC} strokeDashoffset={CIRC*(1-fill)} transform="rotate(-90 250 250)"
            style={{filter:`drop-shadow(0 0 12px ${hexA(accent,0.7)})`}}/>
        </svg>
        <div style={{position:"absolute",inset:0,display:"flex",flexDirection:"column",justifyContent:"center",alignItems:"center",padding:"0 36px"}}>
          <div style={{display:"flex",alignItems:"baseline",justifyContent:"center",gap:suffixClean.startsWith("/")?0:14,maxWidth:430,whiteSpace:"nowrap",filter:"drop-shadow(0 8px 22px rgba(255,255,255,0.72))"}}>
            <span style={{fontFamily,fontWeight:800,fontSize:numberFont,lineHeight:0.86,color,letterSpacing:0}}>{n}</span>
            {suffixClean ? <span style={{fontFamily,fontWeight:800,fontSize:suffixFont,lineHeight:0.9,color,letterSpacing:0,textTransform:"none"}}>{suffixClean}</span> : null}
          </div>
          {label?<div style={{fontFamily,fontWeight:800,fontSize:34,lineHeight:1.05,color:accent,textTransform:"uppercase",marginTop:18,textAlign:"center",maxWidth:430}}>{label}</div>:null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const listFrom = (value: any): string[] => Array.isArray(value) ? value.map((v) => String(v)) : [];
const resolveOffsets = (offsets: any, count: number, fps: number, fallbackSeconds = 1.15) => {
  const raw = Array.isArray(offsets) ? offsets : [];
  return Array.from({length: count}, (_, k) => {
    const ms = raw[k];
    return ms != null ? Math.round(Number(ms) / 1000 * fps) : Math.round(k * fallbackSeconds * fps);
  }).map((o, k) => k === 0 && o > Math.round(fps * 0.35) ? 0 : o);
};

const activeFromOffsets = (frame: number, offsets: number[]) => {
  let active = 0;
  for (let k = 0; k < offsets.length; k++) {
    if (frame >= offsets[k]) active = k;
  }
  return active;
};

const RowReveal: React.FC<{index:number;text:string;active:boolean;future:boolean;color:string;accent:string;bg:string}> = ({index,text,active,future,color,accent,bg}) => {
  const light = isLightHex(bg);
  const fill = active ? (light ? "#E1F0EA" : hexA(accent, 0.18)) : (light ? THEME.off : hexA(THEME.off, 0.92));
  const border = active ? hexA(accent, 0.7) : hexA(color, 0.1);
  return (
    <div style={{
      height: 96,
      display: "flex",
      alignItems: "center",
      gap: 24,
      padding: "0 24px",
      borderRadius: 16,
      background: fill,
      border: `2px solid ${border}`,
      boxShadow: active ? "0 16px 30px rgba(0,0,0,0.18)" : "0 6px 18px rgba(0,0,0,0.06)",
      overflow: "hidden",
    }}>
      <div style={{
        width: 56,
        height: 56,
        borderRadius: 14,
        background: active ? accent : hexA(accent, 0.13),
        color: active ? bg : accent,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily,
        fontWeight: 800,
        fontSize: 36,
      }}>{index + 1}</div>
      {future ? (
        <div style={{display:"flex",flexDirection:"column",gap:14}}>
          <div style={{width:330,height:14,borderRadius:8,background:hexA(color,0.1)}}/>
          <div style={{width:460,height:10,borderRadius:8,background:hexA(color,0.07)}}/>
        </div>
      ) : (
        <div style={{fontFamily,fontWeight:800,fontSize:36,lineHeight:1.05,color:active ? color : hexA(color,0.62),textTransform:"uppercase"}}>
          {text}
        </div>
      )}
    </div>
  );
};

const TokenGlyph: React.FC<{type:string;active:boolean;accent:string;color:string}> = ({type,active,accent,color}) => {
  const ink = active ? accent : hexA(accent, 0.28);
  if (/volumen|volume/i.test(type)) {
    return (
      <svg width="84" height="58" viewBox="0 0 84 58">
        <path d="M18 24 C20 48,64 48,66 24" fill="none" stroke={ink} strokeWidth="7" strokeLinecap="round"/>
        <path d="M26 24 H58" fill="none" stroke={ink} strokeWidth="7" strokeLinecap="round"/>
      </svg>
    );
  }
  return (
    <svg width="76" height="58" viewBox="0 0 76 58">
      <rect x="20" y="8" width="36" height="36" rx="10" fill={ink}/>
      <rect x="16" y="50" width="44" height="6" rx="3" fill={hexA(active ? accent : color, active ? 0.75 : 0.16)}/>
    </svg>
  );
};

type OverlayImageSlot = {
  id?: string;
  role?: string;
  item_index?: number;
  item?: string;
  src?: string;
  label?: string;
};

const slotListFrom = (value: any): OverlayImageSlot[] => Array.isArray(value) ? value.filter(Boolean) : [];
const slotByRole = (slots: OverlayImageSlot[], roles: string[]) =>
  slots.find((s) => roles.includes(String(s.role || s.id || "").toLowerCase()));
const slotForItem = (slots: OverlayImageSlot[], index: number, label: string, token: string) => {
  const cleanLabel = String(label || "").toLowerCase();
  const cleanToken = String(token || "").toLowerCase();
  return slots.find((s) => {
    const role = String(s.role || "").toLowerCase();
    const id = String(s.id || "").toLowerCase();
    const item = String(s.item || "").toLowerCase();
    return s.item_index === index || role === "item_card" && s.item_index === index ||
      (!!item && cleanLabel.includes(item)) || (!!id && (id.includes(cleanToken) || id.includes(cleanLabel.split(/\s+/).slice(-1)[0])));
  });
};

const CardImage: React.FC<{slot?:OverlayImageSlot;label:string;accent:string;color:string;active?:boolean;fit?:React.CSSProperties["objectFit"]}> = ({slot,label,accent,color,active=false,fit="cover"}) => {
  if (slot?.src) {
    return (
      <Img
        src={resolveSrc(slot.src)}
        style={{width:"100%",height:"100%",objectFit:fit,display:"block",filter:active ? "saturate(1.05) contrast(1.04)" : "saturate(0.82) contrast(0.96)"}}
      />
    );
  }
  return (
    <div style={{width:"100%",height:"100%",display:"flex",alignItems:"center",justifyContent:"center",flexDirection:"column",gap:10,background:hexA(accent,0.08)}}>
      <TokenGlyph type={label} active={active} accent={accent} color={color}/>
      <div style={{fontFamily,fontWeight:800,fontSize:16,color:active ? color : hexA(color,0.56),textTransform:"uppercase",maxWidth:"86%",textAlign:"center"}}>{label}</div>
    </div>
  );
};

export const CausalMeter: React.FC<any> = ({title="",items,offsets,tokens,meter_label,meter_caption,meter_values,future_reveal,visual_asset_strategy,layout_variant,image_slots,color,accent,bg}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const rows=listFrom(items).slice(0,4);
  const tokenList=listFrom(tokens);
  const meterVals=listFrom(meter_values);
  const offs=resolveOffsets(offsets, rows.length, fps, 1.12);
  const active=activeFromOffsets(f, offs);
  const light=isLightHex(bg);
  const allowImageSlots=String(visual_asset_strategy || "").toLowerCase() !== "diagram";
  const slots=allowImageSlots ? slotListFrom(image_slots) : [];
  const sourceSlot=slotByRole(slots, ["source_card","source"]);
  const compactImageMode=layout_variant === "source_meter" || layout_variant === "image_diagnosis" || String(visual_asset_strategy || "").includes("image") || !!sourceSlot;
  const positions=compactImageMode ? [
    {x:430,y:440},
    {x:430,y:440},
    {x:430,y:440},
    {x:430,y:440},
  ] : [
    {x:410,y:270},
    {x:485,y:455},
    {x:410,y:640},
    {x:560,y:640},
  ];
  const meterValue=meterVals[active] || meterVals[meterVals.length-1] || "";
  const meterParts=String(meterValue).match(/^(\d+)\s*(.*)$/);
  const meterNum=meterParts ? meterParts[1] : meterValue;
  const meterUnit=meterParts ? meterParts[2] : "";
  const ratio=rows.length<=1 ? 1 : (active+1)/rows.length;
  const futureMode=future_reveal || "skeleton_only";
  return (
    <AbsoluteFill style={{background:light ? `linear-gradient(180deg,#ECE7DD,${THEME.off})` : bg,overflow:"hidden"}}>
      <DottedTexture color={light ? THEME.ink : color} opacity={light ? 0.04 : 0.08}/>
      <div style={{position:"absolute",left:-160,top:210,width:460,height:980,borderRadius:260,background:hexA(accent,0.08),filter:"blur(1px)"}}/>
      <div style={{position:"absolute",right:-180,top:260,width:420,height:880,borderRadius:240,background:hexA(accent,0.07),filter:"blur(1px)"}}/>
      <div style={{position:"absolute",left:0,right:0,bottom:0,height:560,background:`linear-gradient(180deg,transparent 0%,${hexA(accent,0.1)} 100%)`}}/>
      <div style={{position:"absolute",left:104,right:104,bottom:130,height:3,borderRadius:3,background:hexA(accent,0.16)}}/>
      {title ? <div style={{position:"absolute",left:82,top:84,fontFamily,fontWeight:800,fontSize:36,color:hexA(color,0.68),textTransform:"uppercase"}}>{title}</div> : null}
      <div style={{position:"absolute",right:80,top:74,width:190,height:54,borderRadius:14,background:hexA(accent,0.12),display:"flex",alignItems:"center",justifyContent:"center",fontFamily,fontWeight:800,fontSize:28,color:accent}}>
        {Math.min(rows.length,active+1)}/{rows.length}
      </div>
      <div style={{position:"absolute",left:56,top:150,width:968,height:770,borderRadius:30,background:`linear-gradient(145deg,${hexA(THEME.panel,0.96)} 0%,${hexA(THEME.panel,0.82)} 52%,${hexA(accent,0.12)} 100%)`,border:`2px solid ${hexA(color,0.12)}`,boxShadow:"0 22px 40px rgba(0,0,0,0.16)"}}/>
      <svg width="1080" height="900" viewBox="0 0 1080 900" style={{position:"absolute",left:0,top:150,overflow:"visible"}}>
        <defs>
          <filter id="sourcePulse"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        {(compactImageMode ? positions.slice(active, active + 1) : positions.slice(0, rows.length)).map((p,localK)=>{
          const k=compactImageMode ? active : localK;
          const isActive=k===active;
          const start=Math.max(0, f-offs[k]);
          const draw=interpolate(start,[0,18],[0,1],C);
          const path=compactImageMode
            ? `M 294 420 C 365 395, 388 448, ${p.x+22} ${p.y+58} C ${p.x+190} ${p.y+96}, 670 430, 758 382`
            : `M ${p.x+148} ${p.y+68} C ${p.x+258} ${p.y+20}, 650 ${p.y+120}, 758 382`;
          return (
            <g key={k}>
              <path d={path} stroke={isActive ? accent : hexA(color,0.08)} strokeWidth={isActive?5:3} fill="none"
                strokeDasharray="480" strokeDashoffset={isActive ? 480*(1-draw) : 0} opacity={isActive?1:0.55}/>
              {isActive ? <circle cx="758" cy="382" r={15+Math.sin(f/5)*3} fill={accent} filter="url(#sourcePulse)" opacity="0.9"/> : null}
            </g>
          );
        })}
      </svg>
      <div style={{position:"absolute",left:96,top:388,width:214,height:286,borderRadius:24,background:THEME.off,border:`2px solid ${hexA(color,0.12)}`,boxShadow:"0 18px 22px rgba(0,0,0,0.18)",overflow:"hidden"}}>
        <CardImage slot={sourceSlot} label={sourceSlot?.label || rows[active] || ""} accent={accent} color={color} active/>
        <div style={{position:"absolute",left:22,right:22,bottom:18,height:10,borderRadius:8,background:accent,boxShadow:`0 0 18px ${hexA(accent,0.35)}`}}/>
      </div>
      {(compactImageMode ? positions.slice(active, active + 1) : positions.slice(0, rows.length)).map((p,localK)=>{
        const k=compactImageMode ? active : localK;
        const isActive=k===active;
        const appear=spring({frame:f-offs[k],fps,config:{damping:16,mass:0.6}});
        const label=rows[k] || "";
        const cardSlot=slotForItem(slots,k,label,tokenList[k] || "");
        return (
          <div key={k} style={{position:"absolute",left:p.x,top:p.y,width:compactImageMode?188:148,height:compactImageMode?172:136,borderRadius:22,background:isActive?hexA(accent,0.16):hexA(THEME.off,0.72),border:`2px solid ${isActive?hexA(accent,0.72):hexA(color,0.1)}`,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:10,opacity:f>=offs[k]-2?1:0.5,transform:`scale(${isActive?0.94+0.06*appear:1})`,boxShadow:isActive?`0 0 0 22px ${hexA(accent,0.08)}`:"none",overflow:"hidden",padding:cardSlot?.src?0:12}}>
            {cardSlot?.src ? (
              <div style={{width:"100%",height:compactImageMode?118:88,overflow:"hidden",borderRadius:20}}>
                <CardImage slot={cardSlot} label={label} accent={accent} color={color} active={isActive}/>
              </div>
            ) : <TokenGlyph type={tokenList[k] || label} active={isActive} accent={accent} color={color}/>}
            <div style={{fontFamily,fontWeight:800,fontSize:18,color:isActive?color:hexA(color,0.5),textTransform:"uppercase",textAlign:"center",maxWidth:128}}>{label.split(/\s+/).slice(-1)[0]}</div>
          </div>
        );
      })}
      <div style={{position:"absolute",left:758,top:372,width:230,height:320,borderRadius:28,background:THEME.off,border:`2px solid ${hexA(color,0.13)}`,boxShadow:"0 20px 24px rgba(0,0,0,0.2)"}}>
        {meter_label ? <div style={{position:"absolute",left:28,top:28,fontFamily,fontWeight:800,fontSize:24,color:hexA(color,0.68),textTransform:"uppercase"}}>{meter_label}</div> : null}
        <svg width="230" height="230" viewBox="0 0 230 230" style={{position:"absolute",left:0,top:68}}>
          <circle cx="115" cy="115" r="74" stroke={hexA(accent,0.18)} strokeWidth="20" fill="none"/>
          <circle cx="115" cy="115" r="74" stroke={accent} strokeWidth="20" fill="none" strokeLinecap="round" strokeDasharray={2*Math.PI*74}
            strokeDashoffset={(2*Math.PI*74)*(1-Math.min(1,Math.max(0.1,ratio)))} transform="rotate(-90 115 115)"/>
        </svg>
        <div style={{position:"absolute",left:42,top:132,width:146,display:"flex",alignItems:"baseline",justifyContent:"center",gap:7}}>
          <span style={{fontFamily,fontWeight:800,fontSize:52,lineHeight:0.9,color}}>{meterNum}</span>
          {meterUnit ? <span style={{fontFamily,fontWeight:800,fontSize:27,lineHeight:1,color}}>{meterUnit}</span> : null}
        </div>
        {meter_caption ? <div style={{position:"absolute",left:48,top:194,width:134,fontFamily,fontWeight:800,fontSize:22,color:accent,textAlign:"center",textTransform:"uppercase"}}>{meter_caption}</div> : null}
      </div>
      <div style={{position:"absolute",left:76,top:948,width:928,display:"flex",flexDirection:"column",gap:18}}>
        {rows.map((row,k)=>{
          const future=f<offs[k]-2;
          return <RowReveal key={k} index={k} text={row} active={!future && k===active} future={future && futureMode==="skeleton_only"} color={color} accent={accent} bg={bg}/>;
        })}
      </div>
      <div style={{position:"absolute",left:132,top:1308,width:816,height:8,borderRadius:8,background:hexA(color,0.12)}}>
        <div style={{height:"100%",width:`${Math.round(100*(active+1)/Math.max(1,rows.length))}%`,borderRadius:8,background:accent}}/>
      </div>
    </AbsoluteFill>
  );
};

export const ObjectCallout: React.FC<any> = ({label,side="left",color,accent,bg}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const p=spring({frame:f,fps,config:{damping:15,mass:0.6}});
  const left=side==="right" ? 620 : 80;
  const top=side==="bottom" ? 1220 : side==="right" ? 520 : 280;
  return (
    <AbsoluteFill style={{pointerEvents:"none"}}>
      <div style={{position:"absolute",left,top,transform:`translateY(${(1-p)*22}px)`,opacity:p,display:"flex",alignItems:"center",gap:14,padding:"14px 20px",borderRadius:999,background:hexA(bg,0.88),border:`2px solid ${hexA(accent,0.6)}`,boxShadow:"0 12px 30px rgba(0,0,0,0.18)"}}>
        <div style={{width:18,height:18,borderRadius:999,background:accent}}/>
        <div style={{fontFamily,fontWeight:800,fontSize:28,color,textTransform:"uppercase"}}>{label}</div>
      </div>
    </AbsoluteFill>
  );
};

export const StepList: React.FC<any> = ({items,offsets,variant,placement,futureReveal,durMs,color,accent,bg,laneBottom=0,laneTop=0}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const light=isLightHex(bg);
  const itemCount=(items as string[]).length;
  const shortSequence=itemCount>=3 && Number(durMs || 0)>0 && Number(durMs || 0)<2600;
  const rawOffs=(items as string[]).map((_,k)=> {
    if (shortSequence) return k*6;
    return offsets&&offsets[k]!=null ? Math.round(offsets[k]/1000*fps) : k*Math.round(fps*1.3);
  });
  const offs=rawOffs.map((o,k)=>k===0 && o>Math.round(fps*0.35) ? 0 : o);
  let active=0; for(let k=0;k<offs.length;k++){ if(f>=offs[k]) active=k; }
  const v=variant || "checklist";
  const compact=v==="compact" || shortSequence;
  // La posicion sale SOLO del placement declarado; el variant es solo estilo
  // (no debe reposicionar). Asi 'safe_center' se queda centrado y no invade la
  // lane del caption (center_low).
  const lower=placement==="safe_lower";
  const width=compact ? 760 : v==="rule" ? 860 : 900;
  const rowH=compact ? (shortSequence ? 68 : 76) : 96;
  const fontSize=compact ? (shortSequence ? 34 : 38) : v==="rule" ? 43 : 50;
  const badge=compact ? (shortSequence ? 54 : 64) : 88;
  const solidOff = light ? THEME.off : hexA(bg, 0.88);
  return (
    <AbsoluteFill style={{justifyContent:lower?"flex-end":"center",alignItems:"center",paddingBottom:Math.max(lower?560:0,laneBottom),paddingTop:laneTop}}>
      <div style={{display:"flex",flexDirection:"column",gap:compact?18:30,width}}>
        {(items as string[]).map((it,k)=>{
          const future=shortSequence ? false : f<offs[k]-2;
          const s=future ? 1 : spring({frame:f-offs[k],fps,config:{damping:16,mass:0.6}});
          const on=!future && k===active;
          const diagnosis=v==="diagnosis";
          const criteria=v==="criteria";
          const label=String(it || "");
          const textFont=Math.max(30,Math.min(fontSize,fontSize-Math.max(0,label.length-20)*0.8));
          const solidOn = diagnosis ? "#E1F0EA" : criteria ? "#E6F2EE" : THEME.off;
          const bgOn=light ? solidOn : diagnosis ? hexA(accent,0.24) : criteria ? hexA(accent,0.18) : hexA(bg,0.82);
          const bgOff=solidOff;
          const contentOpacity=future ? (v==="rule" ? 0.58 : 0.42) : Math.max(0.92, s);
          const showFutureText = future && futureReveal === "ghost_text";
          return (
            <div key={k} style={{
              position:"relative",
              display:"flex",
              alignItems:"center",
              gap:compact?16:22,
              minHeight:rowH,
              boxSizing:"border-box",
              opacity:1,
              transform:future?"none":`translateX(${(1-s)*-70}px)`,
              background:on?bgOn:bgOff,
              border:`1px solid ${on?hexA(accent,0.54):hexA(color,0.16)}`,
              borderRadius:criteria?8:10,
              padding:compact?"10px 14px":"14px 18px",
              boxShadow:on?`0 16px 42px rgba(0,0,0,${light ? 0.12 : 0.32})`:future?"none":"0 10px 26px rgba(0,0,0,0.12)",
              backdropFilter:light ? "none" : "blur(2px)",
              overflow:"hidden",
              isolation:"isolate",
            }}>
              <div style={{minWidth:badge,height:badge,borderRadius:criteria?999:22,background:on?accent:hexA(accent,0.16),color:on?bg:accent,
                display:"flex",justifyContent:"center",alignItems:"center",fontFamily,fontWeight:800,fontSize:48,
                boxShadow:on?`0 0 24px ${hexA(accent,0.6)}`:"none",opacity:contentOpacity,flex:"0 0 auto"}}>{k+1}</div>
              {future && !showFutureText ? (
                <div style={{display:"flex",flexDirection:"column",gap:12,opacity:contentOpacity,flex:1,minWidth:0}}>
                  <div style={{width:v==="rule"?360:300,height:13,borderRadius:8,background:hexA(color,v==="rule"?0.16:0.1)}}/>
                  <div style={{width:v==="rule"?500:430,height:9,borderRadius:8,background:hexA(color,v==="rule"?0.1:0.07)}}/>
                </div>
              ) : (
                <div style={{fontFamily,fontWeight:800,fontSize:textFont,lineHeight:1.04,color:on?color:hexA(color,0.6),textTransform:"uppercase",
                  textShadow:light ? "none" : "0 4px 10px rgba(0,0,0,0.8)",opacity:contentOpacity,flex:1,minWidth:0,overflowWrap:"break-word"}}>{label}</div>
              )}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const KeywordPop: React.FC<any> = ({words,color,accent,bg,placement="safe_center",mustNotCover=[],onMedia=false}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const p=spring({frame:f,fps,config:{damping:10,mass:0.5}});
  const text=(words as string[]).join(" ");
  const fs=captionSize(text.replace(/\s+/g,""), "word_pop")+26;
  const must=Array.isArray(mustNotCover) ? mustNotCover : [];
  const avoidCaption=must.includes("caption");
  const top=placement==="safe_top";
  const lower=placement==="safe_lower";
  const left=placement==="left_callout";
  const right=placement==="right_callout";
  const light=isLightHex(bg);
  const area: React.CSSProperties = top
    ? {justifyContent:"flex-start",alignItems:"center",paddingTop:250}
    : lower
      ? {justifyContent:"flex-end",alignItems:"center",paddingBottom:avoidCaption?620:420}
      : left
        ? {justifyContent:"center",alignItems:"flex-start",paddingLeft:82,paddingBottom:avoidCaption?210:0}
        : right
          ? {justifyContent:"center",alignItems:"flex-end",paddingRight:82,paddingBottom:avoidCaption?210:0}
          : {justifyContent:"center",alignItems:"center",paddingBottom:avoidCaption?220:0};
  return (
    <AbsoluteFill style={area}>
      <div style={{transform:`scale(${0.55+0.5*p}) rotate(${(1-p)*-4}deg)`,opacity:p,fontFamily,fontWeight:800,fontSize:Math.min(118,fs),
        lineHeight:1.02,color:accent,textTransform:"uppercase",textAlign:"center",padding:"18px 36px",maxWidth:850,
        background:onMedia ? (light ? THEME.off : THEME.panel) : hexA(light ? THEME.off : THEME.panel,light?0.9:0.82),border:`2px solid ${hexA(accent,0.2)}`,borderRadius:8,
        boxShadow:light ? "0 16px 46px rgba(13,13,13,0.15)" : "0 20px 56px rgba(0,0,0,0.34)",
        textShadow:`0 0 20px ${hexA(accent,0.24)}`}}>
        {text}
      </div>
    </AbsoluteFill>
  );
};

export const LowerThird: React.FC<any> = ({text,sub,subSource,color,accent,bg,placement,mustNotCover=[],onMedia=false}) => {
  const f=useCurrentFrame(); const {durationInFrames}=useVideoConfig();
  const d=Math.max(1,durationInFrames);
  const slideIn=Math.min(9,Math.max(1,Math.floor(d*0.35)));
  const slideOut=Math.max(slideIn+1,d-slideIn);
  const fadeIn=Math.min(7,Math.max(1,Math.floor(d*0.3)));
  const fadeOut=Math.max(fadeIn+1,d-fadeIn);
  const x=d<=2 ? 0 : interpolate(f,[0,slideIn,slideOut,d],[-42,0,0,-42],C);
  const o=d<=2 ? 1 : interpolate(f,[0,fadeIn,fadeOut,d],[0,1,1,0],C);
  const top=placement==="safe_top";
  const lower=placement==="safe_lower";
  const must=Array.isArray(mustNotCover) ? mustNotCover : [];
  const keepClear=must.includes("face") || must.includes("subject") || must.includes("data");
  const mainSize=Math.max(34,Math.min(48,52-Math.max(0,String(text||"").length-16)*1.2));
  const subSize=Math.max(20,Math.min(26,28-Math.max(0,String(sub||"").length-28)*0.35));
  const showSub=Boolean(sub && (subSource==="narrated" || subSource==="user"));
  return (
    <AbsoluteFill style={{
      justifyContent:top?"flex-start":"flex-end",
      alignItems:"center",
      paddingTop:top?(keepClear?132:176):0,
      paddingBottom:top?0:(lower?620:420),
      paddingLeft:78,
      paddingRight:78,
    }}>
      {/* Sobre media (foto/video) el panel accent semitransparente se lavaba y el
          rotulo quedaba ilegible (ALERTA en el reel de cremas): panel OPACO claro
          con tinta oscura y barra accent. Sobre plates se conserva el panel accent. */}
      <div style={{
        transform:`translateX(${x}px)`,
        opacity:o,
        maxWidth:850,
        background:onMedia ? THEME.off : hexA(accent,0.94),
        borderLeft:onMedia ? `10px solid ${accent}` : undefined,
        padding:"15px 26px 17px",
        borderRadius:8,
        boxShadow:onMedia ? "0 16px 44px rgba(0,0,0,0.38)" : "0 14px 38px rgba(0,0,0,0.22)",
        width:"fit-content",
      }}>
        <div style={{fontFamily,fontWeight:800,fontSize:mainSize,color:onMedia ? THEME.ink : bg,textTransform:"uppercase",lineHeight:0.98,maxWidth:790,overflowWrap:"break-word"}}>{text}</div>
        {showSub?<div style={{fontFamily,fontWeight:700,fontSize:subSize,color:onMedia ? hexA(THEME.ink,0.78) : hexA(bg,0.86),marginTop:4,lineHeight:1.05,maxWidth:790,overflowWrap:"break-word"}}>{sub}</div>:null}
      </div>
    </AbsoluteFill>
  );
};

export const ChapterDots: React.FC<any> = ({title,labels,activeIndex,highlightUntil,color,accent,bg,laneBottom=0,laneTop=0}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const light=isLightHex(bg);
  const items=Array.isArray(labels) && labels.length ? labels.map((x:any)=>String(x)).slice(0,5) : [];
  const active=Number(activeIndex ?? highlightUntil ?? Math.min(items.length-1,Math.floor(interpolate(f,[0,Math.max(1,fps*2.6)],[0,items.length],C))));
  const p=spring({frame:f,fps,config:{damping:16,mass:0.7}});
  if (!items.length) return null;
  return (
    <AbsoluteFill style={{justifyContent:"center",alignItems:"center",paddingLeft:84,paddingRight:84,paddingBottom:Math.max(180,laneBottom),paddingTop:laneTop}}>
      <div style={{
        width:"100%",
        maxWidth:870,
        transform:`translateY(${(1-p)*30}px)`,
        opacity:p,
        background:light ? hexA(THEME.off,0.9) : hexA(bg,0.72),
        border:`2px solid ${hexA(accent,0.24)}`,
        borderRadius:8,
        padding:"34px 38px 36px",
        boxShadow:light ? "0 14px 45px rgba(13,13,13,0.14)" : "0 18px 55px rgba(0,0,0,0.3)",
      }}>
        {title ? <div style={{fontFamily,fontWeight:800,fontSize:34,lineHeight:1.05,color:hexA(color,0.72),textTransform:"uppercase",marginBottom:28}}>
          {title}
        </div> : null}
        <div style={{display:"grid",gridTemplateColumns:`repeat(${items.length},1fr)`,gap:14,alignItems:"start"}}>
          {items.map((label:string,i:number)=>{
            const on=i<=active;
            const pop=spring({frame:f-i*4,fps,config:{damping:14,mass:0.55}});
            return (
              <div key={i} style={{display:"flex",flexDirection:"column",alignItems:"center",gap:14,opacity:f>=i*3?1:0,transform:`translateY(${(1-pop)*18}px)`}}>
                <div style={{
                  width:on?58:44,
                  height:on?58:44,
                  borderRadius:8,
                  background:on?accent:hexA(color,light?0.12:0.18),
                  border:`2px solid ${on?accent:hexA(color,0.18)}`,
                  boxShadow:on?`0 0 18px ${hexA(accent,0.54)}`:"none",
                }}/>
                <div style={{fontFamily,fontWeight:800,fontSize:22,lineHeight:1.04,color:on?color:hexA(color,0.52),textAlign:"center",textTransform:"uppercase",maxWidth:145,overflowWrap:"break-word"}}>
                  {label}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const Annotation: React.FC<any> = ({label,color,accent}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const R=175,CIRC=2*Math.PI*R; const d=interpolate(f,[0,Math.round(fps*0.5)],[0,1],C);
  return (
    <AbsoluteFill style={{justifyContent:"center",alignItems:"center"}}>
      <svg width="440" height="440" style={{position:"absolute"}}>
        <circle cx="220" cy="220" r={R} stroke={accent} strokeWidth="9" fill="none" strokeLinecap="round"
          strokeDasharray={CIRC} strokeDashoffset={CIRC*(1-d)} transform="rotate(-90 220 220)"
          style={{filter:`drop-shadow(0 0 10px ${hexA(accent,0.7)})`}}/>
      </svg>
      {label?<div style={{position:"absolute",transform:"translateY(250px)",fontFamily,fontWeight:700,fontSize:34,color:accent,textTransform:"uppercase"}}>{label}</div>:null}
    </AbsoluteFill>
  );
};

// ---------- ELEMENTOS EXPRESIVOS (declared_only: geometria y tratamiento, nunca contenido) ----------

// Punch de foco sobre media real: oscurece el frame y abre un spotlight animado
// sobre la zona declarada (target_x/target_y en 0-100). No inventa contenido:
// solo dirige la mirada a algo que YA esta en el media.
export const FocusPunch: React.FC<any> = ({target_x, target_y, radius = 300, label, color, accent}) => {
  const f = useCurrentFrame(); const {fps, durationInFrames} = useVideoConfig();
  const x = Math.max(4, Math.min(96, Number(target_x) || 50));
  const y = Math.max(4, Math.min(96, Number(target_y) || 50));
  const r0 = Math.max(140, Math.min(480, Number(radius) || 300));
  const pIn = spring({frame: f, fps, config: {damping: 15, mass: 0.7}});
  const out = interpolate(f, [Math.max(1, durationInFrames - 10), durationInFrames], [1, 0], C);
  const r = interpolate(pIn, [0, 1], [r0 * 1.9, r0]);
  const dark = 0.55 * Math.min(1, f / 8);
  const px = (x / 100) * 1080; const py = (y / 100) * 1920;
  const labelLeft = x > 55;
  return (
    <AbsoluteFill style={{pointerEvents: "none", opacity: out}}>
      <AbsoluteFill style={{background: `radial-gradient(circle ${Math.round(r)}px at ${x}% ${y}%, transparent ${Math.round(r * 0.72)}px, rgba(0,0,0,${dark}) ${Math.round(r)}px)`}}/>
      <div style={{position: "absolute", left: px - r, top: py - r, width: r * 2, height: r * 2, borderRadius: "50%",
        border: `3px solid ${hexA(accent, 0.9)}`, boxShadow: `0 0 44px ${hexA(accent, 0.35)}, inset 0 0 44px ${hexA(accent, 0.14)}`}}/>
      {label ? <div style={{position: "absolute",
        left: labelLeft ? undefined : Math.min(700, px + r * 0.74),
        right: labelLeft ? Math.min(700, (1080 - px) + r * 0.74) : undefined,
        top: Math.max(140, Math.min(1480, py - 32)),
        background: hexA(THEME.off, 0.95), border: `2px solid ${hexA(accent, 0.5)}`, borderRadius: 14,
        padding: "10px 18px", fontFamily, fontWeight: 800, fontSize: 34, color: THEME.ink,
        textTransform: "uppercase", opacity: pIn, maxWidth: 360}}>{label}</div> : null}
    </AbsoluteFill>
  );
};

// Comparacion lado a lado: dos opciones declaradas con divisor animado y veredicto
// opcional. Los medias vienen de image_slots (roles left/right) resueltos por el
// motor; sin src se muestra un bloque de marca con el label como protagonista.
// Diagrama de profundidad (orientation="vertical"): dos estratos apilados que
// comparten una linea de frontera. Superior = superficie, inferior = profundidad.
// Llena la zona vertical libre (mata el top-heavy/mitad-inferior-muerta que un
// SplitCompare horizontal deja) y comunica "arriba vs mas abajo" por geometria,
// no solo por texto. El estrato inferior (donde empieza el problema) es el verdict.
const DepthDiagram: React.FC<any> = ({top_label, bottom_label, note_top, note_bottom, color, accent, bg, laneBottom = 570, laneTop = 0, durMs = 3000}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const light = isLightHex(bg);
  const inTop = spring({frame: f, fps, config: {damping: 15, mass: 0.7}});
  const inBottom = spring({frame: Math.max(0, f - 7), fps, config: {damping: 15, mass: 0.7}});
  const boundary = interpolate(Math.min(inTop, inBottom), [0, 1], [0, 1], C);
  const revealFrame = Math.round((durMs / 1000) * fps * 0.55);
  const focus = interpolate(f, [revealFrame, revealFrame + 12], [0, 1], C);
  const W = 812;
  const topH = 300, botH = 372;
  const inkTop = light ? THEME.ink : color;
  const band = (isTop: boolean) => {
    const label = isTop ? top_label : bottom_label;
    const note = isTop ? note_top : note_bottom;
    const enter = isTop ? inTop : inBottom;
    const dy = (isTop ? -1 : 1) * (1 - enter) * 60;
    // El estrato profundo es el verdict: se resalta; el superficial se atenua al revelarse.
    const hot = !isTop;
    const dim = isTop ? 1 - 0.28 * focus : 1;
    const glow = hot ? focus : 0;
    return (
      <div style={{width: W, height: isTop ? topH : botH, transform: `translateY(${dy}px)`, opacity: Math.min(1, enter) * dim,
        borderRadius: isTop ? "26px 26px 0 0" : "0 0 26px 26px",
        border: `${hot ? 3 : 2}px solid ${hot && glow > 0 ? accent : hexA(color, light ? 0.16 : 0.24)}`,
        borderTopWidth: isTop ? undefined : 0,
        background: isTop
          ? (light ? `linear-gradient(180deg,${hexA(THEME.off, 0.92)},${hexA(THEME.off, 0.66)})` : `linear-gradient(180deg,${hexA(THEME.panel, 0.7)},${hexA(THEME.panel, 0.5)})`)
          : (light ? `linear-gradient(180deg,${hexA(color, 0.10)},${hexA(color, 0.20)})` : `linear-gradient(180deg,${hexA(bg, 0.55)},${hexA(bg, 0.8)})`),
        boxShadow: hot && glow > 0 ? `0 24px 60px ${hexA(accent, 0.28 * glow)}` : "none",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: "0 40px"}}>
        <div style={{fontFamily, fontWeight: 800, fontSize: 68, lineHeight: 1.0, textTransform: "uppercase", textAlign: "center",
          color: hot && glow > 0 ? accent : hexA(inkTop, 0.9)}}>{label}</div>
        {note ? <div style={{fontFamily, fontWeight: 600, fontSize: 27, lineHeight: 1.12, textAlign: "center",
          color: hexA(inkTop, 0.55)}}>{note}</div> : null}
      </div>
    );
  };
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", paddingBottom: laneBottom, paddingTop: laneTop, pointerEvents: "none"}}>
      <div style={{position: "relative", display: "flex", flexDirection: "column", alignItems: "center"}}>
        {band(true)}
        {/* Linea de frontera: hasta aqui llega la superficie; debajo empieza el problema. */}
        <div style={{position: "absolute", top: topH - 3, left: -18, width: W + 36, height: 6, borderRadius: 6,
          background: accent, opacity: 0.85 * boundary, transform: `scaleX(${boundary})`,
          boxShadow: `0 0 26px ${hexA(accent, 0.5)}`}}/>
        {band(false)}
      </div>
    </AbsoluteFill>
  );
};

export const SplitCompare: React.FC<any> = ({left_label, right_label, image_slots, verdict, orientation, note_top, note_bottom, color, accent, bg, laneBottom = 570, laneTop = 0, durMs = 3000, onMedia = false}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const light = isLightHex(bg);
  if (orientation === "vertical") {
    return <DepthDiagram top_label={left_label} bottom_label={right_label} note_top={note_top} note_bottom={note_bottom}
      color={color} accent={accent} bg={bg} laneBottom={laneBottom} laneTop={laneTop} durMs={durMs}/>;
  }
  const slots = Array.isArray(image_slots) ? image_slots : [];
  const srcFor = (role: string) => slots.find((s: any) => s && s.role === role && s.src)?.src;
  const inL = spring({frame: f, fps, config: {damping: 15, mass: 0.7}});
  const inR = spring({frame: Math.max(0, f - 6), fps, config: {damping: 15, mass: 0.7}});
  const verdictFrame = Math.round((durMs / 1000) * fps * 0.62);
  const hasVerdict = verdict === "left" || verdict === "right";
  const v = hasVerdict ? interpolate(f, [verdictFrame, verdictFrame + 10], [0, 1], C) : 0;
  const divH = interpolate(Math.min(inL, inR), [0, 1], [0, 620]);
  const panel = (side: "left" | "right") => {
    const win = verdict === side;
    // Jerarquia PERSISTENTE: antes del veredicto el lado ganador ya trae un hint
    // de acento y el perdedor un leve recess, para que el frame NUNCA sea "dos
    // cajas identicas compitiendo" (rubrica: dos piezas del mismo peso = major,
    // hallado en render real). El punch del veredicto (dim+borde full+check) sigue.
    const preHint = hasVerdict && win ? 1 : 0;
    const loserRecess = hasVerdict && !win ? 0.93 : 1;
    // Sobre media (foto/video), bajar la opacidad del panel perdedor deja ver la
    // foto A TRAVES del panel (cara de la persona asomando detras del texto,
    // hallado en revision de render real) -- el dim de casi 50% asume un fondo
    // neutro, no una foto de fondo. Sobre media, recess leve sin transparencia.
    const dim = onMedia
      ? (hasVerdict && !win ? 0.88 : 1)
      : (v > 0 && !win ? 1 - 0.45 * v : 1) * loserRecess;
    const lift = v > 0 && win ? -10 * v : 0;
    const src = srcFor(side);
    const label = side === "left" ? left_label : right_label;
    const enter = side === "left" ? inL : inR;
    const shift = side === "left" ? -(1 - enter) * 140 : (1 - enter) * 140;
    const winBorder = v > 0 && win;
    return (
      <div style={{width: 452, transform: `translateX(${shift}px) translateY(${lift}px)`, opacity: Math.min(1, enter) * dim,
        display: "flex", flexDirection: "column", alignItems: "center", gap: 18}}>
        <div style={{width: 452, height: 452, borderRadius: 26, overflow: "hidden",
          border: `3px solid ${winBorder ? accent : hexA(color, (light ? 0.14 : 0.22) + preHint * 0.18)}`,
          boxShadow: winBorder ? `0 24px 60px ${hexA(accent, 0.30)}` : "0 18px 44px rgba(0,0,0,0.20)",
          background: light ? THEME.off : hexA(THEME.panel, 0.8),
          display: "flex", alignItems: "center", justifyContent: "center"}}>
          {src
            ? <Img src={resolveSrc(src)} style={{width: "100%", height: "100%", objectFit: "cover"}}/>
            : <div style={{fontFamily, fontWeight: 800, fontSize: 52, textAlign: "center", padding: "0 26px",
                textTransform: "uppercase", lineHeight: 1.04,
                color: winBorder ? accent : hexA(light ? THEME.ink : color, 0.82)}}>{label}</div>}
        </div>
        {src ? <div style={{background: winBorder ? accent : (light ? hexA(THEME.off, 0.96) : hexA(THEME.panel, 0.92)),
          border: `2px solid ${hexA(accent, winBorder ? 0.9 : 0.35)}`, borderRadius: 16, padding: "12px 22px",
          fontFamily, fontWeight: 800, fontSize: 36, textTransform: "uppercase",
          color: winBorder ? (isLightHex(accent) ? THEME.ink : "#ffffff") : (light ? THEME.ink : color)}}>{label}</div>
        : winBorder ? <div style={{width: 46, height: 46, borderRadius: "50%", background: accent, color: isLightHex(accent) ? THEME.ink : "#ffffff",
            display: "flex", alignItems: "center", justifyContent: "center", fontFamily, fontWeight: 800, fontSize: 28,
            boxShadow: `0 10px 26px ${hexA(accent, 0.4)}`}}>{"✓"}</div> : null}
      </div>
    );
  };
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", paddingBottom: laneBottom, paddingTop: laneTop, pointerEvents: "none"}}>
      <div style={{display: "flex", alignItems: "center", gap: 34}}>
        {panel("left")}
        <div style={{width: 4, height: divH, borderRadius: 4, background: `linear-gradient(180deg,transparent,${hexA(accent, 0.75)},transparent)`}}/>
        {panel("right")}
      </div>
    </AbsoluteFill>
  );
};

// Texto cinetico full-bleed: palabras gigantes secuenciales ancladas a la voz via
// item_anchors -> itemMs. Una palabra a la vez, con punch y barra de acento. Para
// golpes ritmicos sostenidos donde KeywordPop (0.6-1.2s) queda corto.
export const BigWordSequence: React.FC<any> = ({words, offsets, color, accent, bg, laneBottom = 570, laneTop = 0}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const light = isLightHex(bg);
  const list = (Array.isArray(words) ? words : []).map((w: any) => String(w));
  if (!list.length) return null;
  const offs: number[] = Array.isArray(offsets) && offsets.length === list.length ? offsets : list.map((_: string, i: number) => i * 700);
  const tMs = (f / fps) * 1000;
  let idx = 0; for (let i = 0; i < list.length; i++) { if (offs[i] <= tMs) idx = i; else break; }
  // La PRIMERA palabra se muestra desde el inicio del overlay (f=0), no desde
  // offs[0]. Antes se hacia return null hasta offs[0], que en escenas donde el
  // primer item llega tarde dejaba el panel vacio varios segundos (bug real en
  // render). offs solo debe gobernar las TRANSICIONES entre palabras, no la
  // aparicion de la primera.
  const wordStartMs = idx === 0 ? 0 : offs[idx];
  const local = ((tMs - wordStartMs) / 1000) * fps;
  const pIn = spring({frame: Math.max(0, local), fps, config: {damping: 11, mass: 0.55}});
  const word = list[idx];
  const size = word.length <= 5 ? 200 : word.length <= 8 ? 150 : word.length <= 12 ? 110 : 84;
  const tilt = (idx % 2 === 0 ? -1 : 1) * (2.2 - 1.6 * Math.min(1, pIn));
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", paddingBottom: laneBottom, paddingTop: laneTop, pointerEvents: "none"}}>
      {/* Piso de opacidad 0.7 (antes 0.25): una palabra a 25% se leia como fantasma
          roto; la palabra dominante debe estar SIEMPRE legible cuando esta en pantalla. */}
      <div style={{transform: `scale(${0.86 + 0.14 * pIn}) rotate(${tilt}deg)`, opacity: Math.min(1, 0.7 + 0.3 * pIn), textAlign: "center", maxWidth: 960}}>
        <div style={{fontFamily, fontWeight: 800, fontSize: size, lineHeight: 0.98, textTransform: "uppercase",
          color: light ? THEME.ink : color,
          textShadow: light ? "0 2px 0 rgba(255,255,255,0.6)" : "0 10px 34px rgba(0,0,0,0.5)"}}>{word}</div>
        <div style={{height: 10, width: `${Math.min(100, 34 + word.length * 6)}%`, margin: "18px auto 0", borderRadius: 8,
          background: accent, transform: `scaleX(${pIn})`, boxShadow: `0 0 26px ${hexA(accent, 0.4)}`}}/>
      </div>
    </AbsoluteFill>
  );
};
