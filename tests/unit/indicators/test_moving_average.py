import math

import pytest

from astock_quant.indicators.moving_average import moving_average, rolling_mean_before


def test_prior_average_excludes_current_value_and_includes_boundary() -> None:
    values = (10.0, 20.0, 30.0, 40.0, 50.0, 90.0)

    assert rolling_mean_before(values, 5) == (None, None, None, None, None, 30.0)
    assert moving_average(values, 5) == (None, None, None, None, 30.0, 46.0)


@pytest.mark.parametrize("period", (0, -1, 1.5, True))
def test_invalid_period_is_rejected(period: object) -> None:
    with pytest.raises(ValueError, match="period"):
        rolling_mean_before((1.0,), period)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", (float("nan"), float("inf"), -float("inf")))
def test_non_finite_value_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        moving_average((1.0, value), 2)


def test_calculations_are_pure_and_accept_empty_input() -> None:
    values = [1.0, 2.0, 3.0]

    assert moving_average(values, 2) == (None, 1.5, 2.5)
    assert rolling_mean_before((), 2) == ()
    assert values == [1.0, 2.0, 3.0]
    assert all(value is None or math.isfinite(value) for value in moving_average(values, 2))
