"""Persistent capture queue — shots always live in the cache folder.
Постоянная очередь снимков — все кадры всегда лежат в папке кэша.

Policy (user request): every screenshot is written into the local cache as
soon as it enters the queue, independently of sending and of the
keep_local_cache setting. The queue survives restarts: an index at
``CACHE_DIR / queue.json`` references the content-addressed files in
``CACHE_DIR / shots`` (same fingerprint logic as ``app.cache``), so the same
bytes are never stored twice. The send flow simply reuses the very same
files (dedup by hash) — zero duplication with Discord.

Политика (по запросу): каждый скрин при попадании в очередь пишется в кэш —
независимо от отправки и настройки keep_local_cache. Очередь переживает
перезапуск: индекс ``CACHE_DIR / queue.json`` ссылается на файлы по хэшу из
``CACHE_DIR / shots``. Те же байты дважды не сохраняются никогда.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from app.cache import cache_root
from app.paths import CACHE_DIR

logger = logging.getLogger("screensaver.queue")

INDEX_FILE = "queue.json"
FORMAT_VERSION = 1


def index_path() -> Path:
    return CACHE_DIR / INDEX_FILE


def store_shot(data: bytes, filename: str = "shot.png") -> str:
    """Persist shot bytes into the cache, deduped by content.
    Сохранить байты в кэш (дедуп по содержимому); вернуть имя файла в кэше."""
    suffix = Path(filename).suffix.lower() or ".png"
    digest = hashlib.blake2b(data, digest_size=16).hexdigest()
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{digest}{suffix}"
    if not target.exists():
        target.write_bytes(data)
        if os.name == "posix":
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
    return target.name


def shot_path(cache_name: str) -> Path:
    return cache_root() / cache_name


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_entries() -> list[dict]:
    """Load the queue index; tolerates a missing/corrupt file. / Прочитать индекс."""
    path = index_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("queue index is unreadable — keeping an empty queue (file kept for inspection)")
        return []
    items = raw.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def write_entries(entries: list[dict]) -> None:
    """Atomically rewrite the index. / Атомарно перезаписать индекс."""
    _atomic_write(index_path(), {"version": FORMAT_VERSION, "items": list(entries)})


def make_entry(shot_id: str, filename: str, cache_name: str,
               mime: str = "image/png", checked: bool = True) -> dict:
    return {"id": shot_id, "filename": filename, "ext": Path(filename).suffix.lower() or ".png",
            "mime": mime, "file": cache_name, "checked": bool(checked)}


def restore_entries() -> list[dict]:
    """Entries whose cached file still exists (missing files are dropped).
    Только те записи, чьи файлы в кэше ещё есть."""
    good = []
    for entry in load_entries():
        cache_name = str(entry.get("file", ""))
        if not cache_name or not shot_path(cache_name).is_file():
            logger.warning("queue entry %r references a missing cache file — skipped", entry.get("filename"))
            continue
        good.append(entry)
    return good
