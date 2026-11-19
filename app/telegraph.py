"""telegra.ph (Telegraph) anonymous upload — BB-code media source.
Анонимная загрузка в телеграф (telegra.ph) — источник медиа-ссылок для BB-кода.

Why this exists: it lives inside the Telegram infrastructure, is reachable
from Russia without VPN, accepts anonymous uploads without any account or
key, and returns permanent direct links. Limitations: only
jpg/jpeg/png/gif/mp4, and roughly ~6 MB per file — so big screenshots are
transparently downscaled to 2560 px wide and re-encoded as JPEG (q90) before
upload. Постоянные прямые ссылки без аккаунта; только jpg/png/gif/mp4 и
~6 МБ на файл, поэтому большие скриншоты автоматически уменьшаются до
2560 px по ширине и пережимаются в JPEG (q90).
"""

from __future__ import annotations

import io
import json

import httpx
from PIL import Image

TELEGRAPH_UPLOAD_URL = "https://telegra.ph/upload"
TELEGRAPH_BASE = "https://telegra.ph"

# Hard safety margin under the ~6 MB practical ceiling of the undocumented
# endpoint (the limit includes multipart overhead, so keep clear headroom).
LIMIT_BYTES = 5_500_000
_TARGET_WIDTH = 2560
_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".mp4": "video/mp4",
}


class TelegraphError(RuntimeError):
    """telegra.ph refused or is unreachable. / telegra.ph отказал или недоступен."""


def _is_static_image(name: str) -> bool:
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return suffix in {"png", "jpg", "jpeg", "bmp", "webp"}


def prepare_payload(data: bytes, filename: str) -> tuple[bytes, str, str]:
    """Return (data, filename, mime) that telegra.ph will accept.
    Возвращает (данные, имя, mime), которые telegra.ph примет.

    - non-image files that fit the limit pass through untouched;
    - unsupported image formats (bmp/webp) are re-encoded to JPEG;
    - oversize static images are downscaled to ``_TARGET_WIDTH`` px wide and
      re-encoded as JPEG with decreasing quality until they fit.
    """
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in {"gif", "mp4"}:
        if len(data) <= LIMIT_BYTES:
            return data, filename, _MIME[f".{suffix}"]
        raise TelegraphError(
            f"file is too big for telegra.ph ({len(data)} bytes, limit ~6 MB) / "
            f"файл слишком большой для telegra.ph ({len(data)} байт, лимит ~6 МБ)")

    if not _is_static_image(filename):
        raise TelegraphError(
            f"unsupported file type for telegra.ph: {filename} "
            "(allowed: jpg, png, gif, mp4) / тип файла не поддерживается")

    if suffix == "png" and len(data) <= LIMIT_BYTES:
        return data, filename, "image/png"
    if suffix in {"jpg", "jpeg"} and len(data) <= LIMIT_BYTES:
        return data, filename, "image/jpeg"

    # Oversize or unsupported-but-decodable image: downscale + re-encode.
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 — Pillow raises many exception types
        raise TelegraphError(f"cannot decode image {filename}: {exc}") from exc

    if image.mode in ("P", "RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        background.paste(image, mask=image.getchannel("A") if image.mode in ("RGBA", "LA") else None)
        image = background
    else:
        image = image.convert("RGB")

    width, height = image.size
    if width > _TARGET_WIDTH:
        new_height = max(1, round(height * _TARGET_WIDTH / width))
        image = image.resize((_TARGET_WIDTH, new_height), Image.LANCZOS)

    quality = 90
    while True:
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality, optimize=True)
        encoded = buffer.getvalue()
        if len(encoded) <= LIMIT_BYTES:
            break
        if quality > 60:
            quality -= 15
            continue
        if image.width > 1280:
            new_height = max(1, round(image.height * 1280 / image.width))
            image = image.resize((1280, new_height), Image.LANCZOS)
            quality = 90
            continue
        raise TelegraphError(
            "image stays above telegra.ph limits even after recompression / "
            "изображение остаётся слишком большим для telegra.ph даже после сжатия")

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return encoded, f"{stem}.jpg", "image/jpeg"


def _parse_response(text: str) -> str:
    try:
        payload = json.loads(text or "")
    except ValueError as exc:
        raise TelegraphError(f"telegra.ph returned non-JSON: {text[:200]!r}") from exc

    if isinstance(payload, list):
        entry = payload[0] if payload else {}
        if isinstance(entry, dict):
            src = entry.get("src")
            if isinstance(src, str) and src:
                return f"{TELEGRAPH_BASE}{src}" if src.startswith("/") else src
            error = entry.get("error") or payload
            raise TelegraphError(f"telegra.ph refused the file / Отказ: {error}")
    if isinstance(payload, dict):
        error = payload.get("error") or payload
        raise TelegraphError(f"telegra.ph refused the file / Отказ: {error}")
    raise TelegraphError(f"telegra.ph returned unexpected payload: {text[:200]!r}")


def upload_file(data: bytes, filename: str, *, timeout: float = 120.0) -> str:
    """Upload bytes to telegra.ph; return the direct URL.
    Загружает байты в telegra.ph и возвращает прямую ссылку."""
    data, filename, mime = prepare_payload(data, filename)
    files = {"file": (filename, data, mime)}
    try:
        response = httpx.post(TELEGRAPH_UPLOAD_URL, files=files, timeout=timeout)
    except httpx.HTTPError as exc:
        raise TelegraphError(f"telegra.ph is unreachable / telegra.ph недоступен: {exc}") from exc
    if response.status_code != 200:
        raise TelegraphError(f"telegra.ph HTTP {response.status_code}: {(response.text or '')[:200]}")
    return _parse_response(response.text or "")
