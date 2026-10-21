"""Application paths split between the program and a user's data directory."""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from astock_quant.core.errors import ConfigurationError


@dataclass(frozen=True)
class AppPaths:
    """Resolved locations used by the application.

    Resolution is side-effect free. Call :meth:`ensure_data_tree` before a
    component needs to persist personal data.
    """

    program_root: Path
    data_root: Path
    market: Path
    state: Path
    research: Path
    runs: Path
    reports: Path
    logs: Path
    settings_file: Path
    manifest_file: Path

    @classmethod
    def resolve(
        cls, program_dir: Path, env: Mapping[str, str]
    ) -> "AppPaths":
        """Build paths from an explicit data override or Windows local data."""
        program_root = Path(program_dir)
        data_override = env.get("ASTOCK_QUANT_DATA_DIR")
        if data_override:
            data_root = Path(data_override)
        else:
            local_app_data = env.get("LOCALAPPDATA")
            if not local_app_data:
                raise ConfigurationError(
                    stage="path resolution",
                    scope="personal data directory",
                    source="LOCALAPPDATA",
                    detail="LOCALAPPDATA is required when ASTOCK_QUANT_DATA_DIR is not set",
                )
            data_root = Path(local_app_data) / "AStockQuant"

        return cls(
            program_root=program_root,
            data_root=data_root,
            market=data_root / "market",
            state=data_root / "state",
            research=data_root / "research",
            runs=data_root / "runs",
            reports=data_root / "reports",
            logs=data_root / "logs",
            settings_file=data_root / "settings.json",
            manifest_file=data_root / "data_manifest.json",
        )

    def ensure_data_tree(self) -> None:
        """Create the personal-data directory tree without touching the program."""
        for directory in (
            self.data_root,
            self.market,
            self.state,
            self.research,
            self.runs,
            self.reports,
            self.logs,
        ):
            directory.mkdir(parents=True, exist_ok=True)
