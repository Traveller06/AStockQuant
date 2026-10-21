from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from astock_quant.app.paths import AppPaths
from astock_quant.data.migration import MigrationService


def _paths(root: Path) -> AppPaths:
    return AppPaths.resolve(root / "program", {"ASTOCK_QUANT_DATA_DIR": str(root / "personal" / "AStockQuant")})


def _legacy(root: Path) -> Path:
    root.mkdir()
    cache = root / "cache"
    cache.mkdir()
    (cache / "600000.csv").write_bytes(b"date,close\n2026-09-11,10\n")
    (root / "research_sample.json").write_text('{"stocks":["600000"]}', encoding="utf-8")
    (root / "watchlist.json").write_text('["600000"]', encoding="utf-8")
    return root


def _snapshot(root: Path) -> tuple[tuple[str, bytes, int], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def test_migration_copies_verifies_keeps_legacy_and_is_idempotent(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "legacy")
    paths = _paths(tmp_path / "new")
    before = _snapshot(legacy)
    service = MigrationService(paths)
    plan = service.plan(legacy)

    result = service.execute(plan)

    assert result.status == "completed"
    assert (paths.market / "legacy_daily" / "600000.csv").read_bytes() == (
        legacy / "cache" / "600000.csv"
    ).read_bytes()
    assert (paths.research / "research_sample.json").exists()
    assert _snapshot(legacy) == before
    assert service.execute(service.plan(legacy)).status == "already_migrated"


def test_interrupted_copy_can_be_rolled_back_without_touching_legacy(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "legacy")
    paths = _paths(tmp_path / "new")
    before = _snapshot(legacy)
    calls = 0

    def fail_after_first(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("simulated interruption")
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    service = MigrationService(paths, copier=fail_after_first)
    plan = service.plan(legacy)

    with pytest.raises(OSError, match="simulated interruption"):
        service.execute(plan)
    assert not paths.data_root.exists()
    assert plan.staging_root.exists()

    service.rollback(plan.staging_root)

    assert not plan.staging_root.exists()
    assert _snapshot(legacy) == before


def test_cli_defaults_to_dry_run_and_does_not_create_personal_data(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path / "legacy")
    data_root = tmp_path / "personal" / "AStockQuant"
    environment = dict(os.environ, ASTOCK_QUANT_DATA_DIR=str(data_root))

    completed = subprocess.run(
        [sys.executable, "scripts/migrate_v7.py", str(legacy)],
        cwd=Path(__file__).parents[2],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"migration_id"' in completed.stdout
    assert not data_root.exists()
