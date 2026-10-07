from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any


FORBIDDEN_SPOKEN_PATTERNS = (
    r"\bmini[- ]?payoff\b",
    r"\b(?:audio|narraci[oó]n|est[ií]mulo visual|b[- ]?roll|sfx|motion card|lower third)\s*:",
    r"\bstatus(?: final)?\s*:",
    r"\[(?:sfx|b[- ]?roll|visual|pausa|m[uú]sica)[^\]]*\]",
)


def chapter_spoken_text(chapter: dict[str, Any]) -> str:
    return str(chapter.get("spoken_text") or chapter.get("text") or "").strip()


def full_script(data: dict[str, Any]) -> str:
    return "\n\n".join(chapter_spoken_text(chapter) for chapter in data.get("chapters") or []).strip()


def forbidden_spoken_terms(text: str) -> list[str]:
    return [pattern for pattern in FORBIDDEN_SPOKEN_PATTERNS if re.search(pattern, text, re.I)]


def script_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_approved_script(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = ("schema_version", "run_id", "script_locked", "script_hash", "title", "thumbnail_promise", "hook", "target_minutes", "audience_profile", "chapters")
    for key in required:
        if key not in data:
            errors.append("falta campo requerido: %s" % key)
    schema_version = str(data.get("schema_version") or "")
    if schema_version not in {"1.0", "1.1", "1.2"}:
        errors.append("schema_version debe ser 1.0, 1.1 o 1.2")
    if data.get("script_locked") is not True:
        errors.append("script_locked debe ser true")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}", str(data.get("run_id") or "")):
        errors.append("run_id invalido")
    chapters = data.get("chapters") or []
    if not isinstance(chapters, list) or len(chapters) < 2:
        errors.append("se requieren al menos 2 chapters")
    ids: set[str] = set()
    for index, chapter in enumerate(chapters):
        cid = str(chapter.get("id") or "")
        if not re.fullmatch(r"C\d{2}", cid):
            errors.append("chapter[%d].id debe usar C00" % index)
        if cid in ids:
            errors.append("chapter id repetido: %s" % cid)
        ids.add(cid)
        if len(str(chapter.get("title") or "").strip()) < 3:
            errors.append("chapter[%d].title demasiado corto" % index)
        spoken = chapter_spoken_text(chapter)
        if len(spoken) < 80:
            errors.append("chapter[%d].spoken_text demasiado corto" % index)
        if schema_version in {"1.1", "1.2"} and not str(chapter.get("spoken_text") or "").strip():
            errors.append("chapter[%d].spoken_text es obligatorio en schema 1.1+" % index)
    text = full_script(data)
    for pattern in forbidden_spoken_terms(text):
        errors.append("texto hablado contiene metadata prohibida: %s" % pattern)
    expected = script_hash(text)
    if str(data.get("script_hash") or "") != expected:
        errors.append("script_hash no coincide; el guion fue modificado despues de aprobarse")
    hook = str(data.get("hook") or "").strip().lower()
    if hook and hook not in text.lower()[: max(600, len(hook) + 100)]:
        errors.append("hook no aparece al inicio del guion bloqueado")
    if int(data.get("avatar_appearances", 2) or 0) != 2:
        errors.append("avatar_appearances debe ser exactamente 2")
    if schema_version in {"1.1", "1.2"}:
        cta = data.get("cta") or {}
        spoken_cta = str(cta.get("spoken_text") or "").strip()
        target_title = str(cta.get("target_video_title") or "").strip()
        screen_copy = str(cta.get("screen_copy") or "").strip()
        if len(spoken_cta) < 18 or len(target_title) < 8 or len(screen_copy) < 4:
            errors.append("cta debe incluir spoken_text, target_video_title y screen_copy concretos")
        if spoken_cta and spoken_cta.lower() not in text.lower()[-max(900, len(spoken_cta) + 120):]:
            errors.append("cta.spoken_text debe aparecer literalmente al final del texto hablado")
        if target_title and target_title.lower() not in spoken_cta.lower():
            errors.append("cta debe nombrar literalmente el video de pantalla final")
        if schema_version == "1.2":
            target_id = str(cta.get("target_video_id") or "")
            target_url = str(cta.get("target_url") or "")
            visibility = str(cta.get("visibility") or "")
            if cta.get("verified") is not True or not re.fullmatch(r"[A-Za-z0-9_-]{11}", target_id):
                errors.append("cta 1.2 requiere target_video_id real y verified=true")
            if target_id and target_id not in target_url:
                errors.append("cta.target_url no corresponde a target_video_id")
            if visibility not in {"public", "unlisted"}:
                errors.append("cta de pantalla final debe apuntar a video public o unlisted")
            if len(str(cta.get("target_channel_id") or "")) < 8 or len(str(cta.get("verified_at") or "")) < 10:
                errors.append("cta 1.2 requiere channel_id y verified_at")
    words = re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ]+\b", text, re.UNICODE)
    target_minutes = float(data.get("target_minutes") or 0)
    if target_minutes:
        wpm = len(words) / target_minutes
        if wpm < 105 or wpm > 190:
            errors.append("densidad estimada %.0f palabras/min fuera de 105-190" % wpm)
    if len(text) >= 400:
        accent_count = len(re.findall(r"[áéíóúÁÉÍÓÚüÜñÑ¿¡]", text))
        if accent_count < 4:
            errors.append("guion largo en español sin suficientes tildes/diacriticos")
    return errors


def load_approved_script(path: str | pathlib.Path) -> dict[str, Any]:
    source = pathlib.Path(path)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    errors = validate_approved_script(data)
    if errors:
        raise ValueError("ApprovedScript invalido:\n- " + "\n- ".join(errors))
    return data


def write_with_hash(path: str | pathlib.Path, data: dict[str, Any]) -> None:
    data = dict(data)
    data["script_hash"] = script_hash(full_script(data))
    pathlib.Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
