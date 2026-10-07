from __future__ import annotations

import json
import os
import pathlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


API = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def oauth_path() -> pathlib.Path:
    configured = os.environ.get("YOUTUBE_OAUTH_FILE")
    if configured:
        return pathlib.Path(configured).expanduser().resolve()
    return pathlib.Path(os.environ.get("APPDATA", pathlib.Path.home())) / "YouTubeAutopilot" / "youtube_oauth.json"


def _json_request(url: str, *, token: str | None = None, data: bytes | None = None, timeout: int = 30) -> dict[str, Any]:
    headers = {"User-Agent": "longform-cta-verifier/1.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _access_token(config: dict[str, Any]) -> str:
    missing = [name for name in ("client_id", "client_secret", "refresh_token") if not config.get(name)]
    if missing:
        raise RuntimeError("OAuth de YouTube incompleto: %s" % ", ".join(missing))
    payload = urllib.parse.urlencode({
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "refresh_token": config["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("ascii")
    token = _json_request(TOKEN_URL, data=payload).get("access_token")
    if not token:
        raise RuntimeError("Google no devolvio access_token para verificar CTA")
    return str(token)


def channel_catalog() -> dict[str, Any]:
    path = oauth_path()
    if not path.is_file():
        raise FileNotFoundError("Falta OAuth de YouTube para construir catalogo: %s" % path)
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    token = _access_token(config)
    channel_query = urllib.parse.urlencode({"part": "id,snippet,contentDetails", "mine": "true"})
    channels = _json_request(API + "/channels?" + channel_query, token=token).get("items") or []
    expected = str(config.get("expected_channel_id") or "")
    matches = [item for item in channels if not expected or item.get("id") == expected]
    if len(matches) != 1:
        raise RuntimeError("OAuth no identifica exactamente el canal esperado %s" % expected)
    channel = matches[0]
    uploads = (((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") or "")
    ids: list[str] = []
    page = ""
    while uploads:
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": "50"}
        if page:
            params["pageToken"] = page
        payload = _json_request(API + "/playlistItems?" + urllib.parse.urlencode(params), token=token)
        ids.extend(str((item.get("contentDetails") or {}).get("videoId") or "") for item in payload.get("items") or [])
        page = str(payload.get("nextPageToken") or "")
        if not page:
            break
    videos: list[dict[str, Any]] = []
    for index in range(0, len(ids), 50):
        batch = [value for value in ids[index:index + 50] if value]
        if not batch:
            continue
        params = urllib.parse.urlencode({"part": "id,snippet,status", "id": ",".join(batch), "maxResults": "50"})
        for item in _json_request(API + "/videos?" + params, token=token).get("items") or []:
            status = item.get("status") or {}
            snippet = item.get("snippet") or {}
            thumbnails = snippet.get("thumbnails") or {}
            thumbnail = next((thumbnails.get(key) for key in ("maxres", "standard", "high", "medium", "default") if thumbnails.get(key)), {})
            videos.append({
                "video_id": str(item.get("id") or ""),
                "title": str(snippet.get("title") or ""),
                "channel_id": str(snippet.get("channelId") or channel.get("id") or ""),
                "visibility": str(status.get("privacyStatus") or ""),
                "url": "https://www.youtube.com/watch?v=" + str(item.get("id") or ""),
                "thumbnail_url": str((thumbnail or {}).get("url") or ""),
            })
    return {
        "channel_id": str(channel.get("id") or ""),
        "channel_title": str((channel.get("snippet") or {}).get("title") or ""),
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "videos": videos,
    }


def verify_cta(cta: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    catalog = catalog or channel_catalog()
    target_id = str(cta.get("target_video_id") or "").strip()
    target_title = str(cta.get("target_video_title") or "").strip().casefold()
    matches = [video for video in catalog.get("videos") or [] if target_id and video.get("video_id") == target_id]
    if not matches and target_title:
        matches = [video for video in catalog.get("videos") or [] if str(video.get("title") or "").strip().casefold() == target_title]
    if len(matches) != 1:
        raise RuntimeError("CTA inexistente o ambiguo en el canal autenticado: %s" % (target_id or cta.get("target_video_title") or "sin target"))
    video = matches[0]
    if video.get("visibility") not in {"public", "unlisted"}:
        raise RuntimeError("CTA apunta a video no disponible para audiencia: %s" % video.get("visibility"))
    if video.get("channel_id") != catalog.get("channel_id"):
        raise RuntimeError("CTA pertenece a otro canal")
    return {
        **cta,
        "target_video_id": video["video_id"],
        "target_video_title": video["title"],
        "target_channel_id": video["channel_id"],
        "target_url": video["url"],
        "thumbnail_url": str(video.get("thumbnail_url") or ("https://i.ytimg.com/vi/%s/hqdefault.jpg" % video["video_id"])),
        "visibility": video["visibility"],
        "verified": True,
        "verified_at": catalog["observed_at"],
    }
