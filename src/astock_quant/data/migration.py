"""Copy, verify, and atomically promote approved v7 data artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil

from astock_quant.app.paths import AppPaths
from astock_quant.compatibility.legacy_v7 import (
    LegacyArtifact,
    LegacyInventory,
    discover_legacy,
    sha256_path,
)
from astock_quant.core.errors import MigrationError


MIGRATION_SCHEMA_VERSION = 1
DESTINATIONS = {
    "cache": Path("market/legacy_daily"),
    "tail_strategy_cache": Path("market/tail_strategy_cache"),
    "research_sample.json": Path("research/research_sample.json"),
    "validation_snapshot_v1.json.gz": Path("research/validation_snapshot_v1.json.gz"),
    "research_data_checkpoint.json": Path("state/research_data_checkpoint.json"),
    "watchlist.json": Path("state/watchlist.json"),
    "paper_account.json": Path("state/paper_account.json"),
    "tail_strategy_state.json": Path("state/tail_strategy_state.json"),
}

Copier = Callable[[Path, Path], None]


def _error(*, scope: Path | str, detail: str) -> MigrationError:
    return MigrationError(
        stage="legacy_migration",
        scope=str(scope),
        source="legacy_v7",
        detail=detail,
    )


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


@dataclass(frozen=True)
class MigrationPlan:
    migration_id: str
    schema_version: int
    legacy_root: Path
    legacy_aggregate_sha256: str
    artifacts: tuple[LegacyArtifact, ...]
    staging_root: Path
    data_root: Path

    def as_dict(self) -> dict[str, object]:
        return {
            "migration_id": self.migration_id,
            "schema_version": self.schema_version,
            "legacy_root": str(self.legacy_root),
            "legacy_aggregate_sha256": self.legacy_aggregate_sha256,
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
            "staging_root": str(self.staging_root),
            "data_root": str(self.data_root),
        }

    def to_json(self) -> str:
        return _json(self.as_dict())


@dataclass(frozen=True)
class MigrationResult:
    migration_id: str
    status: str
    data_root: Path
    manifest_path: Path

    def to_json(self) -> str:
        return _json(
            {
                "migration_id": self.migration_id,
                "status": self.status,
                "data_root": str(self.data_root),
                "manifest_path": str(self.manifest_path),
            }
        )


def _copy_artifact(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, copy_function=shutil.copy2)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


class MigrationService:
    def __init__(self, paths: AppPaths, copier: Copier | None = None) -> None:
        self.paths = paths
        self._copier = copier or _copy_artifact

    def plan(self, legacy: Path | LegacyInventory) -> MigrationPlan:
        inventory = legacy if isinstance(legacy, LegacyInventory) else discover_legacy(legacy)
        identity = f"{MIGRATION_SCHEMA_VERSION}\0{inventory.aggregate_sha256}".encode("ascii")
        migration_id = sha256(identity).hexdigest()[:20]
        staging_root = self.paths.data_root.parent / f".AStockQuant-migration-{migration_id}"
        return MigrationPlan(
            migration_id=migration_id,
            schema_version=MIGRATION_SCHEMA_VERSION,
            legacy_root=inventory.legacy_root,
            legacy_aggregate_sha256=inventory.aggregate_sha256,
            artifacts=inventory.artifacts,
            staging_root=staging_root,
            data_root=self.paths.data_root,
        )

    def execute(self, plan: MigrationPlan) -> MigrationResult:
        self._validate_plan(plan)
        manifest_path = plan.data_root / "migration_manifest.json"
        if plan.data_root.exists():
            if self._is_completed_manifest(manifest_path, plan):
                return MigrationResult(
                    migration_id=plan.migration_id,
                    status="already_migrated",
                    data_root=plan.data_root,
                    manifest_path=manifest_path,
                )
            raise _error(
                scope=plan.data_root,
                detail="data root exists without matching migration manifest; refusing overwrite",
            )
        if plan.staging_root.exists():
            raise _error(
                scope=plan.staging_root,
                detail="staging directory already exists; call rollback before retrying",
            )

        plan.staging_root.parent.mkdir(parents=True, exist_ok=True)
        plan.staging_root.mkdir()
        for artifact in plan.artifacts:
            source = plan.legacy_root / artifact.relative_path
            destination = plan.staging_root / DESTINATIONS[artifact.relative_path]
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._copier(source, destination)
            copied_sha256 = sha256_path(destination)
            if copied_sha256 != artifact.sha256:
                raise _error(
                    scope=destination,
                    detail=f"verification failed for {artifact.relative_path}",
                )

        staged_manifest = plan.staging_root / "migration_manifest.json"
        self._write_manifest(staged_manifest, plan)
        os.replace(plan.staging_root, plan.data_root)
        return MigrationResult(
            migration_id=plan.migration_id,
            status="completed",
            data_root=plan.data_root,
            manifest_path=manifest_path,
        )

    def rollback(self, staging_root: Path) -> None:
        candidate = Path(staging_root)
        expected_parent = self.paths.data_root.parent.resolve()
        if (
            candidate.parent.resolve() != expected_parent
            or not candidate.name.startswith(".AStockQuant-migration-")
            or candidate.resolve() == self.paths.data_root.resolve()
        ):
            raise _error(scope=candidate, detail="refusing rollback outside exact migration staging parent")
        if candidate.exists():
            if not candidate.is_dir() or candidate.is_symlink():
                raise _error(scope=candidate, detail="staging target must be a real directory")
            shutil.rmtree(candidate)

    def _validate_plan(self, plan: MigrationPlan) -> None:
        if plan.schema_version != MIGRATION_SCHEMA_VERSION:
            raise _error(scope=plan.migration_id, detail="unsupported migration schema version")
        if plan.data_root != self.paths.data_root:
            raise _error(scope=plan.data_root, detail="migration plan targets a different data root")
        expected_staging = self.paths.data_root.parent / f".AStockQuant-migration-{plan.migration_id}"
        if plan.staging_root != expected_staging:
            raise _error(scope=plan.staging_root, detail="migration plan targets an invalid staging directory")
        current = discover_legacy(plan.legacy_root)
        if current.aggregate_sha256 != plan.legacy_aggregate_sha256:
            raise _error(scope=plan.legacy_root, detail="legacy data changed after migration planning")
        if tuple(current.artifacts) != tuple(plan.artifacts):
            raise _error(scope=plan.legacy_root, detail="legacy inventory changed after migration planning")

    @staticmethod
    def _write_manifest(path: Path, plan: MigrationPlan) -> None:
        payload = {
            "migration_id": plan.migration_id,
            "schema_version": plan.schema_version,
            "legacy_root": str(plan.legacy_root),
            "legacy_aggregate_sha256": plan.legacy_aggregate_sha256,
            "status": "completed",
            "artifacts": [asdict(artifact) for artifact in plan.artifacts],
        }
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as target:
            target.write(_json(payload))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)

    @staticmethod
    def _is_completed_manifest(path: Path, plan: MigrationPlan) -> bool:
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return (
            payload.get("migration_id") == plan.migration_id
            and payload.get("schema_version") == plan.schema_version
            and payload.get("legacy_aggregate_sha256") == plan.legacy_aggregate_sha256
            and payload.get("status") == "completed"
        )
