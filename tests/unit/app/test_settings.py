from pathlib import Path

import pytest

import astock_quant.app.settings as settings_module
from astock_quant.app.settings import Settings
from astock_quant.core.errors import ConfigurationError


def test_settings_round_trip_is_atomic(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    settings = Settings(
        schema_version=1,
        active_data_provider="eastmoney",
        real_trading_enabled=False,
    )

    settings.save(target)

    assert Settings.load(target) == settings
    assert not target.with_suffix(".json.tmp").exists()


def test_save_keeps_old_file_until_atomic_replace(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "settings.json"
    target.write_text("old settings", encoding="utf-8")
    temporary = target.with_suffix(".json.tmp")
    replacement: tuple[Path, Path] | None = None

    def record_replace(source: Path, destination: Path) -> None:
        nonlocal replacement
        replacement = (source, destination)

    monkeypatch.setattr(settings_module.os, "replace", record_replace)

    Settings().save(target)

    assert target.read_text(encoding="utf-8") == "old settings"
    assert temporary.exists()
    assert Settings.load(temporary) == Settings()
    assert replacement == (temporary, target)


def test_settings_cannot_enable_real_trading_in_v8(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text(
        '{"schema_version":1,"active_data_provider":"eastmoney","real_trading_enabled":true}',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="real trading is disabled"):
        Settings.load(target)


def test_settings_rejects_unknown_schema_version(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text(
        '{"schema_version":2,"active_data_provider":"eastmoney","real_trading_enabled":false}',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="unsupported settings schema version"):
        Settings.load(target)


def test_settings_rejects_non_utf8_file_as_configuration_error(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_bytes(b"\xff")

    with pytest.raises(ConfigurationError, match="invalid settings file"):
        Settings.load(target)


def test_settings_rejects_boolean_schema_version_on_construction() -> None:
    with pytest.raises(ConfigurationError, match="unsupported settings schema version"):
        Settings(schema_version=True)
