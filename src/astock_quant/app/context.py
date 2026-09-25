"""Immutable application service graph for AStockQuant v8."""

from dataclasses import dataclass

from astock_quant.app.paths import AppPaths
from astock_quant.app.settings import Settings
from astock_quant.data.migration import MigrationService
from astock_quant.reports.run_store import RunStore


@dataclass(frozen=True)
class ApplicationContext:
    paths: AppPaths
    settings: Settings
    migration: MigrationService
    run_store: RunStore
