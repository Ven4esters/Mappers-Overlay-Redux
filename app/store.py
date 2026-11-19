"""Atomic JSON persistence for config & history. / Атомарное JSON-хранилище.

Design / Устройство:
- two files: ``config.json`` (settings, profiles, albums) and ``history.json``;
- atomic writes (tmp + os.replace) so a crash can't corrupt state;
- corrupt files are backed up to ``<file>.bak-<timestamp>`` and re-initialised,
  the user never loses the file silently and never sees a traceback on launch;
- file permission 0600 on POSIX (webhook URLs are secrets).
- два файла: ``config.json`` (настройки/профили/альбомы) и ``history.json``;
- атомарная запись (tmp + os.replace);
- повреждённый файл уезжает в ``*.bak-<timestamp>`` и создаётся заново;
- права 0600 на POSIX (URL вебхуков — секрет).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from app.models import Album, AppSettings, HistoryItem, WebhookProfile, new_id, utcnow_iso
from app.paths import CONFIG_FILE, HISTORY_FILE
import logging

from app.webhook_url import is_webhook_url

logger = logging.getLogger("screensaver.store")

SCHEMA_VERSION = 1
HISTORY_LIMIT = 50  # locked spec: keep ~50 entries / зафиксировано ТЗ: ~50 записей


def _chmod_private(path: Path) -> None:
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, UnicodeDecodeError):
        backup = path.with_suffix(path.suffix + f".bak-{utcnow_iso().replace(':', '-')}")
        logger.error("corrupt file %s — backed up to %s and re-initialised", path.name, backup.name)
        try:
            shutil.copy2(path, backup)
        except OSError:
            logger.exception("could not copy corrupt file %s to a backup", path)
        return default


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _chmod_private(path)


class ConfigStore:
    """Profiles + albums + settings persistence. / Профили, альбомы и настройки."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = Path(config_path) if config_path else CONFIG_FILE
        self.settings = AppSettings()
        self.profiles: list[WebhookProfile] = []
        self.albums: list[Album] = []
        self.reload()

    # ------------------------------------------------------------ lifecycle
    def reload(self) -> None:
        raw = _read_json(self._path, default={})
        if not isinstance(raw, dict):
            raw = {}
        self.settings = AppSettings.from_dict(raw.get("settings", {}))
        self.profiles = [WebhookProfile.from_dict(p) for p in raw.get("profiles", []) if isinstance(p, dict)]
        self.albums = [Album.from_dict(a) for a in raw.get("albums", []) if isinstance(a, dict)]

    def save(self) -> None:
        payload = {
            "version": SCHEMA_VERSION,
            "settings": self.settings.to_dict(),
            "profiles": [p.to_dict() for p in self.profiles],
            "albums": [a.to_dict() for a in self.albums],
        }
        _write_json_atomic(self._path, payload)

    # ------------------------------------------------------------- profiles
    def get_profile(self, profile_id: str) -> WebhookProfile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    def active_profile(self) -> WebhookProfile | None:
        active = self.settings.active_profile_id
        return self.get_profile(active) if active else (self.profiles[0] if self.profiles else None)

    def add_profile(self, name: str, webhook_url: str, *, channel_type: str = "forum",
                    username_override: str = "", avatar_url: str = "") -> WebhookProfile:
        if not is_webhook_url(webhook_url):
            raise ValueError("Invalid webhook URL / Некорректный URL вебхука")
        profile = WebhookProfile(
            id=new_id(), name=name.strip() or "Webhook", webhook_url=webhook_url.strip(),
            channel_type=channel_type if channel_type in ("forum", "text") else "forum",
            username_override=username_override.strip(), avatar_url=avatar_url.strip(),
        )
        self.profiles.append(profile)
        if not self.settings.active_profile_id:
            self.settings.active_profile_id = profile.id
        self.save()
        return profile

    def update_profile(self, profile_id: str, **changes: Any) -> WebhookProfile | None:
        profile = self.get_profile(profile_id)
        if profile is None:
            return None
        for key, value in changes.items():
            if key == "webhook_url" and value is not None and value != "":
                if not is_webhook_url(str(value)):
                    raise ValueError("Invalid webhook URL / Некорректный URL вебхука")
                value = str(value).strip()
            if hasattr(profile, key):
                setattr(profile, key, value)
        self.save()
        return profile

    def remove_profile(self, profile_id: str) -> None:
        """Delete a profile and its albums (history entries are kept). / Удалить профиль и его альбомы."""
        self.profiles = [p for p in self.profiles if p.id != profile_id]
        self.albums = [a for a in self.albums if a.profile_id != profile_id]
        if self.settings.active_profile_id == profile_id:
            self.settings.active_profile_id = self.profiles[0].id if self.profiles else ""
        self.save()

    def touch_profile(self, profile_id: str) -> None:
        profile = self.get_profile(profile_id)
        if profile:
            profile.last_used_at = utcnow_iso()
            self.save()

    # --------------------------------------------------------------- albums
    def albums_for(self, profile_id: str) -> list[Album]:
        return [a for a in self.albums if a.profile_id == profile_id]

    def get_album(self, album_id: str) -> Album | None:
        return next((a for a in self.albums if a.id == album_id), None)

    def add_album(self, profile_id: str, name: str, thread_id: str) -> Album:
        album = Album(id=new_id(), profile_id=profile_id,
                      name=name.strip() or "Album", thread_id=str(thread_id).strip())
        self.albums.append(album)
        self.save()
        return album

    def update_album(self, album_id: str, **changes: Any) -> Album | None:
        album = self.get_album(album_id)
        if album is None:
            return None
        for key, value in changes.items():
            if hasattr(album, key):
                setattr(album, key, value)
        self.save()
        return album

    def remove_album(self, album_id: str) -> None:
        self.albums = [a for a in self.albums if a.id != album_id]
        self.save()

    # ------------------------------------------------------------- export
    def export_albums(self, target: Path) -> int:
        """Export the album registry to JSON. / Экспорт реестра альбомов."""
        _write_json_atomic(Path(target), {
            "version": SCHEMA_VERSION,
            "type": "albums",
            "albums": [a.to_dict() for a in self.albums],
        })
        return len(self.albums)

    def import_albums(self, source: Path) -> tuple[int, int]:
        """Merge an exported registry. Returns (added, skipped). / Импорт с слиянием, (добавлено, пропущено)."""
        raw = _read_json(Path(source), default={})
        items = raw.get("albums", []) if isinstance(raw, dict) else []
        known = {(a.profile_id, a.thread_id) for a in self.albums}
        added = skipped = 0
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            album = Album.from_dict(item)
            key = (album.profile_id, album.thread_id)
            if not album.thread_id or key in known:
                skipped += 1
                continue
            self.albums.append(album)
            known.add(key)
            added += 1
        if added:
            self.save()
        return added, skipped


class HistoryStore:
    """Send-history persistence. / История отправок."""

    def __init__(self, history_path: Path | None = None) -> None:
        self._path = Path(history_path) if history_path else HISTORY_FILE

    def all(self) -> list[HistoryItem]:
        raw = _read_json(self._path, default={})
        items = raw.get("items", []) if isinstance(raw, dict) else []
        return [HistoryItem.from_dict(i) for i in items if isinstance(i, dict)]

    def append(self, item: HistoryItem) -> None:
        items = self.all()
        items.append(item)
        _write_json_atomic(self._path, {"version": SCHEMA_VERSION,
                                        "items": [i.to_dict() for i in items[-HISTORY_LIMIT:]]})

    def items_for_album(self, album_id: str, *, status: str = "ok") -> list[HistoryItem]:
        return [i for i in self.all() if i.album_id == album_id and i.status == status]

    def update_item(self, item_id: str, **changes) -> HistoryItem | None:
        items = self.all()
        target = next((i for i in items if i.id == item_id), None)
        if target is None:
            return None
        for key, value in changes.items():
            if hasattr(target, key):
                setattr(target, key, value)
        _write_json_atomic(self._path, {"version": SCHEMA_VERSION,
                                        "items": [i.to_dict() for i in items[-HISTORY_LIMIT:]]})
        return target

    def clear(self) -> None:
        _write_json_atomic(self._path, {"version": SCHEMA_VERSION, "items": []})
