from __future__ import annotations

import hashlib
import json
import pathlib
import time
from typing import Any


DEFAULT_COSTS = {
    "user": 0.0,
    "library": 0.0,
    "deterministic-ui": 0.0,
    "clip_extractor": 0.01,
    "pexels": 0.0,
    "image": 0.04,
    "cutout_motion": 0.12,
    "omni": 0.20,
    "avatar": 0.20,
}


def prompt_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:20]


class ProviderTelemetry:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, *, provider: str, scene: str, query_or_prompt: str = "", started_at: float | None = None,
             result: str, rejection_reason: str = "", asset_before: str | None = None,
             asset_after: str | None = None, estimated_cost_usd: float | None = None,
             metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        start = started_at if started_at is not None else time.time()
        event = {
            "provider": provider,
            "scene": scene,
            "query_or_prompt_hash": prompt_hash(query_or_prompt),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
            "duration_ms": max(0, round((time.time() - start) * 1000)),
            "estimated_cost_usd": round(float(DEFAULT_COSTS.get(provider, 0.0) if estimated_cost_usd is None else estimated_cost_usd), 4),
            "result": result,
            "rejection_reason": str(rejection_reason or "")[:500],
            "asset_before": asset_before,
            "asset_after": asset_after,
            "metadata": metadata or {},
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]

    def summary(self) -> dict[str, Any]:
        events = self.read()
        providers: dict[str, dict[str, Any]] = {}
        scene_outcomes: dict[str, dict[str, Any]] = {}
        for event in events:
            row = providers.setdefault(event["provider"], {"calls": 0, "events": 0, "produced": 0, "selected": 0, "rejected": 0, "failed": 0, "duration_ms": 0, "estimated_cost_usd": 0.0, "rejection_reasons": {}})
            row["events"] += 1
            if event.get("result") in {"produced", "failed"}:
                row["calls"] += 1
            row[event["result"]] = row.get(event["result"], 0) + 1
            row["duration_ms"] += int(event.get("duration_ms") or 0)
            row["estimated_cost_usd"] = round(row["estimated_cost_usd"] + float(event.get("estimated_cost_usd") or 0), 4)
            reason = str(event.get("rejection_reason") or "").strip()
            if reason:
                row["rejection_reasons"][reason] = row["rejection_reasons"].get(reason, 0) + 1
            if event.get("scene"):
                scene_outcomes[str(event["scene"])] = {
                    "provider": event.get("provider"), "result": event.get("result"),
                    "asset": event.get("asset_after"), "rejection_reason": event.get("rejection_reason"),
                }
        surviving_sources = {
            scene: outcome for scene, outcome in scene_outcomes.items()
            if outcome.get("result") == "selected"
        }
        return {
            "events": len(events),
            "providers": providers,
            "total_duration_ms": sum(int(event.get("duration_ms") or 0) for event in events),
            "estimated_cost_usd": round(sum(float(event.get("estimated_cost_usd") or 0) for event in events), 4),
            "scene_outcomes": scene_outcomes,
            "surviving_sources": surviving_sources,
        }
