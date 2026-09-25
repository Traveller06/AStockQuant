# Weekly Trend Confirmation Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, causal weekly-trend/daily-confirmation A-share strategy to AStockQuant v8.0, with realistic next-session matching, persistent state, and complete audit evidence while preserving every existing strategy.

**Architecture:** Complete the existing Phase 1 foundation before starting this Phase 2 plan. Implement the strategy as a modular-monolith plugin whose pure indicator and decision modules consume typed bars and an explicit trading calendar; keep persistence, matching, portfolio mutation, and run storage in adapters and services. Every rule produces typed checks and Chinese reason text, and every task follows a red-green-refactor test cycle with an independent commit.

**Tech Stack:** Python 3.10+, frozen dataclasses, enums, `zoneinfo`, `decimal`, `json`, `pathlib`, pandas only at data-frame adapter boundaries, pytest, existing AStockQuant v8 core models and `RunStore`.

**Spec:** `docs/superpowers/specs/2026-09-25-weekly-trend-confirmation-strategy-design.md`

## Global Constraints

- AStockQuant v7.6.3 remains read-only; do not alter its source, ZIP, cache, sample, account, or state files.
- Resume `docs/superpowers/plans/2026-09-12-v8-phase1-foundation-migration.md` at Task 4 and complete Tasks 4–7 before starting Task 1 below.
- The Phase 1 gate must show all v8 foundation tests passing and the v7.6.3 baseline reporting `Ran 63 tests ... OK` in a dependency-complete environment.
- Strategy ID is exactly `weekly_trend_confirmation`; implementation class is exactly `WeeklyTrendConfirmationStrategy`.
- The new strategy is opt-in and must not replace the existing default strategy.
- Strategy and indicator modules do not import PySide6, requests, AKShare, baostock, concrete caches, or concrete brokers.
- Inputs use one adjustment basis; a run with mixed or unknown adjustment bases fails closed.
- Only completed weeks and confirmed swing points may influence a decision.
- A close-generated signal may first be matched on the next trading session; A-share sells obey T+1.
- An unfilled entry is cancelled without chasing; an unfilled exit remains pending until a tradable session.
- No real-broker adapter, real order, automatic parameter search, or profit threshold is part of this plan.
- All tests use deterministic offline fixtures and must not call the network.
- Each task stages only its listed files and creates one focused commit.

## Review Focus

1. **Unsorted, duplicated, mixed-code, or mixed-adjustment bars:** reject the series with `StrategyInputError` rather than silently sorting or combining it; Task 1 pins these cases.
2. **Holiday-shortened and still-open weeks:** accept a shortened week only when the supplied exchange sessions mark it complete, and exclude the open week; Task 1 pins both cases.
3. **Exact threshold boundaries:** treat `1.5×`, `1.3×`, `±3%`, and `0.99×` as inclusive while breakout close and reclaim comparisons remain strict; Tasks 4–6 pin every boundary.
4. **Suspension and price-limit sessions:** never invent a fill; cancel an entry once and keep an exit pending; Task 9 pins both paths.
5. **Corrupt, incompatible, or time-regressing state:** refuse to resume and retain the last valid atomic state file; Task 7 pins all three failures.

---

## Phase 1 Entry Gate

Before Task 1, execute Tasks 4–7 in `docs/superpowers/plans/2026-09-12-v8-phase1-foundation-migration.md`, beginning with the already-written failing test `tests/unit/compatibility/test_legacy_inventory.py`. Do not rewrite or delete that test.

Run the complete gate from the v8 worktree:

```bash
python -m pytest tests/unit tests/contracts tests/integration -q
python -m unittest discover -s ../astock_quant_v7_6 -p 'test_*.py' -q
git status --short
```

Expected: all Phase 1 tests pass; the legacy suite reports 63 tests and `OK`; only intentionally uncommitted files appear. If pytest or a runtime dependency is absent, install the declared development environment before making a pass/fail claim.

---

### Task 1: Validate daily input and aggregate only completed exchange weeks

**Files:**
- Create: `src/astock_quant/data/calendar.py`
- Create: `src/astock_quant/indicators/__init__.py`
- Create: `src/astock_quant/indicators/weekly_bars.py`
- Test: `tests/unit/indicators/test_weekly_bars.py`
- Fixture: `tests/fixtures/market_calendar.py`

**Interfaces:**
- Consumes: `Sequence[Bar]`, an adjustment-basis string, `TradingCalendar`, and an aware `as_of` timestamp.
- Produces: `TradingCalendar(sessions)`, `WeeklyBar`, `validate_daily_bars(...)`, and `aggregate_completed_weeks(...) -> tuple[WeeklyBar, ...]`.

- [ ] **Step 1: Write failing input-validation and calendar tests**

```python
def test_rejects_unsorted_duplicate_mixed_code_and_mixed_basis(shanghai_bars):
    calendar = fixture_calendar()
    with pytest.raises(StrategyInputError, match="strictly increasing"):
        aggregate_completed_weeks(tuple(reversed(shanghai_bars)), "forward", calendar, AS_OF)
    with pytest.raises(StrategyInputError, match="duplicate"):
        aggregate_completed_weeks(shanghai_bars + (shanghai_bars[-1],), "forward", calendar, AS_OF)
    with pytest.raises(StrategyInputError, match="one code"):
        aggregate_completed_weeks(shanghai_bars + (replace(shanghai_bars[-1], code="000001"),), "forward", calendar, AS_OF)
    with pytest.raises(StrategyInputError, match="adjustment basis"):
        aggregate_completed_weeks(shanghai_bars, "mixed", calendar, AS_OF)


def test_holiday_week_is_complete_but_open_week_is_excluded(holiday_bars):
    weeks = aggregate_completed_weeks(holiday_bars, "forward", fixture_calendar(), AS_OF_WEDNESDAY)
    assert [week.end.date().isoformat() for week in weeks] == ["2026-10-02"]
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run:

```bash
python -m pytest tests/unit/indicators/test_weekly_bars.py -q
```

Expected: collection fails because `astock_quant.indicators.weekly_bars` does not exist.

- [ ] **Step 3: Implement the explicit-session calendar and immutable weekly bar**

```python
@dataclass(frozen=True)
class TradingCalendar:
    sessions: tuple[date, ...]

    def completed_week_ends(self, as_of: datetime) -> tuple[date, ...]: ...


@dataclass(frozen=True)
class WeeklyBar:
    code: str
    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    source: str
```

`TradingCalendar` requires unique, increasing sessions. It groups sessions by ISO year/week; a week is complete only when `as_of` is after the close of that group’s final supplied session. `aggregate_completed_weeks()` preserves the first open, maximum high, minimum low, last close, summed volume/amount, and excludes every week not returned by `completed_week_ends()`.

- [ ] **Step 4: Add exact aggregation and no-mutation assertions**

Assert a shortened week’s OHLCV values exactly, verify source bars are unchanged, and verify timezone-aware weekly endpoints. Run:

```bash
python -m pytest tests/unit/indicators/test_weekly_bars.py -q
```

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/astock_quant/data/calendar.py src/astock_quant/indicators tests/unit/indicators/test_weekly_bars.py tests/fixtures/market_calendar.py
git commit -m "feat: aggregate completed exchange weeks"
```

---

### Task 2: Add causal moving averages and confirmed swing points

**Files:**
- Create: `src/astock_quant/indicators/moving_average.py`
- Create: `src/astock_quant/indicators/swing_detector.py`
- Test: `tests/unit/indicators/test_moving_average.py`
- Test: `tests/unit/indicators/test_swing_detector.py`

**Interfaces:**
- Consumes: finite numeric sequences, `Sequence[Bar | WeeklyBar]`, and left/right confirmation widths.
- Produces: `rolling_mean_before(values, period)`, `moving_average(values, period)`, `SwingKind`, `SwingPoint`, and `confirmed_swings(...)`.

- [ ] **Step 1: Write failing moving-average tests**

```python
def test_prior_average_excludes_current_value_and_includes_boundary():
    values = (10.0, 20.0, 30.0, 40.0, 50.0, 90.0)
    assert rolling_mean_before(values, 5) == (None, None, None, None, None, 30.0)
    assert moving_average(values, 5)[-1] == 46.0


def test_invalid_period_and_non_finite_value_are_rejected():
    with pytest.raises(ValueError, match="period"):
        rolling_mean_before((1.0,), 0)
    with pytest.raises(ValueError, match="finite"):
        moving_average((1.0, float("nan")), 2)
```

- [ ] **Step 2: Write failing swing causality tests**

```python
def test_swing_becomes_visible_only_on_confirmation_bar(swing_bars):
    points = confirmed_swings(swing_bars, left=2, right=2)
    high = next(point for point in points if point.kind is SwingKind.HIGH)
    assert high.pivot_at == swing_bars[2].timestamp
    assert high.confirmed_at == swing_bars[4].timestamp


def test_appending_future_bars_does_not_change_existing_confirmed_points(swing_bars, future_bars):
    prefix = confirmed_swings(swing_bars, left=2, right=2)
    extended = tuple(point for point in confirmed_swings(swing_bars + future_bars, 2, 2) if point.confirmed_at <= swing_bars[-1].timestamp)
    assert extended == prefix
```

- [ ] **Step 3: Run both files and verify imports fail**

```bash
python -m pytest tests/unit/indicators/test_moving_average.py tests/unit/indicators/test_swing_detector.py -q
```

Expected: collection fails for the two missing modules.

- [ ] **Step 4: Implement pure calculations and explicit confirmation dates**

```python
class SwingKind(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class SwingPoint:
    kind: SwingKind
    pivot_at: datetime
    confirmed_at: datetime
    price: float
```

Use strict greater-than for swing highs and strict less-than for swing lows against both windows. Equal neighboring extrema produce no swing. Return only points whose right window exists, and preserve chronological confirmation order.

- [ ] **Step 5: Run focused tests and commit**

```bash
python -m pytest tests/unit/indicators/test_moving_average.py tests/unit/indicators/test_swing_detector.py -q
git add src/astock_quant/indicators tests/unit/indicators
git commit -m "feat: add causal averages and swing detection"
```

---

### Task 3: Define stable strategy configuration and decision contracts

**Files:**
- Create: `src/astock_quant/strategies/__init__.py`
- Create: `src/astock_quant/strategies/weekly_trend/__init__.py`
- Create: `src/astock_quant/strategies/weekly_trend/config.py`
- Create: `src/astock_quant/strategies/weekly_trend/models.py`
- Test: `tests/unit/strategies/weekly_trend/test_models.py`

**Interfaces:**
- Consumes: standard-library types plus `SwingPoint`.
- Produces: `WeeklyTrendConfig`, `RuleCheck`, `TrendAssessment`, `SetupKind`, `SetupHit`, `SetupAssessment`, `PatternStatus`, `PatternState`, `ConfirmationResult`, `DecisionAction`, `StrategyDecision`, and `StrategyEvaluation`.

- [ ] **Step 1: Write failing default-config and immutability tests**

```python
def test_default_configuration_matches_approved_spec():
    config = WeeklyTrendConfig()
    assert config.strategy_id == "weekly_trend_confirmation"
    assert config.strategy_version == "1.0.0"
    assert config.parameter_version == "weekly-trend-v1"
    assert config.weekly_ma_periods == (5, 10, 20)
    assert config.breakout_volume_multiple == Decimal("1.5")
    assert config.support_tolerance == Decimal("0.03")
    assert config.setup_valid_sessions == 20
    assert config.stabilization_low_tolerance == Decimal("0.01")
    assert config.daily_volume_multiple == Decimal("1.3")


def test_configuration_is_immutable_and_rejects_invalid_thresholds():
    with pytest.raises(FrozenInstanceError):
        WeeklyTrendConfig().setup_valid_sessions = 10
    with pytest.raises(ValueError, match="positive"):
        WeeklyTrendConfig(setup_valid_sessions=0)
```

- [ ] **Step 2: Write failing stable-enum and decision-contract tests**

```python
def test_setup_priority_and_pattern_status_values_are_stable():
    assert SetupKind.priority() == (SetupKind.BREAKOUT, SetupKind.GOLDEN_CROSS, SetupKind.PULLBACK)
    assert [item.value for item in PatternStatus] == [
        "inactive", "waiting_confirmation", "confirmed", "expired", "invalidated", "cancelled_unfilled"
    ]


def test_decision_requires_chinese_reason_and_all_rule_checks():
    with pytest.raises(ValueError, match="reason_zh"):
        RuleCheck(code="trend.ma_order", passed=False, actual="10", threshold="20", reason_zh="")
```

- [ ] **Step 3: Run and verify the package is missing**

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_models.py -q
```

Expected: collection fails because the weekly strategy package does not exist.

- [ ] **Step 4: Implement frozen contracts with exact public fields**

```python
@dataclass(frozen=True)
class RuleCheck:
    code: str
    passed: bool
    actual: str
    threshold: str
    reason_zh: str


@dataclass(frozen=True)
class PatternState:
    code: str
    status: PatternStatus
    setup: SetupHit | None
    created_at: datetime | None
    expires_on: date | None
    emitted_signal_id: str | None
    strategy_version: str
    parameter_version: str
    data_cutoff: datetime


@dataclass(frozen=True)
class StrategyEvaluation:
    signal: Signal | None
    decision: StrategyDecision
    next_state: PatternState
    initial_stop: float | None
```

All public dataclasses validate aware datetimes, non-empty codes/reasons, finite positive reference prices, and consistent status fields. `WeeklyTrendConfig.to_manifest_parameters()` returns JSON-safe strings/numbers for `RunManifest.parameters`.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_models.py -q
git add src/astock_quant/strategies tests/unit/strategies/weekly_trend/test_models.py
git commit -m "feat: define weekly strategy contracts"
```

---

### Task 4: Evaluate the weekly uptrend without future data

**Files:**
- Create: `src/astock_quant/strategies/weekly_trend/trend.py`
- Test: `tests/unit/strategies/weekly_trend/test_trend.py`
- Fixture: `tests/fixtures/weekly_trend.py`

**Interfaces:**
- Consumes: completed `WeeklyBar` values, confirmed weekly `SwingPoint` values, and `WeeklyTrendConfig`.
- Produces: `assess_weekly_trend(...) -> TrendAssessment` with five named `RuleCheck` values.

- [ ] **Step 1: Write failing qualified-trend and insufficient-data tests**

```python
def test_trend_requires_ma_order_rising_mas_two_closes_and_higher_swings(uptrend_fixture):
    result = assess_weekly_trend(*uptrend_fixture)
    assert result.qualified is True
    assert result.sufficient_data is True
    assert {check.code for check in result.checks} == {
        "trend.ma_order", "trend.ma_rising", "trend.two_closes_above_ma20",
        "trend.higher_highs", "trend.higher_lows",
    }


def test_missing_two_confirmed_highs_or_lows_is_insufficient(uptrend_fixture):
    weeks, swings, config = uptrend_fixture
    result = assess_weekly_trend(weeks, swings[:2], config)
    assert result.qualified is False
    assert result.sufficient_data is False
    assert any(check.code == "trend.swing_history" for check in result.checks)
```

- [ ] **Step 2: Add one parameterized test for every hard-condition failure**

```python
@pytest.mark.parametrize("mutation,failed_code", [
    ("ma_order", "trend.ma_order"),
    ("ma5_flat", "trend.ma_rising"),
    ("close_below_ma20", "trend.two_closes_above_ma20"),
    ("lower_high", "trend.higher_highs"),
    ("lower_low", "trend.higher_lows"),
])
def test_each_hard_condition_blocks_trend(uptrend_fixture, mutation, failed_code):
    result = assess_weekly_trend(*mutate_trend(uptrend_fixture, mutation))
    assert result.qualified is False
    assert next(check for check in result.checks if check.code == failed_code).passed is False
```

- [ ] **Step 3: Run and verify `assess_weekly_trend` is missing**

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_trend.py -q
```

Expected: import or name failure for `assess_weekly_trend`.

- [ ] **Step 4: Implement all five checks using only data visible at `as_of`**

Filter swings with `confirmed_at <= weeks[-1].end`. Compute MA5W/10W/20W over completed weeks only. MA order uses strict `>`; rising MAs use strict current-above-previous; the two closes use inclusive `>= MA20W`; higher highs/lows use strict `>`.

- [ ] **Step 5: Add a prefix-invariance test, run, and commit**

Append future weeks and swings, evaluate with the original cutoff, and assert the original `TrendAssessment` is unchanged.

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_trend.py -q
git add src/astock_quant/strategies/weekly_trend/trend.py tests/unit/strategies/weekly_trend/test_trend.py tests/fixtures/weekly_trend.py
git commit -m "feat: evaluate causal weekly uptrends"
```

---

### Task 5: Detect breakout, golden-cross, and pullback setups

**Files:**
- Create: `src/astock_quant/strategies/weekly_trend/setups.py`
- Test: `tests/unit/strategies/weekly_trend/test_setups.py`

**Interfaces:**
- Consumes: completed weeks, confirmed swings, `TrendAssessment`, an optional prior breakout price, and config.
- Produces: `detect_setups(...) -> SetupAssessment` containing all hits and one priority-selected setup.

- [ ] **Step 1: Write failing breakout threshold tests**

```python
def test_breakout_requires_strict_close_above_high_and_inclusive_1_5_volume(breakout_fixture):
    assessment = detect_setups(*breakout_fixture(volume_multiple=Decimal("1.5")))
    assert assessment.selected.kind is SetupKind.BREAKOUT
    assert assessment.selected.reference_price == breakout_fixture.previous_high

    equal_close = detect_setups(*breakout_fixture(close_at_previous_high=True))
    assert not any(hit.kind is SetupKind.BREAKOUT for hit in equal_close.hits)
```

- [ ] **Step 2: Write failing golden-cross and pullback tests**

```python
def test_golden_cross_requires_both_weekly_volume_checks(golden_fixture):
    assert detect_setups(*golden_fixture()).selected.kind is SetupKind.GOLDEN_CROSS
    assert detect_setups(*golden_fixture(not_above_previous=True)).selected is None
    assert detect_setups(*golden_fixture(below_prior_five_average=True)).selected is None


def test_pullback_keeps_all_support_hits_and_selects_highest(pullback_fixture):
    result = detect_setups(*pullback_fixture(supports=(10.0, 10.5, 11.0, 11.2)))
    pullbacks = [hit for hit in result.hits if hit.kind is SetupKind.PULLBACK]
    assert {hit.reference_price for hit in pullbacks} == {10.5, 11.0, 11.2}
    assert result.selected.reference_price == 11.2
```

- [ ] **Step 3: Write the same-week priority test**

Create a fixture that hits all three setup kinds. Assert all are present in `hits`, audit checks exist for each, and `selected.kind is SetupKind.BREAKOUT`.

- [ ] **Step 4: Run and verify the detector is missing**

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_setups.py -q
```

Expected: import or name failure for `detect_setups`.

- [ ] **Step 5: Implement explicit inclusive zones and priority selection**

The support zone intersects when `week.low <= support * 1.03` and `week.high >= support * 0.97`; reclaim requires strict `week.close > support`. Prior five-week means exclude the current week. Record the optional second-week `1.2×` breakout quality check without delaying the first breakout setup.

- [ ] **Step 6: Run focused tests and commit**

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_setups.py -q
git add src/astock_quant/strategies/weekly_trend/setups.py tests/unit/strategies/weekly_trend/test_setups.py
git commit -m "feat: detect prioritized weekly setups"
```

---

### Task 6: Confirm setups on daily bars and calculate risk exits

**Files:**
- Create: `src/astock_quant/strategies/weekly_trend/daily_confirmation.py`
- Create: `src/astock_quant/strategies/weekly_trend/risk.py`
- Test: `tests/unit/strategies/weekly_trend/test_daily_confirmation.py`
- Test: `tests/unit/strategies/weekly_trend/test_risk.py`

**Interfaces:**
- Consumes: a waiting `PatternState`, visible daily bars, visible confirmed daily swings, weekly trend data, and config.
- Produces: `confirm_daily_setup(...) -> ConfirmationResult`, `initial_stop(...) -> float | None`, and `trend_exit(...) -> ExitDecision`.

- [ ] **Step 1: Write failing stabilization and volume-boundary tests**

```python
def test_three_day_stabilization_uses_inclusive_one_percent_floor(confirm_fixture):
    result = confirm_daily_setup(*confirm_fixture(current_low=Decimal("9.90"), prior_three_low=Decimal("10.00")))
    assert result.confirmed is True


def test_daily_volume_uses_prior_five_days_and_inclusive_1_3_multiple(confirm_fixture):
    result = confirm_daily_setup(*confirm_fixture(prior_five_volume=100, current_volume=130))
    assert result.confirmed is True
    assert next(check for check in result.checks if check.code == "confirm.volume").actual == "130"
```

- [ ] **Step 2: Write failing per-setup confirmation tests**

```python
def test_breakout_confirmation_does_not_require_ma10(confirm_fixture):
    result = confirm_daily_setup(*confirm_fixture(kind=SetupKind.BREAKOUT, close_below_ma10=True, reclaim_breakout=True))
    assert result.confirmed is True


@pytest.mark.parametrize("kind", [SetupKind.GOLDEN_CROSS, SetupKind.PULLBACK])
def test_golden_and_pullback_require_strict_close_above_ma10(confirm_fixture, kind):
    result = confirm_daily_setup(*confirm_fixture(kind=kind, close_equal_ma10=True))
    assert result.confirmed is False
```

- [ ] **Step 3: Write failing stop and trend-exit tests**

```python
def test_initial_stop_uses_latest_swing_confirmed_by_signal_time(daily_swings, signal_time):
    assert initial_stop(daily_swings, signal_time) == 9.42


@pytest.mark.parametrize("cause", ["close_below_ma20", "ma_order_broken", "swing_structure_broken"])
def test_each_weekly_break_triggers_exit(exit_fixture, cause):
    decision = trend_exit(*exit_fixture(cause))
    assert decision.should_exit is True
    assert decision.reason_code == f"exit.{cause}"
```

- [ ] **Step 4: Run and verify both modules are missing**

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_daily_confirmation.py tests/unit/strategies/weekly_trend/test_risk.py -q
```

Expected: collection fails for the missing modules.

- [ ] **Step 5: Implement strict reclaims and inclusive tolerances**

Stabilization uses `low[t] >= min(low[t-3:t]) * 0.99`, `close[t] > close[t-1]`, and `close[t] > open[t]`. Breakout-zone intersection is inclusive at 97%/103%, but reclaim is strict `close > breakout`. MA10 reclaim is strict. `initial_stop()` ignores swings confirmed after signal time.

- [ ] **Step 6: Run focused tests and commit**

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_daily_confirmation.py tests/unit/strategies/weekly_trend/test_risk.py -q
git add src/astock_quant/strategies/weekly_trend/daily_confirmation.py src/astock_quant/strategies/weekly_trend/risk.py tests/unit/strategies/weekly_trend
git commit -m "feat: confirm daily entries and risk exits"
```

---

### Task 7: Implement the 20-session state machine and atomic state store

**Files:**
- Create: `src/astock_quant/strategies/weekly_trend/state_machine.py`
- Create: `src/astock_quant/strategies/weekly_trend/state_store.py`
- Test: `tests/unit/strategies/weekly_trend/test_state_machine.py`
- Test: `tests/unit/strategies/weekly_trend/test_state_store.py`

**Interfaces:**
- Consumes: `PatternState`, setup assessment, trend assessment, confirmation result, calendar sessions, config, and a state JSON path.
- Produces: `advance_state(...) -> PatternState`, `mark_entry_unfilled(...)`, and `WeeklyTrendStateStore.load/save`.

- [ ] **Step 1: Write failing expiry, invalidation, replacement, and one-shot tests**

```python
def test_setup_expires_after_twenty_trading_sessions(waiting_state, sessions):
    assert advance_state(waiting_state, sessions[19], trend_ok(), no_confirmation()).status is PatternStatus.WAITING_CONFIRMATION
    assert advance_state(waiting_state, sessions[20], trend_ok(), no_confirmation()).status is PatternStatus.EXPIRED


def test_trend_break_invalidates_immediately(waiting_state, sessions):
    assert advance_state(waiting_state, sessions[3], trend_broken(), no_confirmation()).status is PatternStatus.INVALIDATED


def test_higher_priority_setup_replaces_lower_priority_state(waiting_pullback_state, breakout_setup):
    next_state = advance_state(waiting_pullback_state, TODAY, trend_ok(), no_confirmation(), breakout_setup)
    assert next_state.setup.kind is SetupKind.BREAKOUT


def test_confirmed_state_never_emits_a_second_signal(confirmed_state):
    assert advance_state(confirmed_state, TODAY, trend_ok(), confirmed()).emitted_signal_id == confirmed_state.emitted_signal_id
```

- [ ] **Step 2: Write failing persistence safety tests**

```python
def test_store_rejects_corrupt_incompatible_and_time_regressing_state(tmp_path, valid_state):
    store = WeeklyTrendStateStore(tmp_path / "weekly-state.json")
    store.path.write_text("{", encoding="utf-8")
    with pytest.raises(DataCorruptionError):
        store.load(expected_strategy_version="1.0.0", minimum_cutoff=valid_state.data_cutoff)
    store.save(replace(valid_state, strategy_version="0.9.0"))
    with pytest.raises(ConfigurationError, match="strategy version"):
        store.load("1.0.0", valid_state.data_cutoff)
    store.save(valid_state)
    with pytest.raises(DataCorruptionError, match="cutoff"):
        store.load("1.0.0", valid_state.data_cutoff + timedelta(days=1))
```

- [ ] **Step 3: Run and verify missing modules**

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_state_machine.py tests/unit/strategies/weekly_trend/test_state_store.py -q
```

Expected: collection fails for `state_machine` and `state_store`.

- [ ] **Step 4: Implement session-count expiry and fail-closed JSON parsing**

The creation session is not counted; the first later exchange session is day 1. Transition order is: terminal-state no-op, trend invalidation, expiry, higher-priority replacement, confirmation. `mark_entry_unfilled()` changes only `CONFIRMED` to `CANCELLED_UNFILLED`.

`WeeklyTrendStateStore.save()` writes schema version 1 UTF-8 JSON to a sibling temporary file, flushes, `fsync()`s, and `os.replace()`s. `load()` validates schema, strategy/parameter versions, aware cutoff, and monotonic cutoff before returning state.

- [ ] **Step 5: Add atomic-write preservation test, run, and commit**

Inject a failing replace function, assert the prior valid file remains byte-identical, then run:

```bash
python -m pytest tests/unit/strategies/weekly_trend/test_state_machine.py tests/unit/strategies/weekly_trend/test_state_store.py -q
git add src/astock_quant/strategies/weekly_trend/state_machine.py src/astock_quant/strategies/weekly_trend/state_store.py tests/unit/strategies/weekly_trend
git commit -m "feat: add weekly setup state lifecycle"
```

---

### Task 8: Orchestrate the strategy and register it as opt-in

**Files:**
- Modify: `src/astock_quant/core/models.py`
- Modify: `tests/unit/core/test_models.py`
- Create: `src/astock_quant/strategies/interfaces.py`
- Create: `src/astock_quant/strategies/registry.py`
- Create: `src/astock_quant/strategies/weekly_trend/strategy.py`
- Test: `tests/unit/strategies/weekly_trend/test_strategy.py`
- Test: `tests/unit/strategies/test_registry.py`

**Interfaces:**
- Consumes: typed daily bars, completed weeks, calendar, current state, config, and `source_run_id`.
- Produces: `Strategy` protocol, `Signal.new(...)`, `WeeklyTrendConfirmationStrategy.evaluate(...)`, and `StrategyRegistry`.

- [ ] **Step 1: Write failing signal-correlation tests**

```python
def test_signal_factory_creates_stable_correlation_fields():
    signal = Signal.new(
        source_run_id="run-1", strategy_id="weekly_trend_confirmation", code="600000",
        timestamp=SIGNAL_TIME, side=Side.BUY, strength=1.0,
        reason="突破回踩确认", parameter_version="weekly-trend-v1",
    )
    assert signal.signal_id
    assert signal.source_run_id == "run-1"


def test_order_and_trade_can_retain_the_originating_signal_id():
    order = Order.new("run-1", "paper", "600000", Market.SSE, Side.BUY, 100, 10.2, signal_id="sig-1")
    assert order.signal_id == "sig-1"
```

Extend `Signal` with leading fields `signal_id` and `source_run_id`, retain its existing fields, and provide the factory so callers do not generate identifiers themselves. Add trailing `signal_id: str | None = None` to `Order`; add required `signal_id: str` to `Trade`. Keep `Order.new()` backward compatible by making its new `signal_id` argument keyword-only with a `None` default, while the new strategy always supplies it. Update the exact-field contract tests in `tests/unit/core/test_models.py`.

- [ ] **Step 2: Write failing end-to-end decision tests**

```python
def test_evaluate_returns_one_signal_stop_and_complete_chinese_decision(strategy_fixture):
    result = WeeklyTrendConfirmationStrategy().evaluate(**strategy_fixture)
    assert result.signal.strategy_id == "weekly_trend_confirmation"
    assert result.signal.timestamp == strategy_fixture["daily_bars"][-1].timestamp
    assert result.initial_stop == strategy_fixture["expected_stop"]
    assert result.next_state.status is PatternStatus.CONFIRMED
    assert result.decision.reason_zh
    assert all(check.reason_zh for check in result.decision.all_checks)


def test_appending_future_data_preserves_every_historical_evaluation(strategy_history):
    prefix = evaluate_history(strategy_history.prefix)
    extended = evaluate_history(strategy_history.prefix + strategy_history.future)
    assert extended[:len(prefix)] == prefix
```

- [ ] **Step 3: Write failing opt-in registry test**

```python
def test_weekly_confirmation_is_available_but_not_default():
    registry = StrategyRegistry.with_builtins()
    assert registry.get("weekly_trend_confirmation").strategy_id == "weekly_trend_confirmation"
    assert registry.default_strategy_id != "weekly_trend_confirmation"
```

- [ ] **Step 4: Run and verify factory, strategy, and registry failures**

```bash
python -m pytest tests/unit/core/test_models.py tests/unit/strategies/weekly_trend/test_strategy.py tests/unit/strategies/test_registry.py -q
```

Expected: failures because `Signal.new`, the strategy coordinator, and registry do not exist.

- [ ] **Step 5: Implement the coordinator without I/O or account mutation**

```python
class Strategy(Protocol):
    strategy_id: str
    strategy_version: str

    def evaluate(self, *, source_run_id: str, daily_bars: Sequence[Bar], adjustment_basis: str,
                 calendar: TradingCalendar, as_of: datetime,
                 state: PatternState) -> StrategyEvaluation: ...
```

The coordinator validates/aggregates input, computes visible swings and trend, detects setups, advances state, checks daily confirmation, calculates the stop, and creates at most one signal. It creates a `StrategyDecision` on every path, including insufficient data, trend rejection, waiting, expiry, invalidation, and signal emission.

- [ ] **Step 6: Run focused tests and commit**

```bash
python -m pytest tests/unit/core/test_models.py tests/unit/strategies -q
git add src/astock_quant/core/models.py src/astock_quant/strategies tests/unit/core/test_models.py tests/unit/strategies
git commit -m "feat: orchestrate weekly confirmation strategy"
```

---

### Task 9: Add next-session A-share matching and portfolio constraints

**Files:**
- Create: `src/astock_quant/backtest/__init__.py`
- Create: `src/astock_quant/backtest/models.py`
- Create: `src/astock_quant/backtest/fees.py`
- Create: `src/astock_quant/backtest/matcher.py`
- Create: `src/astock_quant/backtest/portfolio.py`
- Test: `tests/unit/backtest/test_matcher.py`
- Test: `tests/unit/backtest/test_portfolio.py`

**Interfaces:**
- Consumes: `Signal`, `ExecutionBar`, `Position`, cash, fee config, and prior pending exit.
- Produces: `ExecutionBar`, `MatchStatus`, `MatchResult`, `FeeSchedule`, `match_next_session(...)`, and `PortfolioLedger.apply(...)`.

- [ ] **Step 1: Write failing next-session and T+1 tests**

```python
def test_close_signal_can_only_fill_on_next_session(buy_signal, next_execution_bar):
    result = match_next_session(buy_signal, next_execution_bar, position=None)
    assert result.status is MatchStatus.FILLED
    assert result.trade.traded_at > buy_signal.timestamp


def test_position_bought_today_cannot_be_sold_today(position_bought_today, sell_signal, same_day_bar):
    result = match_next_session(sell_signal, same_day_bar, position_bought_today)
    assert result.status is MatchStatus.PENDING_EXIT
    assert result.reason_code == "match.t_plus_one"
```

- [ ] **Step 2: Write failing suspension and limit tests**

```python
def test_suspended_or_limit_up_entry_is_cancelled_once(buy_signal, next_execution_bar):
    for bar in (replace(next_execution_bar, is_suspended=True), replace(next_execution_bar, at_limit_up=True)):
        result = match_next_session(buy_signal, bar, position=None)
        assert result.status is MatchStatus.CANCELLED_ENTRY


def test_suspended_or_limit_down_exit_remains_pending(sell_signal, position, next_execution_bar):
    for bar in (replace(next_execution_bar, is_suspended=True), replace(next_execution_bar, at_limit_down=True)):
        assert match_next_session(sell_signal, bar, position).status is MatchStatus.PENDING_EXIT
```

- [ ] **Step 3: Write failing lot, cash, fees, and reconciliation tests**

Use a 100-share buy, commission, stamp tax on sell only, and slippage. Assert cash never becomes negative and `ending_equity == starting_cash + realized_pnl + unrealized_pnl - fees` within one cent using `Decimal`.

- [ ] **Step 4: Run and verify the backtest package is missing**

```bash
python -m pytest tests/unit/backtest/test_matcher.py tests/unit/backtest/test_portfolio.py -q
```

Expected: collection fails because `astock_quant.backtest` does not exist.

- [ ] **Step 5: Implement explicit execution metadata and conservative matching**

```python
@dataclass(frozen=True)
class ExecutionBar:
    bar: Bar
    is_suspended: bool
    at_limit_up: bool
    at_limit_down: bool


class MatchStatus(str, Enum):
    FILLED = "filled"
    CANCELLED_ENTRY = "cancelled_entry"
    PENDING_EXIT = "pending_exit"
```

Entry matching is attempted once on the next session. Exit matching repeats for later sessions while pending. The matcher never infers suspension or limit state from a zero volume alone; the data adapter must supply explicit flags. Use `Decimal(str(value))` for money calculations and round fees only at the configured boundary.

- [ ] **Step 6: Run focused tests and commit**

```bash
python -m pytest tests/unit/backtest -q
git add src/astock_quant/backtest tests/unit/backtest
git commit -m "feat: add constrained A-share backtest matching"
```

---

### Task 10: Run the strategy through the backtest engine and audit store

**Files:**
- Create: `src/astock_quant/backtest/engine.py`
- Create: `src/astock_quant/services/__init__.py`
- Create: `src/astock_quant/services/weekly_trend_service.py`
- Test: `tests/integration/test_weekly_trend_backtest.py`
- Test: `tests/integration/test_weekly_trend_audit.py`

**Interfaces:**
- Consumes: strategy, registry, calendar, daily/execution bars, initial cash, `RunManifest`, `RunStore`, and state store.
- Produces: `BacktestResult`, `BacktestEngine.run(...)`, and `WeeklyTrendService.run_backtest(...)`.

- [ ] **Step 1: Write a failing deterministic full-run test**

```python
def test_frozen_run_reconciles_signals_trades_cash_and_equity(frozen_market, run_store):
    result = WeeklyTrendService(run_store).run_backtest(frozen_market.request)
    assert len(result.signals) == 1
    assert len(result.trades) == 2
    assert result.snapshots[-1].cash >= 0
    assert result.reconciles_to_cent()
```

- [ ] **Step 2: Write failing entry-cancel and delayed-exit integration tests**

Use one fixture whose next entry session is limit-up and assert no later entry trade exists. Use another whose first two exit sessions are limit-down and assert the exit trade occurs on the third tradable session with two pending audit events.

- [ ] **Step 3: Write failing audit-linkage and manifest tests**

```python
def test_completed_run_persists_parameters_decisions_and_correlations(frozen_market, run_store):
    result = WeeklyTrendService(run_store).run_backtest(frozen_market.request)
    completed = run_store.open_completed(result.run_id)
    assert completed.manifest.strategy_id == "weekly_trend_confirmation"
    assert completed.manifest.parameters["parameter_version"] == "weekly-trend-v1"
    decisions = json.loads(completed.path.joinpath("decisions.json").read_text(encoding="utf-8"))
    assert decisions[0]["reason_zh"]
    trades = json.loads(completed.path.joinpath("trades.json").read_text(encoding="utf-8"))
    signals = json.loads(completed.path.joinpath("signals.json").read_text(encoding="utf-8"))
    assert {trade["signal_id"] for trade in trades} <= {signal["signal_id"] for signal in signals}
```

- [ ] **Step 4: Run and verify engine/service failures**

```bash
python -m pytest tests/integration/test_weekly_trend_backtest.py tests/integration/test_weekly_trend_audit.py -q
```

Expected: collection fails because the engine and service do not exist.

- [ ] **Step 5: Implement a deterministic event loop and atomic run completion**

For each session: evaluate at close, queue new signals, match only previously queued entries, process pending exits before new entries, update the ledger, persist decisions/events, and checkpoint strategy state. Start `RunStore` before processing; write `parameters.json`, `signals.json`, `orders.json`, `trades.json`, `decisions.json`, `equity.csv`, and `errors.json`; create `_COMPLETE` only after reconciliation succeeds.

Per-stock `StrategyInputError` appends to `errors.json` and skips that symbol. Configuration, state-schema, ledger, or reconciliation errors mark the run failed and do not create `_COMPLETE`.

- [ ] **Step 6: Run focused integration tests and commit**

```bash
python -m pytest tests/integration/test_weekly_trend_backtest.py tests/integration/test_weekly_trend_audit.py -q
git add src/astock_quant/backtest/engine.py src/astock_quant/services tests/integration/test_weekly_trend_backtest.py tests/integration/test_weekly_trend_audit.py
git commit -m "feat: audit weekly strategy backtests"
```

---

### Task 11: Prove causality and preserve existing strategies

**Files:**
- Create: `tests/contracts/test_weekly_strategy_boundaries.py`
- Create: `tests/regression/test_weekly_strategy_causality.py`
- Create: `tests/regression/test_existing_strategy_baseline.py`
- Create: `tests/fixtures/weekly_strategy_frozen.json`
- Create: `docs/phase2-weekly-strategy-verification.md`

**Interfaces:**
- Consumes: all Phase 2 public interfaces and the read-only v7.6.3 baseline.
- Produces: executable architecture, causality, legacy-preservation, and deterministic-output evidence.

- [ ] **Step 1: Write architecture-boundary tests**

Parse imports under `src/astock_quant/indicators` and `src/astock_quant/strategies` and fail on PySide6, requests, akshare, baostock, concrete data providers, concrete caches, or broker implementations. Assert no v8 module imports a v7 module.

- [ ] **Step 2: Write the full-prefix causality regression**

```python
def test_every_historical_decision_is_prefix_invariant(frozen_history):
    full = evaluate_each_session(frozen_history)
    for end in range(frozen_history.minimum_history, len(frozen_history.bars) + 1):
        prefix = evaluate_each_session(frozen_history.slice(end))
        assert prefix == full[:len(prefix)]
```

This comparison proves every historical result is prefix invariant and includes trend checks, setup hits, state transitions, confirmation checks, signals, stops, and decision reasons—not only final trades.

- [ ] **Step 3: Write existing-strategy preservation checks**

Hash the read-only v7.6.3 archive/tree before and after Phase 2 tests. Run the v7 suite and compare the frozen rule 1/2/3, WorldQuant, and tail-two-day result fixtures already approved by the v7 baseline. The new registry test must show the prior default remains selected.

- [ ] **Step 4: Run the complete Phase 2 gate**

```bash
python -m pytest tests/unit tests/contracts tests/integration tests/regression -q
python -m unittest discover -s ../astock_quant_v7_6 -p 'test_*.py' -q
python -m compileall -q src tests
git diff --check
git status --short
```

Expected: every v8 test passes; legacy reports `Ran 63 tests ... OK`; compilation and whitespace checks succeed; no legacy hash changes; Git status lists only the verification document before commit.

- [ ] **Step 5: Record fresh verification evidence**

Write the exact Python version, platform, commands, test counts, v7 hash before/after, frozen fixture SHA-256, and any deliberately skipped environment-specific UI checks in `docs/phase2-weekly-strategy-verification.md`. Do not state that a Windows GUI was tested unless it was actually opened on Windows.

- [ ] **Step 6: Commit the Phase 2 verification gate**

```bash
git add tests/contracts tests/regression tests/fixtures/weekly_strategy_frozen.json docs/phase2-weekly-strategy-verification.md
git commit -m "test: verify weekly strategy causality and compatibility"
```

Do not tag or publish a release in this task. Release packaging and a Strategy Center UI entry require separate reviewed plans.
