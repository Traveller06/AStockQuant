"""Future sessions cannot alter previous trading decisions or fills."""

from dataclasses import replace

from astock_quant.backtest.engine import BacktestEngine
from astock_quant.data.calendar import TradingCalendar
from tests.integration.test_weekly_trend_backtest import ScriptedStrategy, make_request


def test_every_history_prefix_has_identical_previous_decisions_and_trades():
    request = replace(make_request(days=6), run_id='frozen-causal-run')
    full = BacktestEngine(ScriptedStrategy()).run(request)
    for length in range(1, len(request.calendar.sessions) + 1):
        sessions = request.calendar.sessions[:length]
        prefix = replace(request, calendar=TradingCalendar(sessions), data_as_of=sessions[-1])
        result = BacktestEngine(ScriptedStrategy()).run(prefix)
        assert result.decisions == full.decisions[:len(result.decisions)]
        assert result.signals == full.signals[:len(result.signals)]
        assert result.trades == full.trades[:len(result.trades)]
        assert result.snapshots == full.snapshots[:length]
