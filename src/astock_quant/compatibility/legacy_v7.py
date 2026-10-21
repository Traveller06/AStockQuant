"""Read-only inventory of approved AStockQuant v7 data artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from astock_quant.core.errors import MigrationError


LEGACY_ARTIFACTS = (
    "cache",
    "tail_strategy_cache",
    "research_sample.json",
    "validation_snapshot_v1.json.gz",
    "research_data_checkpoint.json",
    "watchlist.json",
    "paper_account.json",
    "tail_strategy_state.json",
)


def _migration_error(path: Path, detail: str) -> MigrationError:
    return MigrationError(
        stage="legacy_inventory",
        scope=str(path),
        source="legacy_v7",
        detail=detail,
    )


def _files_in(path: Path) -> tuple[Path, ...]:
    if path.is_symlink():
        raise _migration_error(path, f"symlink is not allowed: {path}")
    if path.is_file():
        return (path,)
    if not path.is_dir():
        raise _migration_error(path, f"unsupported legacy artifact: {path}")

    files: list[Path] = []

    def visit(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            if child.is_symlink():
                raise _migration_error(child, f"symlink is not allowed: {child}")
            if child.is_dir():
                visit(child)
            elif child.is_file():
                files.append(child)
            else:
                raise _migration_error(child, f"unsupported legacy entry: {child}")

    visit(path)
    return tuple(files)


def sha256_path(path: Path) -> str:
    """Hash a file or directory deterministically without modifying it."""

    path = Path(path)
    files = _files_in(path)
    digest = sha256()
    if path.is_file():
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    for file_path in files:
        relative = file_path.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(file_path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        with file_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class LegacyArtifact:
    relative_path: str
    kind: str
    byte_size: int
    file_count: int
    modified_time_ns: int
    sha256: str


def _describe(root: Path, relative_path: str) -> LegacyArtifact:
    path = root / relative_path
    files = _files_in(path)
    return LegacyArtifact(
        relative_path=relative_path,
        kind="file" if path.is_file() else "directory",
        byte_size=sum(file_path.stat().st_size for file_path in files),
        file_count=len(files),
        modified_time_ns=path.stat().st_mtime_ns,
        sha256=sha256_path(path),
    )


def _aggregate_sha256(artifacts: tuple[LegacyArtifact, ...]) -> str:
    digest = sha256()
    for artifact in artifacts:
        for value in (
            artifact.relative_path,
            artifact.kind,
            str(artifact.byte_size),
            str(artifact.file_count),
            str(artifact.modified_time_ns),
            artifact.sha256,
        ):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class LegacyInventory:
    legacy_root: Path
    artifacts: tuple[LegacyArtifact, ...]
    aggregate_sha256: str

    def recalculate_sha256(self) -> str:
        refreshed = tuple(
            _describe(self.legacy_root, artifact.relative_path)
            for artifact in self.artifacts
        )
        return _aggregate_sha256(refreshed)


def discover_legacy(root: Path) -> LegacyInventory:
    """Inventory existing allowlisted artifacts under a legacy v7 root."""

    legacy_root = Path(root)
    if legacy_root.is_symlink():
        raise _migration_error(legacy_root, "legacy root symlink is not allowed")
    if not legacy_root.is_dir():
        raise _migration_error(legacy_root, "legacy root must be an existing directory")

    artifacts: list[LegacyArtifact] = []
    for relative_path in LEGACY_ARTIFACTS:
        candidate = legacy_root / relative_path
        if candidate.is_symlink():
            raise _migration_error(candidate, f"symlink is not allowed: {candidate}")
        if candidate.exists():
            artifacts.append(_describe(legacy_root, relative_path))

    frozen_artifacts = tuple(artifacts)
    return LegacyInventory(
        legacy_root=legacy_root,
        artifacts=frozen_artifacts,
        aggregate_sha256=_aggregate_sha256(frozen_artifacts),
    )
