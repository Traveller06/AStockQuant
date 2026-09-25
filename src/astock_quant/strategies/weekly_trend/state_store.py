"""Fail-closed, atomic persistence for weekly strategy state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from astock_quant.core.errors import ConfigurationError, DataCorruptionError

from .models import PatternState, PatternStatus, RuleCheck, SetupHit, SetupKind


SCHEMA_VERSION = 1


def _corrupt(path: Path, detail: str) -> DataCorruptionError:
    return DataCorruptionError(stage="state_load", scope=str(path), source="weekly_trend_state", detail=detail)


def _configuration(path: Path, detail: str) -> ConfigurationError:
    return ConfigurationError(stage="state_load", scope=str(path), source="weekly_trend_state", detail=detail)


def _check_to_dict(check: RuleCheck) -> dict[str, Any]:
    return {
        "code": check.code,
        "passed": check.passed,
        "actual": check.actual,
        "threshold": check.threshold,
        "reason_zh": check.reason_zh,
    }


def _setup_to_dict(setup: SetupHit | None) -> dict[str, Any] | None:
    if setup is None:
        return None
    return {
        "kind": setup.kind.value,
        "occurred_at": setup.occurred_at.isoformat(),
        "reference_price": setup.reference_price,
        "reference_label": setup.reference_label,
        "checks": [_check_to_dict(check) for check in setup.checks],
    }


def _state_to_dict(state: PatternState) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": {
            "code": state.code,
            "status": state.status.value,
            "setup": _setup_to_dict(state.setup),
            "created_at": state.created_at.isoformat() if state.created_at else None,
            "expires_on": state.expires_on.isoformat() if state.expires_on else None,
            "emitted_signal_id": state.emitted_signal_id,
            "strategy_version": state.strategy_version,
            "parameter_version": state.parameter_version,
            "data_cutoff": state.data_cutoff.isoformat(),
        },
    }


def _dict_to_state(payload: dict[str, Any]) -> PatternState:
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("state"), dict):
        raise ValueError("unsupported state schema")
    raw = payload["state"]
    raw_setup = raw["setup"]
    setup = None
    if raw_setup is not None:
        checks = tuple(RuleCheck(**item) for item in raw_setup["checks"])
        setup = SetupHit(
            kind=SetupKind(raw_setup["kind"]),
            occurred_at=datetime.fromisoformat(raw_setup["occurred_at"]),
            reference_price=float(raw_setup["reference_price"]),
            reference_label=raw_setup["reference_label"],
            checks=checks,
        )
    return PatternState(
        code=raw["code"],
        status=PatternStatus(raw["status"]),
        setup=setup,
        created_at=datetime.fromisoformat(raw["created_at"]) if raw["created_at"] else None,
        expires_on=datetime.fromisoformat(raw["expires_on"]).date() if raw["expires_on"] else None,
        emitted_signal_id=raw["emitted_signal_id"],
        strategy_version=raw["strategy_version"],
        parameter_version=raw["parameter_version"],
        data_cutoff=datetime.fromisoformat(raw["data_cutoff"]),
    )


class WeeklyTrendStateStore:
    def __init__(
        self,
        path: Path,
        *,
        replace_func: Callable[[os.PathLike[str], os.PathLike[str]], None] = os.replace,
    ) -> None:
        self.path = Path(path)
        self._replace = replace_func

    def save(self, state: PatternState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(_state_to_dict(state), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def load(
        self,
        expected_strategy_version: str,
        minimum_cutoff: datetime,
        *,
        expected_parameter_version: str | None = None,
    ) -> PatternState | None:
        if minimum_cutoff.tzinfo is None or minimum_cutoff.utcoffset() is None:
            raise ValueError("minimum_cutoff must be timezone-aware")
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("state root must be an object")
            state = _dict_to_state(payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise _corrupt(self.path, f"state file is corrupt or incompatible: {error}") from error

        if state.strategy_version != expected_strategy_version:
            raise _configuration(
                self.path,
                f"strategy version mismatch: expected {expected_strategy_version}, found {state.strategy_version}",
            )
        if expected_parameter_version is not None and state.parameter_version != expected_parameter_version:
            raise _configuration(
                self.path,
                f"parameter version mismatch: expected {expected_parameter_version}, found {state.parameter_version}",
            )
        if state.data_cutoff < minimum_cutoff:
            raise _corrupt(
                self.path,
                f"state cutoff {state.data_cutoff.isoformat()} is earlier than required {minimum_cutoff.isoformat()}",
            )
        return state
