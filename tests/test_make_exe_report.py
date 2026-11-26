"""Отчёт о сборке exe: суммы, файлы проверки и блок для README."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from map_overlay import __version__
from tools.make_exe_report import (
    Artifact,
    BuildInfo,
    artifact,
    as_json,
    build_zip,
    digests,
    human_size,
    main,
    render_readme_block,
    sums_line,
    write_report,
)

# Контрольные значения для файла «hello»: эталон, а не секрет — помечены для detect-secrets.
HELLO_MD5 = "5d41402abc4b2a76b9719d911017c592"  # pragma: allowlist secret
HELLO_SHA256 = (
    "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"  # pragma: allowlist secret
)
BUILT_AT = datetime(2026, 11, 19, 3, 45, tzinfo=UTC)


@pytest.fixture
def exe(tmp_path: Path) -> Path:
    path = tmp_path / "MappersOverlayRedux.exe"
    path.write_bytes(b"hello")
    return path


def test_digests_match_known_values(exe: Path) -> None:
    assert digests(exe) == (HELLO_MD5, HELLO_SHA256)


def test_digests_of_large_file_stream_in_chunks(tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    payload = b"x" * (3 * 1024 * 1024)
    path.write_bytes(payload)
    md5, sha256 = digests(path)
    assert len(md5) == 32
    assert len(sha256) == 64


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 байт (0,0 КБ)"),
        (1024, "1 024 байт (1,0 КБ)"),
        (40 * 1024, "40 960 байт (40,0 КБ)"),
        (1234567, "1 234 567 байт (1,2 МБ)"),
    ],
)
def test_human_size_uses_spaces_and_comma(size: int, expected: str) -> None:
    assert human_size(size) == expected


def test_sums_line_follows_md5sum_format() -> None:
    assert sums_line("abc", Path("dir") / "file.exe") == "abc  file.exe\n"


def test_build_zip_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "dist"
    (source / "sub").mkdir(parents=True)
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "sub" / "b.txt").write_text("b", encoding="utf-8")
    first = build_zip(source, tmp_path / "one.zip")
    second = build_zip(source, tmp_path / "two.zip")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["a.txt", "sub/b.txt"]


def test_artifact_reports_size_and_sums(exe: Path) -> None:
    item = artifact(exe)
    assert (item.path, item.size, item.md5, item.sha256) == (exe, 5, HELLO_MD5, HELLO_SHA256)


def _info(exe: Path, archive: Artifact | None = None) -> BuildInfo:
    return BuildInfo(version="1.2.3", built_at=BUILT_AT, exe=artifact(exe), archive=archive)


def test_readme_block_has_sums_and_honest_virustotal_todo(exe: Path) -> None:
    block = render_readme_block(_info(exe))
    assert HELLO_MD5 in block
    assert HELLO_SHA256 in block
    assert "| Версия | 1.2.3 |" in block
    assert "2026-11-19 03:45 UTC" in block
    assert "VirusTotal | TODO" in block
    assert "Архив релиза" not in block


def test_readme_block_mentions_archive_when_packed(exe: Path, tmp_path: Path) -> None:
    source = tmp_path / "dist"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    packed = artifact(build_zip(source, tmp_path / "pack.zip"))
    block = render_readme_block(_info(exe, packed))
    assert "| Архив релиза | `pack.zip`," in block
    assert packed.sha256 in block


def test_write_report_creates_every_file(exe: Path, tmp_path: Path) -> None:
    out = tmp_path / "release"
    written = write_report(_info(exe), out)
    names = sorted(path.name for path in written)
    assert names == [
        "MD5SUMS.txt",
        "MappersOverlayRedux.exe.md5",
        "MappersOverlayRedux.exe.sha256",
        "README-exe.md",
        "SHA256SUMS.txt",
        "build-info.json",
    ]
    assert (out / "MappersOverlayRedux.exe.sha256").read_text(encoding="utf-8") == (
        f"{HELLO_SHA256}  MappersOverlayRedux.exe\n"
    )
    assert (out / "MD5SUMS.txt").read_text(encoding="utf-8") == (
        f"{HELLO_MD5}  MappersOverlayRedux.exe\n"
    )


def test_build_info_json_is_machine_readable(exe: Path, tmp_path: Path) -> None:
    out = tmp_path / "release"
    write_report(_info(exe), out)
    data = json.loads((out / "build-info.json").read_text(encoding="utf-8"))
    assert data["version"] == "1.2.3"
    assert data["built_at"] == "2026-11-19T03:45:00Z"
    assert data["virus_total"] is None
    assert data["exe"]["sha256"] == HELLO_SHA256
    assert "archive" not in data


def test_as_json_describes_archive(exe: Path, tmp_path: Path) -> None:
    source = tmp_path / "dist"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    packed = artifact(build_zip(source, tmp_path / "pack.zip"))
    data = as_json(_info(exe, packed))
    assert isinstance(data["archive"], dict)
    assert data["archive"]["name"] == "pack.zip"


def test_main_writes_report_and_prints_block(
    exe: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "release"
    source = tmp_path / "dist"
    source.mkdir()
    (source / "inner.dll").write_text("data", encoding="utf-8")
    code = main(
        [
            "--exe",
            str(exe),
            "--pack",
            str(source),
            "--out",
            str(out),
            "--built-at",
            "2026-11-19T03:45:00+00:00",
        ]
    )
    captured = capsys.readouterr().out
    assert code == 0
    assert f"MappersOverlayRedux_{__version__}_win64.zip" in {path.name for path in out.iterdir()}
    assert "Отчёт:" in captured
    assert HELLO_SHA256 in captured


def test_main_rejects_missing_exe(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--exe", str(tmp_path / "none.exe"), "--out", str(tmp_path / "out")])
    assert code == 2
    assert "Нет файла сборки" in capsys.readouterr().err


def test_main_rejects_missing_pack_dir(
    exe: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--exe", str(exe), "--pack", str(tmp_path / "none"), "--out", str(tmp_path / "o")])
    assert code == 2
    assert "Нет папки сборки" in capsys.readouterr().err
