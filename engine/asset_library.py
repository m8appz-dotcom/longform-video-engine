from __future__ import annotations

import hashlib
import contextlib
import json
import pathlib
import re
import shutil
import sqlite3
import time
from typing import Any

from engine.config import ASSET_LIBRARY_DB, ASSET_LIBRARY_DIR


SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY,
  sha256 TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  objects_json TEXT NOT NULL DEFAULT '[]',
  actions_json TEXT NOT NULL DEFAULT '[]',
  mood TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL DEFAULT '',
  job_id TEXT NOT NULL DEFAULT '',
  prompt_query TEXT NOT NULL DEFAULT '',
  width INTEGER NOT NULL DEFAULT 0,
  height INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  license TEXT NOT NULL DEFAULT '',
  qa_status TEXT NOT NULL DEFAULT 'APPROVED',
  ocr_text TEXT NOT NULL DEFAULT '',
  visual_fingerprint_json TEXT NOT NULL DEFAULT '[]',
  use_count INTEGER NOT NULL DEFAULT 0,
  last_used_at REAL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS uses (
  asset_id INTEGER NOT NULL,
  run_id TEXT NOT NULL,
  shot_id TEXT NOT NULL,
  used_at REAL NOT NULL,
  UNIQUE(asset_id, run_id, shot_id)
);
CREATE INDEX IF NOT EXISTS assets_kind_qa ON assets(kind, qa_status);
"""


def _connect() -> sqlite3.Connection:
    pathlib.Path(ASSET_LIBRARY_DIR).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ASSET_LIBRARY_DB)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-záéíóúñ0-9]+", value.lower()) if len(token) > 3}


def register(path: str | pathlib.Path, *, kind: str, description: str, provider: str,
             tags: list[str] | None = None, objects: list[str] | None = None,
             actions: list[str] | None = None, mood: str = "", source_url: str = "",
             job_id: str = "", prompt_query: str = "", width: int = 0, height: int = 0,
             duration_ms: int = 0, license_name: str = "", qa_status: str = "APPROVED",
             ocr_text: str = "", visual_fingerprints: list[int] | None = None) -> int:
    source = pathlib.Path(path).resolve()
    digest = _sha256(source)
    suffix = source.suffix.lower() or ".bin"
    stored = pathlib.Path(ASSET_LIBRARY_DIR) / kind / digest[:2] / (digest + suffix)
    stored.parent.mkdir(parents=True, exist_ok=True)
    if not stored.exists():
        shutil.copy2(source, stored)
    with contextlib.closing(_connect()) as db, db:
        db.execute(
            """INSERT INTO assets(sha256,kind,path,description,tags_json,objects_json,actions_json,mood,provider,source_url,job_id,prompt_query,width,height,duration_ms,license,qa_status,ocr_text,visual_fingerprint_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(sha256) DO UPDATE SET
                 description=excluded.description,
                 tags_json=excluded.tags_json,
                 objects_json=excluded.objects_json,
                 actions_json=excluded.actions_json,
                 mood=excluded.mood,
                 provider=CASE WHEN excluded.provider<>'' THEN excluded.provider ELSE assets.provider END,
                 source_url=CASE WHEN excluded.source_url<>'' THEN excluded.source_url ELSE assets.source_url END,
                 job_id=CASE WHEN excluded.job_id<>'' THEN excluded.job_id ELSE assets.job_id END,
                 prompt_query=CASE WHEN excluded.prompt_query<>'' THEN excluded.prompt_query ELSE assets.prompt_query END,
                 width=MAX(assets.width,excluded.width),
                 height=MAX(assets.height,excluded.height),
                 duration_ms=MAX(assets.duration_ms,excluded.duration_ms),
                 license=CASE WHEN excluded.license<>'' THEN excluded.license ELSE assets.license END,
                 qa_status=excluded.qa_status,
                 ocr_text=excluded.ocr_text,
                 visual_fingerprint_json=excluded.visual_fingerprint_json""",
            (digest, kind, str(stored), description, json.dumps(tags or [], ensure_ascii=False),
             json.dumps(objects or [], ensure_ascii=False), json.dumps(actions or [], ensure_ascii=False), mood,
             provider, source_url, job_id, prompt_query, width, height, duration_ms, license_name,
             qa_status, ocr_text, json.dumps(visual_fingerprints or []), time.time()),
        )
        return int(db.execute("SELECT id FROM assets WHERE sha256=?", (digest,)).fetchone()[0])


def search(query: str, *, kinds: tuple[str, ...], run_id: str, used_hashes: set[str], limit: int = 12) -> list[dict[str, Any]]:
    target = _tokens(query)
    placeholders = ",".join("?" for _ in kinds)
    with contextlib.closing(_connect()) as db, db:
        rows = db.execute(
            f"SELECT * FROM assets WHERE kind IN ({placeholders}) AND qa_status='APPROVED' ORDER BY COALESCE(last_used_at,0) ASC, use_count ASC LIMIT 250",
            kinds,
        ).fetchall()
    ranked = []
    for row in rows:
        item = dict(row)
        if item["sha256"] in used_hashes or not pathlib.Path(item["path"]).is_file():
            continue
        haystack = " ".join([item["description"], item["prompt_query"], item["mood"], item["tags_json"], item["objects_json"], item["actions_json"]])
        overlap = len(target & _tokens(haystack))
        if overlap == 0:
            continue
        fatigue = min(4.0, float(item["use_count"]) * 0.35)
        recency = 2.0 if item["last_used_at"] and time.time() - float(item["last_used_at"]) < 30 * 86400 else 0.0
        item["match_score"] = overlap * 3.0 - fatigue - recency
        ranked.append(item)
    return sorted(ranked, key=lambda item: item["match_score"], reverse=True)[:limit]


def mark_used(asset_id: int, run_id: str, shot_id: str) -> None:
    with contextlib.closing(_connect()) as db, db:
        db.execute("INSERT OR IGNORE INTO uses(asset_id,run_id,shot_id,used_at) VALUES(?,?,?,?)", (asset_id, run_id, shot_id, time.time()))
        db.execute("UPDATE assets SET use_count=(SELECT COUNT(*) FROM uses WHERE asset_id=?),last_used_at=? WHERE id=?", (asset_id, time.time(), asset_id))
