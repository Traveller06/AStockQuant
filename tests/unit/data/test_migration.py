from dataclasses import replace
from pathlib import Path

import pytest

from astock_quant.app.paths import AppPaths
from astock_quant.core.errors import MigrationError
from astock_quant.data.migration import DESTINATIONS, MigrationService


def _paths(root: Path) -> AppPaths:
    return AppPaths.resolve(root / "program", {"ASTOCK_QUANT_DATA_DIR": str(root / "data")})


def _legacy(root: Path) -> Path:
    root.mkdir()
    (root / "research_sample.json").write_text('{"stocks":[]}', encoding="utf-8")
    (root / "watchlist.json").write_text('["600000"]', encoding="utf-8")
    return root


def test_plan_is_deterministic_and_uses_the_approved_destination_mapping(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "legacy")
    service = MigrationService(_paths(tmp_path / "new"))

    first = service.plan(legacy)
    second = service.plan(legacy)

    assert first == second
    assert first.migration_id
    assert first.schema_version == 1
    assert DESTINATIONS["research_sample.json"] == Path("research/research_sample.json")
    assert DESTINATIONS["watchlist.json"] == Path("state/watchlist.json")


def test_existing_unrelated_data_root_is_never_overwritten(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "legacy")
    paths = _paths(tmp_path / "new")
    paths.data_root.mkdir(parents=True)
    marker = paths.data_root / "belongs-to-user.txt"
    marker.write_text("keep", encoding="utf-8")
    service = MigrationService(paths)

    with pytest.raises(MigrationError, match="without matching migration manifest"):
        service.execute(service.plan(legacy))

    assert marker.read_text(encoding="utf-8") == "keep"


def test_rollback_refuses_paths_outside_the_exact_staging_parent(tmp_path: Path) -> None:
    service = MigrationService(_paths(tmp_path / "new"))

    with pytest.raises(MigrationError, match="staging"):
        service.rollback(tmp_path / "not-a-staging-directory")


def test_execute_rejects_a_forged_staging_path(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "legacy")
    service = MigrationService(_paths(tmp_path / "new"))
    forged = replace(service.plan(legacy), staging_root=tmp_path / "forged")

    with pytest.raises(MigrationError, match="staging"):
        service.execute(forged)

    assert not forged.staging_root.exists()
