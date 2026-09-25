"""Persisted application settings for the v8 application."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path

from astock_quant.core.errors import ConfigurationError


@dataclass(frozen=True)
class Settings:
    """The supported, safe settings schema for v8."""

    schema_version: int = 1
    active_data_provider: str = "eastmoney"
    real_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise _configuration_error(
                "schema_version", "unsupported settings schema version"
            )
        if self.real_trading_enabled is not False:
            raise _configuration_error(
                "real_trading_enabled", "real trading is disabled in v8"
            )

    @classmethod
    def load(cls, path: Path) -> "Settings":
        """Load and validate a settings document."""
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _configuration_error(str(source), "invalid settings file") from error

        if not isinstance(payload, dict):
            raise _configuration_error(str(source), "settings file must contain an object")
        expected_fields = {
            "schema_version",
            "active_data_provider",
            "real_trading_enabled",
        }
        if set(payload) != expected_fields:
            raise _configuration_error(str(source), "settings file has an unsupported schema")
        if type(payload["schema_version"]) is not int:
            raise _configuration_error("schema_version", "unsupported settings schema version")
        if not isinstance(payload["active_data_provider"], str):
            raise _configuration_error("active_data_provider", "invalid active data provider")
        if type(payload["real_trading_enabled"]) is not bool:
            raise _configuration_error("real_trading_enabled", "invalid real trading setting")

        return cls(**payload)

    def save(self, path: Path) -> None:
        """Atomically write settings to a sibling temporary file and replace it."""
        target = Path(path)
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(asdict(self), stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)


def _configuration_error(source: str, detail: str) -> ConfigurationError:
    return ConfigurationError(
        stage="settings validation",
        scope="settings",
        source=source,
        detail=detail,
    )
