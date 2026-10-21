from dataclasses import replace
from datetime import date, datetime, timedelta
import os
from zoneinfo import ZoneInfo

import pytest

from astock_quant.core.errors import ConfigurationError, DataCorruptionError
from astock_quant.strategies.weekly_trend.models import PatternState, PatternStatus, SetupHit, SetupKind
from astock_quant.strategies.weekly_trend.state_store import WeeklyTrendStateStore


SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 25, 15, 0, tzinfo=SHANGHAI)


def _state() -> PatternState:
    setup = SetupHit(SetupKind.BREAKOUT, NOW - timedelta(days=7), 12.5, "前高", ())
    return PatternState(
        code="600000",
        status=PatternStatus.WAITING_CONFIRMATION,
        setup=setup,
        created_at=setup.occurred_at,
        expires_on=date(2026, 10, 23),
        emitted_signal_id=None,
        strategy_version="1.0.0",
        parameter_version="weekly-trend-v1",
        data_cutoff=NOW,
    )


def test_store_round_trips_all_state_fields(tmp_path) -> None:
    store = WeeklyTrendStateStore(tmp_path / "weekly-state.json")
    state = _state()

    store.save(state)

    assert store.load("1.0.0", NOW, expected_parameter_version="weekly-trend-v1") == state


def test_store_rejects_corrupt_incompatible_and_time_regressing_state(tmp_path) -> None:
    store = WeeklyTrendStateStore(tmp_path / "weekly-state.json")
    store.path.write_text("{", encoding="utf-8")
    with pytest.raises(DataCorruptionError):
        store.load("1.0.0", NOW)

    store.save(replace(_state(), strategy_version="0.9.0"))
    with pytest.raises(ConfigurationError, match="strategy version"):
        store.load("1.0.0", NOW)

    store.save(_state())
    with pytest.raises(DataCorruptionError, match="cutoff"):
        store.load("1.0.0", NOW + timedelta(days=1))

    with pytest.raises(ConfigurationError, match="parameter version"):
        store.load("1.0.0", NOW, expected_parameter_version="other")


def test_missing_state_file_returns_none(tmp_path) -> None:
    store = WeeklyTrendStateStore(tmp_path / "missing.json")
    assert store.load("1.0.0", NOW) is None


def test_failed_atomic_replace_preserves_prior_valid_file(tmp_path) -> None:
    path = tmp_path / "weekly-state.json"
    stable_store = WeeklyTrendStateStore(path)
    stable_store.save(_state())
    before = path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    failing_store = WeeklyTrendStateStore(path, replace_func=fail_replace)
    with pytest.raises(OSError, match="simulated"):
        failing_store.save(replace(_state(), data_cutoff=NOW + timedelta(days=1)))

    assert path.read_bytes() == before
    assert not (tmp_path / "weekly-state.json.tmp").exists()
