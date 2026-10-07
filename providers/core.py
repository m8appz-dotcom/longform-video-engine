#!/usr/bin/env python3
"""Productores del Reel Engine (misma interfaz para mock y real).
- MockProviders: offline, sin llaves (ffmpeg sintetico). Para tests/desarrollo.
- RealProviders: llama a los modelos reales leyendo llaves de os.environ (.env). Sin red en este sandbox.
get_providers() elige por PROVIDER_MODE (mock|real). Este modulo NUNCA hardcodea secretos.
Fuentes API: ElevenLabs /v1/text-to-speech/{voice_id}; Google Gemini Omni Flash
/v1beta/interactions; Codex OAuth image_generation (gpt-image-2);
Kreado via backend local /api/kreado/generate; tokens privados viven solo en ese backend.
"""
import os, json, time, base64, tempfile, urllib.request, urllib.error, urllib.parse, re, shutil, subprocess, hashlib, math, pathlib
from engine import media_tools
from providers.kreado import KreadoService

def run(args): return media_tools.run(args, capture_output=True, text=True)

def _mock_color(value):
    return hashlib.sha256(str(value or "mock").encode("utf-8")).hexdigest()[:6].upper()

def _mock_offset(value, span):
    return int(hashlib.sha256(str(value or "mock").encode("utf-8")).hexdigest()[6:12], 16) % max(1, span)

def _curl_bytes(url, method="GET", headers=None, data=None, timeout=180):
    exe = shutil.which("curl") or shutil.which("curl.exe")
    if not exe:
        raise RuntimeError("urllib fallo y no se encontro curl.exe para fallback HTTP")
    body = None
    if data is not None:
        body = data if isinstance(data, (bytes, bytearray)) else json.dumps(data).encode()
    args = [exe, "-L", "--silent", "--show-error", "--fail", "--max-time", str(timeout)]
    if method and method.upper() != "GET":
        args += ["-X", method.upper()]
    for k, v in (headers or {}).items():
        args += ["-H", "%s: %s" % (k, v)]
    if body is not None:
        args += ["--data-binary", "@-"]
    args.append(url)
    rr = subprocess.run(args, input=body, capture_output=True)
    if rr.returncode != 0:
        detail = (rr.stderr or rr.stdout or b"curl fallo")[-500:].decode("utf-8", "replace")
        raise RuntimeError("curl HTTP fallo: %s" % detail)
    return rr.stdout

def _http(url, method="GET", headers=None, data=None, timeout=180):
    body = None
    if data is not None:
        body = data if isinstance(data, (bytes, bytearray)) else json.dumps(data).encode()
    hdr = {"User-Agent": "reel-engine/0.1", "Accept": "application/json,*/*"}
    hdr.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return 200, _curl_bytes(url, method=method, headers=hdr, data=data, timeout=timeout)

def _download(url, path, timeout=300, headers=None):
    hdr = {"User-Agent": "reel-engine/0.1", "Accept": "*/*"}
    hdr.update(headers or {})
    req = urllib.request.Request(url, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
            f.write(r.read())
    except Exception:
        data = _curl_bytes(url, headers=hdr, timeout=timeout)
        open(path, "wb").write(data)
    return path

def _need(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError("falta la variable de entorno %s (define .env y PROVIDER_MODE=real)" % name)
    return v

def _env_float(name, default):
    raw = os.environ.get(name, str(default))
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError("%s debe ser numerico, recibido: %r" % (name, raw))

def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in ("1", "true", "yes", "on")

def _safe_avatar_prompt(prompt):
    text = prompt or ""
    text = re.sub(r"\b[\w.-]+\.(?:com|net|org|io|ai|co)\b", "premium brand visual style", text, flags=re.I)
    return text

CLIP_QUERY_NOISE_PATTERNS = [
    r"\b(?:no|without)\s+(?:subtitles?|captions?|text(?:\s+overlays?)?|overlays?|logos?|watermarks?|social\s+ui|ui)\b",
    r"\bsin\s+(?:subtitulos|subtítulos|captions?|texto|overlays?|logos?|marcas?\s+de\s+agua|interfaz|ui)\b",
    r"\b(?:raw\s+broadcast|full\s+match\s+broadcast|full\s+match|full\s+episode)\b",
    r"\b(?:vertical|portrait|9:16|reels?|shorts?|tiktok|instagram|documentary|cinematic|editorial|audience|language|tone|format)\b",
]
CLIP_QUERY_PHRASE_COMPACTIONS = []
CLIP_QUERY_DROP_TOKENS = {
    # Solo ruido real. NO recortar anclas de tipo de material ('stock footage',
    # 'b roll', 'clip', 'scene', 'screen recording', 'animation'): el contrato
    # vivo del servicio (GET /api/search-guidelines) las RECOMIENDA dentro del
    # query -- orientan la busqueda de YouTube al material correcto. La drop-list
    # vieja recortaba 'footage' y mataba el patron '{subject} stock footage'.
    "official", "highlight", "highlights",
}
CLIP_QUERY_MAX_TERMS = 8  # el ancla de tipo va al FINAL ('... stock footage'); truncar a 6 la cortaba

def sanitize_clip_extractor_query(query):
    q = str(query or "").strip()
    if not q:
        return ""
    original = q
    for pat, repl in CLIP_QUERY_PHRASE_COMPACTIONS:
        q = re.sub(pat, repl, q, flags=re.I)
    q = re.sub(r"[_/|]+", " ", q)
    for pat in CLIP_QUERY_NOISE_PATTERNS:
        q = re.sub(pat, " ", q, flags=re.I)
    words = re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", q)
    filtered = [w for w in words if w.lower() not in CLIP_QUERY_DROP_TOKENS]
    max_terms = int(os.environ.get("CLIP_EXTRACTOR_QUERY_MAX_TERMS", CLIP_QUERY_MAX_TERMS) or CLIP_QUERY_MAX_TERMS)
    if len(filtered) > max_terms:
        filtered = filtered[:max_terms]
    q = " ".join(filtered)
    q = re.sub(r"\s+", " ", q).strip(" ,.;:-")
    if q != original:
        print("  clip_extractor query saneado: %r -> %r" % (original, q))
    return q

class MockProviders:
    mode = "mock"
    def __init__(self, W, H, fps=24): self.W, self.H, self.fps = W, H, fps
    def tts_voiceover(self, text, dur, path):
        run(["ffmpeg","-y","-f","lavfi","-i","sine=frequency=150:duration=%.2f"%dur,
             "-af","tremolo=f=6:d=0.7,volume=1.8","-ar","48000",path]); return path
    def ambient_bed(self, dur, path):
        run(["ffmpeg","-y","-f","lavfi","-i","anoisesrc=color=pink:duration=%.2f:amplitude=0.05"%dur,
             "-ar","48000",path]); return path
    def image_plate(self, palette, path, prompt=None):
        bg=palette["background"].lstrip("#"); ac=palette["primary"].lstrip("#")
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0x%s:s=%dx%d"%(bg,self.W,self.H),
             "-vf","drawbox=x=0:y=%d:w=%d:h=14:color=0x%s@1:t=fill"%(int(self.H*0.62),self.W,ac),
             "-frames:v","1",path]); return path
    def _mock_generated_video_clip(self, prompt, dur, path, first_frame=None):
        offset = _mock_offset(prompt, max(1, int(self.W * .18)))
        vf=(
            "drawbox=x=0:y=0:w=iw:h=ih:color=0xF0EDE6@1:t=fill,"
            "drawbox=x=%d:y=520:w=840:h=620:color=0xFFFFFF@0.52:t=fill," % (120 + offset) +
            "drawbox=x=0:y=1360:w=iw:h=14:color=0x2D8C74@1:t=fill,"
            "format=yuv420p"
        )
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0xF0EDE6:s=%dx%d:d=%.2f"%(self.W,self.H,dur),
             "-vf",vf,"-r",str(self.fps),path]); return path
    def video_clip(self, source, prompt, dur, path, first_frame=None):
        if (source or "").lower() != "google":
            raise RuntimeError("mock video_clip solo acepta source=google; recibido %r" % source)
        return self._mock_generated_video_clip(prompt, dur, path, first_frame=first_frame)
    def omni_clip(self, prompt, dur, path):
        return self._mock_generated_video_clip(prompt, dur, path)
    def cutout_clip(self, script, dur, path, characteristics=None):
        result = self._mock_generated_video_clip("cutout motion " + str(script), dur, path)
        pathlib.Path(path + ".cutout.json").write_text(json.dumps({
            "provider": "cutout_motion", "mock": True, "characteristics": characteristics or {}, "audio_removed": True,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    def avatar_clip(self, audio_path, dur, path, prompt=None, script_segment=None):
        head_x, head_y = int(self.W * .43), int(self.H * .20)
        head_w, head_h = int(self.W * .14), int(self.H * .25)
        body_x, body_y = int(self.W * .35), int(self.H * .43)
        body_w, body_h = int(self.W * .30), int(self.H * .50)
        vf=(
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x%s@0.18:t=fill," % _mock_color(script_segment) +
            "drawbox=x=%d:y=%d:w=%d:h=%d:color=0xD8D2C5@1:t=fill,"
            "drawbox=x=%d:y=%d:w=%d:h=%d:color=0xFFFFFF@1:t=fill,"
            "drawbox=x=%d:y=%d:w=%d:h=10:color=0x2D8C74@1:t=fill,"
            "format=yuv420p"
        ) % (head_x, head_y, head_w, head_h, body_x, body_y, body_w, body_h, body_x, int(self.H * .94), body_w)
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0xF0EDE6:s=%dx%d:d=%.2f"%(self.W,self.H,dur),
             "-vf",vf,"-r",str(self.fps),"-pix_fmt","yuv420p",path]); return path
    def pexels_clip(self, query, dur, path, characteristics=None):
        x, y, w, h = int(self.W * .04) + _mock_offset(query, int(self.W * .12)), int(self.H * .14) + _mock_offset("y" + query, int(self.H * .15)), int(self.W * .76), int(self.H * .58)
        vf=(
            "drawbox=x=0:y=0:w=iw:h=ih:color=0xF5F3EE@1:t=fill,"
            "drawbox=x=%d:y=%d:w=%d:h=%d:color=0x%s@0.24:t=fill,"
            "drawbox=x=%d:y=%d:w=%d:h=10:color=0x2D8C74@0.9:t=fill,"
            "format=yuv420p"
        ) % (x, y, w, h, _mock_color(query), x, int(self.H * .84), w)
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0xF5F3EE:s=%dx%d:d=%.2f"%(self.W,self.H,dur),
             "-vf",vf,"-r",str(self.fps),path]); return path
    def clip_extractor_clip(self, query, dur, path, characteristics=None, model=None, vllm_base_url=None, max_clip_seconds=None):
        x, y, w, h = int(self.W * .04) + _mock_offset(query, int(self.W * .14)), int(self.H * .10) + _mock_offset("y" + query, int(self.H * .18)), int(self.W * .76), int(self.H * .60)
        vf=(
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x101418@1:t=fill,"
            "drawbox=x=%d:y=%d:w=%d:h=%d:color=0x%s@0.32:t=fill,"
            "drawbox=x=%d:y=%d:w=%d:h=%d:color=0xFFFFFF@0.22:t=fill,"
            "drawbox=x=%d:y=%d:w=%d:h=14:color=0x2D8C74@1:t=fill,"
            "format=yuv420p"
        ) % (x, y, w, h, _mock_color(query), int(self.W*.14), int(self.H*.27), int(self.W*.72), int(self.H*.16), int(self.W*.14), int(self.H*.55), int(self.W*.58))
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0x101418:s=%dx%d:d=%.2f"%(self.W,self.H,dur),
             "-vf",vf,"-r",str(self.fps),path]); return path
    def image_clip(self, prompt, path, model=None):
        x = int(self.W * .04) + _mock_offset(prompt, int(self.W * .18))
        y = int(self.H * .12) + _mock_offset("y" + str(prompt), int(self.H * .18))
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0xF0EDE6:s=%dx%d"%(self.W,self.H),
             "-vf","drawbox=x=%d:y=%d:w=%d:h=%d:color=0x%s@0.24:t=fill,format=rgba"%(x,y,int(self.W*.72),int(self.H*.56),_mock_color(prompt)),
             "-frames:v","1",path]); return path
    def image_asset(self, prompt, path, model=None, size=None):
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0xF0EDE6:s=1024x1024",
             "-vf","drawbox=x=170:y=170:w=684:h=684:color=0x2D8C74@0.14:t=fill,drawbox=x=356:y=356:w=312:h=312:color=0xFFFFFF@0.72:t=fill,format=rgba",
             "-frames:v","1",path]); return path

class RealProviders:
    mode = "real"
    def __init__(self, W, H, fps=24): self.W, self.H, self.fps = W, H, fps
    def _normalize_image(self, src, path):
        rr=run(["ffmpeg","-y","-i",src,"-vf",
                "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,format=rgba" % (self.W,self.H,self.W,self.H),
                "-frames:v","1",path])
        if rr.returncode != 0 or not os.path.exists(path):
            raise RuntimeError("normalizacion de imagen fallo: %s" % (rr.stderr or rr.stdout)[-300:])
        return path
    def tts_voiceover(self, text, dur, path):
        # ElevenLabs con timestamps por caracter -> alimenta el alignment sin whisperX.
        key=_need("ELEVENLABS_API_KEY"); voice=_need("ELEVENLABS_VOICE_ID")
        url="https://api.elevenlabs.io/v1/text-to-speech/%s/with-timestamps"%voice
        body={"text":text,"model_id":os.environ.get("ELEVENLABS_MODEL","eleven_multilingual_v2"),
              "voice_settings":{"stability":_env_float("ELEVENLABS_STABILITY",0.68),
                                "similarity_boost":_env_float("ELEVENLABS_SIMILARITY",0.84),
                                "style":_env_float("ELEVENLABS_STYLE",0.12),
                                "use_speaker_boost":_env_bool("ELEVENLABS_USE_SPEAKER_BOOST", True),
                                "speed":_env_float("ELEVENLABS_SPEED",0.98)}}
        st,raw=_http(url,"POST",{"xi-api-key":key,"Content-Type":"application/json","Accept":"application/json"},body)
        if st>=300: raise RuntimeError("ElevenLabs %s: %s"%(st, raw[:200]))
        d=json.loads(raw)
        mp3=tempfile.mktemp(suffix=".mp3"); open(mp3,"wb").write(base64.b64decode(d["audio_base64"]))
        run(["ffmpeg","-y","-i",mp3,"-ar","48000",path])
        al=d.get("alignment") or d.get("normalized_alignment")
        if al:
            open(os.path.splitext(path)[0]+".align.json","w",encoding="utf-8").write(json.dumps(al,ensure_ascii=False))
        return path
    def ambient_bed(self, dur, path):
        run(["ffmpeg","-y","-f","lavfi","-i","anoisesrc=color=pink:duration=%.2f:amplitude=0.05"%dur,
             "-ar","48000",path]); return path
    def image_plate(self, palette, path, prompt=None):
        prov = os.environ.get("IMAGE_PROVIDER", "local").lower()
        if prov == "openai":
            raise RuntimeError("IMAGE_PROVIDER=openai ya no se usa para imagenes; usa IMAGE_PROVIDER=codex con CODEX_HOME/auth.json")
        if prov == "codex":
            from providers import codex_oauth
            orientation = "horizontal 16:9" if self.W >= self.H else "vertical 9:16"
            p = prompt or ("Fondo %s abstracto y limpio, sin texto, paleta de marca %s, "
                           "estetica editorial y espacio limpio para subtitulos" % (orientation, palette.get("primary", "")))
            default_size = "1536x1024" if self.W >= self.H else "1024x1536"
            png = codex_oauth.image(p, size=os.environ.get("CODEX_IMAGE_SIZE", default_size),
                                    model=os.environ.get("CODEX_IMAGE_MODEL", "gpt-image-2"))
            tmp = tempfile.mktemp(suffix=".png"); open(tmp, "wb").write(png)
            return self._normalize_image(tmp, path)
        bg = palette["background"].lstrip("#"); ac = palette["primary"].lstrip("#")
        run(["ffmpeg","-y","-f","lavfi","-i","color=c=0x%s:s=%dx%d" % (bg, self.W, self.H),
             "-vf","drawbox=x=0:y=%d:w=%d:h=14:color=0x%s@1:t=fill" % (int(self.H*0.62), self.W, ac),
             "-frames:v","1", path])
        return path
    def image_clip(self, prompt, path, model=None):
        from providers import codex_oauth
        if not prompt:
            raise RuntimeError("image_clip requiere prompt")
        landscape = self.W >= self.H
        packaging_text = any(term in prompt.lower() for term in ("packaging", "label", "etiqueta", "envase", "frasco", "tarro", "botella", "lumera"))
        text_rule = (
            "No watermark or UI. Packaging must use a readable fictional label and must not imitate a real trademark. "
            if packaging_text else
            "No text, no logos, no watermark, no UI. "
        )
        p = (
            ("Landscape 16:9 still image for a long-form YouTube video. " if landscape else "Vertical 9:16 still image for a short-form reel. ")
            + text_rule +
            "Keep the main subject clearly visible and leave safe space for captions. "
            + prompt
        )
        default_size = "1536x1024" if landscape else "1024x1536"
        png = codex_oauth.image(
            p,
            size=os.environ.get("CODEX_IMAGE_SIZE", default_size),
            model=model or os.environ.get("CODEX_IMAGE_MODEL", "gpt-image-2"),
            timeout=int(os.environ.get("CODEX_IMAGE_TIMEOUT", "300") or 300),
        )
        tmp = tempfile.mktemp(suffix=".png")
        open(tmp, "wb").write(png)
        return self._normalize_image(tmp, path)
    def image_asset(self, prompt, path, model=None, size=None):
        from providers import codex_oauth
        if not prompt:
            raise RuntimeError("image_asset requiere prompt")
        p = (
            "Square or card-ready editorial image asset for a Remotion overlay. "
            "No text, no logos, no watermark, no UI. "
            "Keep one clear subject centered with generous clean margins. "
            + prompt
        )
        png = codex_oauth.image(
            p,
            size=size or os.environ.get("CODEX_OVERLAY_IMAGE_SIZE", "1024x1024"),
            model=model or os.environ.get("CODEX_IMAGE_MODEL", "gpt-image-2"),
            timeout=int(os.environ.get("CODEX_IMAGE_TIMEOUT", "300") or 300),
        )
        open(path, "wb").write(png)
        return path
    def _google_key(self):
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or _need("GEMINI_API_KEY")

    def _omni_model(self, model=None):
        return model or os.environ.get("OMNI_VIDEO_MODEL") or "gemini-omni-flash-preview"

    def _omni_aspect_ratio(self):
        value = os.environ.get("OMNI_VIDEO_ASPECT_RATIO", "9:16")
        if value not in ("9:16", "16:9"):
            raise RuntimeError("OMNI_VIDEO_ASPECT_RATIO debe ser '9:16' o '16:9'; recibido %r" % value)
        return value

    def _omni_response_format(self):
        fmt = {
            "type": "video",
            "aspect_ratio": self._omni_aspect_ratio(),
        }
        # La documentacion oficial recomienda delivery=uri para videos grandes
        # o >720p cuando este disponible. Omni Flash no expone parametro
        # resolution estable; delivery=uri es la opcion correcta para maxima
        # calidad disponible sin limites de payload inline.
        delivery = os.environ.get("OMNI_VIDEO_DELIVERY", "uri").strip().lower()
        if delivery:
            fmt["delivery"] = delivery
        return fmt

    def _omni_request_body(self, prompt, model):
        body = {
            "model": model,
            "input": prompt,
            "response_format": self._omni_response_format(),
        }
        if body["response_format"].get("delivery") == "uri":
            body["store"] = True
        for env_name, key in (
            ("OMNI_VIDEO_BACKGROUND", "background"),
            ("OMNI_VIDEO_STORE", "store"),
            ("OMNI_VIDEO_STREAM", "stream"),
        ):
            if env_name in os.environ:
                body[key] = _env_bool(env_name)
        return body

    def _omni_output_video(self, data):
        video = data.get("output_video") or {}
        if video.get("uri") or video.get("data"):
            return video
        for step in data.get("steps") or []:
            for item in step.get("content") or []:
                if item.get("type") == "video":
                    return item
        return {}

    def _download_omni_uri(self, uri, path, key):
        file_id = None
        m = re.search(r"/files/([^/:?]+)", uri)
        if m:
            file_id = m.group(1)
        elif uri.startswith("files/"):
            file_id = uri.split("/", 1)[1].split(":", 1)[0]
        attempts = int(os.environ.get("OMNI_VIDEO_POLL_ATTEMPTS", "72"))
        sleep_s = float(os.environ.get("OMNI_VIDEO_POLL_SECONDS", "5"))
        base = "https://generativelanguage.googleapis.com/v1beta"
        if file_id:
            for _ in range(attempts):
                st, raw = _http("%s/files/%s?key=%s" % (base, file_id, urllib.parse.quote(key)), "GET", timeout=60)
                if st >= 300:
                    raise RuntimeError("Gemini Omni file poll %s: %s" % (st, raw[:200]))
                info = json.loads(raw) or {}
                state = str(info.get("state") or "").upper()
                if state == "ACTIVE":
                    break
                if state == "FAILED":
                    raise RuntimeError("Gemini Omni file generation failed: %s" % raw[:240])
                time.sleep(sleep_s)
            download_url = "%s/files/%s:download?alt=media&key=%s" % (base, file_id, urllib.parse.quote(key))
            return _download(download_url, path, timeout=300)
        return _download(uri, path, timeout=300, headers={"x-goog-api-key": key})

    def _omni_generate(self, prompt, dur, path, model=None):
        key = self._google_key()
        model = self._omni_model(model)
        base = "https://generativelanguage.googleapis.com/v1beta"
        if dur:
            prompt = "%s\nTarget duration: about %.1f seconds." % (prompt, float(dur))
        body = self._omni_request_body(prompt, model)
        st, raw = _http("%s/interactions?key=%s" % (base, urllib.parse.quote(key)), "POST",
                        {"Content-Type": "application/json"}, body, timeout=180)
        if st >= 300:
            raise RuntimeError("Gemini Omni submit %s: %s" % (st, raw[:300]))
        data = json.loads(raw) or {}
        video = self._omni_output_video(data)
        if video.get("data"):
            open(path, "wb").write(base64.b64decode(video["data"]))
        elif video.get("uri"):
            self._download_omni_uri(video["uri"], path, key)
        else:
            try:
                debug_dir = os.environ.get("WORK_DIR") or os.path.join(os.getcwd(), "work")
                os.makedirs(debug_dir, exist_ok=True)
                text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
                open(os.path.join(debug_dir, "omni_last_no_video.json"), "w", encoding="utf-8").write(text)
            except Exception:
                pass
            raise RuntimeError("Gemini Omni sin output_video: %s" % raw[:500])
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            raise RuntimeError("Gemini Omni descargo un archivo vacio")
        return path

    def omni_clip(self, prompt, dur, path):
        tmp = tempfile.mktemp(suffix=".mp4")
        try:
            self._omni_generate(prompt, math.ceil(float(dur)), tmp, model=self._omni_model())
            return self._normalize_video(tmp, path, dur=dur)
        finally:
            try: os.remove(tmp)
            except OSError: pass

    def cutout_clip(self, script, dur, path, characteristics=None):
        from providers.cutout_video import CutoutVideoClient
        return CutoutVideoClient(self.W, self.H, self.fps).render_clip(script, dur, path, characteristics=characteristics)

    def video_clip(self, source, prompt, dur, path, first_frame=None):
        provider = os.environ.get("VIDEO_PROVIDER", source or "").lower()
        if provider == "google" or (source or "").lower() == "google":
            if first_frame:
                prompt = "%s\nUse the supplied first frame as visual direction if supported; preserve the same subject and composition." % prompt
            return self.omni_clip(prompt, dur, path)
        raise RuntimeError("VIDEO_PROVIDER/clip.source legacy no permitido: %r/%r. Usa source=google solo con justificacion o una fuente real." % (provider, source))
    def seedance_clip(self, prompt, dur, path, first_frame=None, tier=None, force_wavespeed=False):
        raise RuntimeError("Seedance/WaveSpeed esta deshabilitado en Reel Engine; usa clip_extractor, pexels, image o google justificado")
    def omni_avatar_clip(self, dur, path, prompt=None, script_segment=None):
        raise RuntimeError("Avatar Google/Omni esta deshabilitado en Reel Engine; usa AVATAR_PROVIDER=kreado")
    def avatar_clip(self, audio_path, dur, path, prompt=None, script_segment=None):
        provider = os.environ.get("AVATAR_PROVIDER", "kreado").lower()
        if provider not in ("kreado", "kreado-ai", "kreadoai"):
            raise RuntimeError("AVATAR_PROVIDER no soportado: %s" % provider)
        text = (script_segment or "").strip()
        task_name = "reel-engine-avatar-%d" % int(time.time())
        return KreadoService().generate_avatar_video(
            text=text,
            output_path=path,
            task_name=task_name,
            audio_path=audio_path,
        )
    # Pexels: stock real en la orientacion nativa del perfil activo.
    def pexels_clip(self, query, dur, path, characteristics=None):
        key=_need("PEXELS_API_KEY")
        from urllib.parse import quote
        from engine.media_prefilter import prefilter_search_thumbnail
        characteristics=characteristics or {}
        candidate_offset=max(0, int(characteristics.get("candidate_offset") or 0))
        stop=set("vertical close up person no text high quality background".split())
        terms=[t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t)>2 and t not in stop]
        bad=set("coming soon sign signage letter letters billboard cinema theater movie logo text".split())
        query_text=query.lower()
        wants_body_product=any(token in query_text for token in ("body cream", "body lotion", "skincare product", "cosmetic product"))
        wants_reading=any(token in query_text for token in ("read", "reading", "label", "examine", "examines", "choosing", "compare", "comparing"))
        wants_applying=any(token in query_text for token in ("apply", "applies", "applying", "massage", "rubbing"))
        product_words=set("cream lotion moisturizer skincare cosmetic bottle jar package product".split())
        unrelated_product_words=set("serum oil sunscreen makeup lipstick concealer book grocery medicine hair shampoo".split())
        reading_words=set("read reading looking examine examines checking choosing compare comparing holding".split())
        applying_words=set("apply applies applying massage rubbing".split())

        def semantic_score(text):
            words=set(re.findall(r"[a-z0-9]+", text.lower()))
            penalty=0
            hits=0
            if wants_body_product:
                product_hits=len(words & product_words)
                hits+=product_hits
                if not product_hits: penalty+=3
                if words & unrelated_product_words: penalty+=4
            if wants_reading:
                action_hits=len(words & reading_words)
                hits+=action_hits
                if not action_hits: penalty+=2
                if "book" in words: penalty+=5
            if wants_applying:
                action_hits=len(words & applying_words)
                hits+=action_hits
                if not action_hits: penalty+=2
            return penalty, hits
        def search(orientation):
            url="https://api.pexels.com/videos/search?query=%s&per_page=15"%quote(query)
            if orientation: url+="&orientation=%s"%orientation
            st,raw=_http(url,"GET",{"Authorization":key})
            if st>=300: raise RuntimeError("Pexels search %s: %s"%(st, raw[:200]))
            return (json.loads(raw) or {}).get("videos") or []
        def candidates(vids, want_vertical):
            cand=[]
            for v in vids:
                text=" ".join(str(x or "").lower() for x in (v.get("url"), v.get("image"), (v.get("user") or {}).get("name")))
                hits=sum(1 for t in set(terms) if t in text)
                penalty=sum(1 for t in bad if t in text and t not in terms)
                semantic_penalty, semantic_hits=semantic_score(text)
                best=None
                for f in v.get("video_files", []):
                    w,h=f.get("width") or 0, f.get("height") or 0
                    if not f.get("link"): continue
                    if want_vertical and h<=w: continue
                    if not want_vertical and (h>w or h<1080): continue  # landscape: minimo full HD para croppear a 9:16
                    link=f["link"]
                    link_text=("%s %s"%(text,link)).lower()
                    link_hits=sum(1 for t in set(terms) if t in link_text)
                    link_penalty=penalty+sum(1 for t in bad if t in link_text and t not in terms)
                    score=(semantic_penalty, -semantic_hits, -max(hits,link_hits), link_penalty, abs(w-1080) if want_vertical else -h)
                    if best is None or score < best[0]:
                        best=(score, link, w, h)
                if best:
                    cand.append({
                        "score": list(best[0]), "video_link": best[1], "width": best[2], "height": best[3],
                        "video_id": v.get("id"), "thumbnail": v.get("image"), "page_url": v.get("url"),
                        "creator": (v.get("user") or {}).get("name"),
                        "semantic_penalty": semantic_penalty,
                        "semantic_hits": semantic_hits,
                    })
            cand.sort(key=lambda row: tuple(row["score"]))
            return cand
        want_vertical = self.H > self.W
        preferred_orientation = "portrait" if want_vertical else "landscape"
        cand=candidates(search(preferred_orientation), want_vertical)
        # Fallback landscape: Pexels tiene mucho mas footage de personas/accion en
        # horizontal. Antes se rechazaba entero ('sin clips verticales') y cada fallo
        # empujaba la escena a image/plate; ahora se center-cropea a 9:16 con la
        # misma _normalize_video que ya usa clip_extractor.
        if not cand:
            cand=candidates(search(None), not want_vertical)
        if not cand: raise RuntimeError("Pexels: sin clips utilizables para '%s'"%query)

        # Inspect no more than three cheap thumbnails, then download no more than
        # two full videos. This keeps stock search bounded and rejects obvious
        # watermarks, tutorials, dense text and incompatible presenters early.
        audit=[]
        eligible=[]
        for index, row in enumerate(cand[:3]):
            record=dict(row)
            thumb=path+".pexels_candidate_%d.jpg"%(index+1)
            try:
                if row.get("thumbnail"):
                    _download(row["thumbnail"], thumb)
                    result=prefilter_search_thumbnail(pathlib.Path(thumb), characteristics or {})
                else:
                    result={"status":"REJECT","errors":["candidato sin thumbnail"],"ocr_text":"","metrics":{}}
            except Exception as exc:
                result={"status":"REJECT","errors":["thumbnail: %s"%str(exc)[:180]],"ocr_text":"","metrics":{}}
            record["thumbnail_path"]=thumb if os.path.isfile(thumb) else None
            record["prefilter"]=result
            audit.append(record)
            if result.get("status")=="PASS": eligible.append(row)
        with open(path+".pexels_candidates.json", "w", encoding="utf-8") as handle:
            json.dump({"query":query,"characteristics":characteristics,"candidate_offset":candidate_offset,"candidates":audit}, handle, ensure_ascii=False, indent=2)
        if not eligible:
            raise RuntimeError("Pexels: los 3 thumbnails fallaron prefiltro para '%s'"%query)
        if candidate_offset >= len(eligible):
            raise RuntimeError("Pexels: candidate_offset %d fuera de %d candidatos elegibles para '%s'"%(candidate_offset,len(eligible),query))
        errors=[]
        for index, row in enumerate(eligible[candidate_offset:candidate_offset+1]):
            tmp=path+".pexels_src_%d.mp4"%(index+1)
            try:
                _download(row["video_link"], tmp)
                result=self._normalize_video(tmp, path, dur)
                with open(path+".pexels.json", "w", encoding="utf-8") as handle:
                    json.dump({
                        "provider":"pexels", "query":query, "video_id":row.get("video_id"),
                        "page_url":row.get("page_url"), "creator":row.get("creator"),
                        "source_width":row.get("width"), "source_height":row.get("height"),
                        "candidate_offset":candidate_offset, "thumbnail":row.get("thumbnail"),
                    }, handle, ensure_ascii=False, indent=2)
                return result
            except Exception as exc:
                errors.append("candidate %s: %s"%(row.get("video_id"), str(exc)[:180]))
            finally:
                try: os.remove(tmp)
                except OSError: pass
        raise RuntimeError("Pexels: candidatos descargados fallaron: %s"%" | ".join(errors))
    def _normalize_video(self, src, path, dur=None):
        vf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d,format=yuv420p" % (
            self.W, self.H, self.W, self.H, self.fps
        )
        args = ["ffmpeg", "-y", "-i", src]
        if dur:
            args += ["-t", "%.3f" % float(dur)]
        args += ["-an", "-vf", vf, "-r", str(self.fps), "-pix_fmt", "yuv420p", path]
        rr = run(args)
        if rr.returncode != 0 or not os.path.exists(path) or os.path.getsize(path) <= 0:
            raise RuntimeError("normalizacion de video fallo: %s" % (rr.stderr or rr.stdout)[-500:])
        return path
    def clip_extractor_clip(self, query, dur, path, characteristics=None, model=None, vllm_base_url=None, max_clip_seconds=None):
        base = os.environ.get("CLIP_EXTRACTOR_BASE_URL", "http://100.121.147.73:8765").rstrip("/")
        overall_deadline = time.time() + float(os.environ.get("CLIP_EXTRACTOR_TIMEOUT", "60"))
        query = sanitize_clip_extractor_query(query)
        if not query:
            raise RuntimeError("clip_extractor requiere query")
        st, raw = _http("%s/api/health" % base, "GET", timeout=min(int(os.environ.get("CLIP_EXTRACTOR_HEALTH_TIMEOUT", "15")), max(2, int(overall_deadline - time.time()))))
        if st >= 300:
            raise RuntimeError("Clip Extractor health %s: %s" % (st, raw[:240]))
        try:
            health = json.loads(raw)
        except Exception:
            health = {}
        if health.get("ok") is not True:
            raise RuntimeError("Clip Extractor no esta healthy: %s" % raw[:240])
        body = {
            "query": query,
            "max_clip_seconds": int(max(2, min(30, math.ceil(float(max_clip_seconds or dur))))),
            "dry_run": False,
            "output_dir": os.environ.get("CLIP_EXTRACTOR_OUTPUT_DIR", "./clips"),
            "model": model or os.environ.get("CLIP_EXTRACTOR_MODEL", "gemma-local"),
            "vllm_base_url": vllm_base_url or os.environ.get("CLIP_EXTRACTOR_VLLM_BASE_URL", "http://127.0.0.1:18100/v1"),
            # characteristics ES parte del contrato de /api/clips (ver GET
            # /api/search-guidelines): source_mode antepone variantes de busqueda
            # del tipo de material, avoid penaliza clases malas (tutorial/review/
            # reaction) en titulo/canal Y en la validacion de Gemma, y
            # must_have_visuals define el momento exacto a localizar. Antes se
            # recibia como parametro y se TIRABA (nunca entraba al body): todo el
            # steering estaba muerto -- por eso volvian tutoriales con logos.
            "characteristics": characteristics or {},
        }
        if _env_bool("CLIP_EXTRACTOR_REUSE_COMPLETED", True):
            try:
                history_status, history_raw = _http("%s/api/clips" % base, "GET", timeout=30)
                history = json.loads(history_raw) if history_status < 300 else {}
                matches = [item for item in (history.get("items") or [])
                           if item.get("status") == "completed"
                           and sanitize_clip_extractor_query(item.get("query") or "") == query
                           and (item.get("characteristics") or {}) == (characteristics or {})
                           and (item.get("download_url") or item.get("downloads"))]
                if matches:
                    state = max(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
                    downloads = state.get("downloads") or []
                    dl_url = state.get("download_url")
                    mp4s = [item for item in downloads if item.get("url") and (str(item.get("id") or "").lower() == "mp4" or str(item.get("url")).lower().endswith(".mp4"))]
                    if mp4s:
                        dl_url = mp4s[0]["url"]
                    if dl_url:
                        dl_url = urllib.parse.urljoin(base + "/", dl_url)
                        tmp = tempfile.mktemp(suffix=".mp4")
                        try:
                            _download(dl_url, tmp, timeout=int(os.environ.get("CLIP_EXTRACTOR_DOWNLOAD_TIMEOUT", "300")))
                            self._normalize_video(tmp, path, dur=dur)
                        finally:
                            try: os.remove(tmp)
                            except OSError: pass
                        sidecar = {"provider": "clip_extractor", "base_url": base, "clip_id": state.get("clip_id") or state.get("id"), "query": query, "characteristics": characteristics or {}, "download_url": dl_url, "status": "completed", "reused_completed_job": True, "quality": state.get("quality")}
                        open(path + ".clip_extractor.json", "w", encoding="utf-8").write(json.dumps(sidecar, ensure_ascii=False, indent=2))
                        print("  clip_extractor: trabajo completado reutilizado %s" % (state.get("clip_id") or state.get("id")))
                        return path
            except Exception as reuse_error:
                print("  clip_extractor: cache remota no disponible: %s" % str(reuse_error)[:140])
        st, raw = _http(
            "%s/api/clips" % base,
            "POST",
            {"Content-Type": "application/json"},
            body,
            timeout=min(int(os.environ.get("CLIP_EXTRACTOR_SUBMIT_TIMEOUT", "20")), max(2, int(overall_deadline - time.time()))),
        )
        if st >= 300:
            raise RuntimeError("Clip Extractor submit %s: %s" % (st, raw[:500]))
        data = json.loads(raw)
        clip_id = data.get("clip_id") or data.get("id")
        if not clip_id:
            raise RuntimeError("Clip Extractor no devolvio clip_id: %s" % raw[:300])
        poll_s = float(os.environ.get("CLIP_EXTRACTOR_POLL_SECONDS", "1.5"))
        # Clip Extractor is the preferred source for exact real events, but it
        # must not consume the whole scene budget and starve Pexels.
        deadline = overall_deadline
        state = data
        while time.time() < deadline:
            status = str(state.get("status") or "").lower()
            if status == "completed":
                break
            if status == "failed":
                detail = state.get("error_detail") or state.get("error") or state.get("logs") or state
                raise RuntimeError("Clip Extractor fallo %s: %s" % (clip_id, json.dumps(detail, ensure_ascii=False)[:800]))
            time.sleep(poll_s)
            remaining = max(2, deadline - time.time())
            st, raw = _http(
                "%s/api/clips/%s" % (base, urllib.parse.quote(str(clip_id))),
                "GET",
                timeout=max(2, min(10, int(math.ceil(remaining)))),
            )
            if st >= 300:
                raise RuntimeError("Clip Extractor poll %s: %s" % (st, raw[:300]))
            state = json.loads(raw)
        else:
            raise RuntimeError("Clip Extractor timeout para clip_id=%s" % clip_id)
        downloads = state.get("downloads") or []
        dl_url = state.get("download_url")
        # Preferir la MAYOR resolucion disponible (mandato del dueño). Los
        # variants pueden traer height/width/resolution/label; se ordena por el
        # area/altura descubierta y se cae al variant id='mp4' o al download_url.
        def _variant_score(item):
            for k in ("height", "resolution_height", "h"):
                v = item.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    return int(v)
            label = str(item.get("resolution") or item.get("label") or item.get("quality") or "")
            m = re.search(r"(\d{3,4})\s*[pP]", label) or re.search(r"\d{3,4}\s*[xX]\s*(\d{3,4})", label)
            if m:
                return int(m.group(1))
            w = item.get("width") or 0
            return int(w) if isinstance(w, (int, float)) else 0
        mp4s = [d for d in downloads if d.get("url") and (str(d.get("id") or "").lower() == "mp4" or str(d.get("mime") or d.get("type") or "").lower().endswith("mp4") or str(d.get("url")).lower().endswith(".mp4"))]
        if mp4s:
            best = max(mp4s, key=_variant_score)
            dl_url = best["url"]
            if _variant_score(best):
                print("  clip_extractor: variant %sp elegido de %d disponibles" % (_variant_score(best), len(mp4s)))
        if not dl_url:
            raise RuntimeError("Clip Extractor completed sin download_url: %s" % json.dumps(state, ensure_ascii=False)[:600])
        dl_url = urllib.parse.urljoin(base + "/", dl_url)
        tmp = tempfile.mktemp(suffix=".mp4")
        _download(dl_url, tmp, timeout=int(os.environ.get("CLIP_EXTRACTOR_DOWNLOAD_TIMEOUT", "300")))
        self._normalize_video(tmp, path, dur=dur)
        sidecar = {
            "provider": "clip_extractor",
            "base_url": base,
            "clip_id": clip_id,
            "query": query,
            "characteristics": characteristics or {},
            "download_url": dl_url,
            "status": state.get("status"),
            "steps": state.get("steps") or [],
            "logs": (state.get("logs") or [])[-30:],
            "output_path": state.get("output_path"),
            "downloads": downloads,
        }
        open(path + ".clip_extractor.json", "w", encoding="utf-8").write(json.dumps(sidecar, ensure_ascii=False, indent=2))
        return path

def get_providers(W=1080, H=1920, fps=24):
    return RealProviders(W,H,fps) if os.environ.get("PROVIDER_MODE","mock").lower()=="real" else MockProviders(W,H,fps)
