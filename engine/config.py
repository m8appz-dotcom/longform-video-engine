"""Configuracion central de reel-engine-v2: paths, modos y helpers de entorno.

Todos los modulos del engine importan de aqui; nada de calcular ROOT a mano
en cada archivo.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# .env nunca se cargaba: PROVIDER_MODE=real quedaba en el archivo pero el
# proceso Python siempre veia el default "mock" (corridas silenciosas sin
# gasto real ni aviso). override=False: una var ya exportada en la shell gana.
try:
    from dotenv import load_dotenv
    # La shell siempre gana. El perfil longform aporta defaults propios y el
    # .env compartido completa credenciales que no esten definidas.
    load_dotenv(os.path.join(ROOT, ".env.longform"), override=False)
    load_dotenv(os.path.join(ROOT, ".env"), override=False)
except ImportError:
    pass

REMOTION_DIR = os.environ.get("REMOTION_DIR", os.path.join(ROOT, "remotion"))
WORK_DIR = os.environ.get("WORK_DIR", os.path.join(ROOT, "work"))
CONTRACTS_DIR = os.path.join(ROOT, "contracts")
PROMPTS_DIR = os.path.join(ROOT, "prompts")
PUB_MEDIA = os.path.join(REMOTION_DIR, "public", "media")
ASSET_LIBRARY_DIR = os.environ.get("LONGFORM_ASSET_LIBRARY", os.path.join(ROOT, "asset-library"))
ASSET_LIBRARY_DB = os.path.join(ASSET_LIBRARY_DIR, "assets.sqlite3")
SCHEMA_PATH = os.path.join(CONTRACTS_DIR, "reel_plan.schema.json")

# Tope duro de reintentos por etapa: al agotarse, el pipeline PARA y reporta.
# Jamas iterar en silencio (leccion de la corrida que loopeo una hora).
MAX_STAGE_RETRIES = int(os.environ.get("MAX_STAGE_RETRIES", "2"))


def env_truthy(name):
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def production_mode():
    return os.environ.get("PROVIDER_MODE", "mock").lower() == "real"


def no_provider_calls():
    return env_truthy("NO_PROVIDER_CALLS")


def prompt_text(name, language="es"):
    """Carga prompts/<name>.md — la UNICA ubicacion de prompts del sistema.

    language!='es' busca prompts/<name>_<language>.md (p.ej. script_en.md,
    structure_arc_en.md). 'es' sigue sin sufijo (compat con todos los prompts
    existentes). Falta el archivo localizado -> error explicito, nunca un
    fallback silencioso a espanol (produciria un guion en el idioma
    equivocado sin que nadie lo note)."""
    lang = (language or "es").strip().lower()
    if lang and lang != "es":
        localized = os.path.join(PROMPTS_DIR, "%s_%s.md" % (name, lang))
        if os.path.exists(localized):
            with open(localized, encoding="utf-8") as f:
                return f.read()
        raise FileNotFoundError(
            "no existe %s para language=%r; crea prompts/%s_%s.md (copia el .md base y traducelo)"
            % (localized, language, name, lang))
    path = os.path.join(PROMPTS_DIR, "%s.md" % name)
    with open(path, encoding="utf-8") as f:
        return f.read()


TMP_DIR = os.path.join(WORK_DIR, "tmp")


def subprocess_env():
    """Entorno para subprocesos (Remotion/ffmpeg/npx): temp en D, nunca en C.
    El disco del sistema llego a 0 bytes en una corrida real por el temp/cache."""
    env = dict(os.environ)
    os.makedirs(TMP_DIR, exist_ok=True)
    env["TMP"] = TMP_DIR
    env["TEMP"] = TMP_DIR
    return env


def ensure_dirs():
    for d in (WORK_DIR, PUB_MEDIA, TMP_DIR, ASSET_LIBRARY_DIR):
        os.makedirs(d, exist_ok=True)
