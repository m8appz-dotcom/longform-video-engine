#!/usr/bin/env python3
"""Generate and judge script candidates without choosing by model reputation.

Writers are distinct providers only: Codex OAuth and Gemma/vLLM. OpenAI and
same-model prompt variants are intentionally excluded.
"""
import argparse
import json
import os
import sys
import time
import traceback

from engine.config import ROOT, REMOTION_DIR as _REM, WORK_DIR as _WORK  # V2PORT
WORK = os.path.join(ROOT, "work")
os.makedirs(WORK, exist_ok=True)

from engine import llm


def candidate_id(writer_id, index):
    safe = "".join(ch if ch.isalnum() else "-" for ch in writer_id.lower()).strip("-")
    return "script-%02d-%s" % (index, safe or "writer")


def redact_candidate(candidate):
    return {
        "id": candidate["id"],
        "status": candidate["status"],
        "hook": candidate.get("hook", ""),
        "body": candidate.get("body", ""),
        "word_count": candidate.get("scorecard", {}).get("word_count"),
        "score": candidate.get("scorecard", {}).get("score"),
        "eligible": candidate.get("scorecard", {}).get("eligible", False),
        "hard_rejects": candidate.get("scorecard", {}).get("hard_rejects", []),
        "issues": candidate.get("scorecard", {}).get("issues", []),
        "dimensions": candidate.get("scorecard", {}).get("dimensions", {}),
    }


def run_audition(topic, language="es"):
    writers = llm.get_script_audition_writers()
    if not writers:
        raise RuntimeError("no hay writers habilitados; usa SCRIPT_AUDITION_WRITERS=codex,gemma")

    candidates = []
    for idx, writer in enumerate(writers, 1):
        cid = candidate_id(writer["id"], idx)
        item = {
            "id": cid,
            "writer": {
                "id": writer["id"],
                "provider": writer["provider"],
                "model": writer["model"],
            },
            "status": "failed",
        }
        try:
            hook, words = writer["client"].script(topic, language=language)
            body = " ".join(words)
            scorecard = llm.score_script_candidate(hook, body, language=language)
            item.update({
                "status": "ok",
                "hook": hook,
                "body": body,
                "scorecard": scorecard,
            })
        except Exception as exc:
            item.update({
                "error": str(exc),
                "trace": traceback.format_exc(limit=4),
                "scorecard": {
                    "score": 0,
                    "eligible": False,
                    "hard_rejects": ["writer fallo"],
                    "issues": [str(exc)[:240]],
                },
            })
        candidates.append(item)

    eligible = [c for c in candidates if c.get("status") == "ok" and c.get("scorecard", {}).get("eligible")]
    pool = eligible or [c for c in candidates if c.get("status") == "ok"]
    winner = None
    if pool:
        winner = sorted(pool, key=lambda c: c.get("scorecard", {}).get("score", 0), reverse=True)[0]

    payload = {
        "topic": topic,
        "language": language,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy": {
            "selection_basis": "blind_output_quality",
            "excluded": ["openai", "same_model_prompt_variants"],
            "writers": [w["id"] for w in writers],
        },
        "candidates": candidates,
        "winner_id": winner["id"] if winner else None,
    }

    scorecard = {
        "topic": topic,
        "language": language,
        "created_at": payload["created_at"],
        "selection_basis": "blind_output_quality",
        "winner": redact_candidate(winner) if winner else None,
        "ranking": sorted([redact_candidate(c) for c in candidates], key=lambda c: c.get("score") or 0, reverse=True),
        "failed_writers": [
            {"id": c["id"], "writer": c.get("writer"), "error": c.get("error")}
            for c in candidates if c.get("status") != "ok"
        ],
    }

    candidates_path = os.path.join(WORK, "script_candidates.json")
    scorecard_path = os.path.join(WORK, "script_scorecard.json")
    winner_path = os.path.join(WORK, "script_winner.txt")
    with open(candidates_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(scorecard_path, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, ensure_ascii=False, indent=2)
    if winner:
        with open(winner_path, "w", encoding="utf-8") as f:
            f.write("HOOK:\n%s\n\nGUION:\n%s\n" % (winner.get("hook", ""), winner.get("body", "")))

    if not winner:
        raise RuntimeError("ningun writer produjo un guion util; revisa %s" % candidates_path)
    return payload, scorecard, candidates_path, scorecard_path, winner_path


def main():
    parser = argparse.ArgumentParser(description="Audicion ciega de guiones para Reel Engine")
    parser.add_argument("--topic", default=os.environ.get("TOPIC", ""), help="Tema del reel")
    parser.add_argument("--language", default=os.environ.get("SCRIPT_LANGUAGE", "es"),
                         help="Idioma del guion: es (default) | en. Requiere prompts/script_<lang>.md y prompts/structure_*_<lang>.md")
    args = parser.parse_args()
    topic = (args.topic or "").strip()
    language = (args.language or "es").strip().lower()
    if not topic:
        print("uso: python scripts/script_audition.py --topic \"tema\" [--language en]", file=sys.stderr)
        return 2
    payload, scorecard, candidates_path, scorecard_path, winner_path = run_audition(topic, language)
    winner = scorecard["winner"]
    print("SCRIPT AUDITION OK")
    print("  language: %s" % language)
    print("  writers: %s" % ", ".join(payload["policy"]["writers"]))
    print("  winner: %s score=%s eligible=%s" % (winner["id"], winner["score"], winner["eligible"]))
    print("  candidates: %s" % candidates_path)
    print("  scorecard: %s" % scorecard_path)
    print("  winner_text: %s" % winner_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())


def run(topic, language="es"):
    """Adapter programatico: audicion ciega, devuelve el resumen del ganador."""
    payload, scorecard, candidates_path, scorecard_path, winner_path = run_audition(topic, language)
    winner = scorecard["winner"]
    return "winner=%s score=%s eligible=%s (%s)" % (
        winner.get("id"), winner.get("score"), winner.get("eligible"), winner_path)
