"""catbox.moe anonymous upload. / Анонимная загрузка на catbox.moe.

No account, no stored keys — uploads are anonymous (keyed by source IP).
Direct permanent links come back, which is exactly what BB-code needs.
Без аккаунта и ключей — анонимная загрузка (по IP). Возвращает прямые
постоянные ссылки — то, что нужно для BB-кода.
"""

from __future__ import annotations

import httpx

CATBOX_API = "https://catbox.moe/user/api.php"
_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}


class CatboxError(RuntimeError):
    """catbox.moe refused or is unreachable. / catbox.moe отказал или недоступен."""


def guess_mime(filename: str) -> str:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".png"
    return _MIME.get(suffix, "application/octet-stream")


def upload_file(data: bytes, filename: str, *, userhash: str = "",
                timeout: float = 120.0) -> str:
    """Upload bytes to catbox.moe; return the direct URL. / Загрузить байты; прямая ссылка."""
    payload = {"reqtype": "fileupload"}
    if userhash:
        payload["userhash"] = userhash
    files = {"fileToUpload": (filename, data, guess_mime(filename))}
    try:
        response = httpx.post(CATBOX_API, data=payload, files=files, timeout=timeout)
    except httpx.HTTPError as exc:
        raise CatboxError(f"catbox.moe is unreachable / catbox.moe недоступен: {exc}") from exc

    text = (response.text or "").strip()
    if response.status_code == 200 and text.startswith("http"):
        return text
    if response.status_code == 200:
        raise CatboxError(f"catbox.moe rejected the file / Отказ: {text[:200]}")
    raise CatboxError(f"catbox.moe HTTP {response.status_code}: {text[:200]}")
