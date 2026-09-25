"""Single composition root for AStockQuant application services."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from astock_quant.app.context import ApplicationContext
from astock_quant.app.paths import AppPaths
from astock_quant.app.settings import Settings
from astock_quant.data.migration import MigrationService
from astock_quant.reports.run_store import RunStore


def create_application(
    program_dir: Path,
    env: Mapping[str, str],
    ensure_data: bool = False,
) -> ApplicationContext:
    """Construct services, writing defaults only when explicitly requested."""

    paths = AppPaths.resolve(program_dir, env)
    if ensure_data:
        paths.ensure_data_tree()

    if paths.settings_file.is_file():
        settings = Settings.load(paths.settings_file)
    else:
        settings = Settings()
        if ensure_data:
            settings.save(paths.settings_file)

    return ApplicationContext(
        paths=paths,
        settings=settings,
        migration=MigrationService(paths),
        run_store=RunStore(paths.runs),
    )
