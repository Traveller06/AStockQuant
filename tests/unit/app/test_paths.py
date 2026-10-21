import importlib
from pathlib import Path

import astock_quant.app.paths as paths_module
from astock_quant.app.paths import AppPaths


def test_windows_data_root_uses_localappdata(tmp_path: Path) -> None:
    paths = AppPaths.resolve(
        program_dir=tmp_path / "program",
        env={"LOCALAPPDATA": str(tmp_path / "local")},
    )

    assert paths.program_root == tmp_path / "program"
    assert paths.data_root == tmp_path / "local" / "AStockQuant"
    assert paths.market == paths.data_root / "market"
    assert paths.runs == paths.data_root / "runs"
    assert paths.settings_file == paths.data_root / "settings.json"
    assert paths.manifest_file == paths.data_root / "data_manifest.json"


def test_explicit_test_override_wins(tmp_path: Path) -> None:
    paths = AppPaths.resolve(
        tmp_path / "program", {"ASTOCK_QUANT_DATA_DIR": str(tmp_path / "override")}
    )

    assert paths.data_root == tmp_path / "override"


def test_resolution_does_not_create_personal_data_directories(tmp_path: Path) -> None:
    data_root = tmp_path / "local" / "AStockQuant"

    AppPaths.resolve(tmp_path / "program", {"LOCALAPPDATA": str(tmp_path / "local")})

    assert not data_root.exists()


def test_import_does_not_create_personal_data_directories(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "local" / "AStockQuant"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    importlib.reload(paths_module)

    assert not data_root.exists()


def test_ensure_data_tree_creates_only_personal_data_directories(tmp_path: Path) -> None:
    program_root = tmp_path / "program"
    paths = AppPaths.resolve(program_root, {"LOCALAPPDATA": str(tmp_path / "local")})

    paths.ensure_data_tree()

    assert paths.data_root.is_dir()
    assert paths.market.is_dir()
    assert paths.state.is_dir()
    assert paths.research.is_dir()
    assert paths.runs.is_dir()
    assert paths.reports.is_dir()
    assert paths.logs.is_dir()
    assert not program_root.exists()
