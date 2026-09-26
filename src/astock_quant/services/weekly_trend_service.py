"""Run weekly-trend backtests and persist an auditable atomic result set."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Callable, Mapping
from uuid import uuid4

from astock_quant.backtest.engine import BacktestEngine, BacktestRequest, BacktestResult, ReconciliationError
from astock_quant.core.enums import RunStatus
from astock_quant.core.models import Bar, RunManifest
from astock_quant.reports.run_store import RunStore
from astock_quant.strategies.weekly_trend.strategy import WeeklyTrendConfirmationStrategy


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _hash_payload(value: object) -> str:
    encoded = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


class WeeklyTrendService:
    REQUIRED_AUDIT_FILES = frozenset({
        "manifest.json", "parameters.json", "signals.json", "orders.json",
        "trades.json", "decisions.json", "checks.json", "events.json",
        "errors.json", "equity.csv",
    })
    def __init__(
        self,
        run_store: RunStore,
        *,
        strategy: object | None = None,
        result_validator: Callable[[BacktestResult], bool] | None = None,
    ) -> None:
        self.run_store = run_store
        self.strategy = strategy or WeeklyTrendConfirmationStrategy()
        self.result_validator = result_validator or (lambda result: result.reconciles_to_cent())

    def run_backtest(self, request: BacktestRequest) -> BacktestResult:
        run_id = request.run_id or str(uuid4())
        effective = replace(request, run_id=run_id)
        config = self.strategy.config
        parameters = config.to_manifest_parameters()
        parameters.update(
            {
                "initial_cash": str(request.initial_cash),
                "commission_rate": str(request.fees.commission_rate),
                "minimum_commission": str(request.fees.minimum_commission),
                "stamp_tax_rate": str(request.fees.stamp_tax_rate),
                "slippage_rate": str(request.fees.slippage_rate),
                "adjustment_basis": request.adjustment_basis,
                "max_position_fraction": str(request.max_position_fraction),
            }
        )
        manifest = RunManifest(
            run_id=run_id,
            app_version=request.app_version,
            strategy_id=self.strategy.strategy_id,
            strategy_version=self.strategy.strategy_version,
            parameters=parameters,
            sample_sha256=_hash_payload(sorted(request.daily_bars)),
            data_cutoff=request.data_as_of.isoformat(),
            data_sha256=_hash_payload(request.daily_bars),
            status=RunStatus.NOT_STARTED,
            started_at=datetime.now().astimezone(),
        )
        self.run_store.start(manifest)
        try:
            result = BacktestEngine(self.strategy).run(effective)
            if not self.result_validator(result):
                raise ReconciliationError("cash, holdings, fees, and equity do not reconcile")
            self._persist(result, parameters)
            self.run_store.complete(run_id, required_files=set(self.REQUIRED_AUDIT_FILES))
            return result
        except Exception:
            self.run_store.finish(run_id, RunStatus.FAILED)
            raise

    def _persist(self, result: BacktestResult, parameters: Mapping[str, object]) -> None:
        run_id = result.run_id
        self.run_store.write_json(run_id, "parameters.json", _json_value(parameters))
        self.run_store.write_json(run_id, "signals.json", _json_value(result.signals))
        self.run_store.write_json(run_id, "orders.json", _json_value(result.orders))
        self.run_store.write_json(run_id, "trades.json", _json_value(result.trades))
        self.run_store.write_json(run_id, "decisions.json", _json_value(result.decisions))
        self.run_store.write_json(run_id, "checks.json", _json_value(result.checks))
        self.run_store.write_json(run_id, "events.json", _json_value(result.events))
        self.run_store.write_json(run_id, "errors.json", _json_value(result.errors))
        self.run_store.write_table(
            run_id,
            "equity.csv",
            (
                {
                    "session": point.session.isoformat(),
                    "cash": str(point.cash),
                    "equity": str(point.equity),
                    "realized_pnl": str(point.realized_pnl),
                    "unrealized_pnl": str(point.unrealized_pnl),
                    "total_fees": str(point.total_fees),
                    "position_count": point.position_count,
                }
                for point in result.snapshots
            ),
        )
