import React from "react";
import {AbsoluteFill, staticFile} from "remotion";
import {loadFont as loadPlusJakarta} from "@remotion/google-fonts/PlusJakartaSans";
import {loadFont as loadInter} from "@remotion/google-fonts/Inter";
import {loadFont as loadMontserrat} from "@remotion/google-fonts/Montserrat";
import {loadFont as loadBebas} from "@remotion/google-fonts/BebasNeue";
import {loadFont as loadOswald} from "@remotion/google-fonts/Oswald";
import {loadFont as loadPlayfair} from "@remotion/google-fonts/PlayfairDisplay";
import {loadFont as loadAnton} from "@remotion/google-fonts/Anton";
import type {ReelProps} from "./types";

export const FONT_FAMILIES: Record<string, string> = {
  plus_jakarta: "Plus Jakarta Sans, Arial, sans-serif",
  inter: "Inter, Arial, sans-serif",
  montserrat: "Montserrat, Arial, sans-serif",
  bebas: "Bebas Neue, Impact, sans-serif",
  oswald: "Oswald, Arial Narrow, sans-serif",
  playfair: "Playfair Display, Georgia, serif",
  anton: "Anton, Impact, sans-serif",
};
let reelFontsLoaded=false;
export const ensureReelFonts=()=>{
  if(reelFontsLoaded)return;
  reelFontsLoaded=true;
  FONT_FAMILIES.plus_jakarta=loadPlusJakarta("normal", {weights: ["500", "700", "800"], subsets: ["latin"]}).fontFamily;
  FONT_FAMILIES.inter=loadInter("normal", {weights: ["500", "700", "800"], subsets: ["latin"]}).fontFamily;
  FONT_FAMILIES.montserrat=loadMontserrat("normal", {weights: ["500", "700", "800"], subsets: ["latin"]}).fontFamily;
  FONT_FAMILIES.bebas=loadBebas("normal", {weights: ["400"], subsets: ["latin"]}).fontFamily;
  FONT_FAMILIES.oswald=loadOswald("normal", {weights: ["500", "700"], subsets: ["latin"]}).fontFamily;
  FONT_FAMILIES.playfair=loadPlayfair("normal", {weights: ["700", "800"], subsets: ["latin"]}).fontFamily;
  FONT_FAMILIES.anton=loadAnton("normal", {weights: ["400"], subsets: ["latin"]}).fontFamily;
};
export const fontFamily = "var(--reel-font)";
export const resolveSrc = (m: string) => (/^https?:\/\//.test(m) ? m : staticFile(m));
export const isVideo = (m: string) => /\.(mp4|mov|webm|m4v)(\?|$)/i.test(m);
export const C = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};
export const hexA = (hex: string, a: number) => {
  if (!/^#?[0-9A-Fa-f]{6}$/.test(hex)) return `color-mix(in srgb, ${hex} ${Math.round(a*100)}%, transparent)`;
  const n = hex.replace("#", "");
  const r = parseInt(n.slice(0,2),16), g = parseInt(n.slice(2,4),16), b = parseInt(n.slice(4,6),16);
  return `rgba(${r},${g},${b},${a})`;
};
export const THEME = {
  cream: "var(--reel-cream)",
  off: "var(--reel-off)",
  green: "var(--reel-accent)",
  teal: "var(--reel-secondary)",
  darkGreen: "var(--reel-panel)",
  red: "var(--reel-danger)",
  purple: "var(--reel-accent)",
  magenta: "var(--reel-secondary)",
  yellow: "var(--reel-warning)",
  ink: "var(--reel-ink)",
  muted: "var(--reel-muted)",
  panel: "var(--reel-panel)",
};
export const hx = (c?: string, fallback = "#000000") => c ? (c.startsWith("#") ? c : `#${c}`) : fallback;
const colorLuma = (hex?: string) => {
  if (!hex || !/^#?[0-9A-Fa-f]{6}$/.test(hex)) return 0.5;
  const n = hex.replace("#", "");
  const r = parseInt(n.slice(0, 2), 16) / 255;
  const g = parseInt(n.slice(2, 4), 16) / 255;
  const b = parseInt(n.slice(4, 6), 16) / 255;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const isLightHex = (hex?: string) => colorLuma(hex) >= 0.55;

export const resolveStyleVars = (props: ReelProps): React.CSSProperties => {
  const p = props.style?.palette || {};
  const light = props.style?.base_theme === "light";
  const bg = hx(p.bg, props.brand.bg);
  const fg = hx(p.fg, props.brand.fg);
  const accent = hx(p.accent, props.brand.accent);
  const warning = hx(p.warning, "#B08A2E");
  const font = FONT_FAMILIES[props.style?.font || "inter"] || FONT_FAMILIES.plus_jakarta;
  return {
    ["--reel-font" as any]: font,
    ["--reel-bg" as any]: bg,
    ["--reel-fg" as any]: fg,
    ["--reel-accent" as any]: accent,
    ["--reel-secondary" as any]: hx(p.secondary, "#3AAD8E"),
    ["--reel-danger" as any]: light ? warning : hx(p.danger, "#C0392B"),
    ["--reel-warning" as any]: warning,
    ["--reel-panel" as any]: hx(p.panel, light ? "#FFFFFF" : bg),
    ["--reel-cream" as any]: hx(p.cream, "#F0EDE6"),
    ["--reel-off" as any]: hx(p.off, "#F5F3EE"),
    ["--reel-ink" as any]: hx(p.ink, "#0D0D0D"),
    ["--reel-muted" as any]: hx(p.muted, "#6B6860"),
  } as React.CSSProperties;
};

// ---------- pista visual base ----------
export const DottedTexture: React.FC<{opacity?: number; color?: string}> = ({opacity = 0.22, color = "#ffffff"}) =>
  React.createElement(AbsoluteFill, {
    style: {
      opacity,
      backgroundImage: `radial-gradient(circle, ${hexA(color, 0.42)} 1.2px, transparent 1.3px)`,
      backgroundSize: "24px 24px",
      maskImage: "linear-gradient(180deg, transparent, black 14%, black 82%, transparent)",
    },
  });
