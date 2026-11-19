"""Local cache of sent screenshots. / Локальный кэш отправленных скриншотов.

Keyed by content hash — re-sending the same bytes never duplicates files.
Used by BB-code export and "Повторить" retry; see app/bbcode.py (module 9).
Ключ — хэш содержимого: повторная отправка тех же байт не плодит файлы.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.paths import CACHE_DIR

_SAFE_SUFFIX_CHARS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
_EXT_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}


def mime_for_suffix(suffix: str) -> str:
    """MIME type for an image file extension. / MIME-тип по расширению."""
    suffix = suffix.lower().lstrip(".")
    return _EXT_MIME.get(f".{suffix}", "image/png")


def guess_ext(mime: str, filename: str = "") -> str:
    """Extension for a shot: from MIME first, then from filename. / Расширение для снимка."""
    ext = _MIME_EXT.get((mime or "").lower())
    if ext:
        return ext
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in _SAFE_SUFFIX_CHARS else ".png"


def cache_root() -> Path:
    return CACHE_DIR / "shots"


def save_shot(data: bytes, filename: str = "shot.png") -> Path:
    """Write bytes into the cache, deduped by content. / Сохранить байты в кэш (дедуп по хэшу)."""
    digest = hashlib.blake2b(data, digest_size=16).hexdigest()
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{digest}{Path(filename).suffix.lower() or '.png'}"
    if not target.exists():
        target.write_bytes(data)
        if os.name == "posix":
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
    return target


def cache_stats() -> tuple[int, int]:
    """(files, bytes) currently held in the shots cache. / (файлов, байт) в кэше снимков."""
    files = 0
    total = 0
    root = cache_root()
    if not root.exists():
        return 0, 0
    for path in root.iterdir():
        if path.is_file():
            try:
                total += path.stat().st_size
                files += 1
            except OSError:
                continue
    return files, total


def clear_cache() -> tuple[int, int]:
    """Delete cache contents; returns (files removed, bytes freed). / Очистить кэш; (файлов, байт)."""
    removed = freed = 0
    root = cache_root()
    if not root.exists():
        return 0, 0
    for path in root.iterdir():
        if path.is_file():
            try:
                freed += path.stat().st_size
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed, freed
