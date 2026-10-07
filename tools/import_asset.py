from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import asset_library
from engine.provider_telemetry import ProviderTelemetry


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa un asset manual con procedencia obligatoria")
    parser.add_argument("path")
    parser.add_argument("--kind", choices=["video", "image", "music"], required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--shot-id", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--source-url", default="")
    parser.add_argument("--license", required=True)
    parser.add_argument("--telemetry", default="")
    args = parser.parse_args()
    source = pathlib.Path(args.path).resolve()
    if not source.is_file():
        raise SystemExit("asset no existe: %s" % source)
    started = time.time()
    asset_id = asset_library.register(source, kind=args.kind, description=args.description, provider="manual-import", source_url=args.source_url, license_name=args.license, qa_status="PENDING_REVIEW")
    asset_library.mark_used(asset_id, args.run_id, args.shot_id)
    telemetry_path = pathlib.Path(args.telemetry) if args.telemetry else pathlib.Path("work") / "longform_runs" / args.run_id / "provider_events.jsonl"
    ProviderTelemetry(telemetry_path).emit(provider="manual-import", scene=args.shot_id, query_or_prompt=args.description, started_at=started, result="imported", asset_after=str(source), estimated_cost_usd=0, metadata={"asset_id": asset_id, "license": args.license, "source_url": args.source_url, "qa_status": "PENDING_REVIEW"})
    print(json.dumps({"status": "IMPORTED_PENDING_REVIEW", "asset_id": asset_id, "path": str(source)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
