#!/usr/bin/env python3
"""Transporte OAuth de Codex (token crudo de ~/.codex/auth.json) -> backend Responses de ChatGPT.
ADVERTENCIA: reusar este token fuera de la Codex CLI va contra los Terminos de OpenAI; puede
romperse al expirar/rotar y arriesga tu cuenta. Bajo tu propio riesgo.
Mecanismo (impl comunitaria openai-oauth):
  endpoint  : https://chatgpt.com/backend-api/codex/responses
  auth      : Authorization: Bearer <access_token>  +  chatgpt-account-id: <account_id>
  refresh   : POST https://auth.openai.com/oauth/token (client_id app_EMoamEEZ73f0CkXaXp7hrann)
  cuerpo    : Responses con store=false, stream=true (SSE). Texto e imagen via tools Codex OAuth.
"""
import os, json, datetime, uuid, base64, time, urllib.request, urllib.error
from engine import media_tools

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
BASE = os.environ.get("CODEX_BASE_URL", "https://chatgpt.com/backend-api/codex")

def _auth_path():
    if os.environ.get("CODEX_AUTH"):
        return media_tools.native_path(os.environ["CODEX_AUTH"])
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(media_tools.native_path(home), "auth.json")

def _load():
    p = _auth_path()
    if not os.path.exists(p):
        raise RuntimeError("no existe %s ; corre 'codex login' en este entorno" % p)
    return p, json.load(open(p, encoding="utf-8"))

def _open(url, method="POST", headers=None, data=None, timeout=180):
    body = None if data is None else (data if isinstance(data,(bytes,bytearray)) else json.dumps(data).encode())
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s en %s: %s" % (e.code, url, e.read()[:300]))

def _fresh_token():
    p, d = _load()
    t = d.get("tokens") or d
    access, refresh = t.get("access_token"), t.get("refresh_token")
    last = d.get("last_refresh") or t.get("last_refresh")
    need = not access
    if not need and last:
        try:
            lt = datetime.datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            need = (datetime.datetime.now(datetime.timezone.utc) - lt).days >= 9
        except Exception:
            need = False
    if need and refresh:
        r = _open(TOKEN_URL, "POST", {"Content-Type": "application/json"},
                  {"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": refresh})
        nj = json.loads(r.read())
        t["access_token"] = nj.get("access_token", access)
        for k in ("refresh_token", "id_token"):
            if nj.get(k): t[k] = nj[k]
        d["tokens"] = t
        d["last_refresh"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        json.dump(d, open(p, "w"), indent=2)
        access = t["access_token"]
    return access, (t.get("account_id") or d.get("account_id"))

def _version():
    if os.environ.get("CODEX_VERSION"):
        return os.environ["CODEX_VERSION"]
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    try:
        return json.load(open(os.path.join(media_tools.native_path(home), "version.json"))).get("version", "0.0.0")
    except Exception:
        return "0.0.0"

def _headers(access, account):
    v = _version()
    return {
        "Authorization": "Bearer %s" % access,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "chatgpt-account-id": account or "",
        "OpenAI-Beta": "responses=experimental",
        "originator": "codex_cli_rs",
        "session_id": str(uuid.uuid4()),
        "version": v,
        "User-Agent": "codex_cli_rs/%s" % v,
    }

def responses(input_items, model=None, tools=None, instructions=None, timeout=180):
    access, account = _fresh_token()
    if not access:
        raise RuntimeError("sin access_token en auth.json; corre 'codex login'")
    model = model or os.environ.get("CODEX_MODEL", "gpt-5.4")
    body = {"model": model, "input": input_items, "store": False, "stream": True}
    if not instructions:
        instructions = os.environ.get("CODEX_INSTRUCTIONS", "Eres un asistente util. Responde solo lo pedido.")
    body["instructions"] = instructions
    if tools: body["tools"] = tools
    r = _open(BASE + "/responses", "POST", _headers(access, account), body, timeout=timeout)
    out = []
    for raw in r:
        line = raw.decode("utf-8", "ignore").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("[DONE]", ""):
            continue
        try:
            ev = json.loads(payload)
        except Exception:
            continue
        if ev.get("type", "").endswith("output_text.delta"):
            out.append(ev.get("delta", ""))
        elif ev.get("type", "") == "response.completed":
            break
    return "".join(out).strip()

def ping():
    return responses([{"role": "user", "content": [{"type": "input_text", "text": "responde solo: OK"}]}])


def _image_once(prompt, size=None, model=None, timeout=300):
    """Una llamada de generacion de imagen. Devuelve bytes PNG o lanza."""
    access, account = _fresh_token()
    if not access:
        raise RuntimeError("sin access_token en auth.json; corre 'codex login'")
    image_model = model or os.environ.get("CODEX_IMAGE_MODEL", "gpt-image-2")
    response_model = os.environ.get("CODEX_IMAGE_RESPONSE_MODEL") or os.environ.get("CODEX_MODEL", "gpt-5.4")
    size = size or os.environ.get("CODEX_IMAGE_SIZE", "1024x1536")
    tool = {"type": "image_generation", "model": image_model}
    if size and size != "auto":
        tool["size"] = size
    body = {"model": response_model, "tools": [tool],
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "store": False, "stream": True}
    r = _open(BASE + "/responses", "POST", _headers(access, account), body, timeout=timeout)
    b64 = None
    for raw in r:
        line = raw.decode("utf-8", "ignore").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("[DONE]", ""):
            continue
        try:
            ev = json.loads(payload)
        except Exception:
            continue
        t = ev.get("type", "")
        if t == "response.output_item.done":
            item = ev.get("item", {})
            if item.get("type") == "image_generation_call" and item.get("result"):
                b64 = item["result"]; break
        elif t == "response.completed":
            break
    if not b64:
        raise RuntimeError("Codex image stream completed without an image result")
    return base64.b64decode(b64)


def image(prompt, size=None, model=None, timeout=300):
    """Genera imagen via Codex con REINTENTOS ante fallos transitorios. Devuelve
    bytes PNG.

    Sin esto, un solo 403/timeout/stream-vacio transitorio (frecuente en gpt-
    image-2 tras varias imagenes seguidas, por throttle) mataba TODA la etapa
    props y desperdiciaba las imagenes ya generadas (hallado en corrida real:
    5 imagenes OK y la 6a murio por un 403 puntual). Backoff exponencial con
    jitter fijo por intento; CODEX_IMAGE_RETRIES controla los intentos (default 4)."""
    retries = int(os.environ.get("CODEX_IMAGE_RETRIES", "4") or 4)
    base_sleep = float(os.environ.get("CODEX_IMAGE_RETRY_BASE_SECONDS", "8") or 8)
    last = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return _image_once(prompt, size=size, model=model, timeout=timeout)
        except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            last = e
            if attempt >= retries:
                break
            # Backoff creciente (8s, 16s, 24s...) para dejar pasar el throttle
            # de la API de imagen antes de reintentar el mismo prompt.
            sleep_s = base_sleep * attempt
            print("  [codex image] intento %d/%d fallo (%s); reintento en %.0fs"
                  % (attempt, retries, str(e)[:80], sleep_s))
            time.sleep(sleep_s)
    raise last
