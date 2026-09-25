"""Atomic, redacted storage for reproducible strategy runs."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import io
import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from astock_quant.core.enums import RunStatus
from astock_quant.core.errors import DataCorruptionError, DataIncompleteError
from astock_quant.core.models import JSONValue, RunManifest


SENSITIVE_KEYS = frozenset({"password", "account_password", "token", "secret"})
COMPLETABLE_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.INCOMPLETE})
TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.INCOMPLETE, RunStatus.FAILED})


def _corruption(scope: str | Path, detail: str) -> DataCorruptionError:
    return DataCorruptionError(stage="run_store", scope=str(scope), source="runs", detail=detail)


def _incomplete(scope: str | Path, detail: str) -> DataIncompleteError:
    return DataIncompleteError(stage="run_store", scope=str(scope), source="runs", detail=detail)


def _redact(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if str(key).lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _manifest_dict(manifest: RunManifest) -> dict[str, object]:
    payload = asdict(manifest)
    payload["status"] = manifest.status.value
    payload["started_at"] = manifest.started_at.isoformat()
    payload["finished_at"] = manifest.finished_at.isoformat() if manifest.finished_at else None
    return _redact(payload)  # type: ignore[return-value]


def _manifest_from_dict(payload: Mapping[str, object]) -> RunManifest:
    try:
        return RunManifest(
            run_id=str(payload["run_id"]),
            app_version=str(payload["app_version"]),
            strategy_id=str(payload["strategy_id"]),
            strategy_version=str(payload["strategy_version"]),
            parameters=payload["parameters"],  # type: ignore[arg-type]
            sample_sha256=str(payload["sample_sha256"]),
            data_cutoff=str(payload["data_cutoff"]),
            data_sha256=str(payload["data_sha256"]),
            status=RunStatus(str(payload["status"])),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            finished_at=(
                datetime.fromisoformat(str(payload["finished_at"]))
                if payload.get("finished_at") is not None
                else None
            ),
            errors=tuple(payload.get("errors", ())),  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _corruption("manifest.json", f"invalid run manifest: {exc}") from exc


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class StoredRun:
    manifest: RunManifest
    path: Path


class RunStore:
    def __init__(self, runs_root: Path) -> None:
        self.runs_root = Path(runs_root)

    def start(self, manifest: RunManifest) -> StoredRun:
        run_path = self._run_path(manifest.run_id)
        if run_path.exists() or run_path.is_symlink():
            raise _corruption(manifest.run_id, "run directory already exists")
        run_path.mkdir(parents=True)
        running = replace(manifest, status=RunStatus.RUNNING, finished_at=None)
        self._write_manifest(run_path, running)
        return StoredRun(running, run_path)

    def write_json(self, run_id: str, name: str, value: JSONValue | object) -> Path:
        run_path = self._existing_run_path(run_id)
        output = run_path / self._validate_output_name(name)
        content = json.dumps(_redact(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        _atomic_text(output, content)
        return output

    def write_table(
        self,
        run_id: str,
        name: str,
        rows: Iterable[Mapping[str, object]],
    ) -> Path:
        run_path = self._existing_run_path(run_id)
        output = run_path / self._validate_output_name(name)
        materialized = tuple(rows)
        stream = io.StringIO(newline="")
        if materialized:
            fieldnames = list(materialized[0].keys())
            if any(list(row.keys()) != fieldnames for row in materialized):
                raise ValueError("all table rows must have the same ordered fields")
            writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(materialized)
        _atomic_text(output, stream.getvalue())
        return output

    def finish(self, run_id: str, status: RunStatus) -> StoredRun:
        if status not in TERMINAL_STATUSES:
            raise ValueError("finish status must be completed, incomplete, or failed")
        stored = self._read_run(self._existing_run_path(run_id))
        finished = replace(stored.manifest, status=status, finished_at=datetime.now().astimezone())
        self._write_manifest(stored.path, finished)
        if status in COMPLETABLE_STATUSES:
            _atomic_text(stored.path / "_COMPLETE", f"{status.value}\n")
        return StoredRun(finished, stored.path)

    def open_completed(self, run_id: str) -> StoredRun:
        run_path = self._existing_run_path(run_id)
        if not (run_path / "_COMPLETE").is_file():
            raise _incomplete(run_id, "completion marker is missing")
        stored = self._read_run(run_path)
        if stored.manifest.status not in COMPLETABLE_STATUSES:
            raise _incomplete(run_id, f"run status {stored.manifest.status.value} is not completed")
        return stored

    def list_recent(self, limit: int | None = None) -> tuple[StoredRun, ...]:
        if not self.runs_root.exists():
            return ()
        runs = [
            self._read_run(path)
            for path in self.runs_root.iterdir()
            if path.is_dir() and not path.is_symlink() and (path / "manifest.json").is_file()
        ]
        runs.sort(key=lambda stored: stored.manifest.started_at, reverse=True)
        return tuple(runs if limit is None else runs[:limit])

    def _run_path(self, run_id: str) -> Path:
        if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id or Path(run_id).is_absolute():
            raise ValueError("run_id must be one safe path component")
        return self.runs_root / run_id

    def _existing_run_path(self, run_id: str) -> Path:
        run_path = self._run_path(run_id)
        if run_path.is_symlink() or not run_path.is_dir():
            raise _corruption(run_id, "run directory does not exist or is unsafe")
        return run_path

    @staticmethod
    def _validate_output_name(name: str) -> str:
        if (
            not name
            or name in {".", ".."}
            or ".." in name
            or "/" in name
            or "\\" in name
            or Path(name).is_absolute()
        ):
            raise ValueError("output name must be one safe path component")
        return name

    @staticmethod
    def _write_manifest(run_path: Path, manifest: RunManifest) -> None:
        content = json.dumps(_manifest_dict(manifest), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        _atomic_text(run_path / "manifest.json", content)

    @staticmethod
    def _read_run(run_path: Path) -> StoredRun:
        manifest_path = run_path / "manifest.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _corruption(run_path.name, f"invalid run manifest: {exc}") from exc
        manifest = _manifest_from_dict(payload)
        if manifest.run_id != run_path.name:
            raise _corruption(run_path.name, "manifest run ID does not match directory")
        return StoredRun(manifest, run_path)
