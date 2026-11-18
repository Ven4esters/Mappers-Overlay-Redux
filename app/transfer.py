"""Export/import of the whole local state as one JSON bundle.
Экспорт/импорт всего локального состояния одним JSON-файлом.

The bundle contains webhook URLs — it is a secret. Importing replaces the
current config + history; the previous files are copied into a timestamped
backup directory first.
Бандл содержит URL вебхуков — это секрет. Импорт заменяет текущие config и
историю; перед заменой файлы копируются в каталог с меткой времени.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.paths import CACHE_DIR, CONFIG_FILE, HISTORY_FILE

BUNDLE_VERSION = 1


class TransferError(RuntimeError):
    """Raised when a bundle cannot be produced or applied. / Бандл не применён."""


@dataclass
class ImportResult:
    """Where the pre-import backup was written. / Куда сложена резервная копия."""

    backup_dir: Path


def export_bundle(dest: Path, *, config_path: Path = CONFIG_FILE,
                  history_path: Path = HISTORY_FILE) -> Path:
    """Write config + history into ``dest``. / Выгрузить config и историю в файл."""
    config = _read_json(config_path, default={})
    history = _read_json(history_path, default={"version": 1, "items": []})
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "app": "screensaver-into-discord",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "config": config if isinstance(config, dict) else {},
        "history": history if isinstance(history, dict) else {"version": 1, "items": []},
    }
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name == "posix":
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
    return dest


def import_bundle(src: Path, *, config_path: Path = CONFIG_FILE,
                  history_path: Path = HISTORY_FILE,
                  backup_root: Path | None = None) -> ImportResult:
    """Replace config + history with the bundle's contents (after backup).
    Заменить config и историю содержимым бандла (после бэкапа)."""
    src = Path(src)
    try:
        bundle = json.loads(src.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TransferError(f"Could not read the file / Не удалось прочитать файл: {exc}") from exc
    except ValueError as exc:
        raise TransferError(f"Not valid JSON / Некорректный JSON: {exc}") from exc

    if not isinstance(bundle, dict):
        raise TransferError("Not an app backup / Это не резервная копия приложения")
    config = bundle.get("config")
    history = bundle.get("history", {"version": 1, "items": []})
    if not isinstance(config, dict) or not any(k in config for k in ("profiles", "albums", "settings")):
        raise TransferError("Corrupt config inside the bundle / Повреждённый config в файле")
    if not isinstance(history, dict) or not isinstance(history.get("items", []), list):
        raise TransferError("Corrupt history inside the bundle / Повреждённая история в файле")

    backup_dir = _backup_current(config_path, history_path, backup_root or (CACHE_DIR / "backups"))
    _atomic_write(Path(config_path), config)
    _atomic_write(Path(history_path), history)
    return ImportResult(backup_dir=backup_dir)


# --------------------------------------------------------------- helpers
def _read_json(path: Path, default):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name == "posix":
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, path)


def _backup_current(config_path: Path, history_path: Path, backup_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_root / stamp
    target.mkdir(parents=True, exist_ok=True)
    for path in (Path(config_path), Path(history_path)):
        if path.exists():
            try:
                shutil.copy2(path, target / path.name)
            except OSError:
                pass
    return target
