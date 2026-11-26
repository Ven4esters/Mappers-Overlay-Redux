"""SBOM релиза: состав поставки в формате CycloneDX JSON."""

from __future__ import annotations

import json
from pathlib import Path

from tools.make_sbom import (
    Component,
    build_bom,
    components_from,
    installed_components,
    main,
    normalise_name,
    write_bom,
)


def test_name_is_normalised_like_pypi() -> None:
    assert normalise_name("PurePySide6_Addons") == "purepyside6-addons"
    assert normalise_name("ruamel.yaml") == "ruamel-yaml"


def test_purl_escapes_version() -> None:
    assert Component("PySide6", "6.8.1").purl == "pkg:pypi/pyside6@6.8.1"


def test_components_are_unique_and_sorted() -> None:
    items = components_from([("b", "1"), ("A", "2"), ("a", "2")])
    assert [item.name for item in items] == ["A", "b"]


def test_bom_has_required_fields() -> None:
    document = build_bom(
        app_version="1.22.0",
        components=[Component("PySide6-Essentials", "6.8.1")],
        generated_at="2026-11-19T12:00:00Z",
    )
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.5"
    assert document["metadata"]["component"]["version"] == "1.22.0"
    assert document["components"][0]["purl"] == "pkg:pypi/pyside6-essentials@6.8.1"


def test_write_bom_is_utf8_json(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "sbom.json"
    write_bom(path, build_bom(app_version="1.0.0", components=[], generated_at="now"))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["components"] == []


def test_installed_components_include_runtime_dependency() -> None:
    names = {normalise_name(item.name) for item in installed_components()}
    assert "pyperclip" in names


def test_main_writes_file(tmp_path: Path, capsys) -> None:
    assert main(["--out", str(tmp_path / "sbom.json")], root=tmp_path) == 0
    assert (tmp_path / "sbom.json").exists()
    assert "SBOM:" in capsys.readouterr().out


def test_metadata_is_read_without_index_operator(monkeypatch) -> None:
    """SBOM читает имя пакета через .get(): на Python 3.12 ``[]`` даёт предупреждение."""

    class StrictMetadata:
        def __getitem__(self, key: str) -> str:
            raise AssertionError(f"метаданные читаются через []: {key} — нужен .get()")

        def get(self, key: str, default: str | None = None) -> str | None:
            return {"Name": "PySide6-Essentials"}.get(key, default)

    class FakeDistribution:
        metadata = StrictMetadata()
        version = "6.8.1"

    monkeypatch.setattr("tools.make_sbom.distributions", lambda: [FakeDistribution()])
    assert [item.name for item in installed_components()] == ["PySide6-Essentials"]
