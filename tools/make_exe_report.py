"""Отчёт о собранном exe: контрольные суммы, файлы проверки и блок для README.

Зачем это нужно. `build_exe.bat` отдаёт папку `dist\\MappersOverlayRedux` с
`MappersOverlayRedux.exe`, но чтобы выложить сборку в релиз и дать людям возможность проверить
файл, нужны числа: MD5,
SHA256, размер, дата сборки. Считать их руками (`certutil`, `Get-FileHash`) и переписывать в
README — источник опечаток: одна цифра не туда, и проверка «не сходится» у всех, кто скачал.
Поэтому числа считает инструмент, а в README вставляется готовый блок целиком.

Что делает инструмент:

* считает MD5 и SHA256 потоком, не загружая exe в память целиком;
* пишет рядом с отчётом `<имя>.md5` и `<имя>.sha256` в формате `md5sum`/`sha256sum`
  (``<хеш>  <имя>``) — их проверяют `md5sum -c` и `sha256sum -c`;
* собирает `MD5SUMS.txt` и `SHA256SUMS.txt` по всем файлам релиза;
* печатает готовый блок для README (`README-exe.md`) с местом под ссылку на VirusTotal;
* по `--pack` упаковывает папку сборки в детерминированный zip: порядок файлов и дата внутри
  архива фиксированы, поэтому повторная сборка того же набора файлов даёт тот же хеш;
* пишет `build-info.json` — те же данные машинно-читаемо, на случай автоматизации релиза.

Запуск (обычно вызывается из `build_exe.bat`)::

    python -m tools.make_exe_report --exe dist\\MappersOverlayRedux\\MappersOverlayRedux.exe \
        --pack dist\\MappersOverlayRedux --out dist\\release
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from map_overlay import __version__

CHUNK: Final = 1 << 20
# Дата внутри zip фиксирована: иначе архив получает новый хеш от каждой сборки на пустом месте.
ZIP_DATE: Final = (1980, 1, 1, 0, 0, 0)
ZIP_MODE: Final = 0o644 << 16
VIRUS_TOTAL_TODO: Final = "TODO: ссылка появится после загрузки файла на virustotal.com"


@dataclass(frozen=True)
class Artifact:
    """Файл релиза с посчитанными суммами."""

    path: Path
    size: int
    md5: str
    sha256: str


@dataclass(frozen=True)
class BuildInfo:
    """Данные сборки, из которых собираются файлы отчёта."""

    version: str
    built_at: datetime
    exe: Artifact
    archive: Artifact | None = None


def digests(path: Path) -> tuple[str, str]:
    """MD5 и SHA256 файла, посчитанные за один проход."""
    # usedforsecurity=False: MD5 здесь нужен для сверки файла, а не для защиты.
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def human_size(size: int) -> str:
    """Размер в байтах с разрядами и удобной единицей: ``1 234 567 байт (1,2 МБ)``.

    До мегабайта показываем килобайты: «0,0 МБ» у файла на 40 КБ — бесполезная цифра.
    """
    scale, unit = (1024, "КБ") if size < 1024 * 1024 else (1024 * 1024, "МБ")
    value = f"{size / scale:.1f}"
    return f"{size:,} байт ({value} {unit})".replace(",", " ").replace(".", ",")


def sums_line(digest: str, path: Path) -> str:
    """Строка формата `md5sum`: хеш, два пробела, имя файла."""
    return f"{digest}  {path.name}\n"


def build_zip(source: Path, dest: Path) -> Path:
    """Упаковать папку сборки в детерминированный zip."""
    files = sorted(path for path in source.rglob("*") if path.is_file())
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(
                str(path.relative_to(source)).replace("\\", "/"), date_time=ZIP_DATE
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ZIP_MODE
            archive.writestr(info, path.read_bytes())
    return dest


def artifact(path: Path) -> Artifact:
    """Собрать сведения о файле: размер, MD5, SHA256."""
    md5, sha256 = digests(path)
    return Artifact(path=path, size=path.stat().st_size, md5=md5, sha256=sha256)


def render_readme_block(info: BuildInfo) -> str:
    """Готовый блок для README: таблица с суммами и местом под VirusTotal."""
    lines = [
        "| Параметр | Значение |",
        "| --- | --- |",
        f"| Файл | `{info.exe.path.name}` |",
        f"| Версия | {info.version} |",
        f"| Размер | {human_size(info.exe.size)} |",
        f"| Собран | {info.built_at:%Y-%m-%d %H:%M} UTC |",
        f"| MD5 | `{info.exe.md5}` |",
        f"| SHA256 | `{info.exe.sha256}` |",
        f"| VirusTotal | {VIRUS_TOTAL_TODO} |",
    ]
    if info.archive is not None:
        lines.append(
            f"| Архив релиза | `{info.archive.path.name}`, "
            f"{human_size(info.archive.size)}, sha256 `{info.archive.sha256}` |"
        )
    return "\n".join(lines) + "\n"


def as_json(info: BuildInfo) -> dict[str, object]:
    """Те же данные в машинном виде: их читает будущая автоматизация релиза."""
    data: dict[str, object] = {
        "version": info.version,
        "built_at": f"{info.built_at:%Y-%m-%dT%H:%M:%SZ}",
        "virus_total": None,
        "exe": {
            "name": info.exe.path.name,
            "size": info.exe.size,
            "md5": info.exe.md5,
            "sha256": info.exe.sha256,
        },
    }
    if info.archive is not None:
        data["archive"] = {
            "name": info.archive.path.name,
            "size": info.archive.size,
            "md5": info.archive.md5,
            "sha256": info.archive.sha256,
        }
    return data


def _write_sums(path: Path, rows: Iterable[tuple[str, Path]]) -> None:
    path.write_text("".join(sums_line(digest, target) for digest, target in rows), encoding="utf-8")


def write_report(info: BuildInfo, out: Path) -> list[Path]:
    """Записать отчёт в каталог `out` и вернуть список созданных файлов."""
    out.mkdir(parents=True, exist_ok=True)
    artifacts = [info.exe] if info.archive is None else [info.exe, info.archive]
    written: list[Path] = []
    for item in artifacts:
        for suffix, digest in ((".md5", item.md5), (".sha256", item.sha256)):
            sidecar = out / f"{item.path.name}{suffix}"
            sidecar.write_text(sums_line(digest, item.path), encoding="utf-8")
            written.append(sidecar)
    md5_sums = out / "MD5SUMS.txt"
    _write_sums(md5_sums, [(item.md5, item.path) for item in artifacts])
    written.append(md5_sums)
    sha_sums = out / "SHA256SUMS.txt"
    _write_sums(sha_sums, [(item.sha256, item.path) for item in artifacts])
    written.append(sha_sums)
    readme = out / "README-exe.md"
    readme.write_text(render_readme_block(info), encoding="utf-8")
    written.append(readme)
    machine = out / "build-info.json"
    machine.write_text(
        json.dumps(as_json(info), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    written.append(machine)
    return written


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(description="Отчёт о собранном exe: суммы и блок для README.")
    parser.add_argument("--exe", type=Path, required=True, help="собранный .exe")
    parser.add_argument("--pack", type=Path, help="папка сборки, которую упаковать в zip")
    parser.add_argument("--out", type=Path, default=Path("dist/release"), help="каталог для отчёта")
    parser.add_argument("--built-at", help="время сборки в ISO 8601 (по умолчанию — сейчас)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Собрать отчёт: суммы, файлы проверки и блок для README."""
    args = parse_args(argv)
    if not args.exe.is_file():
        print(f"Нет файла сборки: {args.exe}", file=sys.stderr)
        return 2
    if args.pack is not None and not args.pack.is_dir():
        print(f"Нет папки сборки: {args.pack}", file=sys.stderr)
        return 2
    built_at = datetime.fromisoformat(args.built_at) if args.built_at else datetime.now(UTC)
    archive: Artifact | None = None
    if args.pack is not None:
        packed = build_zip(args.pack, args.out / f"MappersOverlayRedux_{__version__}_win64.zip")
        archive = artifact(packed)
    info = BuildInfo(
        version=__version__, built_at=built_at, exe=artifact(args.exe), archive=archive
    )
    for path in write_report(info, args.out):
        print(f"Отчёт: {path}")
    print(render_readme_block(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
