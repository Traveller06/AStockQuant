import pytest

from astock_quant.core.errors import (
    AStockQuantError,
    ConfigurationError,
    DataCorruptionError,
    DataIncompleteError,
    InternalApplicationError,
    MatchingConstraintError,
    MigrationError,
    NetworkDataError,
    StrategyInputError,
)


def test_domain_error_exposes_user_safe_context():
    error = DataIncompleteError(stage="strict_300", scope="600000", source="cache", detail="missing close")

    assert error.user_context() == {
        "category": "data_incomplete",
        "stage": "strict_300",
        "scope": "600000",
        "source": "cache",
        "detail": "missing close",
    }


@pytest.mark.parametrize(
    ("error_type", "category"),
    [
        (NetworkDataError, "network_data"),
        (DataIncompleteError, "data_incomplete"),
        (DataCorruptionError, "data_corruption"),
        (ConfigurationError, "configuration"),
        (StrategyInputError, "strategy_input"),
        (MatchingConstraintError, "matching_constraint"),
        (MigrationError, "migration"),
        (InternalApplicationError, "internal_application"),
    ],
)
def test_typed_domain_errors_have_fixed_categories(error_type, category):
    error = error_type(stage="test", scope="scope", source="source", detail="detail")

    assert isinstance(error, AStockQuantError)
    assert error.category == category
