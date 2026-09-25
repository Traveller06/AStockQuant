from pathlib import Path

import pytest

from astock_quant.compatibility.legacy_v7 import discover_legacy
from astock_quant.core.errors import MigrationError


def _snapshot_files(root: Path) -> tuple[tuple[str, bytes, int], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    )


def test_inventory_finds_only_approved_legacy_artifacts(tmp_path: Path) -> None:
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "600000.csv").write_text(
        "date,close\n2026-09-11,10\n", encoding="utf-8"
    )
    (tmp_path / "research_sample.json").write_text('{"stocks":[]}', encoding="utf-8")
    (tmp_path / "unknown.txt").write_text("ignore", encoding="utf-8")

    inventory = discover_legacy(tmp_path)

    assert [item.relative_path for item in inventory.artifacts] == [
        "cache",
        "research_sample.json",
    ]
    assert inventory.legacy_root == tmp_path
    assert inventory.aggregate_sha256 == inventory.recalculate_sha256()


def test_inventory_is_repeatable_and_does_not_mutate_legacy_files(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "600000.csv").write_bytes(b"date,close\n2026-09-11,10\n")
    (tmp_path / "watchlist.json").write_text('["600000"]', encoding="utf-8")
    before = _snapshot_files(tmp_path)

    first = discover_legacy(tmp_path)
    second = discover_legacy(tmp_path)

    assert first == second
    assert _snapshot_files(tmp_path) == before
    assert first.aggregate_sha256 == second.aggregate_sha256


def test_inventory_rejects_symlink_inside_approved_directory(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    target = tmp_path / "outside.csv"
    target.write_text("private", encoding="utf-8")
    link = cache / "linked.csv"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(MigrationError, match="symlink"):
        discover_legacy(tmp_path)
