from __future__ import annotations

import hashlib
import json
import pathlib
import re
import statistics
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any


NEUTRAL_PROFILE: dict[str, Any] = {
    "id": "frontier-dark-v1",
    "source": {"type": "builtin", "value": "frontier-dark", "capturedAt": ""},
    "tokens": {
        "colors": {
            "background": "#0A0A0A",
            "surface": "#191919",
            "surfaceSoft": "#1A1C20",
            "surfaceMid": "#363A3F",
            "text": "#FFFFFF",
            "body": "#DADBDF",
            "muted": "#7D8187",
            "hairline": "#212327",
            "accent": "#FFFFFF",
            "accentSecondary": "#7C3AED",
            "highlight": "#FF7A17",
            "danger": "#FF7A17",
        },
        "semanticColors": {
            "skinSurface": "#D6A18A",
            "skinDeep": "#B97562",
            "tissue": "#C98C75",
            "fluid": "#6F9FA3",
            "fat": "#D2A548",
            "neutral": "#A7ADB2",
        },
        "fonts": {
            "display": '"Inter", Arial, sans-serif',
            "body": '"Inter", Arial, sans-serif',
            "mono": '"Geist Mono", Consolas, monospace',
        },
        "radii": {"panel": 8, "button": 9999},
        "borders": {"width": 1, "color": "#212327"},
        "shadows": {"panel": "none"},
    },
    "typography": {
        "displayWeight": 400,
        "bodyWeight": 400,
        "labelWeight": 400,
        "displayLetterSpacing": 0,
        "labelLetterSpacing": 0,
        "uppercaseLabels": True,
    },
    "composition": {
        "density": "balanced",
        "alignment": "editorial-left",
        "imageTreatment": "high-contrast",
        "cardLanguage": "restrained",
        "edgePadding": 64,
        "panelGap": 32,
        "cardRadius": 8,
        "splitRatio": 0.5,
    },
    "motion": {
        "tempo": "measured",
        "easing": "cubic-bezier(0.16,1,0.3,1)",
        "transitionFrames": 14,
        "cameraBehavior": "subtle",
        "entrance": "rise",
        "emphasis": "focus",
        "intensity": 0.55,
    },
    "advancedVisuals": {"three": [], "webgl": [], "canvas": [], "shaders": [], "particles": []},
    "rendering": {
        "spatialMode": "flat",
        "surfaceStyle": "solid",
        "allowThree": False,
        "allowWebgl": False,
        "allowCanvas": False,
        "allowShaders": False,
        "allowParticles": False,
    },
    "effects": {"useShadows": False, "useGradients": False, "borderStyle": "hairline"},
    "evidence": {"files": [], "fingerprint": "frontier-dark-v1"},
}


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = _copy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = _copy(value)
    return result


def _fetch(url: str, timeout: float = 15.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "LongformDesignProfile/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = str(response.headers.get("content-type") or "")
        charset_match = re.search(r"charset=([^; ]+)", content_type, re.I)
        charset = charset_match.group(1) if charset_match else "utf-8"
        return response.read(2_000_000).decode(charset, errors="replace")


def _css_urls(page_url: str, html: str) -> list[str]:
    values = re.findall(r"<link[^>]+href=[\"']([^\"']+)[\"'][^>]*>", html, re.I)
    urls: list[str] = []
    page_host = urllib.parse.urlparse(page_url).netloc.lower()
    for value in values:
        absolute = urllib.parse.urljoin(page_url, value)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.netloc.lower() != page_host or not parsed.path.lower().endswith(".css"):
            continue
        if absolute not in urls:
            urls.append(absolute)
        if len(urls) >= 10:
            break
    return urls


def _script_urls(page_url: str, html: str) -> list[str]:
    values = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"'][^>]*>", html, re.I)
    urls: list[str] = []
    page_host = urllib.parse.urlparse(page_url).netloc.lower()
    for value in values:
        absolute = urllib.parse.urljoin(page_url, value)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.netloc.lower() != page_host or not parsed.path.lower().endswith((".js", ".mjs")):
            continue
        if absolute not in urls:
            urls.append(absolute)
        if len(urls) >= 12:
            break
    return urls


def _normalize_hex(value: str) -> str:
    value = value.upper()
    if len(value) == 4:
        value = "#" + "".join(char * 2 for char in value[1:])
    return value


def _luminance(hex_value: str) -> float:
    color = _normalize_hex(hex_value).lstrip("#")
    channels = [int(color[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _color_tokens(css: str) -> dict[str, str]:
    colors = [_normalize_hex(value) for value in re.findall(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b", css)]
    counts = Counter(value for value in colors if value not in {"#000000", "#FFFFFF"})
    common = [value for value, _ in counts.most_common(16)]
    light = [value for value in common if _luminance(value) > 0.72]
    dark = [value for value in common if _luminance(value) < 0.18]
    mid = [value for value in common if 0.18 <= _luminance(value) <= 0.72]
    background = light[0] if light else NEUTRAL_PROFILE["tokens"]["colors"]["background"]
    text = dark[0] if dark else NEUTRAL_PROFILE["tokens"]["colors"]["text"]
    accent = mid[0] if mid else NEUTRAL_PROFILE["tokens"]["colors"]["accent"]
    highlight = mid[1] if len(mid) > 1 else NEUTRAL_PROFILE["tokens"]["colors"]["highlight"]
    danger_candidates = [
        value for value in common
        if int(value[1:3], 16) > int(value[3:5], 16) * 1.25
        and int(value[1:3], 16) > int(value[5:7], 16) * 1.18
        and 0.08 < _luminance(value) < 0.62
    ]
    return {
        "background": background,
        "surface": light[1] if len(light) > 1 else "#FFFFFF",
        "text": text,
        "accent": accent,
        "highlight": highlight,
        "danger": danger_candidates[0] if danger_candidates else NEUTRAL_PROFILE["tokens"]["colors"]["danger"],
    }


def _composition_tokens(css: str) -> dict[str, Any]:
    radii = [float(value) for value in re.findall(r"border-radius\s*:\s*([0-9.]+)px", css, re.I)]
    paddings = [float(value) for value in re.findall(r"padding(?:-[a-z]+)?\s*:\s*([0-9.]+)px", css, re.I)]
    radius = min(8, round(statistics.median(radii))) if radii else 4
    median_padding = statistics.median(paddings) if paddings else 20
    density = "compact" if median_padding <= 14 else "relaxed" if median_padding >= 30 else "balanced"
    return {
        "density": density,
        "alignment": "editorial-left",
        "imageTreatment": "natural",
        "cardLanguage": "restrained",
        "edgePadding": 72 if density == "compact" else 96 if density == "relaxed" else 86,
        "panelGap": 36 if density == "compact" else 56 if density == "relaxed" else 46,
        "cardRadius": radius,
        "splitRatio": 0.5,
    }


def _advanced_visual_tokens(text: str) -> dict[str, list[str]]:
    advanced = text.lower()
    return {
        "three": ["observed"] if any(token in advanced for token in ("three.js", "three.module", "@react-three")) else [],
        "webgl": ["observed"] if "webgl" in advanced else [],
        "canvas": ["observed"] if "<canvas" in advanced or "getcontext(\"2d\")" in advanced or "getcontext('2d')" in advanced else [],
        "shaders": ["observed"] if any(token in advanced for token in ("fragmentshader", "vertexshader", "gl_fragcolor")) else [],
        "particles": ["observed"] if any(token in advanced for token in ("particles.js", "tsparticles", "particle")) else [],
    }


def _motion_tokens(css: str, combined: str, advanced: dict[str, list[str]]) -> dict[str, Any]:
    durations: list[int] = []
    for value, unit in re.findall(r"(?:duration|transition)[^;}{:]*:\s*[^;}{]*?([0-9.]+)\s*(ms|s)\b", css, re.I):
        milliseconds = round(float(value) * (1000 if unit.lower() == "s" else 1))
        if 40 <= milliseconds <= 5000:
            durations.append(milliseconds)
    observed = sorted(set(durations))[:12]
    median_ms = statistics.median(observed) if observed else 460
    keyframes = list(dict.fromkeys(re.findall(r"@keyframes\s+([A-Za-z0-9_-]+)", css, re.I)))[:12]
    motion_text = (" ".join(keyframes) + " " + combined).lower()
    entrance = "slide" if any(token in motion_text for token in ("slide", "translatex")) else "scale" if any(token in motion_text for token in ("zoom", "scale(")) else "rise"
    emphasis = "pulse" if any(token in motion_text for token in ("pulse", "bounce")) else "focus" if any(token in motion_text for token in ("blur", "focus")) else "scan"
    spatial = bool(advanced["three"] or advanced["webgl"])
    return {
        "tempo": "fast" if median_ms < 280 else "slow" if median_ms > 800 else "measured",
        "easing": "cubic-bezier(0.16,1,0.3,1)",
        "transitionFrames": max(8, min(24, round(median_ms / 1000 * 30))),
        "cameraBehavior": "active" if spatial or any(token in motion_text for token in ("scrolltrigger", "parallax")) else "subtle",
        "entrance": entrance,
        "emphasis": emphasis,
        "intensity": 0.72 if spatial else 0.58 if observed else 0.5,
        "hasCssAnimation": bool(re.search(r"@keyframes|animation\s*:|transition\s*:", css, re.I)),
        "hasScrollMotion": any(token in combined.lower() for token in ("scrolltrigger", "intersectionobserver", "locomotive-scroll")),
        "observedDurationsMs": observed,
        "keyframes": keyframes,
    }


def _rendering_tokens(advanced: dict[str, list[str]]) -> dict[str, Any]:
    spatial = bool(advanced["three"] or advanced["webgl"])
    return {
        "spatialMode": "three" if spatial else "layered" if advanced["canvas"] else "flat",
        "surfaceStyle": "dimensional" if spatial else "solid",
        "allowThree": bool(advanced["three"]),
        "allowWebgl": bool(advanced["webgl"]),
        "allowCanvas": bool(advanced["canvas"]),
        "allowShaders": bool(advanced["shaders"]),
        "allowParticles": bool(advanced["particles"]),
    }


def _instruction_overrides(instructions: str) -> dict[str, Any]:
    text = str(instructions or "").strip()
    if not text:
        return {}
    low = text.lower()
    overlay: dict[str, Any] = {}
    color_aliases = {
        "background": ("background", "fondo"),
        "surface": ("surface", "superficie"),
        "text": ("text", "texto", "ink", "tinta"),
        "accent": ("accent", "acento", "primary", "primario"),
        "highlight": ("highlight", "resalte", "secondary", "secundario"),
        "danger": ("danger", "alerta", "error"),
    }
    colors: dict[str, str] = {}
    for key, aliases in color_aliases.items():
        match = re.search(r"(?:%s)\s*(?:=|:|es)?\s*(#[0-9a-fA-F]{6})\b" % "|".join(map(re.escape, aliases)), text, re.I)
        if match:
            colors[key] = _normalize_hex(match.group(1))
    if colors:
        overlay["tokens"] = {"colors": colors}

    composition: dict[str, Any] = {}
    if any(term in low for term in ("compact", "compacto", "dense", "denso")):
        composition.update({"density": "compact", "edgePadding": 72, "panelGap": 36})
    elif any(term in low for term in ("relaxed", "relajado", "espacioso", "airy")):
        composition.update({"density": "relaxed", "edgePadding": 96, "panelGap": 56})
    radius = re.search(r"(?:radius|radio)\s*(?:=|:|de)?\s*([0-9.]+)\s*px", low)
    if radius:
        composition["cardRadius"] = min(8, round(float(radius.group(1))))
    split = re.search(r"(?:split|division|proporcion)\s*(?:=|:|de)?\s*(0?\.[0-9]+|[0-9]{2})", low)
    if split:
        value = float(split.group(1))
        composition["splitRatio"] = value / 100 if value > 1 else value
    if composition:
        overlay["composition"] = composition

    advanced = _advanced_visual_tokens(text)
    if any(advanced.values()):
        overlay["advancedVisuals"] = advanced
        overlay["rendering"] = _rendering_tokens(advanced)
    motion: dict[str, Any] = {}
    if any(term in low for term in ("slide", "deslizar", "deslizamiento")):
        motion["entrance"] = "slide"
    elif any(term in low for term in ("scale", "zoom", "escala")):
        motion["entrance"] = "scale"
    elif any(term in low for term in ("rise", "subir", "ascenso")):
        motion["entrance"] = "rise"
    if any(term in low for term in ("high energy", "alta energia", "dinamico", "dynamic")):
        motion["intensity"] = 0.82
    elif any(term in low for term in ("subtle", "sutil", "calm", "calmo")):
        motion["intensity"] = 0.4
    if motion:
        overlay["motion"] = motion
    return overlay


def validate_design_profile(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tokens = profile.get("tokens") or {}
    for group in ("colors", "semanticColors"):
        for key, value in (tokens.get(group) or {}).items():
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(value or "")):
                errors.append("%s.%s debe ser un color hexadecimal de 6 digitos" % (group, key))
    composition = profile.get("composition") or {}
    split_ratio = composition.get("splitRatio", 0.5)
    try:
        split_ratio = float(split_ratio)
    except (TypeError, ValueError):
        errors.append("composition.splitRatio debe ser numerico")
    else:
        if not 0.35 <= split_ratio <= 0.65:
            errors.append("composition.splitRatio debe estar entre 0.35 y 0.65")
    motion = profile.get("motion") or {}
    try:
        intensity = float(motion.get("intensity", 0.5))
    except (TypeError, ValueError):
        errors.append("motion.intensity debe ser numerico")
    else:
        if not 0 <= intensity <= 1.2:
            errors.append("motion.intensity debe estar entre 0 y 1.2")
    rendering = profile.get("rendering") or {}
    if str(rendering.get("spatialMode") or "flat") not in {"flat", "layered", "three"}:
        errors.append("rendering.spatialMode invalido")
    for key in ("allowThree", "allowWebgl", "allowCanvas", "allowShaders", "allowParticles"):
        if key in rendering and not isinstance(rendering[key], bool):
            errors.append("rendering.%s debe ser booleano" % key)
    typography = profile.get("typography") or {}
    for key in ("displayWeight", "bodyWeight", "labelWeight"):
        try:
            weight = int(typography.get(key, 400))
        except (TypeError, ValueError):
            errors.append("typography.%s debe ser numerico" % key)
        else:
            if weight < 100 or weight > 900:
                errors.append("typography.%s debe estar entre 100 y 900" % key)
    for key in ("displayLetterSpacing", "labelLetterSpacing"):
        try:
            spacing = float(typography.get(key, 0) or 0)
        except (TypeError, ValueError):
            errors.append("typography.%s debe ser numerico" % key)
        else:
            if spacing < 0:
                errors.append("typography.%s no admite tracking negativo" % key)
    effects = profile.get("effects") or {}
    for key in ("useShadows", "useGradients"):
        if key in effects and not isinstance(effects[key], bool):
            errors.append("effects.%s debe ser booleano" % key)
    return errors


def _font_tokens(css: str) -> dict[str, str]:
    def semantic_name(value: str) -> str:
        clean = value.strip().strip("\"'")
        var = re.fullmatch(r"var\(--font-([^)]+)\)", clean, re.I)
        if var:
            token = var.group(1).replace("-", " ").strip().lower()
            known = {"jakarta": "Plus Jakarta Sans", "plus jakarta": "Plus Jakarta Sans", "inter": "Inter", "montserrat": "Montserrat"}
            return known.get(token, token.title())
        clean = re.sub(r"^__", "", clean)
        clean = re.sub(r"_[a-f0-9]{6,}$", "", clean, flags=re.I)
        clean = clean.replace("_", " ").strip()
        if re.search(r"plus\s+jakarta", clean, re.I):
            return "Plus Jakarta Sans"
        return clean

    families = []
    for raw in re.findall(r"font-family\s*:\s*([^;}{]+)", css, re.I):
        first = semantic_name(raw.split(",")[0])
        if first and first.lower() not in {
            "inherit", "sans-serif", "serif", "system-ui", "ui-sans-serif",
            "ui-serif", "ui-rounded", "ui-monospace", "monospace", "cursive", "fantasy",
        }:
            families.append(first)
    common = [value for value, _ in Counter(families).most_common(4)]
    mono = next((value for value in common if "mono" in value.lower()), "Geist Mono, Consolas, monospace")
    proportional = [value for value in common if "mono" not in value.lower()]
    return {
        "display": proportional[0] if proportional else "Inter",
        "body": proportional[1] if len(proportional) > 1 else (proportional[0] if proportional else "Inter"),
        "mono": mono,
    }


def _typography_tokens(css: str) -> dict[str, Any]:
    weights = [int(value) for value in re.findall(r"font-weight\s*:\s*([1-9]00)\b", css, re.I)]
    common = [value for value, _ in Counter(weights).most_common()]
    body_weight = common[0] if common else 400
    display_weight = max(weights) if weights else body_weight
    return {
        "displayWeight": max(300, min(900, display_weight)),
        "bodyWeight": max(300, min(700, body_weight)),
        "labelWeight": max(300, min(700, body_weight)),
        "displayLetterSpacing": 0,
        "labelLetterSpacing": 0,
        "uppercaseLabels": bool(re.search(r"text-transform\s*:\s*uppercase", css, re.I)),
    }


def _effect_tokens(css: str) -> dict[str, Any]:
    shadows = [value.strip() for value in re.findall(r"box-shadow\s*:\s*([^;}{]+)", css, re.I)]
    use_shadows = any(value.lower() not in {"none", "initial", "inherit"} for value in shadows)
    return {
        "useShadows": use_shadows,
        "useGradients": bool(re.search(r"(?:linear|radial|conic)-gradient\s*\(", css, re.I)),
        "borderStyle": "hairline" if re.search(r"border(?:-[a-z]+)?\s*:\s*1px\b", css, re.I) else "solid",
    }


def extract_design_profile(url: str, cache_dir: pathlib.Path) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("design source URL debe usar http/https")
    html = _fetch(url)
    evidence: list[dict[str, str]] = [{"url": url, "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest()}]
    css_parts = ["\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.I | re.S))]
    for css_url in _css_urls(url, html):
        try:
            css = _fetch(css_url)
        except Exception:
            continue
        css_parts.append(css)
        evidence.append({"url": css_url, "sha256": hashlib.sha256(css.encode("utf-8")).hexdigest()})
    script_parts: list[str] = []
    for script_url in _script_urls(url, html):
        try:
            script = _fetch(script_url)
        except Exception:
            continue
        script_parts.append(script)
        evidence.append({"url": script_url, "sha256": hashlib.sha256(script.encode("utf-8")).hexdigest()})
    css_text = "\n".join(css_parts)
    script_text = "\n".join(script_parts)
    combined = html + "\n" + css_text + "\n" + script_text
    fingerprint = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    profile = _copy(NEUTRAL_PROFILE)
    profile.update({
        "id": "url-" + fingerprint[:16],
        "source": {"type": "url", "value": url, "capturedAt": "runtime"},
        "evidence": {"files": evidence, "fingerprint": fingerprint},
    })
    profile["tokens"]["colors"] = _color_tokens(css_text)
    profile["tokens"]["fonts"] = _font_tokens(css_text)
    profile["typography"] = _typography_tokens(css_text)
    profile["composition"] = _composition_tokens(css_text)
    profile["advancedVisuals"] = _advanced_visual_tokens(combined)
    profile["motion"] = _motion_tokens(css_text, combined, profile["advancedVisuals"])
    profile["rendering"] = _rendering_tokens(profile["advancedVisuals"])
    profile["effects"] = _effect_tokens(css_text)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / (profile["id"] + ".json")).write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return profile


def resolve_design_profile(data: dict[str, Any], cache_dir: pathlib.Path) -> dict[str, Any]:
    explicit = data.get("design_profile") or {}
    source = data.get("design_source") or {}
    if isinstance(source, str):
        source = {"type": "url" if source.startswith(("http://", "https://")) else "instructions", "value": source}
    profile = _copy(NEUTRAL_PROFILE)
    source_type = str(source.get("type") or "").lower() if isinstance(source, dict) else ""
    source_instructions = str(source.get("value") or "").strip() if source_type == "instructions" else ""
    direct_instructions = str(data.get("design_instructions") or "").strip()
    instructions = " ".join(value for value in (source_instructions, direct_instructions) if value).strip()
    instruction_url = re.search(r"https?://[^\s<>\"']+", instructions)
    if source_type == "instructions" and instruction_url:
        source = {"type": "url", "value": instruction_url.group(0).rstrip(".,);]")}
        source_type = "url"
    if isinstance(source, dict) and str(source.get("type") or "").lower() == "url" and str(source.get("value") or "").strip():
        url = str(source["value"]).strip()
        cache_key = "url-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        latest = cache_dir / (cache_key + "-latest.json")
        try:
            profile = extract_design_profile(url, cache_dir)
            latest.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            if latest.is_file():
                profile = json.loads(latest.read_text(encoding="utf-8"))
                profile.setdefault("source", {})["refreshError"] = str(exc)[:300]
            else:
                raise RuntimeError("no se pudo resolver DesignProfile desde %s: %s" % (url, exc)) from exc
    if instructions:
        profile = _deep_merge(profile, _instruction_overrides(instructions))
        profile["instructions"] = instructions
    if isinstance(explicit, dict) and explicit:
        profile = _deep_merge(profile, explicit)
    profile = _deep_merge(NEUTRAL_PROFILE, profile)
    if (explicit and not explicit.get("id")) or instructions:
        profile["id"] = "project-" + hashlib.sha256(json.dumps(profile, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    else:
        profile["id"] = str(profile.get("id") or "frontier-dark-v1")
    errors = validate_design_profile(profile)
    if errors:
        raise ValueError("DesignProfile invalido: " + "; ".join(errors))
    return profile


def remotion_theme(profile: dict[str, Any]) -> dict[str, Any]:
    colors = ((profile.get("tokens") or {}).get("colors") or {})
    fonts = ((profile.get("tokens") or {}).get("fonts") or {})
    semantic = ((profile.get("tokens") or {}).get("semanticColors") or {})
    return {
        "background": str(colors.get("background") or NEUTRAL_PROFILE["tokens"]["colors"]["background"]),
        "surface": str(colors.get("surface") or "#FFFFFF"),
        "text": str(colors.get("text") or NEUTRAL_PROFILE["tokens"]["colors"]["text"]),
        "accent": str(colors.get("accent") or NEUTRAL_PROFILE["tokens"]["colors"]["accent"]),
        "highlight": str(colors.get("highlight") or NEUTRAL_PROFILE["tokens"]["colors"]["highlight"]),
        "danger": str(colors.get("danger") or NEUTRAL_PROFILE["tokens"]["colors"]["danger"]),
        "body": str(colors.get("body") or colors.get("text") or NEUTRAL_PROFILE["tokens"]["colors"]["body"]),
        "muted": str(colors.get("muted") or NEUTRAL_PROFILE["tokens"]["colors"]["muted"]),
        "hairline": str(colors.get("hairline") or NEUTRAL_PROFILE["tokens"]["colors"]["hairline"]),
        "accentSecondary": str(colors.get("accentSecondary") or NEUTRAL_PROFILE["tokens"]["colors"]["accentSecondary"]),
        "semanticColors": {key: str(semantic.get(key) or value) for key, value in NEUTRAL_PROFILE["tokens"]["semanticColors"].items()},
        "fontDisplay": str(fonts.get("display") or '"Inter", Arial, sans-serif'),
        "fontBody": str(fonts.get("body") or fonts.get("display") or '"Inter", Arial, sans-serif'),
        "fontMono": str(fonts.get("mono") or '"Geist Mono", Consolas, monospace'),
        "typography": profile.get("typography") or {},
        "motion": profile.get("motion") or {},
        "composition": profile.get("composition") or {},
        "advancedVisuals": profile.get("advancedVisuals") or {},
        "rendering": profile.get("rendering") or {},
        "effects": profile.get("effects") or {},
        "profileId": str(profile.get("id") or "frontier-dark-v1"),
    }


def design_prompt_scope(profile: dict[str, Any]) -> str:
    theme = remotion_theme(profile)
    composition = theme.get("composition") or {}
    advanced = theme.get("advancedVisuals") or {}
    rendering = theme.get("rendering") or {}
    typography = theme.get("typography") or {}
    effects = theme.get("effects") or {}
    observed_advanced = [key for key, values in advanced.items() if values]
    parts = [
        "Project design profile %s" % theme.get("profileId"),
        "palette background %s, text %s, accent %s, highlight %s" % (
            theme.get("background"), theme.get("text"), theme.get("accent"), theme.get("highlight"),
        ),
        "display typography %s, body typography %s" % (theme.get("fontDisplay"), theme.get("fontBody")),
        "type weights display=%s body=%s label=%s, letter spacing=0" % (
            typography.get("displayWeight"), typography.get("bodyWeight"), typography.get("labelWeight"),
        ),
        "composition %s" % ", ".join("%s=%s" % (key, value) for key, value in composition.items()),
        "motion grammar entrance=%s emphasis=%s intensity=%s spatial=%s" % (
            (theme.get("motion") or {}).get("entrance"), (theme.get("motion") or {}).get("emphasis"),
            (theme.get("motion") or {}).get("intensity"), rendering.get("spatialMode"),
        ),
        "effects shadows=%s gradients=%s border=%s" % (
            effects.get("useShadows"), effects.get("useGradients"), effects.get("borderStyle"),
        ),
    ]
    if observed_advanced:
        parts.append("observed advanced motion language: %s" % ", ".join(observed_advanced))
    instructions = str(profile.get("instructions") or "").strip()
    if instructions:
        parts.append("project instructions: %s" % re.sub(r"\s+", " ", instructions)[:320])
    return ". ".join(part for part in parts if part).strip() + "."
