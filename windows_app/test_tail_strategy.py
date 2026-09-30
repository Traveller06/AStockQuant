import tempfile
import unittest
from datetime import date
from pathlib import Path
import zipfile
import importlib.util
import sys
import types

import numpy as np
import pandas as pd

try:
    from astock_quant_v7_6.tail_strategy import (
        TailCache, create_tail_audit_bundle, entry_fill, evaluate_candidate,
        fetch_tail_minutes, fetch_tail_spot, import_minute_csv, is_main_board, next_trading_sessions,
        normalize_minute_frame, normalize_spot_frame, rank_candidates,
        run_tail_backtest, load_tail_state, save_tail_state, simulate_position,
    )
except ModuleNotFoundError:
    from tail_strategy import (
        TailCache, create_tail_audit_bundle, entry_fill, evaluate_candidate,
        fetch_tail_minutes, fetch_tail_spot, import_minute_csv, is_main_board, next_trading_sessions,
        normalize_minute_frame, normalize_spot_frame, rank_candidates,
        run_tail_backtest, load_tail_state, save_tail_state, simulate_position,
    )


def passing_fixture():
    dates = pd.bdate_range(end="2026-09-11", periods=70)
    close = np.linspace(8.5, 10.0, len(dates))
    daily = pd.DataFrame(
        {
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(len(dates), 100.0),
        },
        index=dates,
    )
    snapshot = {
        "code": "600001",
        "name": "测试股份",
        "timestamp": "2026-09-14 14:50:00",
        "price": 10.5,
        "change_pct": 5.0,
        "amplitude": 4.0,
        "turnover": 5.0,
        "float_market_cap": 10_000_000_000.0,
        "volume": 300.0,
    }
    return snapshot, daily


class TailScreenTests(unittest.TestCase):
    def test_board_filter_rejects_st_chinext_star_and_bse(self):
        self.assertTrue(is_main_board("600001", "测试股份"))
        self.assertTrue(is_main_board("002001", "测试股份"))
        for code, name in (
            ("600001", "ST测试"),
            ("600001", "*ST测试"),
            ("600001", "退市测试"),
            ("300001", "测试"),
            ("688001", "测试"),
            ("920001", "测试"),
        ):
            self.assertFalse(is_main_board(code, name), (code, name))

    def test_passing_fixture_passes_all_filters(self):
        snapshot, daily = passing_fixture()
        result = evaluate_candidate(snapshot, daily)
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(result["code"], "600001")
        self.assertGreater(result["ma10"], 0)
        self.assertGreater(result["today_volume_ratio"], 0.9)
        self.assertGreater(result["week_volume_ratio"], 0.5)

    def test_equal_thresholds_fail_strict_screen(self):
        snapshot, daily = passing_fixture()
        for field, value in (
            ("price", 13.0),
            ("float_market_cap", 20_000_000_000.0),
            ("change_pct", 9.0),
            ("amplitude", 6.0),
            ("turnover", 10.0),
        ):
            changed = dict(snapshot)
            changed[field] = value
            result = evaluate_candidate(changed, daily)
            self.assertFalse(result["passed"], field)

    def test_price_must_be_strictly_above_ma10(self):
        snapshot, daily = passing_fixture()
        snapshot["price"] = float(daily.close.tail(10).mean())
        self.assertFalse(evaluate_candidate(snapshot, daily)["passed"])

    def test_return_thresholds_are_strict(self):
        snapshot, daily = passing_fixture()
        for sessions, threshold in ((6, 7.0), (20, 16.0), (30, 28.0), (60, 100.0)):
            changed = daily.copy()
            changed.iloc[-sessions, changed.columns.get_loc("close")] = snapshot["price"] / (1 + threshold / 100)
            result = evaluate_candidate(snapshot, changed)
            self.assertFalse(result["passed"], sessions)

    def test_volume_thresholds_are_strict(self):
        snapshot, daily = passing_fixture()
        changed = dict(snapshot)
        changed["volume"] = float(daily.volume.iloc[-1]) * 0.9
        self.assertFalse(evaluate_candidate(changed, daily)["passed"])

        changed = dict(snapshot)
        previous_week = float(daily.loc["2026-09-07":"2026-09-11", "volume"].sum())
        changed["volume"] = previous_week * 0.5
        self.assertFalse(evaluate_candidate(changed, daily)["passed"])

    def test_recent_limit_up_is_rejected(self):
        snapshot, daily = passing_fixture()
        changed = daily.copy()
        index = changed.index[-5]
        prior = changed.index[-6]
        changed.loc[index, "close"] = changed.loc[prior, "close"] * 1.098
        self.assertFalse(evaluate_candidate(snapshot, changed)["passed"])

    def test_missing_required_value_is_rejected_with_reason(self):
        snapshot, daily = passing_fixture()
        snapshot["turnover"] = np.nan
        result = evaluate_candidate(snapshot, daily)
        self.assertFalse(result["passed"])
        self.assertTrue(any("缺失" in reason for reason in result["failures"]))

    def test_rank_is_change_then_volume_ratio_then_code(self):
        rows = [
            {"code": "600003", "change_pct": 4.0, "today_volume_ratio": 1.5},
            {"code": "600002", "change_pct": 5.0, "today_volume_ratio": 1.2},
            {"code": "600001", "change_pct": 5.0, "today_volume_ratio": 1.2},
            {"code": "600004", "change_pct": 5.0, "today_volume_ratio": 2.0},
        ]
        self.assertEqual(
            [row["code"] for row in rank_candidates(rows)],
            ["600004", "600001", "600002", "600003"],
        )


def minute_frame(day, rows):
    records = []
    for clock, opened, high, low, close, volume, tradable in rows:
        records.append(
            {
                "time": pd.Timestamp(f"{day} {clock}"),
                "open": opened,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "tradable": tradable,
            }
        )
    return pd.DataFrame(records).set_index("time")


def position(entry_day="2026-09-07", entry_price=10.0):
    return {
        "code": "600001",
        "entry_time": pd.Timestamp(f"{entry_day} 14:55"),
        "entry_price": entry_price,
        "shares": 1000,
        "peak": entry_price,
        "trailing_armed": False,
    }


def costs(slippage=0.0):
    return {"commission": 0.0003, "min_commission": 5.0, "stamp": 0.0005, "slippage": slippage}


class TailExecutionTests(unittest.TestCase):
    def setUp(self):
        self.calendar = pd.to_datetime(["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10"])

    def test_entry_uses_first_traded_bar_at_or_after_1455(self):
        bars = minute_frame(
            "2026-09-07",
            [
                ("14:54", 10.0, 10.0, 10.0, 10.0, 100, True),
                ("14:55", 10.1, 10.1, 10.1, 10.1, 0, True),
                ("14:56", 10.2, 10.2, 10.2, 10.2, 50, True),
            ],
        )
        fill = entry_fill(bars)
        self.assertEqual(fill["time"].strftime("%H:%M"), "14:56")
        self.assertEqual(fill["price"], 10.2)

    def test_entry_does_not_treat_closing_auction_as_continuous_fill(self):
        bars = minute_frame(
            "2026-09-07",
            [
                ("14:57", 10.2, 10.2, 10.2, 10.2, 50, True),
                ("15:00", 10.3, 10.3, 10.3, 10.3, 50, True),
            ],
        )
        self.assertIsNone(entry_fill(bars))

    def test_next_sessions_use_trading_calendar_not_natural_days(self):
        calendar = pd.to_datetime(["2026-09-11", "2026-09-14", "2026-09-15"])
        t1, t2 = next_trading_sessions(calendar, date(2026, 9, 11))
        self.assertEqual(t1, date(2026, 9, 14))
        self.assertEqual(t2, date(2026, 9, 15))

    def test_buy_day_stop_is_ignored_under_t_plus_one(self):
        days = {
            date(2026, 9, 7): minute_frame("2026-09-07", [("14:56", 10, 10, 9.4, 9.5, 100, True)]),
            date(2026, 9, 8): minute_frame("2026-09-08", [("09:31", 10, 10.1, 9.9, 10, 100, True)]),
            date(2026, 9, 9): minute_frame("2026-09-09", [("14:55", 10, 10, 9.9, 10, 100, True)]),
        }
        result = simulate_position(position(), days, self.calendar, costs())
        self.assertEqual(result["reason"], "T+2到期")
        self.assertEqual(result["exit_time"].date(), date(2026, 9, 9))

    def test_stop_loss_sells_at_minus_five_percent(self):
        days = {
            date(2026, 9, 8): minute_frame("2026-09-08", [("09:31", 10, 10, 9.5, 9.6, 100, True)])
        }
        result = simulate_position(position(), days, self.calendar, costs())
        self.assertEqual(result["reason"], "止损")
        self.assertAlmostEqual(result["exit_price"], 9.5)

    def test_trailing_arms_at_five_percent_and_exits_after_relative_drawdown(self):
        days = {
            date(2026, 9, 8): minute_frame(
                "2026-09-08",
                [
                    ("09:31", 10.2, 10.6, 10.4, 10.5, 100, True),
                    ("09:32", 10.55, 10.6, 10.55, 10.56, 100, True),
                ],
            )
        }
        result = simulate_position(position(), days, self.calendar, costs())
        self.assertEqual(result["reason"], "5%后回落0.3%")
        self.assertAlmostEqual(result["exit_price"], 10.55)

    def test_newly_armed_trailing_never_fills_inside_same_minute(self):
        days = {
            date(2026, 9, 8): minute_frame(
                "2026-09-08",
                [
                    ("09:31", 10.0, 10.6, 10.0, 10.5, 100, True),
                    ("09:32", 10.7, 10.8, 10.7, 10.75, 100, True),
                ],
            ),
            date(2026, 9, 9): minute_frame("2026-09-09", [("14:55", 10.8, 10.8, 10.8, 10.8, 100, True)]),
        }
        result = simulate_position(position(), days, self.calendar, costs())
        self.assertEqual(result["reason"], "T+2到期")

    def test_gap_through_stop_uses_worse_open_and_slippage(self):
        days = {
            date(2026, 9, 8): minute_frame("2026-09-08", [("09:31", 9.3, 9.4, 9.2, 9.3, 100, True)])
        }
        result = simulate_position(position(), days, self.calendar, costs(slippage=0.001))
        self.assertAlmostEqual(result["exit_price"], 9.3 * 0.999)

    def test_t2_nontradable_carries_to_next_trading_day(self):
        days = {
            date(2026, 9, 9): minute_frame("2026-09-09", [("14:55", 9.8, 9.8, 9.8, 9.8, 0, False)]),
            date(2026, 9, 10): minute_frame("2026-09-10", [("09:31", 9.7, 9.7, 9.7, 9.7, 100, True)]),
        }
        result = simulate_position(position(), days, self.calendar, costs())
        self.assertEqual(result["reason"], "到期顺延卖出")
        self.assertEqual(result["extra_hold_days"], 1)

    def test_fees_reconcile_to_net_profit(self):
        days = {
            date(2026, 9, 8): minute_frame("2026-09-08", [("09:31", 9.5, 9.6, 9.5, 9.5, 100, True)])
        }
        result = simulate_position(position(), days, self.calendar, costs())
        expected = 9_500 - 5 - 9_500 * 0.0005 - 10_000 - 5
        self.assertAlmostEqual(result["net_pnl"], expected)


class TailCacheTests(unittest.TestCase):
    def test_empty_minute_cache_uses_datetime_index(self):
        with tempfile.TemporaryDirectory() as folder:
            empty = TailCache(Path(folder)).load_minutes("600001")
            self.assertIsInstance(empty.index, pd.DatetimeIndex)
            self.assertEqual(empty.index.name, "time")

    def test_minute_merge_is_incremental_unique_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TailCache(Path(folder))
            first = minute_frame(
                "2026-09-08",
                [
                    ("14:54", 10.0, 10.1, 9.9, 10.0, 10, True),
                    ("14:55", 10.0, 10.2, 10.0, 10.1, 20, True),
                ],
            )
            second = minute_frame(
                "2026-09-08",
                [
                    ("14:55", 10.0, 10.3, 10.0, 10.2, 30, True),
                    ("14:56", 10.2, 10.3, 10.1, 10.2, 40, True),
                ],
            )
            cache.merge_minutes("600001", first)
            cache.merge_minutes("600001", second)
            loaded = TailCache(Path(folder)).load_minutes("600001")
            self.assertEqual(len(loaded), 3)
            self.assertTrue(loaded.index.is_monotonic_increasing)
            self.assertEqual(float(loaded.loc["2026-09-08 14:55", "close"]), 10.2)

    def test_daily_merge_preserves_old_rows_and_replaces_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TailCache(Path(folder))
            _, daily = passing_fixture()
            cache.merge_daily("600001", daily.iloc[:60])
            changed = daily.iloc[59:].copy()
            changed.iloc[0, changed.columns.get_loc("close")] = 99.0
            cache.merge_daily("600001", changed)
            loaded = cache.load_daily("600001")
            self.assertEqual(len(loaded), 70)
            self.assertEqual(float(loaded.iloc[59].close), 99.0)

    def test_spot_normalization_maps_complete_real_schema(self):
        raw = pd.DataFrame(
            [
                {
                    "代码": "1",
                    "名称": "测试股份",
                    "最新价": 10.5,
                    "涨跌幅": 5.0,
                    "振幅": 4.0,
                    "换手率": 3.0,
                    "流通市值": 10_000_000_000,
                    "成交量": 123456,
                }
            ]
        )
        rows = normalize_spot_frame(raw, timestamp="2026-09-14 14:50:00")
        self.assertEqual(rows[0]["code"], "000001")
        self.assertEqual(rows[0]["float_market_cap"], 10_000_000_000.0)
        self.assertEqual(rows[0]["turnover"], 3.0)
        self.assertEqual(rows[0]["timestamp"], "2026-09-14 14:50:00")

    def test_spot_normalization_rejects_missing_provider_field(self):
        raw = pd.DataFrame([{"代码": "600001", "名称": "测试"}])
        with self.assertRaisesRegex(ValueError, "实时行情缺少字段"):
            normalize_spot_frame(raw)

    def test_minute_normalization_accepts_chinese_provider_columns(self):
        raw = pd.DataFrame(
            [
                {
                    "时间": "2026-09-08 14:55:00",
                    "开盘": 10.0,
                    "最高": 10.2,
                    "最低": 9.9,
                    "收盘": 10.1,
                    "成交量": 200,
                    "成交额": 202000,
                }
            ]
        )
        normalized = normalize_minute_frame(raw, "600001")
        self.assertEqual(normalized.index[0], pd.Timestamp("2026-09-08 14:55:00"))
        self.assertEqual(normalized.iloc[0]["code"], "600001")
        self.assertTrue(bool(normalized.iloc[0]["tradable"]))

    def test_standard_csv_import_validates_and_persists_by_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "minutes.csv"
            pd.DataFrame(
                [
                    {"代码": "600001", "时间": "2026-09-08 14:55", "开盘": 10, "最高": 10.2, "最低": 9.9, "收盘": 10.1, "成交量": 20, "成交额": 20200},
                    {"代码": "000001", "时间": "2026-09-08 14:55", "开盘": 11, "最高": 11.2, "最低": 10.9, "收盘": 11.1, "成交量": 30, "成交额": 33300},
                ]
            ).to_csv(source, index=False)
            cache = TailCache(root / "cache")
            result = import_minute_csv(source, cache)
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["codes"], 2)
            self.assertEqual(len(cache.load_minutes("600001")), 1)

    def test_snapshot_and_coverage_are_auditable(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TailCache(Path(folder))
            snapshot, _ = passing_fixture()
            path = cache.save_snapshot("2026-09-14 14:50:00", [snapshot])
            cache.merge_minutes("600001", minute_frame("2026-09-08", [("14:55", 10, 10, 10, 10, 20, True)]))
            coverage = cache.coverage()
            self.assertTrue(path.exists())
            self.assertEqual(coverage["minute_days"], 1)
            self.assertEqual(coverage["snapshot_count"], 1)


class TailPortfolioTests(unittest.TestCase):
    def _portfolio_fixture(self, root):
        cache = TailCache(root)
        codes = [f"60000{i}" for i in range(1, 7)]
        for offset, code in enumerate(codes):
            cache.merge_minutes(
                code,
                pd.concat(
                    [
                        minute_frame("2026-09-07", [("14:55", 10, 10, 10, 10, 1000, True)]),
                        minute_frame("2026-09-08", [("09:31", 10, 10.1, 9.9, 10, 1000, True)]),
                        minute_frame("2026-09-09", [("14:55", 10.1, 10.1, 10.1, 10.1, 1000, True)]),
                    ]
                ),
            )
        rows = [
            {
                "code": code,
                "name": f"测试{code}",
                "timestamp": "2026-09-07 14:50:00",
                "passed": True,
                "change_pct": 6.0 - index * 0.1,
                "today_volume_ratio": 1.5,
            }
            for index, code in enumerate(codes)
        ]
        return cache, rows

    def test_top_five_equal_weight_respects_lots_cash_and_caps(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, rows = self._portfolio_fixture(Path(folder))
            result = run_tail_backtest(
                rows,
                cache,
                {
                    "initial_cash": 100_000,
                    "top_n": 5,
                    "max_position_pct": 20,
                    "total_position_pct": 80,
                    "commission": 0,
                    "min_commission": 0,
                    "stamp": 0,
                    "slippage": 0,
                },
            )
            orders = result["orders"]
            self.assertEqual(len(orders), 5)
            self.assertTrue(all(order["shares"] % 100 == 0 for order in orders))
            self.assertTrue(all(order["entry_amount"] <= 20_000 for order in orders))
            self.assertLessEqual(sum(order["entry_amount"] for order in orders), 80_000)
            self.assertGreaterEqual(float(result["summary"]["minimum_cash"]), 0)

    def test_backtest_ledger_reconciles_final_equity(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, rows = self._portfolio_fixture(Path(folder))
            result = run_tail_backtest(rows, cache, {"initial_cash": 100_000, "top_n": 1, "slippage": 0})
            realized = sum(trade["net_pnl"] for trade in result["trades"])
            self.assertAlmostEqual(result["summary"]["final_equity"], 100_000 + realized)
            self.assertEqual(result["summary"]["strategy_id"], "TAIL_2D_V1")
            self.assertEqual(result["summary"]["exact_minute_only"], True)

    def test_open_position_is_marked_to_last_cached_minute(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TailCache(Path(folder))
            cache.merge_minutes(
                "600001",
                pd.concat(
                    [
                        minute_frame("2026-09-07", [("14:55", 10, 10, 10, 10, 1000, True)]),
                        minute_frame("2026-09-08", [("14:55", 9, 9, 9, 9, 1000, True)]),
                    ]
                ),
            )
            rows = [{"code": "600001", "name": "测试", "timestamp": "2026-09-07 14:50", "passed": True, "change_pct": 5, "today_volume_ratio": 1.5}]
            result = run_tail_backtest(rows, cache, {"initial_cash": 100000, "top_n": 1, "commission": 0, "min_commission": 0, "stamp": 0, "slippage": 0})
            order = result["orders"][0]
            expected = 100000 - order["entry_amount"] + order["shares"] * 9
            self.assertAlmostEqual(result["summary"]["final_equity"], expected)

    def test_state_round_trip_preserves_trailing_peak(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "tail_strategy_state.json"
            state = {"strategy_id": "TAIL_2D_V1", "positions": {"600001": {"peak": 10.6, "trailing_armed": True}}}
            save_tail_state(target, state)
            loaded = load_tail_state(target)
            self.assertEqual(loaded["positions"]["600001"]["peak"], 10.6)
            self.assertTrue(loaded["positions"]["600001"]["trailing_armed"])

    def test_audit_bundle_contains_strategy_outputs_and_excludes_private_account(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "tail_audit.zip"
            result = {
                "summary": {"strategy_id": "TAIL_2D_V1", "final_equity": 100001},
                "orders": [{"code": "600001", "shares": 100}],
                "trades": [{"code": "600001", "net_pnl": 1}],
                "positions": [],
                "equity": [{"time": "2026-09-09", "equity": 100001}],
                "screen_audit": [{"code": "600001", "passed": True}],
                "errors": [],
            }
            included = create_tail_audit_bundle(target, result, {"minute_days": 3})
            self.assertIn("tail_manifest.json", included)
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
            self.assertIn("tail_trades.csv", names)
            self.assertIn("tail_screen_audit.csv", names)
            self.assertNotIn("paper_account.json", names)


class _ProviderResponse:
    def __init__(self, payload=None, text=""):
        self.payload = payload
        self.text = text
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _ProviderSession:
    def __init__(self, payloads):
        self.trust_env = True
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, _ProviderResponse) else _ProviderResponse(item)


class TailProviderTests(unittest.TestCase):
    def test_market_snapshot_uses_no_proxy_session_and_parses_fields(self):
        session = _ProviderSession(
            [
                {
                    "data": {
                        "total": 1,
                        "diff": [
                            {
                                "f12": "600001",
                                "f14": "测试股份",
                                "f2": 10.5,
                                "f3": 5.0,
                                "f5": 123456,
                                "f7": 4.0,
                                "f8": 3.0,
                                "f21": 10_000_000_000,
                            }
                        ],
                    }
                }
            ]
        )
        rows = fetch_tail_spot(session=session)
        self.assertFalse(session.trust_env)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "600001")
        self.assertEqual(rows[0]["turnover"], 3.0)
        self.assertIn("不使用系统代理", rows[0]["source"])
        self.assertIn("fs", session.calls[0][1]["params"])

    def test_market_snapshot_keeps_paging_when_provider_caps_each_page(self):
        first = {"data": {"total": 2, "diff": [{"f12": "600001", "f14": "测试一", "f2": 10, "f3": 1, "f5": 10, "f7": 1, "f8": 1, "f21": 1e9}]}}
        second = {"data": {"total": 2, "diff": [{"f12": "600002", "f14": "测试二", "f2": 11, "f3": 2, "f5": 20, "f7": 2, "f8": 2, "f21": 2e9}]}}
        session = _ProviderSession([first, second])
        rows = fetch_tail_spot(session=session)
        self.assertEqual([row["code"] for row in rows], ["600001", "600002"])
        self.assertEqual([call[1]["params"]["pn"] for call in session.calls], [1, 2])

    def test_market_snapshot_falls_back_to_tencent_after_eastmoney_disconnects(self):
        fields = ["0"] * 46
        fields[1] = "测试股份"
        fields[2] = "600001"
        fields[3] = "10.50"
        fields[4] = "10.00"
        fields[32] = "5.00"
        fields[36] = "123456"
        fields[38] = "3.00"
        fields[43] = "4.00"
        fields[44] = "100.00"
        tencent = _ProviderResponse(text='v_sh600001="' + "~".join(fields) + '";')
        session = _ProviderSession([ConnectionError("东财1断开"), ConnectionError("东财2断开"), tencent])
        try:
            rows = fetch_tail_spot(session=session, fallback_universe=[{"code": "600001", "name": "测试股份"}])
        except Exception:
            rows = []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "600001")
        self.assertEqual(rows[0]["float_market_cap"], 10_000_000_000)
        self.assertIn("腾讯", rows[0]["source"])

    def test_minute_history_uses_no_proxy_session_and_parses_ohlcv(self):
        session = _ProviderSession(
            [
                {
                    "data": {
                        "klines": [
                            "2026-09-11 14:55,10.00,10.10,10.20,9.90,1200,121200.00,3.00,1.00,0.10,2.00"
                        ]
                    }
                }
            ]
        )
        frame = fetch_tail_minutes("600001", "2026-09-11", "2026-09-12", session=session)
        self.assertFalse(session.trust_env)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["code"], "600001")
        self.assertAlmostEqual(float(frame.iloc[0]["close"]), 10.1)
        self.assertEqual(session.calls[0][1]["params"]["secid"], "1.600001")


class _Dummy:
    def __init__(self, *args, **kwargs):
        self.items = []
        self.widgets = []

    def __call__(self, *args, **kwargs):
        return _Dummy()

    def __getattr__(self, name):
        return _Dummy()

    def addItems(self, items):
        self.items.extend(list(items))

    def addWidget(self, widget, *args):
        self.widgets.append(widget)

    def connect(self, *args):
        return None

    def emit(self, *args):
        return None


class _Qt:
    AlignCenter = 0
    Vertical = 1
    Horizontal = 2
    ItemIsEditable = 4
    Checked = 2
    Unchecked = 0


class TailUiContractTests(unittest.TestCase):
    def test_main_window_exposes_v76_tail_strategy_without_removing_old_pages(self):
        module_names = ["PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "pyqtgraph", "requests"]
        previous = {name: sys.modules.get(name) for name in module_names}
        try:
            pyside = types.ModuleType("PySide6")
            qtcore = types.ModuleType("PySide6.QtCore")
            qtgui = types.ModuleType("PySide6.QtGui")
            qtwidgets = types.ModuleType("PySide6.QtWidgets")
            pyqtgraph = types.ModuleType("pyqtgraph")
            requests = types.ModuleType("requests")
            requests.Session = _Dummy
            qtcore.QRectF = qtcore.QThread = qtcore.QTimer = _Dummy
            qtcore.Qt = _Qt
            qtcore.Signal = lambda *args: _Dummy()
            for name in ("QColor", "QPainter", "QPicture"):
                setattr(qtgui, name, _Dummy)
            for name in (
                "QAbstractItemView", "QApplication", "QComboBox", "QDoubleSpinBox", "QFrame", "QGridLayout",
                "QHBoxLayout", "QFileDialog", "QLabel", "QLineEdit", "QListWidget", "QMainWindow", "QMessageBox",
                "QPlainTextEdit", "QProgressBar", "QPushButton", "QSpinBox", "QSplitter", "QStackedWidget",
                "QTabWidget", "QTableWidget", "QTableWidgetItem", "QVBoxLayout", "QWidget",
            ):
                setattr(qtwidgets, name, type(name, (_Dummy,), {}))
            qtwidgets.QAbstractItemView.SelectRows = 1
            qtwidgets.QAbstractItemView.NoEditTriggers = 0
            pyqtgraph.GraphicsObject = _Dummy
            pyqtgraph.PlotWidget = _Dummy
            pyqtgraph.BarGraphItem = _Dummy
            pyqtgraph.GraphicsLayoutWidget = _Dummy
            pyqtgraph.mkPen = lambda *args, **kwargs: _Dummy()
            pyqtgraph.setConfigOptions = lambda **kwargs: None
            sys.modules.update(
                {
                    "PySide6": pyside,
                    "PySide6.QtCore": qtcore,
                    "PySide6.QtGui": qtgui,
                    "PySide6.QtWidgets": qtwidgets,
                    "pyqtgraph": pyqtgraph,
                    "requests": requests,
                }
            )
            path = Path(__file__).with_name("main.py")
            spec = importlib.util.spec_from_file_location("astock_quant_v7_6.main_ui_contract", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            window = module.MainWindow()
            self.assertEqual(module.APP_VERSION, "8.3.3")
            self.assertIn("尾盘两日短线", window.menu.items)
            self.assertTrue(hasattr(window, "tail_strategy"))
            self.assertGreaterEqual(len(window.pages.widgets), 9)
            self.assertEqual(window.menu.items[8], "周线趋势确认")
            self.assertEqual(window.weekly_trend.__class__.__name__, "WeeklyTrendPage")
            self.assertIn("scan_button", vars(window.weekly_trend))
            self.assertIn("screen_table", vars(window.weekly_trend))
        finally:
            for name, value in previous.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value


if __name__ == "__main__":
    unittest.main()
