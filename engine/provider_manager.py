from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from engine.provider_runtime import ProviderRuntime


VALID_STATES = {"healthy", "recovering", "unavailable", "blocked_external"}


def _enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    health_url: str
    managed: bool
    workdir: pathlib.Path | None = None
    argv: tuple[str, ...] = ()
    command: str = ""
    env: dict[str, str] | None = None
    readiness_seconds: float = 25.0


def default_specs() -> dict[str, ProviderSpec]:
    cutout_dir = pathlib.Path(os.environ.get(
        "CUTOUT_WORKDIR",
        r"C:\Users\kenny\Documents\Codex\2026-07-08\analiza-si-esta-es-la-mejor",
    ))
    kreado_dir = pathlib.Path(os.environ.get(
        "KREADO_WORKDIR",
        r"C:\Users\kenny\Documents\Codex\2026-06-25\busca-un-skill-que-valide-si\work\kreado-automation",
    ))
    cutout_command = os.environ.get("CUTOUT_START_COMMAND", "").strip()
    kreado_command = os.environ.get("KREADO_START_COMMAND", "").strip()
    kreado_base = os.environ.get("KREADO_BACKEND_URL", "http://127.0.0.1:8787").rstrip("/")
    kreado_port = urllib.parse.urlparse(kreado_base).port or 8787
    return {
        "cutout_motion": ProviderSpec(
            name="cutout_motion",
            health_url=os.environ.get("CUTOUT_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/health",
            managed=_enabled("CUTOUT_MANAGED", True),
            workdir=cutout_dir,
            argv=() if cutout_command else (sys.executable, "-m", "uvicorn", "cutout_video.api:create_app", "--factory", "--host", "127.0.0.1", "--port", "8000"),
            command=cutout_command,
            env={"PYTHONPATH": "src"},
            readiness_seconds=float(os.environ.get("CUTOUT_READY_TIMEOUT", "35")),
        ),
        "avatar": ProviderSpec(
            name="avatar",
            health_url=kreado_base + "/health",
            managed=_enabled("KREADO_MANAGED", True),
            workdir=kreado_dir,
            argv=() if kreado_command else ("npm.cmd" if os.name == "nt" else "npm", "start"),
            command=kreado_command,
            env={"PORT": str(kreado_port)},
            readiness_seconds=float(os.environ.get("KREADO_READY_TIMEOUT", "25")),
        ),
        "clip_extractor": ProviderSpec(
            name="clip_extractor",
            health_url=os.environ.get("CLIP_EXTRACTOR_BASE_URL", "http://100.121.147.73:8765").rstrip("/") + "/api/health",
            managed=_enabled("CLIP_EXTRACTOR_MANAGED", False),
            workdir=pathlib.Path(os.environ["CLIP_EXTRACTOR_WORKDIR"]) if os.environ.get("CLIP_EXTRACTOR_WORKDIR") else None,
            command=os.environ.get("CLIP_EXTRACTOR_START_COMMAND", "").strip(),
            readiness_seconds=float(os.environ.get("CLIP_EXTRACTOR_READY_TIMEOUT", "25")),
        ),
    }


class ProviderManager:
    def __init__(self, state_path: pathlib.Path, specs: dict[str, ProviderSpec] | None = None):
        self.path = state_path
        self.specs = specs or default_specs()
        self.state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {"providers": {}}
        self.runtime = ProviderRuntime(state_path.with_name("provider_runtime.json"))
        self._state_lock = threading.RLock()

    def _save(self) -> None:
        with self._state_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _set(self, name: str, status: str, **extra: Any) -> dict[str, Any]:
        if status not in VALID_STATES:
            raise ValueError("estado de proveedor invalido: %s" % status)
        record = {"provider": name, "status": status, "checked_at": time.time(), **extra}
        with self._state_lock:
            self.state.setdefault("providers", {})[name] = record
            self._save()
        return record

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @contextmanager
    def _startup_lock(self, name: str, ttl_seconds: float):
        """Cross-process guard so two runs never start the same local service."""
        lock_path = self.path.with_name("%s.start.lock" % name)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        acquired = False
        for _ in range(2):
            try:
                descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, json.dumps({"pid": os.getpid(), "created_at": time.time()}).encode("ascii"))
                os.close(descriptor)
                acquired = True
                break
            except FileExistsError:
                try:
                    existing = json.loads(lock_path.read_text(encoding="ascii"))
                    stale = time.time() - float(existing.get("created_at") or 0) > ttl_seconds
                    owner_alive = self._pid_alive(int(existing.get("pid") or 0))
                    if stale or not owner_alive:
                        lock_path.unlink(missing_ok=True)
                        continue
                except Exception:
                    lock_path.unlink(missing_ok=True)
                    continue
                break
        try:
            yield acquired
        finally:
            if acquired:
                lock_path.unlink(missing_ok=True)

    @staticmethod
    def _probe(url: str, timeout: float = 3.0) -> tuple[bool, str, int | None]:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "longform-provider-manager/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(500).decode("utf-8", errors="replace")
                return 200 <= int(response.status) < 300, body, int(response.status)
        except urllib.error.HTTPError as exc:
            return False, str(exc), int(exc.code)
        except Exception as exc:
            return False, str(exc), None

    def _start(self, spec: ProviderSpec) -> int:
        if not spec.workdir or not spec.workdir.is_dir():
            raise RuntimeError("workdir inexistente: %s" % spec.workdir)
        if not spec.command and not spec.argv:
            raise RuntimeError("proveedor sin comando administrado")
        env = os.environ.copy()
        env.update(spec.env or {})
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        stdout_path = self.path.with_name("%s.out.log" % spec.name)
        stderr_path = self.path.with_name("%s.err.log" % spec.name)
        stdout = stdout_path.open("ab")
        stderr = stderr_path.open("ab")
        process = subprocess.Popen(
            spec.command or list(spec.argv),
            cwd=str(spec.workdir),
            env=env,
            shell=bool(spec.command),
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        stdout.close()
        stderr.close()
        self.path.with_name("%s.pid" % spec.name).write_text(str(process.pid), encoding="ascii")
        return int(process.pid)

    def ensure(self, name: str, *, allow_restart: bool = True) -> dict[str, Any]:
        spec = self.specs[name]
        ok, detail, status_code = self._probe(spec.health_url)
        if ok:
            self.runtime.clear_circuit(name)
            return self._set(name, "healthy", health_url=spec.health_url, auto_started=False)
        if status_code in {401, 402, 403, 429}:
            return self._set(name, "blocked_external", health_url=spec.health_url, error=detail[:300], status_code=status_code)
        if not spec.managed or not allow_restart:
            return self._set(name, "unavailable", health_url=spec.health_url, error=detail[:300], managed=spec.managed)
        with self._startup_lock(name, spec.readiness_seconds + 15.0) as owns_startup:
            self._set(name, "recovering", health_url=spec.health_url, error=detail[:300], restart_attempt=1, startup_owner=owns_startup)
            pid = None
            if owns_startup:
                try:
                    pid = self._start(spec)
                except Exception as exc:
                    return self._set(name, "unavailable", health_url=spec.health_url, error=str(exc)[:300], managed=True)
            deadline = time.monotonic() + spec.readiness_seconds
            last = "readiness timeout"
            while time.monotonic() < deadline:
                ok, last, status_code = self._probe(spec.health_url)
                if ok:
                    self.runtime.clear_circuit(name)
                    return self._set(name, "healthy", health_url=spec.health_url, auto_started=owns_startup, pid=pid)
                if status_code in {401, 402, 403, 429}:
                    return self._set(name, "blocked_external", health_url=spec.health_url, auto_started=owns_startup, pid=pid, error=last[:300], status_code=status_code)
                time.sleep(0.5)
            return self._set(name, "unavailable", health_url=spec.health_url, auto_started=owns_startup, pid=pid, error=str(last)[:300])

    def ensure_all(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(self.specs))) as executor:
            futures = {executor.submit(self.ensure, name): name for name in self.specs}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    results[name] = self._set(name, "unavailable", error=str(exc)[:300])
        return {name: results[name] for name in self.specs}
