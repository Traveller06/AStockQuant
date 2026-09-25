from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from astock_quant.app.bootstrap import create_application
from astock_quant.data.migration import MigrationService
from astock_quant.reports.run_store import RunStore


def test_bootstrap_constructs_services_without_touching_disk(tmp_path: Path) -> None:
    data_root = tmp_path / "data"

    context = create_application(
        program_dir=tmp_path / "program",
        env={"ASTOCK_QUANT_DATA_DIR": str(data_root)},
        ensure_data=False,
    )

    assert context.paths.data_root == data_root
    assert isinstance(context.migration, MigrationService)
    assert isinstance(context.run_store, RunStore)
    assert context.settings.real_trading_enabled is False
    assert not data_root.exists()


def test_bootstrap_can_create_default_tree_and_settings_once(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    environment = {"ASTOCK_QUANT_DATA_DIR": str(data_root)}

    first = create_application(tmp_path / "program", environment, ensure_data=True)
    original = first.paths.settings_file.read_bytes()
    second = create_application(tmp_path / "program", environment, ensure_data=True)

    assert first.paths.settings_file.exists()
    assert second.settings == first.settings
    assert second.paths.settings_file.read_bytes() == original
    assert {path.name for path in data_root.iterdir()} >= {
        "market", "state", "research", "runs", "reports", "logs", "settings.json"
    }


def test_application_context_is_immutable(tmp_path: Path) -> None:
    context = create_application(
        tmp_path / "program",
        {"ASTOCK_QUANT_DATA_DIR": str(tmp_path / "data")},
        ensure_data=False,
    )

    with pytest.raises(FrozenInstanceError):
        context.settings = None
