import React from "react";
import {Composition} from "remotion";
import {Reel} from "./Reel";
import {ReelProps} from "./types";
import {Longform} from "./Longform";
import type {LongformProps} from "./longform-types";
import input from "../input.example.json";

export const RemotionRoot: React.FC = () => {
  const longformDefaults: LongformProps = {
    runId: "default",
    durationMs: 6000,
    audioSrc: "",
    sfx: [],
    musicBeds: [],
    endScreen: undefined,
    showCaptions: false,
    showProgress: false,
    brand: {ink: "#FFFFFF", cream: "#0A0A0A", teal: "#FFFFFF", gold: "#FF7A17", red: "#FF7A17", fontDisplay: '"Inter", Arial, sans-serif', fontBody: '"Inter", Arial, sans-serif'},
    theme: {background: "#0A0A0A", surface: "#191919", text: "#FFFFFF", body: "#DADBDF", muted: "#7D8187", hairline: "#212327", accent: "#FFFFFF", accentSecondary: "#7C3AED", highlight: "#FF7A17", danger: "#FF7A17", fontDisplay: '"Inter", Arial, sans-serif', fontBody: '"Inter", Arial, sans-serif', fontMono: '"Geist Mono", Consolas, monospace', typography: {displayWeight: 400, bodyWeight: 400, labelWeight: 400, displayLetterSpacing: 0, labelLetterSpacing: 0, uppercaseLabels: true}, composition: {density: "balanced", edgePadding: 64, panelGap: 32, cardRadius: 8, splitRatio: .5}, motion: {transitionFrames: 12, entrance: "rise", emphasis: "focus", intensity: .55}, rendering: {spatialMode: "flat", surfaceStyle: "solid", allowThree: false, allowWebgl: false, allowCanvas: false, allowShaders: false, allowParticles: false}, effects: {useShadows: false, useGradients: false, borderStyle: "hairline"}, profileId: "frontier-dark-v1"},
    designProfile: {},
    shots: [{shotId: "default", chapterId: "C01", startMs: 0, endMs: 6000, visualKind: "motion-card", source: "", mediaType: "card", sourceInMs: 0, sourceOutMs: 0, screenCopy: "Longform", subcopy: "Post-script production engine", cardVariant: "chapter"}],
    captions: [],
  };
  return (
    <>
      <Composition
        id="Reel"
        component={Reel}
        durationInFrames={240}
        fps={(input as ReelProps).fps}
        width={(input as ReelProps).width}
        height={(input as ReelProps).height}
        defaultProps={input as ReelProps}
        calculateMetadata={({props}) => {
          const p = props as ReelProps;
          const fps = p.fps || 30;
          return {durationInFrames: Math.max(1, Math.round((p.totalMs / 1000) * fps)), fps, width: p.width || 1080, height: p.height || 1920};
        }}
      />
      <Composition
        id="Longform"
        component={Longform}
        durationInFrames={180}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={longformDefaults}
        calculateMetadata={({props}) => ({durationInFrames: Math.max(1, Math.ceil(((props as LongformProps).durationMs / 1000) * 30)), fps: 30, width: 1920, height: 1080, props})}
      />
    </>
  );
};
