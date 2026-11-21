import React from "react";
import {AbsoluteFill, useCurrentFrame, useVideoConfig, spring} from "remotion";
import {THEME, hexA, fontFamily, isLightHex} from "../theme";

const SPANISH_PUBLIC_FIXES: Record<string,string> = {
  tecnica: "técnica",
  despues: "después",
  evaluacion: "evaluación",
  operacion: "operación",
  articulacion: "articulación",
  repeticion: "repetición",
  porcion: "porción",
};
export const publicText = (value:any) => {
  let out=String(value ?? "");
  for (const [plain, accented] of Object.entries(SPANISH_PUBLIC_FIXES)) {
    out=out.replace(new RegExp(`\\b${plain}\\b`,"gi"), (m)=>m===m.toUpperCase()?accented.toUpperCase():accented);
  }
  return out;
};

export const Cta: React.FC<any> = ({text,button,resource_title,resource_points,resource_footer,mockup_type,color,accent,bg}) => {
  const f=useCurrentFrame(); const {fps}=useVideoConfig();
  const light=isLightHex(bg);
  const s=spring({frame:f+6,fps,config:{damping:14,mass:0.65}}); const s2=spring({frame:f+2,fps,config:{damping:12,mass:0.65}});
  const pulse=1+0.04*Math.sin(f/6);
  const points = Array.isArray(resource_points) && resource_points.length ? resource_points : [];
  const title = publicText(resource_title || text);
  const body = resource_title ? publicText(text) : "";
  const kind = mockup_type || (points.length ? "checklist" : "card");
  return (
    <AbsoluteFill style={{background:THEME.cream}}>
      <AbsoluteFill style={{background:`radial-gradient(80% 52% at 50% 20%, ${hexA(accent,0.22)}, transparent 62%)`}}/>
      <AbsoluteFill style={{justifyContent:"center",alignItems:"center",gap:42}}>
        <div style={{
          width:760,
          minHeight:900,
          background:THEME.off,
          borderRadius:30,
          border:"2px solid rgba(0,0,0,0.08)",
          boxShadow:"0 28px 90px rgba(0,0,0,0.22)",
          padding:"72px 64px",
          transform:`translateY(${(1-s)*26}px) rotate(${(1-s)*-1}deg)`,
          opacity:0.82+0.18*s,
        }}>
          <div style={{height:10,width:160,background:accent,borderRadius:8,marginBottom:30}}/>
          <div style={{fontFamily,fontWeight:800,fontSize:52,lineHeight:1.04,color:THEME.ink,textTransform:"uppercase",marginBottom:18}}>
            {title}
          </div>
          {kind !== "none" && points.length ? (
            <div style={{display:"flex",flexDirection:"column",gap:22,marginTop:38}}>
              {points.slice(0,5).map((p:string,i:number)=> {
                const row=spring({frame:f+2-i*2,fps,config:{damping:14,mass:0.65}});
                return (
                  <div key={i} style={{display:"flex",alignItems:"center",gap:20,opacity:row,transform:`translateX(${(1-row)*-34}px)`}}>
                    <div style={{width:54,height:54,borderRadius:14,background:i<3?accent:"rgba(0,0,0,0.08)",display:"flex",alignItems:"center",justifyContent:"center",
                      color:THEME.off,fontFamily,fontWeight:800,fontSize:34,boxShadow:i<3?`0 0 18px ${hexA(accent,0.3)}`:"none"}}>
                      {i<3 ? "✓" : ""}
                    </div>
                    <div style={{fontFamily,fontWeight:800,fontSize:34,lineHeight:1.08,color:THEME.ink,textTransform:"uppercase"}}>
                      {publicText(p)}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            body ? <div style={{fontFamily,fontWeight:800,fontSize:34,lineHeight:1.08,color:hexA(THEME.ink,0.72),textTransform:"uppercase",marginTop:34}}>
              {body}
            </div> : null
          )}
          {resource_footer ? (
            <>
              <div style={{height:2,width:"100%",background:"rgba(0,0,0,0.1)",marginTop:58}}/>
              <div style={{fontFamily,fontWeight:800,fontSize:28,color:accent,textTransform:"uppercase",marginTop:22}}>
                {publicText(resource_footer)}
              </div>
            </>
          ) : null}
        </div>
        {/* Boton CTA: en tema OSCURO usaba background=THEME.darkGreen (verde
            oscuro) + color=bg (casi negro) -> texto oscuro sobre boton oscuro,
            casi ilegible (hallado en render real del reel en tema oscuro). El
            boton es la accion principal: debe ser el elemento de MAYOR contraste.
            Ahora usa el accent brillante de fondo con texto oscuro (bg) en tema
            oscuro, y tinta/crema en tema claro. */}
        <div style={{fontFamily,fontWeight:800,fontSize:48,color:light?THEME.cream:bg,background:light?THEME.ink:accent,padding:"22px 46px",borderRadius:999,
          transform:`scale(${s2*pulse})`,boxShadow:`0 0 40px ${hexA(accent,0.55)}`,textTransform:"uppercase"}}>{publicText(button)}</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
