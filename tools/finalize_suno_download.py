"""Materializa una descarga MP3 de Suno que Chrome dejo como archivo temporal.

Suno abre el dialogo nativo ``Save As``. Chrome puede mantener el resultado como
``.tmp`` aunque el contenido ya sea un MP3 completo. Este comando no adivina
URLs ni descarga desde Suno: valida el archivo local y lo copia a un nombre
estable para que luego pueda ingerirse con ``ingest_suno_music.py``.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.longform_pipeline import ffprobe


def candidate_files(downloads_dir: pathlib.Path, max_age_seconds: int) -> list[pathlib.Path]:
    now = time.time()
    candidates = []
    for path in downloads_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".tmp", ".crdownload", ".mp3"}:
            continue
        age = now - path.stat().st_mtime
        if 0 <= age <= max_age_seconds:
            candidates.append(path)
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida y materializa el MP3 temporal descargado desde Suno")
    parser.add_argument("--downloads-dir", required=True, help="Carpeta donde Windows guarda la descarga")
    parser.add_argument("--output", required=True, help="Ruta estable de salida, normalmente .mp3")
    parser.add_argument("--max-age-seconds", type=int, default=900)
    parser.add_argument("--settle-ms", type=int, default=500, help="Tiempo para confirmar que el archivo dejo de crecer")
    parser.add_argument("--force", action="store_true", help="Permite reemplazar el output existente")
    args = parser.parse_args()

    downloads_dir = pathlib.Path(args.downloads_dir).resolve()
    output = pathlib.Path(args.output).resolve()
    if not downloads_dir.is_dir():
        raise SystemExit("carpeta de descargas no encontrada: %s" % downloads_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not args.force:
        raise SystemExit("output ya existe; usa --force solo si confirmaste el track: %s" % output)

    selected = None
    for path in candidate_files(downloads_dir, args.max_age_seconds):
        size_before = path.stat().st_size
        time.sleep(max(0, args.settle_ms) / 1000)
        if not path.exists() or path.stat().st_size != size_before or path.stat().st_size <= 0:
            continue
        try:
            metadata = ffprobe(path)
        except Exception:
            continue
        # Suno puede incluir portada embebida; ffprobe la expone como un stream
        # de imagen 360x360 aunque el archivo siga siendo un MP3 valido.
        if metadata.get("duration_ms", 0) > 0 and metadata.get("has_audio"):
            selected = (path, metadata)
            break

    if selected is None:
        raise SystemExit("no se encontro un MP3 temporal estable en %s" % downloads_dir)

    source, metadata = selected
    shutil.copy2(source, output)
    final_metadata = ffprobe(output)
    payload = {
        "status": "PASS",
        "source": str(source),
        "output": str(output),
        "duration_ms": final_metadata["duration_ms"],
        "size_bytes": output.stat().st_size,
        "format": "mp3",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
