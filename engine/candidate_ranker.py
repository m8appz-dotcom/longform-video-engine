from __future__ import annotations

from typing import Any


REAL_PROVIDERS = {"user", "library", "clip_extractor", "pexels"}


def score_candidate(shot: dict[str, Any], provider: str, prefilter: dict[str, Any], *, route_index: int = 0, variant_index: int = 0) -> dict[str, Any]:
    metrics = prefilter.get("metrics") or {}
    quality = float(metrics.get("quality_score") or 50.0)
    proof_kind = str(shot.get("proofKind") or shot.get("mediaNeedKind") or "")
    preferred = str(shot.get("preferredMedium") or "")
    evidence = 30.0
    technical = quality * 0.25
    credibility = 10.0 if provider in REAL_PROVIDERS and proof_kind in {"human_action", "real_event", "third_party_commentary", "cultural_reference", "product_inspection"} else 7.0
    motion = 10.0 if not shot.get("movingVisualRequired") or float(metrics.get("motion_score") or 0) >= 3.0 else 3.0
    continuity = 10.0 if not shot.get("requiresContinuity") or provider in {"ui", "image_pair", "cutout_motion", "omni"} else 6.0
    preference = 6.0 if provider == preferred else max(0.0, 3.0 - route_index)
    learned_bias = float((shot.get("learnedProviderBias") or {}).get(provider) or 0)
    exploration_penalty = route_index * 1.2 + variant_index * 0.3
    total = min(100.0, evidence + technical + credibility + motion + continuity + 10.0 + 5.0 + preference + learned_bias - exploration_penalty)
    return {
        "score": round(total, 2),
        "components": {
            "evidence": evidence, "technical": round(technical, 2), "credibility": credibility,
            "useful_motion": motion, "continuity": continuity, "novelty": 10.0,
            "tts_fit": 5.0, "preference": preference, "learned_bias": learned_bias, "exploration_penalty": round(exploration_penalty, 2),
        },
        "quality": metrics,
    }


def choose_best(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        raise ValueError("no hay candidatos aprobados")
    return max(candidates, key=lambda item: (
        float(item["ranking"]["score"]),
        float((item["ranking"].get("quality") or {}).get("source_width") or 0) * float((item["ranking"].get("quality") or {}).get("source_height") or 0),
        float((item["ranking"].get("quality") or {}).get("width") or 0),
        -int(item.get("variant_index") or 0),
    ))
