from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

from engine.config import ROOT


LEARNING_PATH = pathlib.Path(ROOT) / "work" / "channel_learning.json"
HUMAN_FEEDBACK_PATH = pathlib.Path(ROOT) / "work" / "human_feedback.jsonl"
PROVIDER_ALIASES = {
    "clip_extractor": ("clip extractor", "clip_extractor"),
    "pexels": ("pexels",),
    "cutout": ("stop motion", "stop-motion", "cutout"),
    "image": ("imagen generada", "generador de imagenes", "image"),
    "omni": ("omni", "video generado"),
    "ui": ("motion graphic", "motion graphics", "remotion", "grafica"),
    "avatar": ("avatar", "kreado"),
}


def _load() -> dict[str, Any]:
    if LEARNING_PATH.is_file():
        return json.loads(LEARNING_PATH.read_text(encoding="utf-8"))
    return {"schema_version": 2, "observations": [], "learned_rules": [], "human_feedback": []}


def _load_human_feedback() -> list[dict[str, Any]]:
    if not HUMAN_FEEDBACK_PATH.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in HUMAN_FEEDBACK_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(event, dict) and event.get("run_id") and event.get("status") in {"APPROVED", "REJECTED"}:
            events.append(event)
    return events[-500:]


def _explicitly_targets(event: dict[str, Any], provider: str, proof_kind: str) -> bool:
    note = str(event.get("note") or "").casefold()
    normalized = re.sub(r"[^a-z0-9_áéíóúüñ -]+", " ", note)
    aliases = PROVIDER_ALIASES.get(provider, (provider.replace("_", " "),))
    provider_hit = any(alias and alias in normalized for alias in aliases)
    proof_hit = bool(proof_kind and proof_kind.replace("_", " ").casefold() in normalized)
    return provider_hit or proof_hit


def _rebuild_rules(state: dict[str, Any], human_feedback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feedback_by_run: dict[str, list[dict[str, Any]]] = {}
    for event in human_feedback:
        feedback_by_run.setdefault(str(event.get("run_id")), []).append(event)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in state.get("observations") or []:
        grouped.setdefault((str(item.get("proof_kind") or ""), str(item.get("provider") or "")), []).append(item)
    rules: list[dict[str, Any]] = []
    for (proof_kind, provider), rows in grouped.items():
        runs = {str(row.get("run_id")) for row in rows}
        pass_rate = sum(bool(row.get("run_pass")) for row in rows) / max(1, len(rows))
        avg_quality = sum(float(row.get("quality_score") or 0) for row in rows) / max(1, len(rows))
        approved_runs = {
            run_id for run_id in runs
            if any(event.get("status") == "APPROVED" for event in feedback_by_run.get(run_id, []))
        }
        targeted_rejected_runs = {
            run_id for run_id in runs
            if any(
                event.get("status") == "REJECTED" and _explicitly_targets(event, provider, proof_kind)
                for event in feedback_by_run.get(run_id, [])
            )
        }
        enough_machine_evidence = len(rows) >= 3 and len(runs) >= 2
        positive = enough_machine_evidence and len(approved_runs) >= 2 and pass_rate >= 0.8 and avg_quality >= 70
        negative = enough_machine_evidence and len(targeted_rejected_runs) >= 2
        status = "promoted" if positive or negative else "pending"
        bias = 5.0 if positive else -5.0 if negative else 0.0
        rules.append({
            "proof_kind": proof_kind,
            "provider": provider,
            "samples": len(rows),
            "runs": len(runs),
            "pass_rate": round(pass_rate, 3),
            "average_quality": round(avg_quality, 1),
            "human_approved_runs": len(approved_runs),
            "human_targeted_rejections": len(targeted_rejected_runs),
            "bias": bias,
            "status": status,
        })
    return sorted(rules, key=lambda item: (item["status"] != "promoted", item["proof_kind"], -item["bias"]))


def provider_biases() -> dict[str, dict[str, float]]:
    state = _load()
    feedback = _load_human_feedback()
    state["learned_rules"] = _rebuild_rules(state, feedback)
    result: dict[str, dict[str, float]] = {}
    for rule in state.get("learned_rules") or []:
        if rule.get("status") != "promoted":
            continue
        result.setdefault(str(rule.get("proof_kind") or ""), {})[str(rule.get("provider") or "")] = float(rule.get("bias") or 0)
    return result


def apply_biases(shots: list[dict[str, Any]]) -> None:
    biases = provider_biases()
    for shot in shots:
        shot["learnedProviderBias"] = biases.get(str(shot.get("proofKind") or shot.get("mediaNeedKind") or ""), {})


def record_run(run_id: str, plan: dict[str, Any], qa: dict[str, Any]) -> dict[str, Any]:
    state = _load()
    viewer_score = float(((qa.get("audiovisual_watchthrough") or {}).get("score") or (qa.get("viewer") or {}).get("score") or 0))
    run_ok = qa.get("status") == "PASS"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    observations = state.setdefault("observations", [])
    for shot in plan.get("shots") or []:
        quality = float((((shot.get("candidateSelection") or {}).get("quality") or {}).get("quality_score") or 0))
        observations.append({
            "run_id": run_id, "observed_at": now, "shot_id": shot.get("shotId"),
            "proof_kind": shot.get("proofKind") or shot.get("mediaNeedKind"), "provider": shot.get("provider"),
            "quality_score": quality, "viewer_score": viewer_score, "run_pass": run_ok,
            "degraded": bool((shot.get("candidateSelection") or {}).get("winner") and shot.get("preferredMedium") != (shot.get("candidateSelection") or {}).get("winner")),
        })
    observations[:] = observations[-2000:]
    feedback = _load_human_feedback()
    state["schema_version"] = 2
    state["human_feedback"] = feedback
    state["learned_rules"] = _rebuild_rules(state, feedback)
    state["updated_at"] = now
    state["last_run"] = {"run_id": run_id, "status": qa.get("status"), "viewer_score": viewer_score}
    LEARNING_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARNING_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state
