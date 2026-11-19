from __future__ import annotations

import re


_FLOAT_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def clean_zero(value: float, eps: float = 1e-9) -> float:
    """Убирает отрицательный ноль (-0.0) и микропогрешности плавающей точки."""
    return 0.0 if abs(value) < eps else float(value)


def normalize_angle_180(angle: float) -> float:
    """Нормализует угол в диапазон [-180.0, 180.0], используемый в меню LSP / GTA V."""
    wrapped = (float(angle) + 180.0) % 360.0 - 180.0
    if abs(wrapped + 180.0) < 1e-9 and angle > 0:
        return 180.0
    return clean_zero(wrapped)


def parse_number(raw: str) -> float:
    """Надёжно извлекает число с плавающей точкой из строки буфера обмена."""
    if raw is None:
        raise ValueError("Пустое значение буфера обмена")
    cleaned = raw.strip().replace("\u2212", "-").replace("\xa0", "").replace(" ", "")
    match = _FLOAT_RE.search(cleaned)
    if not match:
        raise ValueError(f"Не удалось распознать число из строки: {raw!r}")
    token = match.group(0).replace(",", ".")
    return clean_zero(float(token))


def format_number(value: float, decimals: int = 4, strip_trailing_zeros: bool = True) -> str:
    """Форматирует число для вставки в поле редактора без экспоненциальной записи и '-0'."""
    val = clean_zero(round(float(value), decimals), eps=0.5 * (10 ** (-decimals)))
    text = f"{val:.{decimals}f}"
    if strip_trailing_zeros and "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", "-0.0", ""):
        return "0"
    return text
