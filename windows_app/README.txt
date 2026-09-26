AStockQuant v8.2.0 - 9月8日规则1三级选股

默认进入周线趋势确认页面的9月8日规则1三级筛选：预确认（周线候选有效，待日线触发）、确认（MA5/MA20和阳包阴）、强确认（同日放量）。筛选只读取现有 cache 股票池，显示实际截止日并独立保存及导出；v8.1 周线筛选仍可切换使用。

AStockQuant v8.1.0 - 周线趋势确认选股

周线趋势确认页面新增「筛选本地股票池」：依据已有前复权日线对缓存中的股票逐只筛选，
显示当日确认与等待确认、股票代码和简称、行情截止日期及规则检查。可保存最近一次筛选并
导出全部股票状态 CSV。缓存缺失或过期的股票不会作为当期信号；旧版策略保持原样。
详细步骤请看「只看这里_v8.1_两步打开.txt」。本版不连接真实券商。

AStockQuant v7.6.3 - 空分钟缓存回测热修

V7.6.3修复“更新分钟并回测”遇到无分钟记录股票时出现 RangeIndex 没有 normalize
方法的问题。空分钟缓存现在与正常缓存统一使用日期时间索引；缺少14:55可成交分钟的
股票会写入错误审计并跳过，其他候选继续回测。v7.6.2已成功取得的全市场行情、筛选
快照、日线和分钟缓存全部保留，策略与费用规则没有改变。

AStockQuant v7.6.2 - 尾盘实时行情多源热修

V7.6.2修复两个已复现问题：东方财富把单页限制为100条时继续按真实总数翻页，不再把
100只误认为全市场；两个东方财富地址都断开或返回数量不完整时，自动读取现有全市场
股票池并分批切换到腾讯实时行情。腾讯备用字段包括最新价、涨跌幅、成交量、振幅、
换手率和流通市值，仍使用原有13项筛选。历史数据、尾盘缓存和买卖规则没有改变。

AStockQuant v7.6.1 - 尾盘行情代理热修

V7.6.1修复尾盘模块首次扫描时可能出现的 ProxyError。全市场实时快照和近期1分钟K线
改为东方财富直连，并明确关闭 Windows/系统代理继承；两个入口各自保留备用域名。筛选、
买卖、费用、持仓和缓存规则没有变化，已有cache、research_sample.json、
tail_strategy_cache与tail_strategy_state.json会继续复用。

AStockQuant v7.6 - 尾盘两日短线独立策略

V7.6完整保留v7.5全部策略和数据，在左侧新增“尾盘两日短线”。策略只允许沪深主板，
排除ST、退市、北交所、创业板和科创板；14:30后扫描、14:50冻结候选，14:55—14:56
使用首个可成交1分钟价格。筛选严格执行股价、流通市值、MA10、6/20/30/60日涨幅、
今日涨幅/振幅/换手率、今日量、周量及10日无涨停条件，并按今日涨幅降序排列。

默认每天前5只、80%总仓位等权、单只不超过20%、100股整数手。买入日不卖，T+1开始：
达到+5%后启动0.3%移动止盈，-5%止损，最迟T+2尾盘退出；停牌或跌停无法成交时如实
记录并顺延。回测计入佣金、最低佣金、印花税和滑点，同一分钟冲突采用保守路径。

新数据永久保存在tail_strategy_cache，模拟状态保存在tail_strategy_state.json。软件升级时
保留这两个位置即可继续增量更新，不会重新下载已有原始数据。免费1分钟接口只提供近期
数据，因此“分钟精确回测”只使用实际缓存；更早数据可在数据管理页导入标准分钟CSV，
绝不把日线近似结果混入分钟精确结果。一键核实包不会包含paper_account.json等账户资料。

本模块只做研究和本地模拟，不连接券商，不自动下单，也不保证未来收益。

AStockQuant v7.5 - WorldQuant-inspired factor ranking and four-rule comparison

V7.5 keeps the strict 300-stock local history and all execution/risk assumptions unchanged.
It adds a fourth entry plan named "4 世坤因子". Six causal OHLCV-only components are
ranked cross-sectionally each day: 20-day momentum, 5-day reversal, 10-day price-volume
correlation, 20-day range position, 20-day low volatility and 5-day volume impulse. The
composite changes only the ordering of simultaneous Rule-1 candidates; it does not silently
change the weekly setup, stop, position limits, fees, slippage or exit rule.

Every validation now compares Rules 1, 2, 3 and the factor plan on the same frozen data and
exports both the comparison summary and annual matrix. The five CSI-300 ETF sleeves reuse the
already-calculated stock curve, avoiding five duplicate stock simulations per period. Raw
history remains in cache, while a completed v7.5 result is saved in validation_snapshot_v1.json.gz
and can be reopened directly while its sample, cache, parameters and engine version are unchanged.

This is a research comparison, not an automatic replacement of Rule 1 and not a return guarantee.
Paper trading remains paused.

AStockQuant v7.3 - Strict sample transfer and restored entry timing

V7.3 restores the user-confirmed entry rule as the default: after the weekly
trend setup is active, a close above MA5 and MA20 plus a bullish engulfing day
creates a Buy Watch signal; same-day volume above the preceding five-day
average upgrades it to Strong Confirmation. Both are executed at the next
session open in backtests. Rule 2 requires same-day volume. Rule 3 accepts a
three-session timing window but fires only after both facts have actually been
observed, so it does not read future bars. Entry timing is independent from the
older entry-quality profiles and is not automatically selected from history.

Strict-300 mode verifies the same immutable universe at every stage: 300 unique
input codes, 300 qualified prepared members, 300 local-cache loads, 300 signal
frames and 300 data-quality rows. A mismatch aborts with missing codes instead
of silently producing a 299-stock result. Strict validation reads the prepared
local cache and uses a shared data cut-off date. It does not silently refresh
individual stocks during validation.

The validation page now displays live percent, current stage and elapsed time.
Each run records a run id, app version, entry rule, sample SHA-256, parameters,
common data cut-off, stage counts and errors. Export adds the manifest JSON,
daily ledger (including stock cash and position count), index events and error
list to the existing trade, annual, rolling, benchmark and data-quality files.
This version does not connect to a broker or guarantee the 2%-5% annual-return
research target.

Windows upgrade (keep existing data):
1. Close the application and stop the old Python process.
2. Back up C:\AStockQuant, especially cache, research_sample.json,
   research_data_checkpoint.json, watchlist.json and paper_account.json.
3. Extract this package into C:\AStockQuant and replace program files. Do not
   delete the cache directory or the JSON data files above.
4. Open Command Prompt and run:
     cd /d C:\AStockQuant
     call .venv\Scripts\activate
     python -m pip install -r requirements.txt
     python main.py
   After dependencies are installed, run.bat is an equivalent launcher.
5. In Research Sample & Data Preparation, finish a qualified 300-stock sample.
   Then open Bull/Bear Dual Engine, keep Entry Rule = 1 Recommended and Sample =
   Strict 300, and run v7.3 validation.

Offline check:
  python test_execution.py

AStockQuant v7.2 - Effective-sample completion and reserve queue

V7.2 changes the 300-symbol acceptance rule from "300 attempted" to "300 with
valid history". It preserves every previously successful symbol, retries the
missing members through the v7.1 multi-provider chain, and then continues into
a deterministic reserve queue drawn from the current cleaned A-share universe
until 300 valid histories have been collected. Each result is labelled as an
original sample member, automatic replacement, or replacement candidate.

Beijing Exchange failures no longer trigger the generic eight-consecutive-
failure circuit breaker, because the 920 code migration can create a localized
provider-compatibility cluster. Non-BSE consecutive failures still trigger the
protective pause. Old v7.1 checkpoints with the same mode/year are migrated by
preserving their successful rows and rebuilding only the remaining queue.

The 300-symbol progress bar now reports valid/target, not attempted/total. A
result is marked complete only at 300 valid symbols. Full-market mode behaves
differently by design: it never hides unavailable securities with replacements;
it records the complete missing list and marks the result unqualified if the
provider chain cannot cover the whole cleaned universe. No strategy, risk,
execution, fee, or validation parameter changed.

AStockQuant v7.1 - Multi-provider full-market data preparation

V7.1 expands the acquisition chain to three independent providers plus one
compatibility route: local cache, Tencent, direct Eastmoney, AKShare, and
BaoStock for Shanghai/Shenzhen securities. All accepted data is normalized to
the same date/open/close/high/low/volume schema and saved to the existing cache.
The selected provider is recorded for every successful symbol.

The direct Eastmoney route uses current 920-prefixed Beijing Exchange codes;
this addresses the 2025 BSE code migration that older wrapper routes may not
yet map consistently. BaoStock is deliberately limited to Shanghai/Shenzhen
fallback rather than silently mixing an unsupported Beijing code. Successful
symbols are preserved, failed symbols remain eligible on the next continuation
run, and both 300-symbol and full-market modes retain atomic per-symbol
checkpoints. The live table is capped at 500 visible rows for responsiveness;
the complete result remains in the checkpoint/sample files. No strategy or
backtest parameter changed.

AStockQuant v7.0.2 - Throttled retry and dual-source recovery

V7.0.2 addresses bulk historical-download failures caused by repeated 501 and
similar server responses. Tencent requests now use a browser referer, bounded
random pacing and up to three attempts with 2/5-second exponential-style
backoff. If the primary source still fails, the worker automatically switches
to the AKShare/Eastmoney historical interface.

An existing completed research sample is reused: successful symbols remain
untouched and only missing or previously failed symbols are requested. The UI
shows the active source, HTTP request count, retry count and consecutive
failures in real time. If eight consecutive symbols fail through both sources,
the task saves a checkpoint and pauses automatically instead of rapidly
marking the entire sample failed. Full primary and backup errors are retained
in the result table. No strategy or backtest parameter changed.

AStockQuant v7.0.1 - Live progress and restart recovery

V7.0.1 fixes the case where a paused preparation task looked empty after the
application was restarted. At launch, the data-preparation page now reads the
saved checkpoint and restores the completed/total count, success, failure,
cache count, next symbol, progress bar, and up to the latest 100 result rows.

Clicking Start with the same sample mode and start year automatically resumes
the checkpoint; Continue remains available as an explicit action. The worker
now reports its current phase before universe retrieval, cache inspection, and
historical-price loading. A one-second running timer remains active while a
network request is waiting, so an unchanged symbol no longer looks like a dead
process. Pause still takes effect after the current request finishes. No
strategy, selection, fee, or execution assumption changed in this hotfix.

AStockQuant v7.0 - Research sample and data preparation center

V7.0 separates historical-data preparation from strategy validation. The new
page offers a 50-stock smoke-test set, a deterministic 300-stock board-rotated
research sample, and the current full A-share universe. It displays processed
and total symbols, successful and failed symbols, cache reuse, the current
symbol, percentage and estimated remaining time.

The worker saves a checkpoint after every symbol. Pause finishes the current
network request and then saves; Continue resumes from the next symbol. Recent
complete cache files are reused. A completed sample is saved locally and up to
500 successful codes are copied into the dual-engine validation pool. Full
market preparation is supported, but one validation run is limited to 500
stocks to control runtime and data-source pressure.

The 300-stock sample rotates across Shanghai main board, Shenzhen main board,
ChiNext, STAR and Beijing groups. This broadens coverage but does not remove
survivorship bias because the source is still today's listed universe. Paper
trading remains disabled. No strategy parameters changed in this release.

AStockQuant v6.9 - Bull/bear dual-engine stability validation

V6.9 keeps the audited stock strategy fixed (original entry/exit, R0.8/P20,
maximum eight stocks) and compares only five predeclared index sleeves: 0%,
10%, 20%, 30% and 40%. The index sleeve uses real 510300 adjusted history and
only unused cash. Its market regime uses the previous trading day's CSI 300
close, MA50, MA200 and momentum, so the current day cannot select itself.

The user's 2%-5% annual-return range and annual loss no worse than -1% are
reference acceptance goals, not guaranteed targets. Historical qualification
also requires at least two thirds of years positive. Ranking protects the worst
year first, then positive-year count, closeness to the reference range, median
return and drawdown. If no plan qualifies, the UI says "未达标，历史候选" rather
than claiming success. Rolling tests use only earlier years to choose the next
year's plan. The 2024-current period remains research replay and does not tune
the selection. Paper trading remains disabled.

AStockQuant v6.8.1 - Research credibility audit hotfix

Hotfix: v6.8 created the raw-history audit dictionary too late. Every stock
therefore raised an internal name error and the UI only reported that all
stocks failed. V6.8.1 initializes the dictionary before the load loop and shows
the first five real per-stock errors if a future complete load failure occurs.
No strategy parameters or backtest rules changed.

AStockQuant v6.8 - Research credibility and benchmark audit

This release is an audit release, not a strategy-optimization release. It
keeps v6.7 assumptions fixed and makes the fallback explicit: if no entry
profile passes the historical rule (at least four of six positive years and no
annual drawdown below -10%), the UI shows “无合格，回退原始” and does not call
that profile historically selected.

The new benchmark audit compares strategy returns with cash, CSI 300 and a
current-sample equal-weight diagnostic index. The equal-weight line normalizes
each available stock from its first available date and is not an executable
shared-cash portfolio; because the list contains today’s symbols, it has
survivorship bias. A data-quality audit reports date duplicates, missing and
non-positive fields, OHLC contradictions, large jumps, gaps versus the index,
and suspicious one-price-limit bars. These checks do not prove fills.

Exports now include `_benchmark_audit.csv` and `_data_quality.csv`. Paper
trading remains disabled and no result guarantees future returns.

AStockQuant v6.7 - Annual stability and rolling validation

This release keeps the v6.6 entry profiles and every trading assumption fixed.
It replaces three two-year blocks with independent calendar-year tests from
2018 through 2023. A profile qualifies only when at least four of six years are
positive and no yearly drawdown is worse than 10 percent.

The rolling audit selects a profile using only years before each test year,
then reports the next year's result. For example, the 2022 row can use results
through 2021 but cannot use 2022. The 2024-current period remains research
replay and never participates in selection. Exports add the complete annual
matrix and rolling audit. Paper trading remains disabled. No result guarantees
future returns. Eight offline point-in-time/execution tests and syntax checks
passed; full Windows GUI and live-data results require local verification.

AStockQuant v6.6 - Entry-signal quality validation

This release fixes the original exit rule, R0.8/P20, maximum 8 positions and
costs. It compares the original entry with five pre-declared filters: positive
60-day relative strength versus CSI 300, positive 10-day MA20 slope, volume
ratio at least 1.2, and quality scores at least 2 or 3. The four-point score is
RS60, MA20 slope, within 2% of the prior 20-day high, and volume confirmation.
All feature values are frozen on the signal date and exported with each trade.

The UI attributes the original-entry trades by quality score and by pass/fail
feature groups. Selection uses 2018-2023 only; 2024 onward remains research
replay and does not select a filter. Paper trading remains disabled. No filter
is guaranteed to improve future returns. Eight offline synthetic execution and
point-in-time tests passed; the Windows GUI and live historical data still need
local verification.

AStockQuant v6.5 - Exit-rule and profit-giveback validation

This release keeps entry logic, R0.8/P20, maximum 8 positions and costs fixed.
It compares five exit rules: original, close below 10-week average, two-week
confirmation, 5-week average downturn, and daily close below MA20. Selection
uses 2018-2023 segments only. Results from 2024 onward are labeled research
replay and never select the rule.

The trade audit adds MFE, MAE and profit giveback. Stock attribution groups
trade count, winners, net P&L, mean return, holding time, MFE and giveback.
No exit rule is guaranteed to improve future performance. Paper trading stays
disabled. All v6.4 execution fixes and limitations below still apply.

AStockQuant v6.4 - Execution audit

This release freezes R0.8/P20, maximum 8 positions, for research diagnostics.
Use the sixth navigation page. Paper trading remains disabled.
Fixes in the shared portfolio engine:
- Opening size uses opening marks, not the same day's closing prices.
- No purchase-day stop sale. Final-day new holdings remain marked to market.
- Invalid initial stops are rejected. Incomplete trailing weeks are excluded.
- Drawdown includes initial capital; annual returns include year transitions.
- Trade audit shows net P&L, net return, calendar holding days, initial stop
  distance, exit reason and purchase-day sale checks. Exports include trades.

IMPORTANT LIMITATIONS:
2024 onward has repeatedly informed development; it is research replay, not
an untouched holdout. Old performance figures are not validated targets.
No profitability guarantee. Only six offline synthetic execution tests and
syntax checks were run here; Windows GUI/live history require local testing.
Daily bars do not model suspended/limit-locked execution, order liquidity or
all exchange-specific lots. Fees retain simplified constant historical rates.
Current stock selection and hardcoded industry mapping may introduce bias.
Price adjustment consistency still requires data-source audit. Holiday-short
weeks at a dataset endpoint may be skipped conservatively. Old single-stock
and legacy research code has not received a complete correctness audit.
Do not use this release for real orders or treat backtest gains as verified.

Install: close the old app, BACK UP C:\AStockQuant\main.py, then extract the
package files into C:\AStockQuant. Keep your cache and account files intact.
Run: python main.py
Optional offline checks: python test_execution.py

The following older changelog is historical, not a current validation claim:

Close the previous version, then extract main.py, run.bat and README.txt directly into C:\AStockQuant.
Choose Replace when Windows asks about main.py, then run: python main.py

The application computes weekly trend, volume, daily confirmation, bullish
engulfing, MACD, KDJ, stop-loss reference and trend-following exit signals.
Signals are research prompts only. They are not guarantees or automatic orders.

V4 adds configurable historical backtesting, next-session execution, A-share
100-share lots, commission/minimum fee, sell-side stamp duty, slippage, stop
loss, trend exit, equity curve, drawdown, win rate and trade details.
V4.1 fixes signal timing: a qualified weekly setup remains active for up to
20 trading sessions while the engine waits for a later daily confirmation.
V4.2 adds a signal funnel and buy-and-hold benchmark curve, and uses the nearer
weekly support line for pullback detection during a bullish trend.
V4.3 uses the selected entry rule: after the weekly bullish prerequisite,
MA5/MA20 plus bullish engulfing triggers an entry observation; same-day volume
upgrades it to a strong confirmation but is not a hard entry requirement.
V5 adds segmented history downloads from 2018, batch comparison of observation
and strong-confirmation modes, equal-weight summaries, abnormal-jump flags,
buy-and-hold comparison, CSV export and stop reference prices in trade details.
V5.1 adds CSI 300 weekly market-regime filtering, 0.8% account-risk sizing,
a 20% default single-stock cap, upward-only trailing stops, gap-stop labeling,
MAE/MFE and holding-day audits, and out-of-sample validation from 2024 by
default. Strategy returns and buy-and-hold returns now use separate charts.

V5.2 compares market filtering OFF, SOFT (index above 20-week average), and
STRICT (5/10/20-week bullish alignment plus rising 20-week average) on exactly
the same out-of-sample period. Each stock produces six combinations across the
three market modes and the two entry modes. The result table exposes raw weekly
candidates, market-blocked candidates, daily confirmations and final trades.
Strategy and benchmark charts are separated and the strategy chart includes a
three-mode legend.

Important: v6.3 is a research and backtesting tool. Positive historical returns
are not guaranteed and the application still does not connect to a broker or
place orders.

V5.2.1 fixes the funnel date-scope mismatch: raw candidates, blocked candidates,
daily confirmations and final trades are all counted only inside the selected
out-of-sample period. It adds winning/losing trade counts, weighted average win
and loss, a profit-concentration warning, and a button that loads a diversified
50-stock research sample. The 50-stock preset is a convenience sample, not a
historically reconstructed index constituent list, so it must not be treated as
proof against survivorship bias.

V5.3 adds a true shared-capital portfolio backtest. All stocks share one account,
signals are ranked and executed on one calendar, and the engine enforces at most
5 concurrent positions, 20% per stock, 80% total exposure, 0.8% account risk per
trade, and at most 2 mapped stocks per broad industry. It reports CAGR, Sharpe,
drawdown, profit factor, capital utilization and calendar-year returns. Signals
are precomputed once per stock and recent local history caches are reused, which
substantially reduces repeated work. The bundled industry map covers the 50-stock
sample; unknown user-added codes receive independent "other" groups and require
manual industry review.

V5.4 adds a normalized CSI 300 benchmark, a daily portfolio-exposure chart,
readable calendar-year returns, per-stock P&L and exit-reason attribution,
fixed-baseline validation for 2020-2021, 2022-2023 and 2024-current, and a six-cell
experiment matrix comparing 20/30/40-day setup windows with 5/8 maximum holdings.
The experiment matrix keeps the entry rule, risk per trade and market-filter mode
fixed so that only the named parameters change. Four CSV files are produced by
the export action: summary, trades, experiments and validation segments.

V5.5 adds benchmark and excess returns to every portfolio and segment, tests all
six 20/30/40-day by 5/8-holding parameter pairs in the 2020-2021 training period,
2022-2023 validation period and 2024-current forward-observation period, and
ranks parameter stability using only the two earlier periods. It also separates
top-10 contributors and bottom-10 detractors, summarizes P&L by exit reason,
auto-sizes result columns, and exports rolling robustness and stability tables.
The 2024-current period is explicitly labeled forward observation because its
results have already been viewed and therefore are no longer untouched data.

V5.5.1 fixes low-contrast result tabs on Windows. Inactive tabs now use a dark
blue background with bright text, the active tab uses a solid blue highlight,
and hover, border, spacing and minimum-width rules improve readability. No
strategy, data, cost, risk or backtest calculation has changed from V5.5.

V5.6 enables the local paper-trading page. It scans the selected stock pool,
uses Tencent quotes when available and falls back to the latest cached close,
shows weekly candidates, MA5/MA20, bullish engulfing, volume, stop references
and entry grades, and requires manual confirmation before every simulated buy
or sell. The account enforces 0.8% risk per trade, 20% per stock, 80% total
exposure, at most five positions and at most two mapped stocks per industry.
Cash, holdings and transaction history are saved in paper_account.json so they
remain after the application closes. Stop and weekly-exit conditions create
alerts only; they never place an automatic order.

V5.6 remains fully disconnected from Guotai Haitong and every other broker.
Paper fills, fees, stamp duty and slippage are simulations, not executable
orders or guarantees of real-market fills.

V5.7 adds an automatically maintained Shanghai, Shenzhen and Beijing A-share
universe. The list is cached for one day and excludes names containing ST or
delisting markers. Full-market scans process quotes in batches of 40, use local
price-history caches, reject securities with fewer than 120 trading sessions,
show progress, and save a restart checkpoint after every batch. The user can
pause safely and continue the unfinished scan after reopening the application.
To keep the interface responsive, the result table retains qualified weekly
candidates and held securities instead of thousands of no-signal rows.

The first full-market scan can take a long time because every eligible symbol
needs sufficient weekly and daily history. Keep the computer awake while it is
running, or use Pause Scan before closing the application. Later runs reuse the
local cache and are substantially faster. If a live market-list source is
temporarily unavailable, the most recently saved universe is used when possible.

V5.8 pauses the paper-trading entry and makes strategy enhancement the sixth
research page. Existing paper_account.json data is preserved but is not loaded,
changed or traded by this version. The enhanced engine adds 60/120-day relative
strength against CSI 300, a cross-sectional liquidity filter, ATR-based initial
and trailing stops, breakeven protection after one unit of risk, a 30-session
time stop, and market-regime exposure caps of 30%, 60% and 80%.

The enhanced page compares the unchanged V5.5 baseline with the enhanced engine
on the 2024-current forward-observation period. It selects among 5, 8 and 10
maximum holdings using only the 2020-2021 and 2022-2023 historical segments, and
shows the selected configuration's segmented results, diagnostic funnel, trade
audit, benchmark return and excess return. This is an anti-overfitting research
workflow, not a promise that the enhanced result or future return will be positive.

V5.9 retires the underperforming V5.8 enhanced entry and ATR exit from the active
research page. It restores the original strategy with eight maximum holdings as
the fixed stock baseline, then uses only otherwise idle cash for a CSI 300 trend
overlay. The overlay uses the prior session's close, 50/200-day averages and
20/60-day momentum, so today's market return cannot determine today's position.

Index limits of 0%, 20%, 40% and 60% are selected only from the 2020-2021 training
and 2022-2023 validation segments. The 2024-current forward-observation period
is checked against four explicit gates: positive return, return above the stock
baseline, daily profit factor above one and drawdown no worse than -12%. The CSI
300 series is an index research proxy, not a directly tradable ETF fill record;
real deployment would require a separate ETF-data and execution-cost validation.

V6.0 replaces the index-return proxy with the actual 510300 front-adjusted price
series. ETF allocation changes include 0.03% commission, a CNY 5 minimum fee and
0.05% slippage. Shanghai/Shenzhen 300 remains the market-state signal, while the
next session's 510300 return is used for the tradable sleeve.

Historical selection now compares 0%, 10%, 20% and 30% ETF caps over three fixed
periods: 2018-2019, 2020-2021 and 2022-2023. Ranking uses positive-period count,
worst return, median return and worst drawdown in that order. The best 2024-current
result is shown only as an observed comparison and cannot become the selected
configuration. V6.0 also forces an explicit chart range to fix the blank equity
chart seen in V5.9.

V6.0.1 fixes Shanghai ETF symbol routing. Codes beginning with 5, including
510300, are now sent to the Shanghai market endpoint instead of being rejected
as unsupported. No signal, selection, fee, risk or validation rule changed.

V6.1 removes the ETF overlay from the active research workflow because every
non-zero ETF cap reduced the 2018-2023 worst-period return and increased the
historical drawdown. It returns to the original eight-position stock strategy
and compares four market-regime risk profiles without changing entries, exits,
fees or the stock universe.

The fixed profile always permits 80% exposure at 0.8% risk per trade. Gentle,
balanced and defensive profiles reduce new-position exposure and per-trade risk
when the prior day's CSI 300 state is normal or weak. Existing positions are not
force-liquidated solely because the market state changes. The same transaction
profit-factor definition is used for every profile. Selection uses the fixed
2018-2019, 2020-2021 and 2022-2023 periods; 2024-current remains observation only.

V6.2 replaces the symmetric V6.1 defensive profiles with asymmetric weak-market
filters. V6.1 showed that defensive sizing reduced the 2022-2023 loss and
drawdown, but unnecessarily reduced returns in normal and strong markets. The
new candidates are fixed risk, half risk only in weak markets, no new positions
in weak markets, and strong-markets-only. Normal and strong states retain the
original 80% exposure and 0.8% per-trade risk except in strong-markets-only mode.

V6.3 ends the market-filter experiment after V6.2 showed that progressively
stricter filters progressively reduced forward return. It restores the original
unfiltered eight-position strategy and tests risk budgets of 0.8%, 1.0% and
1.2% per trade against 20% and 25% single-stock caps.

A configuration is historically eligible only if at least two of the three
fixed periods are profitable and its worst historical drawdown is no worse than
-10%. Eligible configurations are ranked by historical median return, average
return and worst drawdown. The 2024-current result remains a forward observation;
the gate requires higher return than R0.8/P20, profit factor above one and
drawdown no worse than -10%. Simulation trading remains disabled.
