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


# --------------------------------------------------------------------- account
def parse_userfiles(text: str) -> list[str]:
    """Parse the ``reqtype=userfiles`` response: one URL per line.
    Разбор ответа ``userfiles`` — по одному URL на строку."""
    urls = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.lower().startswith("http"):
            urls.append(line)
    return urls


def fetch_userfiles(userhash: str, *, timeout: float = 30.0) -> list[str]:
    """List the files uploaded under a catbox userhash (empty list when none).
    Список файлов на catbox.moe для данного userhash (или пустой список)."""
    if not userhash or not userhash.strip():
        raise CatboxError("userhash is required / нужен userhash")
    payload = {"reqtype": "userfiles", "userhash": userhash.strip()}
    try:
        response = httpx.post(CATBOX_API, data=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise CatboxError(f"catbox.moe is unreachable / catbox.moe недоступен: {exc}") from exc
    if response.status_code != 200:
        raise CatboxError(f"catbox.moe HTTP {response.status_code}: {(response.text or '').strip()[:200]}")
    return parse_userfiles(response.text)


def delete_files(userhash: str, names: list[str], *, timeout: float = 30.0) -> str:
    """Best-effort delete of account files by bare file name.
    Удалить файлы из аккаунта по имени файла (best-effort); вернуть сырой ответ."""
    if not userhash or not names:
        raise CatboxError("userhash and at least one file name are required / нужны userhash и файлы")
    payload = [("reqtype", "deletefiles"), ("userhash", userhash.strip())]
    payload += [("fileToDelete[]", name) for name in names]
    try:
        response = httpx.post(CATBOX_API, data=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise CatboxError(f"catbox.moe is unreachable / catbox.moe недоступен: {exc}") from exc
    return (response.text or "").strip()
