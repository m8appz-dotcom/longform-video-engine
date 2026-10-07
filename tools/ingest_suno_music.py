from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.asset_library import register
from engine.longform_pipeline import ffprobe, sha256


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingesta una descarga manual/navegada de Suno con proveniencia verificable")
    parser.add_argument("audio")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--mood", required=True)
    parser.add_argument("--license", default="Suno Pro commercial use rights at generation time")
    parser.add_argument("--job-id", default="")
    args = parser.parse_args()
    source = pathlib.Path(args.audio).resolve()
    if not source.is_file():
        raise SystemExit("audio no encontrado: %s" % source)
    run_dir = pathlib.Path(args.run_dir).resolve()
    music_dir = run_dir / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    target = music_dir / ("suno_" + sha256(source)[:12] + source.suffix.lower())
    if not target.exists():
        shutil.copy2(source, target)
    meta = ffprobe(target)
    register(target, kind="music", description="Suno instrumental: " + args.mood, provider="suno", tags=["suno", "instrumental", args.mood], mood=args.mood, source_url=args.source_url, job_id=args.job_id, prompt_query=args.prompt, duration_ms=meta["duration_ms"], license_name=args.license)
    manifest = {"provider": "suno", "source_url": args.source_url, "job_id": args.job_id, "prompt": args.prompt, "license": args.license, "tracks": [{"path": str(target), "mood": args.mood, "volume": 0.075}]}
    (run_dir / "music_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "manifest": str(run_dir / "music_manifest.json"), "duration_ms": meta["duration_ms"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
