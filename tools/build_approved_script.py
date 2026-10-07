#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.longform_contract import full_script, validate_approved_script, write_with_hash


def table_audio(markdown: str) -> list[str]:
    rows: list[str] = []
    inside = False
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("|") and "AUDIO / NARRACION" in line.upper():
            inside = True
            continue
        if not inside:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        audio = cells[0].replace("\\|", "|").strip()
        if audio:
            rows.append(audio)
    return rows


def balanced_chapters(rows: list[str], count: int) -> list[list[str]]:
    if count < 2 or count > len(rows):
        raise ValueError("chapters debe estar entre 2 y el numero de filas")
    total = sum(len(re.findall(r"\b\w+\b", row, re.UNICODE)) for row in rows)
    target = total / count
    chapters: list[list[str]] = []
    current: list[str] = []
    words = 0
    for row in rows:
        current.append(row)
        words += len(re.findall(r"\b\w+\b", row, re.UNICODE))
        remaining_rows = len(rows) - sum(len(group) for group in chapters) - len(current)
        remaining_chapters = count - len(chapters) - 1
        if remaining_chapters > 0 and words >= target and remaining_rows >= remaining_chapters:
            chapters.append(current)
            current = []
            words = 0
    chapters.append(current)
    while len(chapters) < count:
        largest = max(range(len(chapters)), key=lambda idx: len(chapters[idx]))
        group = chapters.pop(largest)
        mid = max(1, len(group) // 2)
        chapters[largest:largest] = [group[:mid], group[mid:]]
    return chapters


def main() -> int:
    parser = argparse.ArgumentParser(description="Convierte el guion ganador Markdown en ApprovedScript bloqueado")
    parser.add_argument("input_markdown")
    parser.add_argument("output_json")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--thumbnail-promise", required=True)
    parser.add_argument("--target-minutes", required=True, type=float)
    parser.add_argument("--audience-profile", required=True)
    parser.add_argument("--avatar-feedback", default="")
    parser.add_argument("--chapter-titles", default="Gancho,Qué sí cambia,Qué revisar,Regla de compra")
    args = parser.parse_args()

    source = pathlib.Path(args.input_markdown)
    text = source.read_text(encoding="utf-8-sig")
    if "STATUS FINAL: SCRIPT_COMPLETO" not in text:
        raise ValueError("el guion no esta marcado SCRIPT_COMPLETO")
    rows = table_audio(text)
    if len(rows) < 8:
        raise ValueError("no se pudo extraer una tabla narrativa completa")
    titles = [value.strip() for value in args.chapter_titles.split(",") if value.strip()]
    groups = balanced_chapters(rows, len(titles))
    chapters = [{"id": "C%02d" % (index + 1), "title": titles[index], "text": " ".join(group)} for index, group in enumerate(groups)]
    hook = rows[0]
    data = {
        "schema_version": "1.0",
        "run_id": args.run_id,
        "script_locked": True,
        "script_hash": "",
        "title": args.title,
        "thumbnail_promise": args.thumbnail_promise,
        "hook": hook,
        "target_minutes": args.target_minutes,
        "language": "es",
        "audience_profile": args.audience_profile,
        "avatar_feedback": args.avatar_feedback,
        "avatar_appearances": 2,
        "user_clips": [],
        "chapters": chapters,
        "source_markdown": str(source.resolve()),
    }
    # source_markdown es provenance del builder, no parte del contrato estricto.
    provenance = data.pop("source_markdown")
    output = pathlib.Path(args.output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_with_hash(output, data)
    written = json.loads(output.read_text(encoding="utf-8"))
    errors = validate_approved_script(written)
    if errors:
        output.unlink(missing_ok=True)
        raise ValueError("ApprovedScript invalido:\n- " + "\n- ".join(errors))
    manifest = output.with_suffix(".handoff.json")
    manifest.write_text(json.dumps({"status": "APPROVED_SCRIPT_READY", "source_markdown": provenance, "output": str(output.resolve()), "script_hash": written["script_hash"], "words": len(re.findall(r"\b\w+\b", full_script(written), re.UNICODE)), "rows": len(rows), "chapters": len(chapters)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
