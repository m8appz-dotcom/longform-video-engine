#!/usr/bin/env python3
"""Backend-only Kreado integration for Reel Engine.

This module never stores or sends private Kreado browser headers from the
frontend. It talks only to the local Kreado automation backend, which owns
KreadoClient/auth.
"""
import json
import os
import time
import urllib.error
import urllib.request


ROOT = os.environ.get("ENGINE_ROOT", os.path.dirname(os.path.abspath(__file__)))
WORK = os.environ.get("WORK_DIR", os.path.join(ROOT, "work"))


class KreadoServiceError(RuntimeError):
    pass


def _truthy(value):
    return str(value or "").lower() in ("1", "true", "yes", "on")


class KreadoService:
    def __init__(self, base_url=None, human_id=None, state_path=None, aspect_ratio=None):
        self.base_url = (base_url or os.environ.get("KREADO_BACKEND_URL") or "http://localhost:8787").rstrip("/")
        self.human_id = int(human_id or os.environ.get("KREADO_HUMAN_ID") or "515947")
        self.aspect_ratio = aspect_ratio or os.environ.get("KREADO_ASPECT_RATIO") or "16:9"
        self.generate_path = os.environ.get("KREADO_GENERATE_PATH") or "/api/kreado/generate"
        self.state_path = state_path or os.environ.get("KREADO_TASK_STATE") or os.path.join(WORK, "kreado_tasks.jsonl")

    def _request(self, method, path, body=None, timeout=None):
        timeout_s = float(timeout or os.environ.get("KREADO_HTTP_TIMEOUT_SECONDS") or 650)
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as res:
                raw = res.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:800]
            raise KreadoServiceError(self._friendly_error("http", detail, e.code)) from e
        except urllib.error.URLError as e:
            raise KreadoServiceError(
                "Kreado backend no disponible en %s. Inicia el backend con npm start; si CDP falla, ejecuta neo start."
                % self.base_url
            ) from e
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as e:
            raise KreadoServiceError("Kreado backend devolvio respuesta no JSON: %s" % raw[:300]) from e
        if isinstance(data, dict) and data.get("error"):
            raise KreadoServiceError(self._friendly_error("backend", str(data.get("error"))))
        return data

    def _friendly_error(self, kind, detail, status=None):
        text = str(detail or "")
        low = text.lower()
        prefix = "Kreado"
        if status:
            prefix += " HTTP %s" % status
        if "denied" in low or "permission" in low or "permiso" in low:
            return "%s: permiso denegado para generar video. Revisa creditos/permisos del clon. Detalle: %s" % (prefix, text[:500])
        if "did not finish" in low or "timeout" in low or "timed out" in low:
            return "%s: timeout esperando task. Detalle: %s" % (prefix, text[:500])
        if "failed with status" in low or "task" in low and "failed" in low:
            return "%s: task fallido. Detalle: %s" % (prefix, text[:500])
        if "clone" in low and "not found" in low:
            return "%s: clone no encontrado o sesion vencida. Confirma humanId=%s en /api/kreado/clones. Detalle: %s" % (prefix, self.human_id, text[:500])
        if "token" in low or "unauthorized" in low or "401" in low or "403" in low:
            return "%s: sesion vencida o token invalido. Mantén Chrome logueado con CDP o configura tokens en el backend. Detalle: %s" % (prefix, text[:500])
        return "%s error %s: %s" % (prefix, kind, text[:500])

    def health(self):
        return self._request("GET", "/health", timeout=15)

    def clones(self):
        return self._request("GET", "/api/kreado/clones", timeout=60)

    def record_task(self, record):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        record = {"created_at": int(time.time()), **record}
        with open(self.state_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def generate(self, text, human_id=None, task_name=None, download=False, aspect_ratio=None, audio_path=None):
        body = {
            "humanId": int(human_id or self.human_id),
            "text": text,
            "taskName": task_name or "reel-engine-kreado-%d" % int(time.time()),
            "download": bool(download),
            "aspectRatio": aspect_ratio or self.aspect_ratio,
        }
        if audio_path:
            body["audioPath"] = os.path.abspath(audio_path)
        return self._request("POST", self.generate_path, body=body)

    def _download(self, url, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with urllib.request.urlopen(url, timeout=float(os.environ.get("KREADO_DOWNLOAD_TIMEOUT_SECONDS") or 300)) as res:
            with open(output_path, "wb") as f:
                f.write(res.read())
        return output_path

    def generate_avatar_video(self, text, output_path, human_id=None, task_name=None, aspect_ratio=None, audio_path=None):
        text = str(text or "").strip()
        if not text:
            raise KreadoServiceError("Kreado avatar requiere text/script_segment no vacio")
        human_id = int(human_id or self.human_id)
        aspect_ratio = aspect_ratio or self.aspect_ratio
        result = self.generate(
            text=text,
            human_id=human_id,
            task_name=task_name,
            download=False,
            aspect_ratio=aspect_ratio,
            audio_path=audio_path,
        )
        completed = result.get("completed") or {}
        status = completed.get("status")
        target_url = completed.get("targetFileUrl")
        task_id = result.get("taskId")
        if status != 192 or not target_url:
            self.record_task({
                "humanId": human_id,
                "taskId": task_id,
                "status": status,
                "targetFileUrl": target_url,
                "localVideo": None,
                "aspectRatio": aspect_ratio,
                "audioPath": os.path.abspath(audio_path) if audio_path else None,
            })
            raise KreadoServiceError("Kreado task no completado: taskId=%s status=%s" % (task_id, status))
        local_video = result.get("localVideo")
        if local_video and os.path.exists(local_video):
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(local_video, "rb") as src, open(output_path, "wb") as dst:
                dst.write(src.read())
        else:
            self._download(target_url, output_path)
            local_video = output_path
        self.record_task({
            "humanId": human_id,
            "taskId": task_id,
            "status": status,
            "targetFileUrl": target_url,
            "localVideo": local_video,
            "aspectRatio": aspect_ratio,
            "audioPath": os.path.abspath(audio_path) if audio_path else None,
        })
        return output_path
