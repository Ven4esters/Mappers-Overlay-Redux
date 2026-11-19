from __future__ import annotations

import json
from pathlib import Path

from .logger import get_logger
from .models import AppSettings


logger = get_logger("mapper_assist.config")
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "user_config.json"


class ConfigStore:
    """Чтение и атомарное сохранение пользовательского профиля настроек и калибровки."""

    def __init__(self, path: Path | str = DEFAULT_CONFIG_PATH) -> None:
        self.path = Path(path)

    def load(self) -> AppSettings:
        if not self.path.exists():
            logger.info("Файл настроек %s не найден — используются настройки по умолчанию", self.path)
            return AppSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                settings = AppSettings.from_dict(raw)
                missing = settings.calibration.missing_targets()
                logger.info(
                    "Настройки загружены из %s (неоткалибровано точек: %d)",
                    self.path,
                    len(missing),
                )
                return settings
            logger.warning("Корень файла настроек %s не является JSON-объектом — сброс к стандартным", self.path)
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка чтения файла настроек %s — используются стандартные настройки", self.path)
        return AppSettings()

    def save(self, settings: AppSettings) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".json.tmp")
            payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(self.path)
            logger.debug("Настройки сохранены в %s", self.path)
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось сохранить настройки в файл %s", self.path)
