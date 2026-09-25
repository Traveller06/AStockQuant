"""Conservative next-session matching rules for A-share simulations."""

from __future__ import annotations

from astock_quant.core.enums import Side
from astock_quant.core.models import Signal

from .models import ExecutionBar, LedgerPosition, MatchResult, MatchStatus, MatchedTrade, as_decimal


def match_next_session(
    signal: Signal,
    execution: ExecutionBar,
    position: LedgerPosition | None,
) -> MatchResult:
    """Match a signal without inventing liquidity or bypassing T+1."""
    if signal.code != execution.bar.code:
        return MatchResult.rejected("match.code_mismatch")

    if signal.side is Side.SELL and position is None:
        return MatchResult.rejected("match.no_position")
    if signal.side is Side.BUY and position is not None:
        return MatchResult.rejected("match.position_exists")

    if signal.side is Side.SELL and position is not None:
        if execution.bar.timestamp.date() <= position.opened_at.date():
            return MatchResult.pending_exit("match.t_plus_one")

    if execution.bar.timestamp <= signal.timestamp:
        if signal.side is Side.BUY:
            return MatchResult.pending_entry("match.next_session")
        return MatchResult.pending_exit("match.next_session")

    if signal.side is Side.BUY:
        if execution.is_suspended:
            return MatchResult.cancelled_entry("match.suspended_entry")
        if execution.at_limit_up:
            return MatchResult.cancelled_entry("match.limit_up_entry")
    else:
        if execution.is_suspended:
            return MatchResult.pending_exit("match.suspended_exit")
        if execution.at_limit_down:
            return MatchResult.pending_exit("match.limit_down_exit")

    trade = MatchedTrade(
        code=signal.code,
        side=signal.side,
        price=as_decimal(execution.bar.open),
        traded_at=execution.bar.timestamp,
        signal_id=signal.signal_id,
    )
    return MatchResult(MatchStatus.FILLED, "match.filled", trade)
