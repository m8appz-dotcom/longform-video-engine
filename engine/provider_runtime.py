from __future__ import annotations

import json
import pathlib
import re
import time
from typing import Any, Callable, TypeVar

from engine.provider_telemetry import ProviderTelemetry, prompt_hash

T = TypeVar("T")


class ProviderRuntime:
    def __init__(self, state_path: pathlib.Path):
        self.path = state_path
        self.state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {"circuits": {}, "negative": {}}
        self.telemetry = ProviderTelemetry(state_path.with_name("provider_events.jsonl"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def clear_circuit(self, provider: str) -> None:
        """A successful readiness probe is stronger than a stale runtime failure."""
        self.state.setdefault("circuits", {}).pop(provider, None)
        self._save()

    def call(self, provider: str, signature: str, fn: Callable[[], T], *, scene: str = "",
             query_or_prompt: str = "", estimated_cost_usd: float | None = None,
             metadata: dict[str, Any] | None = None) -> T:
        now = time.time()
        circuit = self.state["circuits"].get(provider) or {}
        if float(circuit.get("until") or 0) > now:
            self.telemetry.emit(provider=provider, scene=scene, query_or_prompt=query_or_prompt, started_at=now, result="failed", rejection_reason="circuit_open", estimated_cost_usd=0, metadata=metadata)
            raise RuntimeError("circuito %s abierto: %s" % (provider, circuit.get("reason", "error previo")))
        negative = self.state["negative"].get(provider + ":" + signature) or {}
        if float(negative.get("until") or 0) > now:
            self.telemetry.emit(provider=provider, scene=scene, query_or_prompt=query_or_prompt, started_at=now, result="failed", rejection_reason="negative_cache", estimated_cost_usd=0, metadata=metadata)
            raise RuntimeError("negative-cache %s: %s" % (provider, negative.get("reason", "sin candidatos")))
        if provider == "clip_extractor":
            previous = next((
                event for event in reversed(self.telemetry.read())
                if event.get("provider") == provider
                and event.get("scene") == scene
                and event.get("query_or_prompt_hash") == prompt_hash(query_or_prompt)
                and event.get("result") == "failed"
                and re.search(r"no candidate\b.*\bmatched|sin candidatos?", str(event.get("rejection_reason") or ""), re.I)
            ), None)
            if previous:
                reason = str(previous.get("rejection_reason") or "sin candidatos")
                self.telemetry.emit(provider=provider, scene=scene, query_or_prompt=query_or_prompt, started_at=now, result="failed", rejection_reason="negative_cache_history: " + reason, estimated_cost_usd=0, metadata=metadata)
                raise RuntimeError("negative-cache historico %s: %s" % (provider, reason[:220]))
        try:
            result = fn()
            self.state["circuits"].pop(provider, None)
            self._save()
            asset_after = None
            if isinstance(result, tuple) and len(result) >= 2:
                asset_after = str(result[1])
            # Provider output exists, but it has not passed local/semantic QA yet.
            self.telemetry.emit(provider=provider, scene=scene, query_or_prompt=query_or_prompt, started_at=now, result="produced", asset_after=asset_after, estimated_cost_usd=estimated_cost_usd, metadata=metadata)
            return result
        except Exception as exc:
            reason = str(exc)[:300]
            if re.search(r"\b(?:400|401|403|429)\b|quota|spending cap|unauthori[sz]ed|forbidden", reason, re.I):
                self.state["circuits"][provider] = {"until": now + 1800, "reason": reason}
            elif "stream completed without an image result" in reason.lower():
                self.state["circuits"][provider] = {"until": now + 120, "reason": reason}
            elif re.search(r"no candidates?|no candidate\b.*\bmatched|sin candidatos?|not found|no result", reason, re.I):
                self.state["negative"][provider + ":" + signature] = {"until": now + 86400, "reason": reason}
            self._save()
            self.telemetry.emit(provider=provider, scene=scene, query_or_prompt=query_or_prompt, started_at=now, result="failed", rejection_reason=reason, estimated_cost_usd=estimated_cost_usd, metadata=metadata)
            raise
