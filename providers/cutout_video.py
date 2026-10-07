from __future__ import annotations

import json
import hashlib
import math
import os
import pathlib
import re
import subprocess
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from engine import media_tools
from engine.config import subprocess_env


class CutoutVideoError(RuntimeError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _clean(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def namespace_script_assets(script: str, asset_provider: str, style_scope: str) -> str:
    match = re.match(
        r"^(Background|Fondo):\s*(.*?)\.\s*(Props|Objetos):\s*(.*?)\.\s*(Relacion|Relación):\s*(.*?)\.\s*\n(.*)$",
        str(script or "").strip(),
        re.I | re.S,
    )
    if not match:
        raise CutoutVideoError("Cutout script no usa el formato Background/Props/Relacion")
    background_label, props_text, relation, narration = match.group(2), match.group(4), match.group(6), match.group(7)
    provider_scope = "preview procedural" if asset_provider == "procedural" else "recorte premium"
    clean_scope = re.sub(r"[.,;:\r\n]+", " ", style_scope).strip()
    suffix = "estilo %s %s" % (provider_scope, clean_scope)
    props = [value.strip() for value in props_text.split(",") if value.strip()]
    scoped_props = ["%s %s" % (value, suffix) for value in props]
    return "Background: %s %s. Props: %s. Relacion: %s.\n%s" % (
        background_label, suffix, ", ".join(scoped_props), relation, narration,
    )


def safe_client_ref(base_ref: str, asset_provider: str, provider_script: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base_ref or "cutout").strip("-._") or "cutout"
    provider = re.sub(r"[^A-Za-z0-9._-]+", "-", asset_provider).strip("-._") or "provider"
    suffix = "-%s-%s" % (provider, hashlib.sha256(provider_script.encode("utf-8")).hexdigest()[:12])
    return base[:max(1, 120 - len(suffix))] + suffix


def validate_analysis(analysis: dict[str, Any], characteristics: dict[str, Any], duration_seconds: float) -> list[str]:
    errors: list[str] = []
    scenes = list(analysis.get("scenes") or [])
    assets = list(analysis.get("asset_specs") or [])
    if len(scenes) != 1:
        errors.append("Cutout debe producir exactamente una escena por beat")
        return errors

    props = [asset for asset in assets if str(asset.get("type") or "").lower() == "prop"]
    characters = [asset for asset in assets if str(asset.get("type") or "").lower() == "character"]
    backgrounds = [asset for asset in assets if str(asset.get("type") or "").lower() == "background"]
    if not backgrounds:
        errors.append("Cutout no detecto background")
    if not 1 <= len(props) <= 3:
        errors.append("Cutout requiere entre 1 y 3 props concretos")
    if len(characters) > 1:
        errors.append("Cutout admite como maximo un personaje por beat")

    observed_labels = [_clean(asset.get("label")) for asset in props + characters]
    for expected in characteristics.get("expected_props") or []:
        expected_clean = _clean(expected)
        if expected_clean and not any(expected_clean in label or label in expected_clean for label in observed_labels):
            errors.append("Cutout no detecto el prop esperado: %s" % expected)

    motion = scenes[0].get("motion") or {}
    if not motion:
        errors.append("Cutout no asigno movimiento a los props")
    if characteristics.get("temporal_action") == "multi_step" and motion and all(str(value or "").lower() == "settle" for value in motion.values()):
        errors.append("Cutout redujo una accion multi_step a movimiento settle")

    estimate = float(analysis.get("estimated_duration_seconds") or 0)
    minimum_estimate = max(1.0, float(duration_seconds) - float(os.environ.get("CUTOUT_DURATION_TOLERANCE_SECONDS", "1.25")))
    if estimate and estimate < minimum_estimate:
        errors.append("Cutout estima %.2fs para un beat de %.2fs" % (estimate, duration_seconds))
    if characteristics.get("requires_readable_data"):
        errors.append("Cutout no puede satisfacer datos legibles")
    if characteristics.get("evidence_mode") in {"documentary", "data_exact"}:
        errors.append("Cutout no puede presentarse como evidencia %s" % characteristics.get("evidence_mode"))
    if str(characteristics.get("stop_motion_intent") or "") not in {"transformative_compression", "playful_surreal", "technical_choreography", "visual_anchor"}:
        errors.append("Cutout requiere una intencion narrativa valida")
    if len(str(characteristics.get("why_stop_motion") or "").strip()) < 18:
        errors.append("Cutout requiere justificar por que mejora el beat")
    return errors


class CutoutVideoClient:
    def __init__(self, width: int, height: int, fps: int = 30):
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.base_url = os.environ.get("CUTOUT_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        self.api_key = os.environ.get("CUTOUT_API_KEY", "").strip()
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CutoutVideoError("CUTOUT_BASE_URL invalida: %s" % self.base_url)
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        if parsed.hostname.lower() not in local_hosts and not _env_bool("CUTOUT_ALLOW_REMOTE"):
            raise CutoutVideoError("Cutout remoto requiere CUTOUT_ALLOW_REMOTE=1 porque sus artefactos GET no tienen auth")

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {"User-Agent": "longform-engine/1.0", "Accept": "application/json,*/*"}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    def _request_json(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 30) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            urllib.parse.urljoin(self.base_url + "/", path.lstrip("/")),
            data=body,
            method=method,
            headers=self._headers(json_body=payload is not None),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            raise CutoutVideoError("Cutout HTTP %s en %s: %s" % (exc.code, path, detail)) from exc
        except Exception as exc:
            raise CutoutVideoError("Cutout no disponible en %s: %s" % (self.base_url, str(exc)[:300])) from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise CutoutVideoError("Cutout devolvio JSON invalido en %s" % path) from exc

    def health(self) -> dict[str, Any]:
        health = self._request_json("/health", timeout=float(os.environ.get("CUTOUT_HEALTH_TIMEOUT", "5")))
        if health.get("ok") is not True:
            raise CutoutVideoError("Cutout health no esta OK: %s" % json.dumps(health, ensure_ascii=False)[:300])
        return health

    def analyze(self, script: str) -> dict[str, Any]:
        return self._request_json(
            "/analyze",
            method="POST",
            payload={"request": script},
            timeout=float(os.environ.get("CUTOUT_ANALYZE_TIMEOUT", "30")),
        )

    def _download(self, url: str, path: pathlib.Path) -> None:
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=float(os.environ.get("CUTOUT_DOWNLOAD_TIMEOUT", "300"))) as response, path.open("wb") as handle:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    handle.write(block)
        except Exception as exc:
            raise CutoutVideoError("Cutout no pudo descargar %s: %s" % (url, str(exc)[:300])) from exc

    def _probe_duration(self, path: pathlib.Path) -> float:
        command = [media_tools.find_binary("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
        result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
        if result.returncode:
            raise CutoutVideoError("ffprobe fallo para Cutout: %s" % result.stderr[-300:])
        return float((result.stdout or "0").strip() or 0)

    def _normalize(self, source: pathlib.Path, output: pathlib.Path, duration_seconds: float) -> dict[str, float]:
        source_duration = self._probe_duration(source)
        source_ratio = source_duration / max(0.001, duration_seconds)
        min_ratio = float(os.environ.get("CUTOUT_MIN_SOURCE_RATIO", "0.85"))
        max_ratio = float(os.environ.get("CUTOUT_MAX_SOURCE_RATIO", "1.50"))
        if not min_ratio <= source_ratio <= max_ratio:
            raise CutoutVideoError("Cutout produjo %.2fs para un beat de %.2fs; retime %.3fx fuera de limites y no se permite loop" % (source_duration, duration_seconds, source_ratio))
        pts_factor = duration_seconds / max(0.001, source_duration)
        output.parent.mkdir(parents=True, exist_ok=True)
        vf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,setpts=%.8f*PTS,fps=%d,format=yuv420p" % (
            self.width, self.height, self.width, self.height, pts_factor, self.fps,
        )
        command = [
            media_tools.find_binary("ffmpeg"), "-y", "-i", str(source), "-t", "%.3f" % duration_seconds,
            "-an", "-vf", vf, "-r", str(self.fps), "-pix_fmt", "yuv420p", str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env())
        if result.returncode or not output.is_file() or output.stat().st_size <= 0:
            raise CutoutVideoError("normalizacion Cutout fallo: %s" % (result.stderr or result.stdout)[-500:])
        return {"source_duration_seconds": round(source_duration, 4), "target_duration_seconds": round(duration_seconds, 4), "pts_factor": round(pts_factor, 6)}

    def render_clip(self, script: str, duration_seconds: float, path: str | pathlib.Path, characteristics: dict[str, Any] | None = None) -> str:
        characteristics = dict(characteristics or {})
        output = pathlib.Path(path)
        asset_provider = os.environ.get("CUTOUT_ASSET_PROVIDER", "codex-oauth")
        style_scope = str(characteristics.get("style_scope") or os.environ.get("CUTOUT_STYLE_SCOPE", "project design profile")).strip()
        provider_script = namespace_script_assets(script, asset_provider, style_scope)
        self.health()
        analysis = self.analyze(provider_script)
        analysis_errors = validate_analysis(analysis, characteristics, duration_seconds)
        if analysis_errors:
            raise CutoutVideoError("Cutout analyze rechazo: %s" % "; ".join(analysis_errors))

        request_body = {
            "request": provider_script,
            "width": self.width,
            "height": self.height,
            "dry_run_audio": True,
            "asset_provider": asset_provider,
            "asset_mode": os.environ.get("CUTOUT_ASSET_MODE", "standard"),
            "mask_provider": os.environ.get("CUTOUT_MASK_PROVIDER", "auto"),
            "motion_mode": os.environ.get("CUTOUT_MOTION_MODE", "layered"),
            "animation_mode": os.environ.get("CUTOUT_ANIMATION_MODE", "layered"),
            "motion_planner": os.environ.get("CUTOUT_MOTION_PLANNER", "rules"),
            "prompt_refiner": os.environ.get("CUTOUT_PROMPT_REFINER", "none"),
            "script_writer": "none",
            "sprite_labels": False,
            "duration_seconds": int(math.ceil(duration_seconds + 1.0)),
            "client_ref": None,
        }
        base_ref = str(characteristics.get("client_ref") or "cutout")
        request_body["client_ref"] = safe_client_ref(base_ref, asset_provider, provider_script)
        job = self._request_json(
            "/jobs",
            method="POST",
            payload=request_body,
            timeout=float(os.environ.get("CUTOUT_SUBMIT_TIMEOUT", "60")),
        )
        job_id = str(job.get("job_id") or "")
        if not job_id:
            raise CutoutVideoError("Cutout no devolvio job_id: %s" % json.dumps(job, ensure_ascii=False)[:500])

        deadline = time.monotonic() + float(os.environ.get("CUTOUT_TIMEOUT", "210"))
        poll_seconds = float(os.environ.get("CUTOUT_POLL_SECONDS", "1.5"))
        status = job
        while time.monotonic() < deadline:
            state = str(status.get("status") or "").lower()
            if state == "completed":
                break
            if state == "failed":
                raise CutoutVideoError("Cutout job %s fallo: %s" % (job_id, str(status.get("error") or status)[:600]))
            time.sleep(poll_seconds)
            status = self._request_json("/jobs/%s" % urllib.parse.quote(job_id), timeout=30)
        else:
            raise CutoutVideoError("Cutout timeout para job_id=%s" % job_id)

        final_url = str((status.get("urls") or {}).get("final_video") or status.get("final_video_url") or "")
        if not final_url:
            raise CutoutVideoError("Cutout completed sin final_video: %s" % json.dumps(status, ensure_ascii=False)[:600])
        final_url = urllib.parse.urljoin(self.base_url + "/", final_url)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_handle = tempfile.NamedTemporaryFile(prefix="cutout-", suffix=".mp4", dir=str(output.parent), delete=False)
        temp_handle.close()
        temp_path = pathlib.Path(temp_handle.name)
        try:
            self._download(final_url, temp_path)
            timing = self._normalize(temp_path, output, float(duration_seconds))
        finally:
            temp_path.unlink(missing_ok=True)

        sidecar = {
            "provider": "cutout_motion",
            "base_url": self.base_url,
            "job_id": job_id,
            "client_ref": request_body.get("client_ref"),
            "asset_provider": request_body["asset_provider"],
            "analysis": analysis,
            "status": status,
            "final_video_url": final_url,
            "audio_removed": True,
            "normalized": {"width": self.width, "height": self.height, "fps": self.fps, "duration_seconds": duration_seconds, "sync_mode": "relative_retime", **timing},
        }
        pathlib.Path(str(output) + ".cutout.json").write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(output)
