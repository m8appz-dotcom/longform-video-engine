"""Contrato del provider Suno.

Suno no expone una API admitida por este motor. La generación ocurre mediante
Chrome autenticado; este módulo solo valida la descarga y su manifiesto de
proveniencia. `tools/ingest_suno_music.py` materializa el resultado.
"""
from __future__ import annotations

import json
import pathlib


def validate_manifest(path: str | pathlib.Path) -> dict:
    source = pathlib.Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    missing = [field for field in ("provider", "source_url", "prompt", "license", "tracks") if not data.get(field)]
    if str(data.get("provider") or "").lower() != "suno":
        missing.append("provider=suno")
    for track in data.get("tracks") or []:
        track_path = pathlib.Path(str(track.get("path") or ""))
        if not track_path.is_absolute():
            track_path = (source.parent / track_path).resolve()
        if not track_path.is_file():
            missing.append("track:%s" % track_path)
    if missing:
        raise ValueError("manifest Suno invalido: " + ", ".join(missing))
    return data
