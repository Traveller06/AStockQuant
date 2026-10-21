from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from astock_quant.core.enums import RunStatus
from astock_quant.core.errors import DataCorruptionError, DataIncompleteError
from astock_quant.core.models import RunManifest
from astock_quant.reports.run_store import RunStore


def _manifest(run_id: str, status: RunStatus = RunStatus.RUNNING, minutes: int = 0) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        app_version="8.0.0",
        strategy_id="weekly",
        strategy_version="1.0.0",
        parameters={"initial_cash": 100000},
        sample_sha256="sample",
        data_cutoff="2026-09-25",
        data_sha256="data",
        status=status,
        started_at=datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes),
    )


def test_only_finished_run_can_be_opened_as_completed(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.start(_manifest("run-001"))

    with pytest.raises(DataIncompleteError, match="completion marker"):
        store.open_completed("run-001")

    store.write_json("run-001", "parameters.json", {"initial": 100000})
    store.finish("run-001", RunStatus.COMPLETED)
    reopened = store.open_completed("run-001")

    assert reopened.manifest.status is RunStatus.COMPLETED
    assert reopened.path.joinpath("_COMPLETE").exists()
    assert not reopened.path.joinpath("parameters.json.tmp").exists()


def test_incomplete_has_marker_but_failed_run_does_not(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.start(_manifest("incomplete"))
    store.finish("incomplete", RunStatus.INCOMPLETE)
    assert store.open_completed("incomplete").manifest.status is RunStatus.INCOMPLETE

    store.start(_manifest("failed"))
    store.finish("failed", RunStatus.FAILED)
    assert not (tmp_path / "failed" / "_COMPLETE").exists()
    with pytest.raises(DataIncompleteError, match="completion marker"):
        store.open_completed("failed")


def test_duplicate_active_run_id_is_rejected(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.start(_manifest("run-001"))

    with pytest.raises(DataCorruptionError, match="already exists"):
        store.start(_manifest("run-001"))


@pytest.mark.parametrize("name", ["../secret.json", "/tmp/secret.json", "nested/file.json", "nested\\file.json"])
def test_output_name_cannot_escape_run_directory(tmp_path: Path, name: str) -> None:
    store = RunStore(tmp_path)
    store.start(_manifest("run-001"))

    with pytest.raises(ValueError, match="output name"):
        store.write_json("run-001", name, {"safe": True})


def test_json_redacts_sensitive_keys_recursively(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.start(_manifest("run-001"))

    store.write_json(
        "run-001",
        "audit.json",
        {
            "password": "one",
            "nested": {"account_password": "two", "token": "three", "safe": "keep"},
            "items": [{"secret": "four"}],
        },
    )
    payload = json.loads((tmp_path / "run-001" / "audit.json").read_text(encoding="utf-8"))

    assert payload == {
        "password": "<redacted>",
        "nested": {"account_password": "<redacted>", "token": "<redacted>", "safe": "keep"},
        "items": [{"secret": "<redacted>"}],
    }


def test_write_table_is_atomic_and_recent_runs_are_newest_first(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.start(_manifest("older", minutes=0))
    store.write_table("older", "trades.csv", ({"code": "600000", "pnl": 1.25},))
    store.finish("older", RunStatus.COMPLETED)
    store.start(_manifest("newer", minutes=5))
    store.finish("newer", RunStatus.COMPLETED)

    assert (tmp_path / "older" / "trades.csv").read_text(encoding="utf-8") == "code,pnl\n600000,1.25\n"
    assert not (tmp_path / "older" / "trades.csv.tmp").exists()
    assert [run.manifest.run_id for run in store.list_recent()] == ["newer", "older"]
