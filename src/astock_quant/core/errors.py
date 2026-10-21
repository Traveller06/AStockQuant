"""Domain errors that expose safe context for user-facing handling."""


class AStockQuantError(Exception):
    """Base error with a stable category and safe diagnostic context."""

    category = "application"

    def __init__(self, *, stage: str, scope: str, source: str, detail: str) -> None:
        super().__init__(detail)
        self.stage = stage
        self.scope = scope
        self.source = source
        self.detail = detail

    def user_context(self) -> dict[str, str]:
        return {
            "category": self.category,
            "stage": self.stage,
            "scope": self.scope,
            "source": self.source,
            "detail": self.detail,
        }


class NetworkDataError(AStockQuantError):
    category = "network_data"


class DataIncompleteError(AStockQuantError):
    category = "data_incomplete"


class DataCorruptionError(AStockQuantError):
    category = "data_corruption"


class ConfigurationError(AStockQuantError):
    category = "configuration"


class StrategyInputError(AStockQuantError):
    category = "strategy_input"


class MatchingConstraintError(AStockQuantError):
    category = "matching_constraint"


class MigrationError(AStockQuantError):
    category = "migration"


class InternalApplicationError(AStockQuantError):
    category = "internal_application"
