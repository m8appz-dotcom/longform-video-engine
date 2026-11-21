#!/usr/bin/env python3
"""Shared media binary resolution for native Windows execution."""
import os
import platform
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))


def native_path(path):
    if not path:
        return path
    system = platform.system().lower()
    text = str(path)
    if system == "windows" and text.startswith("/mnt/") and len(text) > 6 and text[6] == "/":
        drive = text[5].upper()
        rest = text[7:].replace("/", "\\")
        return "%s:\\%s" % (drive, rest)
    return text


def _existing(path):
    return bool(path and os.path.exists(native_path(path)))


def _which(name):
    return shutil.which(name)


def _remotion_compositor_candidates(name):
    exe = name + ".exe" if platform.system().lower() == "windows" else name
    base = os.path.join(ROOT, "remotion", "node_modules", "@remotion")
    system = platform.system().lower()
    if system == "windows":
        pkgs = ["compositor-win32-x64-msvc"]
    elif system == "darwin":
        pkgs = ["compositor-darwin-x64", "compositor-darwin-arm64"]
    else:
        pkgs = ["compositor-linux-x64-gnu", "compositor-linux-x64-musl"]
    for pkg in pkgs:
        yield os.path.join(base, pkg, exe)


def _windows_common_candidates(name):
    exe = name + ".exe"
    for root in (
        os.environ.get("FFMPEG_ROOT"),
        os.path.join(ROOT, ".bin"),
        os.path.join(ROOT, "bin"),
        r"C:\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
    ):
        if not root:
            continue
        if os.path.isdir(root):
            direct = os.path.join(root, exe)
            if _existing(direct):
                yield direct
            if "WinGet" in root:
                for dirpath, _, filenames in os.walk(root):
                    if exe in filenames:
                        yield os.path.join(dirpath, exe)
                        break


def find_binary(name, required=True):
    env_name = "%s_BIN" % name.upper()
    candidates = [os.environ.get(env_name), _which(name)]
    if platform.system().lower() == "windows":
        candidates.extend(_windows_common_candidates(name))
    candidates.extend(_remotion_compositor_candidates(name))
    for candidate in candidates:
        candidate = native_path(candidate)
        if _existing(candidate):
            return candidate
    if required:
        hint = (
            "no se encontro %s. Define %s con la ruta completa o instala FFmpeg "
            "nativo para Windows (por ejemplo winget install Gyan.FFmpeg)."
        ) % (name, env_name)
        raise RuntimeError(hint)
    return None


def media_cmd(args):
    if args and args[0] in ("ffmpeg", "ffprobe"):
        return [find_binary(args[0])] + list(args[1:])
    return list(args)


def run(args, **kwargs):
    return subprocess.run(media_cmd(args), **kwargs)


def ensure_media_env(required=True):
    ffmpeg = find_binary("ffmpeg", required=required)
    ffprobe = find_binary("ffprobe", required=required)
    if ffmpeg:
        os.environ.setdefault("FFMPEG_BIN", ffmpeg)
    if ffprobe:
        os.environ.setdefault("FFPROBE_BIN", ffprobe)
    return {"ffmpeg": ffmpeg, "ffprobe": ffprobe}
