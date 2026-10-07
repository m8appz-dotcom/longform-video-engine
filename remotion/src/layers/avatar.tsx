import React from "react";
import {AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig, interpolate, spring} from "remotion";
import {THEME, hexA, isLightHex, DottedTexture, fontFamily, C} from "../theme";
import {AVATAR_COMPANION_H, AVATAR_CAPTION_BAND_H, AVATAR_H} from "../generated";
import {Scene} from "../types";
import {FramedMedia} from "./surfaces";

// Motion graphics REAL para la mitad superior del avatar (companion.source="motion").
// Antes 'motion' devolvia media vacia y el render caia al chip-placeholder de
// FramedMedia (parecia un bug de debug). Ahora rendereamos un fondo de marca
// ANIMADO + la tipografia del concepto clave de la escena (el label del companion):
// anillos de acento rotando, un orbe en movimiento y las palabras entrando con
// spring. Es la alternativa declarada al broll cuando no hay foto/clip que aporte
// (mandato: "arriba broll O motion graphics"). Cero media externa, cero texto
// inventado: el label ya sale de visual_targets/anchor declarados.
export const MotionGraphicsCompanion: React.FC<{
  label?: string;
  color: string;
  accent: string;
  bg: string;
}> = ({label, color, accent, bg}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const light = isLightHex(bg);
  const words = (label || "")
    .split(/\s*\+\s*|\s{2,}/)
    .map((w) => w.trim())
    .filter(Boolean)
    .slice(0, 3);
  const draw = interpolate(frame, [0, Math.round(fps * 1.2)], [0, 1], C);
  const ink = light ? THEME.ink : color;
  return (
    <AbsoluteFill style={{
      overflow: "hidden",
      background: light
        ? `linear-gradient(150deg, ${THEME.cream}, ${THEME.off})`
        : `radial-gradient(120% 90% at 50% 22%, ${hexA(accent, 0.20)}, ${bg} 72%)`,
    }}>
      <DottedTexture color={ink} opacity={light ? 0.03 : 0.08}/>
      <svg width="1080" height={AVATAR_COMPANION_H} viewBox={`0 0 1080 ${AVATAR_COMPANION_H}`}
        style={{position: "absolute", inset: 0, overflow: "visible"}}>
        {[0, 1, 2].map((i) => (
          <ellipse key={i} cx="540" cy={AVATAR_COMPANION_H * 0.34} rx={220 + i * 120} ry={110 + i * 66}
            fill="none" stroke={hexA(accent, 0.10 + i * 0.03)} strokeWidth="2.5"
            strokeDasharray={`${120 + i * 40} ${40 + i * 12}`}
            transform={`rotate(${(frame * 0.15 + i * 40) % 360} 540 ${AVATAR_COMPANION_H * 0.34})`}/>
        ))}
        <circle cx={540 + Math.sin(frame / 22) * 180} cy={AVATAR_COMPANION_H * 0.28 + Math.cos(frame / 20) * 40}
          r={14} fill={accent} opacity={0.72}/>
      </svg>
      <div style={{
        position: "absolute", inset: 0, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 16, padding: "0 80px",
      }}>
        {words.map((w, i) => {
          const s = Math.max(0, spring({frame: frame - 6 - i * 6, fps, config: {damping: 14, mass: 0.6}}));
          return (
            <div key={w + i} style={{
              fontFamily, fontWeight: 800, textTransform: "uppercase",
              fontSize: words.length > 2 ? 74 : 92, lineHeight: 1.0,
              color: i === 0 ? ink : accent,
              opacity: s,
              transform: `translateY(${(1 - s) * 30}px)`,
              textAlign: "center",
              textShadow: light ? "0 2px 0 rgba(255,255,255,0.7)" : "0 8px 26px rgba(0,0,0,0.5)",
            }}>{w}</div>
          );
        })}
        <div style={{
          marginTop: 8, height: 6, borderRadius: 6, width: 360 * draw,
          background: `linear-gradient(90deg, transparent, ${accent}, transparent)`,
        }}/>
      </div>
    </AbsoluteFill>
  );
};

export const companionForAvatar = (scene: Scene): Scene | undefined =>
  scene.avatarCompanionMedia || scene.avatarCompanionSource === "motion" || scene.avatarCompanionLabel
    ? {...scene, media: scene.avatarCompanionMedia, motion: scene.avatarCompanionMotion || "static", visual_targets: scene.avatarCompanionLabel ? [scene.avatarCompanionLabel] : scene.visual_targets || []}
    : undefined;

// Geometria del avatar (mandato del dueño): mitad superior broll/motion graphics,
// franja de captions en el medio, y el avatar 16:9 EXACTO abajo (1080xAVATAR_H).
// La causa historica del "se veia montado" era meter un clip 16:9 en una banda
// 1080x960 con objectFit:cover + objectPosition fijo "44% 18%", perdiendo ~37%
// horizontal y descentrando la cara. Ahora la banda del avatar ES 16:9 y el clip
// se compone con objectFit:contain -> jamas se recorta la cara, aunque Kreado
// devuelva una resolucion que no sea 16:9 perfecto (mostraria bandas neutras, no
// recorte). Constantes en shared/core.json via codegen: render, validador y
// captions miden lo mismo. El avatar sale exactamente AVATAR_APPEARANCES veces.
//
// Layouts:
// - split_h (default, el del mandato): companion arriba, caption band, avatar 16:9 abajo.
// - frame_low: alias de geometria (mismo esquema; el companion domina por altura).
// - overlay_pip: companion full-bleed + avatar en PiP 16:9 arriba a la derecha.
const AVATAR_TOP = AVATAR_COMPANION_H + AVATAR_CAPTION_BAND_H; // inicio de la banda del avatar

export const AvatarSplitFrame: React.FC<{
  scene: Scene;
  companion?: Scene;
  color: string;
  accent: string;
  bg: string;
}> = ({scene, companion, color, accent, bg}) => {
  const light = isLightHex(bg);
  const layout = scene.avatar_layout || "split_h";
  const companionLabel = scene.avatarCompanionLabel || (companion?.visual_targets || []).slice(0, 2).join(" + ");
  // companion.source="motion" -> motion graphics reales en vez del chip-placeholder.
  const companionIsMotion = scene.avatarCompanionSource === "motion" || companion?.motion === "motion_graphic";
  const frameBg = light
    ? `linear-gradient(180deg,${THEME.cream},${THEME.off})`
    : `linear-gradient(160deg,${THEME.panel},${bg})`;
  if (layout === "overlay_pip") {
    // PiP 430x242 ~= 16:9 (1.777); cover no recorta un clip 16:9 -> center center.
    return (
      <AbsoluteFill style={{pointerEvents: "none", background: frameBg, overflow: "hidden"}}>
        {companionIsMotion ? (
          <MotionGraphicsCompanion label={companionLabel} color={color} accent={accent} bg={bg}/>
        ) : (
          <FramedMedia
            media={companion?.media}
            motion={companion?.motion || "static"}
            color={color}
            accent={accent}
            bg={bg}
            objectPosition="center center"
            fallbackLabel={companionLabel}
          />
        )}
        <div style={{
          position: "absolute", right: 36, top: 250, width: 430, height: 242,
          borderRadius: 22, overflow: "hidden",
          border: `3px solid ${hexA(accent, 0.85)}`,
          boxShadow: "0 22px 54px rgba(0,0,0,0.34)",
          background: light ? THEME.panel : bg,
        }}>
          <FramedMedia
            media={scene.media}
            motion="static"
            color={color}
            accent={accent}
            bg={bg}
            objectFit="contain"
            objectPosition="center center"
          />
        </div>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{pointerEvents: "none", background: frameBg, overflow: "hidden"}}>
      <DottedTexture color={light ? THEME.ink : color} opacity={light ? 0.024 : 0.07}/>
      {/* Companion (broll o motion graphics): mitad superior. */}
      <div style={{
        position: "absolute",
        left: 0, top: 0, width: 1080, height: AVATAR_COMPANION_H,
        overflow: "hidden",
        background: light ? THEME.panel : hexA(color,0.08),
      }}>
        {companionIsMotion ? (
          <MotionGraphicsCompanion label={companionLabel} color={color} accent={accent} bg={bg}/>
        ) : (
          <FramedMedia
            media={companion?.media}
            motion={companion?.motion || "static"}
            color={color}
            accent={accent}
            bg={bg}
            objectPosition="center center"
            fallbackLabel={companionLabel}
          />
        )}
      </div>
      {/* Franja de captions: fondo de marca; CaptionLayer dibuja aqui durante la
          ventana del avatar (nunca sobre la cara). */}
      <div style={{
        position: "absolute",
        left: 0, top: AVATAR_COMPANION_H, width: 1080, height: AVATAR_CAPTION_BAND_H,
        background: light ? THEME.off : hexA(bg, 0.9),
      }}/>
      {/* Fundido companion->franja: sin esto la union se ve como dos tarjetas
          apiladas (hallado en revision de render real: 'partido en dos'). El
          degradado hace que companion+franja se lean como UN panel continuo. */}
      <div style={{
        position: "absolute",
        left: 0, top: AVATAR_COMPANION_H - 140, width: 1080, height: 140,
        background: `linear-gradient(180deg, transparent, ${light ? THEME.off : hexA(bg, 0.9)})`,
      }}/>
      {/* Barra de acento en la union superior de la banda del avatar. */}
      <div style={{
        position: "absolute",
        left: 0, top: AVATAR_TOP, width: 1080, height: 4,
        background: `linear-gradient(90deg,transparent,${hexA(accent, 0.7)},transparent)`,
      }}/>
      {/* Avatar 16:9 EXACTO, sin recorte (contain). */}
      <div style={{
        position: "absolute",
        left: 0, top: AVATAR_TOP, width: 1080, height: AVATAR_H,
        overflow: "hidden",
        background: light ? THEME.off : bg,
      }}>
        <FramedMedia
          media={scene.media}
          motion="static"
          color={color}
          accent={accent}
          bg={bg}
          objectFit="contain"
          objectPosition="center center"
      />
      </div>
    </AbsoluteFill>
  );
};

export const AvatarLayer: React.FC<{scenes:Scene[];color:string;accent:string;bg:string;fps:number}> = ({scenes,color,accent,bg,fps}) => (
  <>{scenes.map((s,i)=>s.role==="avatar" ? (
    <Sequence key={`avatar-layer-${i}`} from={Math.round(s.fromMs/1000*fps)} durationInFrames={Math.max(1,Math.round((s.toMs-s.fromMs)/1000*fps))} name="avatar-split-layer">
      <AvatarSplitFrame scene={s} companion={companionForAvatar(s)} color={color} accent={accent} bg={bg}/>
    </Sequence>
  ) : null)}</>
);
