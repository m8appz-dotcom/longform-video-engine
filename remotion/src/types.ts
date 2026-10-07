export type Caption = { word: string; startMs: number; endMs: number };
export type OverlayComponent =
  | "StoryArcChart"
  | "CountUp"
  | "StatRing"
  | "StepList"
  | "CausalMeter"
  | "ObjectCallout"
  | "KeywordPop"
  | "LowerThird"
  | "Annotation"
  | "ChapterDots"
  | "FocusPunch"
  | "SplitCompare"
  | "BigWordSequence";
export type Scene = {
  role: "hook" | "broll" | "avatar" | "plate";
  source?: "asset" | "google" | "pexels" | "clip_extractor" | "kreado" | "image" | "none" | string;
  media?: string;
  fromMs: number;
  toMs: number;
  motion?: string;
  layout?: "full_bleed" | "full_frame" | "diagram" | "split" | "card" | "cta";
  plate_purpose?: "diagnosis_card" | "stat_card" | "rule_checklist" | "quantity_diagram" | "decision_card" | "cta_resource" | "chapter" | "none";
  visual_mode?: "concrete" | "diagrammatic" | "kinetic_text" | "media_backed" | "cta";
  visual_family?: "hook_spectacle" | "diagnostic_flow" | "criteria_gate" | "rule_cards" | "concrete_proof" | "action_proof" | "quantity_control" | "cta_document" | "avatar_human" | "chapter" | string;
  why_this_visual_not_other?: string;
  editorial_point?: string;
  why_it_matters?: string;
  visual_proof?: string;
  coverage_required?: boolean;
  avatar_key?: string;
  avatarCompanionMedia?: string;
  avatarCompanionMotion?: string;
  avatarCompanionPrompt?: string;
  avatarCompanionSource?: "asset" | "clip_extractor" | "pexels" | "image" | "motion" | string;
  avatarCompanionLabel?: string;
  transition_in?: string;
  caption_position?: "center_low" | "bottom" | "top";
  avatar_layout?: "split_h" | "frame_low" | "overlay_pip";
  treatment?: "none" | "vignette" | "spotlight" | "duotone_brand";
  intent?: string;
  visual_targets?: string[];
  max_duration_ms?: number;
  visualBeats?: VisualBeat[];
};
export type Overlay = {
  type: string;
  component: OverlayComponent | string;
  startMs: number;
  durMs: number;
  params: any;
  itemMs?: number[] | null;
  toolbox?: string[];
  rationale?: string;
  semantic_kind?: "process" | "number" | "list" | "emphasis" | "label" | "object_callout" | "chapter";
  placement?: "safe_top" | "safe_center" | "safe_lower" | "left_callout" | "right_callout" | "full_context";
  must_not_cover?: ("caption" | "face" | "subject" | "hook_subject" | "cta" | "data")[];
  safe_zone?: "top" | "center" | "bottom" | "full" | "left" | "right";
  max_duration_ms?: number;
  blocks_captions?: boolean;
};
export type Sfx = { id: string; atMs: number; gain?: number; auto?: boolean; allow_stack?: boolean };
export type VisualBeat = {
  atMs: number;
  action?: "new_media" | "crop_reframe" | "component_state" | "layout_swap" | "callout_target" | "insert_card" | string;
  semantic_delta?: string;
  target?: string;
  label?: string;
  source?: "explicit" | "props" | string;
  sceneIndex?: number;
  strength?: "soft" | "medium" | string;
  semantic?: boolean;
};
export type PacingBeat = {
  atMs: number;
  kind?: "hook_interrupt" | "reframe" | "accent_wipe" | "zoom_punch" | "focus_pulse" | "layout_shift" | "callout_pulse" | string;
  source?: "auto" | "explicit" | "props" | string;
  sceneIndex?: number;
  strength?: "soft" | "medium" | string;
  semantic?: boolean;
  cosmetic?: boolean;
};
export type VisualStyle = {
  font?: "plus_jakarta" | "inter" | "montserrat" | "bebas" | "oswald" | "playfair" | "anton" | string;
  base_theme?: "light" | "dark" | "mixed";
  background_role?: "cream" | "white" | "dark" | "image" | "mixed";
  caption_style?: "word_pop" | "boxed" | "minimal" | "none";
  caption_emphasis_policy?: "smart_stopwords" | "all_equal" | "minimal_stopwords";
  caption_granularity?: "word";
  caption_decoration?: "none" | "underline";
  caption_position?: "center_low" | "bottom" | "top";
  caption_readability_mode?: "adaptive_boxed" | "high_contrast_boxed";
  render_policy?: "declared_only";
  plate_layout?: "auto" | "none";
  graphic_style?: "clean" | "editorial" | "kinetic" | "documentary" | "minimal" | string;
  hook_overlay?: "none" | "spectacle";
  hook_label?: string;
  hook_text_zone?: "top_clean" | "center_clean" | "bottom_clean" | "auto";
  progress_bar?: "none" | "accent" | "warning";
  texture?: "none" | "subtle" | "dotted";
  style_source?: {
    url?: string;
    notes?: string;
    extracted_guidelines?: string[];
  };
  palette?: {
    bg?: string;
    fg?: string;
    accent?: string;
    secondary?: string;
    danger?: string;
    warning?: string;
    panel?: string;
    cream?: string;
    off?: string;
    ink?: string;
    muted?: string;
  };
};
export type ReelProps = {
  width: number; height: number; fps: number; totalMs: number;
  providerMode?: "mock" | "real" | string;
  policies?: {
    avatar_policy?: string;
    media_policy?: string;
    media_min_scenes?: number;
    avatar_clip_reuse?: boolean;
    render_policy?: "declared_only" | string;
  };
  brand: { bg: string; fg: string; accent: string };
  style?: VisualStyle;
  hook?: { headline?: string; hookEndMs?: number; poster?: string };
  captions: Caption[];
  scenes: Scene[];
  overlays?: Overlay[];
  visualBeats?: VisualBeat[];
  pacingBeats?: PacingBeat[];
  sfx?: Sfx[];
  cta?: {
    text: string;
    button: string;
    fromMs: number;
    resource_title?: string;
    resource_points?: string[];
    mockup_type?: "card" | "checklist" | "document" | "comment" | "none";
    visual_style?: string;
  };
  audio?: string;
};
