# AStockQuant v8.0 Windows Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成周线趋势确认策略的撮合、账户和审计闭环，并在不改变 v7.6.3 旧策略、数据和默认行为的前提下，交付可双击安装的 Windows v8.0 中文桌面版。

**Architecture:** 现有 v7.6.3 平面程序作为 Windows 桌面壳，`astock_quant` 作为独立 v8 内核。新增桌面适配层只转换数据、组装请求和投影结果，不复制策略或撮合规则；新页面通过受保护的导入接入，v8 失效时旧页面仍可使用。

**Tech Stack:** Python 3.10+、PySide6 6.8+、pandas 2.2.3+、NumPy 2.0+、`dataclasses`、`Decimal`、pytest/unittest、Windows batch、ZIP。

**Spec:** `docs/superpowers/specs/2026-09-25-v8-windows-integration-design.md`

## Global Constraints

- 继续使用现有工作树和分支 `codex/v8-phase1`；不重新初始化，不创建新版本开发目录，不使用 `git reset` 或 `git checkout --`。
- 每个 Task 的测试通过后立即提交，更新 `.superpowers/sdd/2026-09-25-v8-windows-integration/progress.md` 和 `docs/development-progress.md`，并同步 GitHub 分支。
- 保留 v7.6.3 全部页面、策略、缓存、模拟持仓和双击启动方式；`legacy_v7` 继续是默认策略。
- `weekly_trend_confirmation` 只能由用户主动打开；本版只用于研究、回测和本地模拟，不连接真实券商。
- 旧 `cache`、`tail_strategy_cache`、`tail_strategy_state.json`、`research_sample.json` 和 `validation_snapshot_v1.json.gz` 不迁移、不改写；v8 只写 `v8_state` 与 `v8_runs`。
- 不增加规格之外的策略参数，不利用已知的 2024 年后结果调参。
- 发布 ZIP 不得包含账户、缓存、持仓、运行结果、用户股票池或个人数据。
- 未在 Windows 实机打开窗口时，验证报告必须明确写“未进行 Windows GUI 实机验证”。

## Review Focus

1. **无效或无时区日期：** 单股转换失败应记录中文错误并跳过，不得修改原 DataFrame；Task 5 的适配器测试固定该行为。
2. **信号日同日交易或退出受限：** 入场只能下一交易日尝试一次，买入当日不得卖出，跌停/停牌退出必须顺延；Task 1 的撮合测试覆盖。
3. **部分运行被误认为完成：** 账户对账失败、清单损坏或写盘中断时不得产生 `_COMPLETE`；Task 2 的审计测试覆盖。
4. **v8 导入失败：** 新页面应显示可操作的中文错误，v7 菜单和旧页面仍能构造；Task 7 的无 PySide6 界面契约测试覆盖。
5. **发布包泄露运行数据：** ZIP 内出现任一受禁名称、`v8_state`、`v8_runs` 或嵌套顶层目录必须失败；Task 8 的发布契约测试覆盖。

---

## File Map

| Path | Responsibility |
|---|---|
| `src/astock_quant/backtest/models.py` | 撮合、持仓、资金快照和回测结果类型 |
| `src/astock_quant/backtest/fees.py` | 佣金、印花税、滑点和金额舍入 |
| `src/astock_quant/backtest/matcher.py` | 下一交易日、T+1、涨跌停和停牌撮合 |
| `src/astock_quant/backtest/portfolio.py` | 现金、整手、持仓、费用和权益对账 |
| `src/astock_quant/backtest/engine.py` | 按交易日执行策略、撮合、账户与审计事件 |
| `src/astock_quant/services/weekly_trend_service.py` | 组装回测请求并产生完整运行目录 |
| `src/astock_quant/desktop/legacy_adapter.py` | 将 v7 pandas 数据只读转换为 v8 `Bar`/`ExecutionBar` |
| `src/astock_quant/desktop/weekly_trend_facade.py` | 桌面线程安全 API、进度、中文错误和结果投影 |
| `windows_app/main.py` | 纳管的 v7.6.3 桌面壳，只增加受保护的新页入口 |
| `windows_app/weekly_trend_page.py` | 周线趋势确认页面，不包含策略或撮合算法 |
| `scripts/import_v763_baseline.py` | 验证整包 SHA-256，再从用户基线 ZIP 只导入白名单程序文件 |
| `scripts/build_windows_release.py` | 从受控源码构建干净、平面根目录的 ZIP |

### Task 1: Add next-session A-share matching and portfolio constraints

**Files:**
- Create (local recovery ledger): `.superpowers/sdd/2026-09-25-v8-windows-integration/progress.md`
- Create: `src/astock_quant/backtest/__init__.py`
- Create: `src/astock_quant/backtest/models.py`
- Create: `src/astock_quant/backtest/fees.py`
- Create: `src/astock_quant/backtest/matcher.py`
- Create: `src/astock_quant/backtest/portfolio.py`
- Test: `tests/unit/backtest/test_matcher.py`
- Test: `tests/unit/backtest/test_portfolio.py`

**Interfaces:**
- Consumes: `Signal`, `Trade`, `Bar`, `Decimal`, `FeeSchedule` configuration and an optional open `Position`.
- Produces: `ExecutionBar`, `MatchStatus`, `MatchResult`, `FeeSchedule.calculate(...)`, `match_next_session(...)`, `PortfolioLedger.apply_fill(...)`, and `PortfolioLedger.snapshot(...)`.

- [ ] **Step 0: Initialize the interruption-safe recovery ledger**

Write the local ledger with the exact plan path, execution mode `native inline`, current HEAD, `Resume point: Task 1`, and the invariant “a task is complete only after focused tests, full tests, commit and GitHub checkpoint all succeed.” Update this file after every later step; `docs/development-progress.md` is the committed remote-readable copy.

- [ ] **Step 1: Write failing next-session, T+1 and restricted-exit tests**

```python
def test_close_signal_fills_only_on_next_session(buy_signal, next_bar):
    result = match_next_session(buy_signal, next_bar, position=None)
    assert result.status is MatchStatus.FILLED
    assert result.trade.traded_at > buy_signal.timestamp

def test_same_day_sell_waits_for_t_plus_one(position_bought_today, sell_signal, same_day_bar):
    result = match_next_session(sell_signal, same_day_bar, position_bought_today)
    assert result.status is MatchStatus.PENDING_EXIT
    assert result.reason_code == "match.t_plus_one"

def test_limit_down_exit_remains_pending(position, sell_signal, next_bar):
    blocked = dataclasses.replace(next_bar, at_limit_down=True)
    assert match_next_session(sell_signal, blocked, position).status is MatchStatus.PENDING_EXIT
```

- [ ] **Step 2: Write failing entry cancellation, lot, cash and reconciliation tests**

```python
def test_limit_up_entry_is_cancelled_and_not_retried(buy_signal, next_bar):
    result = match_next_session(buy_signal, dataclasses.replace(next_bar, at_limit_up=True), None)
    assert result.status is MatchStatus.CANCELLED_ENTRY
    assert result.reason_code == "match.limit_up_entry"

def test_ledger_uses_board_lots_and_never_overdraws():
    ledger = PortfolioLedger(initial_cash=Decimal("100000"), fees=FeeSchedule.default())
    fill = ledger.buy(symbol="600000", price=Decimal("10.01"), requested_shares=999, traded_at=SHANGHAI_OPEN)
    assert fill.shares % 100 == 0
    assert ledger.cash >= 0
    assert ledger.reconciles_to_cent(mark_prices={"600000": Decimal("10.01")})
```

- [ ] **Step 3: Run tests and verify the package is absent**

Run: `python -m pytest tests/unit/backtest/test_matcher.py tests/unit/backtest/test_portfolio.py -q`

Expected: collection fails with `ModuleNotFoundError: astock_quant.backtest`.

- [ ] **Step 4: Implement execution types, fees, conservative matching and the ledger**

```python
@dataclass(frozen=True)
class ExecutionBar:
    bar: Bar
    is_suspended: bool = False
    at_limit_up: bool = False
    at_limit_down: bool = False

class MatchStatus(str, Enum):
    FILLED = "filled"
    CANCELLED_ENTRY = "cancelled_entry"
    PENDING_EXIT = "pending_exit"

def match_next_session(signal: Signal, execution: ExecutionBar,
                       position: Position | None) -> MatchResult:
    if execution.bar.timestamp <= signal.timestamp:
        return MatchResult.pending("match.next_session")
    if signal.side is Side.BUY and (execution.is_suspended or execution.at_limit_up):
        return MatchResult.cancelled_entry("match.entry_unavailable")
    if signal.side is Side.SELL and position and execution.bar.timestamp.date() <= position.opened_at.date():
        return MatchResult.pending_exit("match.t_plus_one")
    if signal.side is Side.SELL and (execution.is_suspended or execution.at_limit_down):
        return MatchResult.pending_exit("match.exit_unavailable")
    return MatchResult.filled_from(signal, execution)
```

All money enters the ledger through `Decimal(str(value))`. Commission and stamp tax are rounded only by `FeeSchedule.quantize_money`; stamp tax applies to sells only. Entry is attempted once; a blocked exit remains pending for later sessions.

- [ ] **Step 5: Run focused and full tests**

Run: `python -m pytest tests/unit/backtest -q && python -m pytest -q && python -m compileall -q src tests && git diff --check`

Expected: all tests pass; cash, fees, holdings and equity reconcile to one cent.

- [ ] **Step 6: Commit and checkpoint**

```bash
git add src/astock_quant/backtest tests/unit/backtest docs/development-progress.md
git commit -m "feat: add constrained A-share backtest matching"
```

### Task 2: Run the strategy through the backtest engine and atomic audit store

**Files:**
- Create: `src/astock_quant/backtest/engine.py`
- Create: `src/astock_quant/services/__init__.py`
- Create: `src/astock_quant/services/weekly_trend_service.py`
- Modify: `src/astock_quant/reports/run_store.py`
- Test: `tests/integration/test_weekly_trend_backtest.py`
- Test: `tests/integration/test_weekly_trend_audit.py`

**Interfaces:**
- Consumes: `WeeklyTrendConfirmationStrategy`, `TradingCalendar`, `ExecutionBar`, `PortfolioLedger`, `RunManifest`, `RunStore`, and strategy state store.
- Produces: `BacktestRequest`, `BacktestResult`, `BacktestEngine.run(request)`, and `WeeklyTrendService.run_backtest(request)`.

- [ ] **Step 1: Write a failing deterministic full-run test**

```python
def test_frozen_run_reconciles_signals_trades_cash_and_equity(frozen_market, run_store):
    result = WeeklyTrendService(run_store).run_backtest(frozen_market.request)
    assert len(result.signals) == 1
    assert len(result.trades) == 2
    assert result.snapshots[-1].cash >= 0
    assert result.reconciles_to_cent()
```

- [ ] **Step 2: Write failing blocked-entry, delayed-exit and incomplete-run tests**

```python
def test_blocked_entry_never_retries(limit_up_entry_market, run_store):
    result = WeeklyTrendService(run_store).run_backtest(limit_up_entry_market.request)
    assert result.trades == ()
    assert [event.code for event in result.events].count("match.entry_unavailable") == 1

def test_reconciliation_failure_never_creates_complete_marker(frozen_market, corrupting_run_store):
    with pytest.raises(ReconciliationError):
        WeeklyTrendService(corrupting_run_store).run_backtest(frozen_market.request)
    assert not any(corrupting_run_store.root.rglob("_COMPLETE"))
```

- [ ] **Step 3: Write failing manifest and correlation tests**

```python
def test_completed_run_links_orders_and_trades_to_signals(frozen_market, run_store):
    result = WeeklyTrendService(run_store).run_backtest(frozen_market.request)
    completed = run_store.open_completed(result.run_id)
    manifest = completed.manifest
    assert manifest.strategy_id == "weekly_trend_confirmation"
    assert manifest.parameters["parameter_version"] == "weekly-trend-v1"
    assert manifest.data_as_of
    assert manifest.sample_sha256 and manifest.data_sha256
    assert {t.signal_id for t in completed.trades} <= {s.signal_id for s in completed.signals}
```

- [ ] **Step 4: Run tests and verify engine/service failures**

Run: `python -m pytest tests/integration/test_weekly_trend_backtest.py tests/integration/test_weekly_trend_audit.py -q`

Expected: collection fails because the engine and service do not exist.

- [ ] **Step 5: Implement the deterministic event loop and atomic completion**

```python
@dataclass(frozen=True)
class BacktestRequest:
    daily_bars: Mapping[str, tuple[Bar, ...]]
    execution_bars: Mapping[str, tuple[ExecutionBar, ...]]
    calendar: TradingCalendar
    initial_cash: Decimal
    fees: FeeSchedule
    adjustment_basis: str
    data_as_of: date
    app_version: str

class BacktestEngine:
    def run(self, request: BacktestRequest) -> BacktestResult:
        """Match prior queues, process pending exits, evaluate close signals, snapshot, reconcile."""
```

For each session the engine matches previously queued orders, handles pending exits before entries, evaluates close data, queues new signals, snapshots equity, and checkpoints state. The service writes `manifest.json`, `parameters.json`, `signals.json`, `orders.json`, `trades.json`, `decisions.json`, `checks.json`, `equity.csv`, and `errors.json`; it calls `RunStore.complete()` only after reconciliation. `StrategyInputError` is per-symbol and append-only; configuration, schema, ledger and reconciliation errors fail the run.

- [ ] **Step 6: Run focused and full tests**

Run: `python -m pytest tests/integration/test_weekly_trend_backtest.py tests/integration/test_weekly_trend_audit.py -q && python -m pytest -q && python -m compileall -q src tests && git diff --check`

Expected: focused and full suites pass; every completed run has all required artifacts and `_COMPLETE`.

- [ ] **Step 7: Commit and checkpoint**

```bash
git add src/astock_quant/backtest/engine.py src/astock_quant/services src/astock_quant/reports/run_store.py tests/integration docs/development-progress.md
git commit -m "feat: audit weekly strategy backtests"
```

### Task 3: Prove causality and preserve the v7.6.3 baseline

**Files:**
- Create: `tests/contracts/test_weekly_strategy_boundaries.py`
- Create: `tests/regression/test_weekly_strategy_causality.py`
- Create: `tests/regression/test_existing_strategy_baseline.py`
- Create: `tests/fixtures/weekly_strategy_frozen.json`
- Create: `scripts/verify_v763_baseline.py`
- Create: `docs/phase2-weekly-strategy-verification.md`

**Interfaces:**
- Consumes: all v8 public strategy/backtest interfaces and the read-only v7.6.3 ZIP.
- Produces: executable boundary, prefix-invariance, legacy-hash and deterministic-output evidence.

- [ ] **Step 1: Write architecture-boundary and default-selection tests**

```python
def test_strategy_and_indicator_modules_have_no_ui_network_or_v7_imports():
    forbidden = {"PySide6", "requests", "akshare", "baostock", "main", "tail_strategy"}
    assert scan_import_roots(SRC / "astock_quant" / "strategies").isdisjoint(forbidden)
    assert scan_import_roots(SRC / "astock_quant" / "indicators").isdisjoint(forbidden)

def test_legacy_strategy_remains_default():
    assert build_default_registry().default_strategy_id == "legacy_v7"
```

- [ ] **Step 2: Write full-prefix causality and immutable-baseline tests**

```python
def test_every_historical_decision_is_prefix_invariant(frozen_history):
    full = evaluate_each_session(frozen_history)
    for end in range(frozen_history.minimum_history, len(frozen_history.bars) + 1):
        prefix = evaluate_each_session(frozen_history.slice(end))
        assert prefix == full[:len(prefix)]

def test_v763_archive_hash_is_unchanged(v763_archive):
    before = sha256_file(v763_archive)
    run_v8_regression_fixture()
    assert sha256_file(v763_archive) == before
```

- [ ] **Step 3: Run the new regression tests and capture initial failures**

Run: `python -m pytest tests/contracts/test_weekly_strategy_boundaries.py tests/regression -q`

Expected: failures identify the missing frozen fixture/baseline helpers before they are added.

- [ ] **Step 4: Add the frozen fixture and verification helpers**

The fixture contains versioned daily and execution bars, explicit suspension/limit flags, expected decisions, orders, trades, ending cash/equity, and SHA-256. The baseline helper opens the source ZIP read-only, extracts to a temporary directory, runs `test_execution.py` and `test_tail_strategy.py`, and lets `TemporaryDirectory` remove only its own directory.

```python
V763_ARCHIVE_SHA256 = "dfc50da574d6a15b280ba65091e883cfd7047cc4238e3aca92badef970be540e"

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def verify_v763_baseline(archive: Path) -> subprocess.CompletedProcess[str]:
    before = sha256_file(archive)
    if before != V763_ARCHIVE_SHA256:
        raise ValueError("基线安装包与已审核版本不一致")
    with tempfile.TemporaryDirectory(prefix="astock-v763-verify-") as raw:
        safe_extract(archive, Path(raw))
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", raw, "-p", "test_*.py", "-q"],
            check=False, capture_output=True, text=True,
        )
    if sha256_file(archive) != before:
        raise RuntimeError("基线安装包在验证期间发生变化")
    return result
```

- [ ] **Step 5: Run the complete Phase 2 gate and write evidence**

Run:

```bash
python -m pytest tests/unit tests/contracts tests/integration tests/regression -q
python -m compileall -q src tests
python scripts/verify_v763_baseline.py '/workspace/scratch/08ddc3994218/upload/AStockQuant_v7_6_3_空分钟缓存修复_双击版.zip'
git diff --check
```

Expected: v8 passes; v7 reports 63 tests and `OK`; archive SHA-256 is identical before/after. Record Python version, platform, exact commands, counts, fixture SHA-256 and the absence of Windows GUI testing in `docs/phase2-weekly-strategy-verification.md`.

- [ ] **Step 6: Commit and checkpoint**

```bash
git add tests/contracts tests/regression tests/fixtures/weekly_strategy_frozen.json scripts/verify_v763_baseline.py docs/phase2-weekly-strategy-verification.md docs/development-progress.md
git commit -m "test: verify weekly strategy causality and compatibility"
```

### Task 4: Import the approved v7.6.3 desktop shell into the single Git project

**Files:**
- Create: `scripts/import_v763_baseline.py`
- Create: `windows_app/main.py`
- Create: `windows_app/tail_strategy.py`
- Create: `windows_app/test_execution.py`
- Create: `windows_app/test_tail_strategy.py`
- Create: `windows_app/requirements.txt`
- Create: `windows_app/1_第一次双击_安装并打开.bat`
- Create: `windows_app/2_以后双击_启动软件.bat`
- Create: `windows_app/install.bat`
- Create: `windows_app/run.bat`
- Create: `windows_app/README.txt`
- Create: `tests/contracts/test_v763_import.py`

**Interfaces:**
- Consumes: the approved archive path, archive SHA-256 `dfc50da574d6a15b280ba65091e883cfd7047cc4238e3aca92badef970be540e`, and a hard-coded 20-file allow-list.
- Produces: `import_baseline(archive: Path, destination: Path) -> ImportReport` and a tracked `windows_app` baseline with no user data.

- [ ] **Step 1: Write failing allow-list, hash and idempotence tests**

```python
def test_import_accepts_only_manifest_files(v763_zip, tmp_path):
    report = import_baseline(v763_zip, tmp_path / "windows_app")
    assert set(report.imported) == set(V763_PROGRAM_MANIFEST)
    assert not any(p.name in FORBIDDEN_RUNTIME_NAMES for p in report.destination.rglob("*"))

def test_import_refuses_wrong_hash_without_partial_output(tampered_zip, tmp_path):
    destination = tmp_path / "windows_app"
    with pytest.raises(BaselineHashMismatch):
        import_baseline(tampered_zip, destination)
    assert not destination.exists()
```

- [ ] **Step 2: Run and verify the importer is absent**

Run: `python -m pytest tests/contracts/test_v763_import.py -q`

Expected: collection fails because `scripts.import_v763_baseline` does not exist.

- [ ] **Step 3: Implement staged, verified import**

```python
def import_baseline(archive: Path, destination: Path) -> ImportReport:
    verify_archive_sha256(archive, "dfc50da574d6a15b280ba65091e883cfd7047cc4238e3aca92badef970be540e")
    with tempfile.TemporaryDirectory(prefix="astock-v763-") as raw:
        stage = Path(raw)
        extract_manifest_members(archive, stage, V763_PROGRAM_MANIFEST)
        verify_exact_member_set(archive, V763_PROGRAM_MANIFEST)
        atomic_copy_tree(stage, destination)
    return ImportReport(destination, tuple(V763_PROGRAM_MANIFEST))
```

The manifest includes only the 20 existing program, launcher and documentation files. It rejects absolute paths, `..`, symlinks, unknown members and a whole-archive hash mismatch before destination replacement.

- [ ] **Step 4: Run the importer once, then verify the untouched baseline**

Run:

```bash
python scripts/import_v763_baseline.py '/workspace/scratch/08ddc3994218/upload/AStockQuant_v7_6_3_空分钟缓存修复_双击版.zip' windows_app
python -m unittest discover -s windows_app -p 'test_*.py' -q
python -m pytest tests/contracts/test_v763_import.py -q
```

Expected: importer reports 20 verified files; v7 reports 63 tests and `OK`; import contract passes.

- [ ] **Step 5: Commit and checkpoint**

```bash
git add scripts/import_v763_baseline.py windows_app tests/contracts/test_v763_import.py docs/development-progress.md
git commit -m "chore: track verified v763 Windows baseline"
```

### Task 5: Adapt legacy pandas bars without mutating old data

**Files:**
- Create: `src/astock_quant/desktop/__init__.py`
- Create: `src/astock_quant/desktop/legacy_adapter.py`
- Test: `tests/unit/desktop/test_legacy_adapter.py`

**Interfaces:**
- Consumes: `Mapping[str, pandas.DataFrame]`, adjustment basis, source name and optional per-symbol execution flags.
- Produces: `AdaptedMarket`, `LegacyDataIssue`, and `adapt_legacy_frames(...) -> AdaptedMarket`.

- [ ] **Step 1: Write failing conversion, immutability and per-symbol-error tests**

```python
def test_adapter_localizes_sorts_and_does_not_mutate_source(valid_legacy_frame):
    original = valid_legacy_frame.copy(deep=True)
    market = adapt_legacy_frames({"600000": valid_legacy_frame}, adjustment_basis="qfq", source="v7_cache")
    bars = market.daily_bars["600000"]
    assert all(bar.timestamp.tz.key == "Asia/Shanghai" for bar in bars)
    assert [bar.timestamp for bar in bars] == sorted({bar.timestamp for bar in bars})
    pandas.testing.assert_frame_equal(valid_legacy_frame, original)

def test_bad_symbol_is_skipped_with_chinese_issue(valid_legacy_frame, bad_timestamp_frame):
    market = adapt_legacy_frames({"600000": valid_legacy_frame, "600001": bad_timestamp_frame}, adjustment_basis="qfq", source="v7_cache")
    assert "600000" in market.daily_bars and "600001" not in market.daily_bars
    assert market.issues[0].symbol == "600001"
    assert "日期" in market.issues[0].message_zh
```

- [ ] **Step 2: Write failing duplicate, missing-field and adjustment-basis tests**

```python
@pytest.mark.parametrize("frame", [duplicate_day_frame(), missing_ohlcv_frame(), non_numeric_price_frame()])
def test_invalid_frame_is_reported_not_partially_converted(frame):
    market = adapt_legacy_frames({"600000": frame}, adjustment_basis="qfq", source="v7_cache")
    assert market.daily_bars == {}
    assert len(market.issues) == 1

def test_adjustment_basis_must_be_explicit(valid_legacy_frame):
    with pytest.raises(ValueError, match="复权"):
        adapt_legacy_frames({"600000": valid_legacy_frame}, adjustment_basis="", source="v7_cache")
```

- [ ] **Step 3: Run and verify the adapter is absent**

Run: `python -m pytest tests/unit/desktop/test_legacy_adapter.py -q`

Expected: collection fails because `astock_quant.desktop.legacy_adapter` does not exist.

- [ ] **Step 4: Implement strict, read-only conversion**

```python
@dataclass(frozen=True)
class AdaptedMarket:
    daily_bars: Mapping[str, tuple[Bar, ...]]
    execution_bars: Mapping[str, tuple[ExecutionBar, ...]]
    calendar: TradingCalendar
    issues: tuple[LegacyDataIssue, ...]
    adjustment_basis: str
    data_as_of: date | None

def adapt_legacy_frames(frames: Mapping[str, pd.DataFrame], *, adjustment_basis: str,
                        source: str, flags: Mapping[str, pd.DataFrame] | None = None) -> AdaptedMarket:
    """Copy each frame, validate it, convert good symbols and report bad symbols."""
```

Normalize dates to market close in `Asia/Shanghai`, enforce unique increasing timestamps and required OHLCV/amount columns, include symbol/source/adjustment basis in every `Bar`, and build a calendar from successful symbols only. Never call an in-place pandas operation on an input frame.

- [ ] **Step 5: Run focused and full tests, then commit**

Run: `python -m pytest tests/unit/desktop/test_legacy_adapter.py -q && python -m pytest -q && python -m compileall -q src tests && git diff --check`

```bash
git add src/astock_quant/desktop tests/unit/desktop docs/development-progress.md
git commit -m "feat: adapt legacy market data for v8"
```

### Task 6: Add the desktop-safe weekly trend facade and result projection

**Files:**
- Create: `src/astock_quant/desktop/weekly_trend_facade.py`
- Test: `tests/unit/desktop/test_weekly_trend_facade.py`
- Test: `tests/integration/test_desktop_weekly_trend_run.py`

**Interfaces:**
- Consumes: legacy frames, `DesktopBacktestOptions`, `LegacyDataAdapter`, `WeeklyTrendService`, `v8_state` and `v8_runs` roots.
- Produces: `DesktopBacktestOptions`, `DesktopRunSummary`, `DesktopRunError`, `WeeklyTrendFacade.run(...)`, `open_last_result()`, and `export_audit_bundle(...)`.

- [ ] **Step 1: Write failing path-isolation and summary tests**

```python
def test_facade_writes_only_v8_roots(tmp_path, legacy_frames):
    facade = WeeklyTrendFacade(app_dir=tmp_path, app_version="8.0.0")
    result = facade.run(legacy_frames, DesktopBacktestOptions.defaults())
    assert result.run_dir.is_relative_to(tmp_path / "v8_runs")
    assert (tmp_path / "v8_state").is_dir()
    assert not (tmp_path / "tail_strategy_state.json").exists()

def test_summary_contains_chinese_metrics_and_audit_counts(completed_run):
    summary = project_desktop_summary(completed_run)
    assert set(summary.metrics) == {"收益", "最大回撤", "交易次数", "胜率", "盈亏因子", "平均仓位"}
    assert summary.data_as_of and summary.error_count >= 0
```

- [ ] **Step 2: Write failing corrupted-last-run and export tests**

```python
def test_corrupt_last_run_is_rejected_with_actionable_chinese_error(tmp_path):
    facade = WeeklyTrendFacade(app_dir=tmp_path, app_version="8.0.0")
    seed_corrupt_complete_run(tmp_path / "v8_runs")
    with pytest.raises(DesktopRunError, match="运行清单.*重新回测"):
        facade.open_last_result()

def test_export_contains_only_selected_run_artifacts(completed_facade, tmp_path):
    bundle = completed_facade.export_audit_bundle(tmp_path / "audit.zip")
    assert zip_names(bundle) == EXPECTED_AUDIT_FILES
```

- [ ] **Step 3: Run and verify the facade is absent**

Run: `python -m pytest tests/unit/desktop/test_weekly_trend_facade.py tests/integration/test_desktop_weekly_trend_run.py -q`

Expected: collection fails because `weekly_trend_facade` does not exist.

- [ ] **Step 4: Implement desktop DTOs and fault translation**

```python
@dataclass(frozen=True)
class DesktopBacktestOptions:
    start: date
    end: date
    adjustment_basis: str
    initial_cash: Decimal
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_rate: Decimal
    slippage_rate: Decimal

class WeeklyTrendFacade:
    def run(self, frames: Mapping[str, pd.DataFrame], options: DesktopBacktestOptions,
            progress: Callable[[int, str], None] | None = None) -> DesktopRunSummary: ...
    def open_last_result(self) -> DesktopRunSummary: ...
    def export_audit_bundle(self, destination: Path) -> Path: ...
```

Use only `app_dir / "v8_state"` and `app_dir / "v8_runs"`. Translate data, configuration, state, reconciliation and I/O failures into `DesktopRunError(stage, scope, message_zh, suggestion_zh)` while retaining exception chaining for logs.

- [ ] **Step 5: Run focused and full tests, then commit**

Run: `python -m pytest tests/unit/desktop tests/integration/test_desktop_weekly_trend_run.py -q && python -m pytest -q && python -m compileall -q src tests && git diff --check`

```bash
git add src/astock_quant/desktop tests/unit/desktop tests/integration/test_desktop_weekly_trend_run.py docs/development-progress.md
git commit -m "feat: expose weekly strategy to desktop"
```

### Task 7: Add the opt-in Windows page with import fault isolation

**Files:**
- Create: `windows_app/weekly_trend_page.py`
- Modify: `windows_app/main.py:1-70, MainWindow.__init__`
- Modify: `windows_app/test_tail_strategy.py`
- Create: `tests/contracts/test_windows_weekly_page.py`

**Interfaces:**
- Consumes: `WeeklyTrendFacade`, `DesktopBacktestOptions`, existing v7 cache-loading functions and PySide6 widgets.
- Produces: `WeeklyTrendPage`, `UnavailableWeeklyTrendPage`, `create_weekly_trend_page(app_dir)`, and one menu/page pair after “尾盘两日短线”.

- [ ] **Step 1: Write failing headless menu/order/default and no-order-button tests**

```python
def test_main_window_adds_weekly_page_after_tail_without_changing_default(headless_qt):
    module = load_windows_main(headless_qt)
    window = module.MainWindow()
    assert module.APP_VERSION == "8.0.0"
    assert window.menu.items[:8] == V763_MENU_PREFIX
    assert window.menu.items[8] == "周线趋势确认"
    assert window.menu.items[9] == "风险控制"
    assert window.menu.current_row == 0

def test_weekly_page_has_no_real_order_action(headless_qt):
    page = load_weekly_page(headless_qt).WeeklyTrendPage(fake_facade())
    assert {b.text for b in page.buttons} == {"运行回测", "打开上次结果", "导出审计包"}
```

- [ ] **Step 2: Write failing import-failure and per-symbol-error tests**

```python
def test_v8_import_failure_preserves_legacy_pages(headless_qt, monkeypatch):
    monkeypatch.setattr(builtins, "__import__", reject_astock_quant_import)
    module = load_windows_main(headless_qt)
    window = module.MainWindow()
    assert len(window.pages.widgets) == 10
    assert "v8 内核加载失败" in window.weekly_trend.status.text
    assert window.tail_strategy is not None

def test_symbol_errors_are_shown_without_marking_batch_failed(page_with_partial_result):
    page_with_partial_result.load_summary(PARTIAL_SUMMARY)
    assert page_with_partial_result.metrics["错误数"].text == "1"
    assert "600001" in page_with_partial_result.error_table.cell_texts
```

- [ ] **Step 3: Run and verify the page/integration is absent**

Run: `python -m pytest tests/contracts/test_windows_weekly_page.py -q && python -m unittest windows_app.test_tail_strategy.TailUiContractTests -q`

Expected: contract fails because `weekly_trend_page.py` and the new menu entry do not exist; legacy test still passes.

- [ ] **Step 4: Implement the page as a thin UI shell**

```python
def create_weekly_trend_page(app_dir: Path) -> QWidget:
    try:
        from astock_quant.desktop.weekly_trend_facade import WeeklyTrendFacade
        return WeeklyTrendPage(WeeklyTrendFacade(app_dir=app_dir, app_version=APP_VERSION))
    except Exception as exc:
        return UnavailableWeeklyTrendPage.from_exception(exc)
```

The page provides date range, adjustment basis, initial cash, commission, stamp tax and slippage inputs; run/open/export buttons; progress and data-as-of labels; six metric cards; signals/orders/trades/unfilled/checks/errors tabs; and the fixed warning “研究/模拟用途，不连接真实券商”. A `QThread` calls the facade and emits DTOs only. `MainWindow` inserts exactly one menu item and page after the tail page, under a guarded import.

- [ ] **Step 5: Run legacy, headless UI and full tests**

Run:

```bash
python -m pytest tests/contracts/test_windows_weekly_page.py -q
python -m unittest discover -s windows_app -p 'test_*.py' -q
python -m pytest -q
python -m compileall -q src tests windows_app
git diff --check
```

Expected: UI contracts pass without PySide6 installed; v7 still reports 63 tests and `OK`; full v8 suite passes.

- [ ] **Step 6: Commit and checkpoint**

```bash
git add windows_app/main.py windows_app/weekly_trend_page.py windows_app/test_tail_strategy.py tests/contracts/test_windows_weekly_page.py docs/development-progress.md
git commit -m "feat: add weekly trend Windows page"
```

### Task 8: Build and verify the clean Windows v8.0 release ZIP

**Files:**
- Create: `scripts/build_windows_release.py`
- Create: `scripts/verify_release.py`
- Create: `tests/contracts/test_windows_release.py`
- Create: `windows_app/3_双击_离线自检.bat`
- Create: `windows_app/test_v8_offline.py`
- Modify: `windows_app/requirements.txt`
- Modify: `windows_app/1_第一次双击_安装并打开.bat`
- Modify: `windows_app/2_以后双击_启动软件.bat`
- Create: `windows_app/V8.0_周线趋势确认说明.txt`
- Create: `windows_app/只看这里_v8.0_两步打开.txt`
- Create: `docs/v8-windows-release-verification.md`

**Interfaces:**
- Consumes: `windows_app`, built `astock_quant` package sources, approved inclusion manifest and forbidden-name rules.
- Produces: `build_release(repo_root: Path, destination: Path) -> ReleaseReport` and `AStockQuant_v8_0_周线趋势确认_双击版.zip`.

- [ ] **Step 1: Write failing root-layout, version and privacy tests**

```python
def test_release_is_flat_runnable_and_v8(release_zip):
    names = zip_names(release_zip)
    assert "main.py" in names
    assert "1_第一次双击_安装并打开.bat" in names
    assert "astock_quant/__init__.py" in names
    assert not any(name.startswith("AStockQuant_v8_0/") for name in names)
    assert 'APP_VERSION = "8.0.0"' in zip_text(release_zip, "main.py")

def test_release_excludes_all_runtime_and_personal_data(release_zip):
    forbidden = {"cache", "tail_strategy_cache", "tail_strategy_state.json", "paper_account.json",
                 "research_sample.json", "validation_snapshot_v1.json.gz", "v8_state", "v8_runs", ".venv"}
    assert not {part for name in zip_names(release_zip) for part in PurePosixPath(name).parts} & forbidden
```

- [ ] **Step 2: Write failing launcher and dependency tests**

```python
def test_launchers_install_and_run_from_their_own_directory(release_zip):
    install = zip_text(release_zip, "1_第一次双击_安装并打开.bat")
    daily = zip_text(release_zip, "2_以后双击_启动软件.bat")
    assert 'cd /d "%~dp0"' in install and 'pip install -r requirements.txt' in install
    assert 'pythonw.exe" main.py' in install and 'pythonw.exe" main.py' in daily
    assert "astock-quant" not in zip_text(release_zip, "requirements.txt")
```

- [ ] **Step 3: Run and verify the builder is absent**

Run: `python -m pytest tests/contracts/test_windows_release.py -q`

Expected: collection fails because `scripts.build_windows_release` does not exist.

- [ ] **Step 4: Implement a manifest-driven clean builder**

```python
def build_release(repo_root: Path, destination: Path) -> ReleaseReport:
    with tempfile.TemporaryDirectory(prefix="astock-v8-release-") as raw:
        stage = Path(raw)
        copy_manifest(repo_root / "windows_app", stage, WINDOWS_PROGRAM_FILES)
        copy_package(repo_root / "src" / "astock_quant", stage / "astock_quant")
        assert_no_forbidden_paths(stage, FORBIDDEN_RELEASE_PARTS)
        run_offline_gate(stage)
        write_reproducible_zip(stage, destination)
    return inspect_release(destination)
```

The builder never copies directory globs from the workspace root. It includes explicit program/docs files and Python package files, strips `__pycache__`/`.pyc`, normalizes ZIP paths and timestamps, and refuses an existing destination unless its SHA-256 is identical.

- [ ] **Step 5: Update version, launchers, requirements and Chinese instructions**

Set the title and `APP_VERSION` to `8.0.0`. Keep the existing two-click flow. Add a third optional launcher that runs all three packaged offline test files. The instructions explicitly say to copy files into `C:\AStockQuant`, replace program files, and never delete the seven old/v8 data paths. They also state that the new page is opt-in and does not place real orders.

```python
# windows_app/main.py
APP_VERSION = "8.0.0"
self.setWindowTitle("股个人量化交易系统 v8.0.0")
```

```bat
rem windows_app/3_双击_离线自检.bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" -m unittest test_execution.py test_tail_strategy.py test_v8_offline.py -q
if errorlevel 1 (pause & exit /b 1)
echo 离线自检通过
pause
```

```text
# windows_app/requirements.txt
PySide6>=6.8
pyqtgraph>=0.13
pandas>=2.2.3
numpy>=2.0
requests>=2.32
akshare>=1.17
baostock>=0.8.9
```

- [ ] **Step 6: Build, re-extract and run the entire clean-room gate**

Run:

```bash
python scripts/build_windows_release.py --output dist/AStockQuant_v8_0_周线趋势确认_双击版.zip
python -m pytest tests/contracts/test_windows_release.py -q
python scripts/verify_release.py dist/AStockQuant_v8_0_周线趋势确认_双击版.zip
python -m pytest -q
python -m compileall -q src tests windows_app
git diff --check
git status --short
```

`verify_release.py` extracts to a new temporary directory, runs the two v7 unittest files and packaged v8 tests/contracts, compiles packaged Python, checks root launchers/version/privacy, and compares the ZIP SHA-256 before/after. Expected: all gates pass, v7 reports 63 tests and `OK`, and no forbidden file is present.

- [ ] **Step 7: Record evidence and commit the release sources**

Write the exact platform, Python version, commands, test counts, archive member count, archive SHA-256, v7 baseline hash and the Windows GUI limitation to `docs/v8-windows-release-verification.md`.

```bash
git add scripts/build_windows_release.py scripts/verify_release.py tests/contracts/test_windows_release.py windows_app/requirements.txt windows_app/*.bat windows_app/test_v8_offline.py windows_app/V8.0_周线趋势确认说明.txt windows_app/只看这里_v8.0_两步打开.txt docs/v8-windows-release-verification.md docs/development-progress.md
git commit -m "build: package AStockQuant v8 Windows release"
```

- [ ] **Step 8: Sync the final commit and preserve the artifact**

Sync the final branch checkpoint to GitHub `Traveller06/AStockQuant` branch `codex/v8-phase1`. Save the verified ZIP as the durable user-facing artifact, and report both its SHA-256 and the exact Git commit. Do not create a release tag until the user confirms the Windows machine smoke test.
