from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


DEFAULT_URL = "http://127.0.0.1:18110"
DEFAULT_RUNTIME = pathlib.Path(r"E:\AI\Runtimes\gemma4-audio")


@dataclass
class ManagedServer:
    process: subprocess.Popen | None = None
    stdout_handle: Any = None
    stderr_handle: Any = None


def enabled() -> bool:
    return os.environ.get("GEMMA_AUDIO_QA_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def service_url() -> str:
    return os.environ.get("GEMMA_AUDIO_QA_URL", DEFAULT_URL).rstrip("/")


def health(timeout: float = 3.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{service_url()}/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if payload.get("ok") else None
    except Exception:
        return None


def ensure_service() -> ManagedServer:
    if health():
        return ManagedServer()
    runtime = pathlib.Path(os.environ.get("GEMMA_AUDIO_RUNTIME", str(DEFAULT_RUNTIME)))
    python = runtime / ".venv" / "Scripts" / "python.exe"
    server = runtime / "server.py"
    if not python.is_file() or not server.is_file():
        raise RuntimeError(f"Gemma audio runtime incompleto: {runtime}")

    logs = runtime / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_handle = (logs / "engine-server.stdout.log").open("a", encoding="utf-8")
    stderr_handle = (logs / "engine-server.stderr.log").open("a", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault(
        "GEMMA4_AUDIO_MODEL_PATH",
        r"E:\AI\Models\gemma-4-E4B-it-ultra-uncensored-heretic-audio",
    )
    env.setdefault("GEMMA4_AUDIO_GPU_MEMORY_GIB", "9")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            str(python),
            "-m",
            "uvicorn",
            "server:app",
            "--app-dir",
            str(runtime),
            "--host",
            "127.0.0.1",
            "--port",
            "18110",
        ],
        cwd=str(runtime),
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        creationflags=creationflags,
    )
    managed = ManagedServer(process, stdout_handle, stderr_handle)
    deadline = time.monotonic() + float(os.environ.get("GEMMA_AUDIO_START_TIMEOUT_SECONDS", "180"))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stop_service(managed)
            raise RuntimeError(f"Gemma audio termino durante el arranque con codigo {process.returncode}")
        if health():
            return managed
        time.sleep(2)
    stop_service(managed)
    raise RuntimeError("Gemma audio no quedo saludable antes del timeout")


def stop_service(managed: ManagedServer) -> None:
    if managed.process is not None and managed.process.poll() is None:
        managed.process.terminate()
        try:
            managed.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            managed.process.kill()
            managed.process.wait(timeout=10)
    for handle in (managed.stdout_handle, managed.stderr_handle):
        if handle is not None:
            handle.close()


def multipart_qa(audio_path: pathlib.Path, expected_text: str, max_wer: float) -> dict[str, Any]:
    boundary = f"----gemma-audio-{uuid.uuid4().hex}"
    pieces: list[bytes] = []

    def field(name: str, value: str) -> None:
        pieces.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    field("expected_text", expected_text)
    field("max_wer", str(max_wer))
    pieces.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'.encode(),
            b"Content-Type: audio/wav\r\n\r\n",
            audio_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        f"{service_url()}/v1/audio/qa",
        data=b"".join(pieces),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    timeout = float(os.environ.get("GEMMA_AUDIO_QA_TIMEOUT_SECONDS", "900"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Gemma audio HTTP {exc.code}: {exc.read()[:500]!r}") from exc


def sample_windows(duration_ms: int) -> list[tuple[str, int, int]]:
    window_ms = min(25_000, max(8_000, duration_ms))
    candidates = [
        ("hook", 0, min(window_ms, duration_ms)),
        ("middle", max(0, duration_ms // 2 - window_ms // 2), min(window_ms, duration_ms)),
        ("cta", max(0, duration_ms - window_ms), min(window_ms, duration_ms)),
    ]
    output = []
    seen = set()
    for label, start_ms, length_ms in candidates:
        key = round(start_ms / 1000)
        if key not in seen:
            output.append((label, start_ms, length_ms))
            seen.add(key)
    return output[: int(os.environ.get("GEMMA_AUDIO_QA_MAX_SAMPLES", "3"))]


def expected_for_window(words: list[dict[str, Any]], start_ms: int, end_ms: int) -> str:
    selected = []
    for item in words:
        word_start = int(item.get("start_ms") or 0)
        word_end = int(item.get("end_ms") or word_start)
        midpoint = (word_start + word_end) // 2
        if start_ms <= midpoint < end_ms:
            selected.append(str(item.get("word") or "").strip())
    return " ".join(word for word in selected if word)


def qa_master_speech(
    master: pathlib.Path,
    voice: dict[str, Any],
    duration_ms: int,
    output_dir: pathlib.Path,
    ffmpeg: str,
    subprocess_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    managed = ensure_service()
    output_dir.mkdir(parents=True, exist_ok=True)
    max_wer = float(os.environ.get("GEMMA_AUDIO_QA_MAX_WER", "0.15"))
    reports = []
    try:
        for label, start_ms, length_ms in sample_windows(duration_ms):
            expected = expected_for_window(voice.get("words") or [], start_ms, start_ms + length_ms)
            if not expected:
                reports.append({"label": label, "ok": False, "error": "sin texto alineado para muestra"})
                continue
            audio_path = output_dir / f"gemma_audio_{label}.wav"
            command = [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-ss",
                f"{start_ms / 1000:.3f}",
                "-i",
                str(master),
                "-t",
                f"{length_ms / 1000:.3f}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_f32le",
                str(audio_path),
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=subprocess_env)
            if result.returncode or not audio_path.is_file():
                reports.append({"label": label, "ok": False, "error": (result.stderr or "ffmpeg fallo")[:300]})
                continue
            response = multipart_qa(audio_path, expected, max_wer)
            reports.append(
                {
                    "label": label,
                    "start_ms": start_ms,
                    "duration_ms": length_ms,
                    "expected_text": expected,
                    **response,
                }
            )
    finally:
        if managed.process is not None:
            stop_service(managed)
    return {
        "status": "PASS" if reports and all(item.get("ok") for item in reports) else "FAIL",
        "provider": "gemma4-e4b-audio-bf16",
        "threshold_max_wer": max_wer,
        "samples": reports,
        "health": health(),
    }
