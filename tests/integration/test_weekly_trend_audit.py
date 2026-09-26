import json

import pytest

from astock_quant.backtest.engine import ReconciliationError
from astock_quant.core.enums import RunStatus
from astock_quant.core.errors import DataIncompleteError
from astock_quant.core.models import RunManifest
from astock_quant.reports.run_store import RunStore
from astock_quant.services.weekly_trend_service import WeeklyTrendService

from .test_weekly_trend_backtest import ScriptedStrategy, make_request


EXPECTED_ARTIFACTS = {
    "_COMPLETE",
    "checks.json",
    "decisions.json",
    "equity.csv",
    "errors.json",
    "events.json",
    "manifest.json",
    "orders.json",
    "parameters.json",
    "signals.json",
    "trades.json",
}


def test_completed_run_persists_required_artifacts_and_correlations(tmp_path) -> None:
    store = RunStore(tmp_path / "runs")
    result = WeeklyTrendService(store, strategy=ScriptedStrategy()).run_backtest(make_request())
    completed = store.open_completed(result.run_id)

    assert {path.name for path in completed.path.iterdir()} == EXPECTED_ARTIFACTS
    assert completed.manifest.strategy_id == "weekly_trend_confirmation"
    assert completed.manifest.parameters["parameter_version"] == "weekly-trend-v1"
    assert completed.manifest.data_cutoff
    assert completed.manifest.sample_sha256 and completed.manifest.data_sha256
    signals = json.loads((completed.path / "signals.json").read_text(encoding="utf-8"))
    orders = json.loads((completed.path / "orders.json").read_text(encoding="utf-8"))
    trades = json.loads((completed.path / "trades.json").read_text(encoding="utf-8"))
    signal_ids = {signal["signal_id"] for signal in signals}
    assert {order["signal_id"] for order in orders} <= signal_ids
    assert {trade["signal_id"] for trade in trades} <= signal_ids


def test_reconciliation_failure_never_creates_complete_marker(tmp_path) -> None:
    store = RunStore(tmp_path / "runs")
    service = WeeklyTrendService(
        store,
        strategy=ScriptedStrategy(),
        result_validator=lambda result: False,
    )

    with pytest.raises(ReconciliationError):
        service.run_backtest(make_request())

    assert not any(store.runs_root.rglob("_COMPLETE"))
    assert store.list_recent()[0].manifest.status.value == "failed"


def test_corrupt_completed_run_is_not_silently_opened(tmp_path) -> None:
    store = RunStore(tmp_path / "runs")
    result = WeeklyTrendService(store, strategy=ScriptedStrategy()).run_backtest(make_request())
    (store.runs_root / result.run_id / "manifest.json").write_text("{bad", encoding="utf-8")

    with pytest.raises(Exception, match="manifest"):
        store.open_completed(result.run_id)


def test_complete_refuses_missing_audit_artifacts(tmp_path) -> None:
    store = RunStore(tmp_path / "runs")
    request = make_request()
    manifest = RunManifest(
        run_id="missing-audit",
        app_version="8.0.0",
        strategy_id="weekly_trend_confirmation",
        strategy_version="1.0.0",
        parameters={},
        sample_sha256="sample",
        data_cutoff=request.data_as_of.isoformat(),
        data_sha256="data",
        status=RunStatus.NOT_STARTED,
        started_at=request.daily_bars["600000"][0].timestamp,
    )
    store.start(manifest)
    store.write_json("missing-audit", "parameters.json", {})

    with pytest.raises(DataIncompleteError, match="required audit artifact"):
        store.complete("missing-audit", required_files={"parameters.json", "trades.json"})

    assert not (store.runs_root / "missing-audit" / "_COMPLETE").exists()
