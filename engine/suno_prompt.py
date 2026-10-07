"""Construye solicitudes limpias para Suno sin mezclar contexto editorial."""
from __future__ import annotations

import re
from typing import Any


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" .;,")


def build_suno_request(*, mood: str = "warm, credible, modern", bpm: int = 92,
                       duration_seconds: int = 180, chapter_titles: list[str] | None = None) -> dict[str, Any]:
    """Return fields for Suno Simple/Advanced UI.

    The description contains only audible musical attributes. Audience,
    language, topic and production metadata stay outside the Suno prompt.
    Negative constraints belong in Advanced/Custom Exclude per Suno guidance.
    """
    mood = _clean(mood) or "warm, credible, modern"
    titles = [_clean(title) for title in (chapter_titles or []) if _clean(title)]
    sections = "intro, restrained development, gentle lift, calm resolved ending"
    if titles:
        sections = "intro, restrained development, gentle lift, resolved ending"
    description = (
        "Instrumental organic electronic underscore, %d BPM, %s, "
        "soft piano, subtle marimba textures, restrained percussion, gentle pulse, "
        "wide warm pads, evolving sections, spacious mix for voiceover, "
        "%s, long-form background score."
    ) % (int(bpm), mood, sections)
    exclude = "vocals, lyrics, spoken words, rap, aggressive drums, dramatic drops, harsh distortion, busy lead melodies"
    return {
        "provider": "suno",
        "mode": "advanced",
        "model": "v5.5",
        "instrumental": True,
        "description": description,
        "exclude": exclude,
        "expected_duration_seconds": max(30, int(duration_seconds)),
        "chapter_titles": titles,
        "editorial_context": "health explainer background for an adult audience; do not paste this field into Suno",
        "source": "Suno official guidance: describe genre/instruments/structure; use Exclude for unwanted elements",
    }
