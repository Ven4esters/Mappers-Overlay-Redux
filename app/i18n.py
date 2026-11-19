"""Minimal JSON-based internationalisation (RU/EN).
Небольшая JSON-интернационализация (RU/EN).

Usage / Использование::

    from app.i18n import tr
    label.setText(tr("empty.title"))

Keys are flat dot-separated strings looked up in ``assets/i18n/<lang>.json``.
Missing keys fall back to Russian, then to the key itself (never raises).
Ключи — плоские строки через точку; при отсутствии — откат на RU, затем на сам ключ.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QLocale, QObject, Signal

from app.paths import I18N_DIR

SUPPORTED_LANGS: tuple[str, ...] = ("ru", "en")
DEFAULT_LANG: str = "ru"


def detect_language() -> str:
    """Pick the UI language from the OS locale, defaulting to Russian.
    Выбрать язык интерфейса из локали ОС (по умолчанию русский)."""
    try:
        sys_lang = QLocale.system().name().split("_")[0].lower()
    except Exception:  # noqa: BLE001 — locale detection must never break startup
        return DEFAULT_LANG
    return sys_lang if sys_lang in SUPPORTED_LANGS else DEFAULT_LANG


class Translator(QObject):
    """Loads language packs and notifies the UI on language change.
    Загружает языковые пакеты и уведомляет UI о смене языка."""

    languageChanged = Signal(str)

    def __init__(self, lang: str | None = None) -> None:
        super().__init__()
        self._lang = lang if lang in SUPPORTED_LANGS else detect_language()
        self._pack: dict[str, str] = {}
        self._fallback: dict[str, str] = {}
        self.load(self._lang)

    @staticmethod
    def _read_pack(lang: str) -> dict[str, str]:
        path = I18N_DIR / f"{lang}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Broken language pack {path}: {exc}") from exc

    def load(self, lang: str) -> None:
        self._lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
        self._pack = self._read_pack(self._lang)
        self._fallback = self._read_pack(DEFAULT_LANG) if self._lang != DEFAULT_LANG else {}

    @property
    def language(self) -> str:
        return self._lang

    def set_language(self, lang: str) -> None:
        if lang not in SUPPORTED_LANGS or lang == self._lang:
            return
        self.load(lang)
        self.languageChanged.emit(lang)

    def tr(self, key: str, **kwargs: object) -> str:
        template = self._pack.get(key) or self._fallback.get(key) or key
        return template.format(**kwargs) if kwargs else template


_translator: Translator | None = None


def translator() -> Translator:
    """Global translator singleton. / Глобальный синглтон переводчика."""
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def set_language(lang: str) -> None:
    translator().set_language(lang)


def tr(key: str, **kwargs: object) -> str:
    return translator().tr(key, **kwargs)
