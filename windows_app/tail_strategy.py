"""尾盘两日短线（TAIL_2D_V1）的纯策略、数据与审计逻辑。

本模块不依赖 PySide6，便于离线测试。界面和后台线程位于 main.py。
"""

from __future__ import annotations

import json
import math
import zipfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


TAIL_STRATEGY_ID = "TAIL_2D_V1"
MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def is_main_board(code: str, name: str) -> bool:
    code = str(code).split(".")[0].zfill(6)
    compact_name = str(name).upper().replace(" ", "")
    return (
        len(code) == 6
        and code.isdigit()
        and code.startswith(MAIN_BOARD_PREFIXES)
        and "ST" not in compact_name
        and "退" not in compact_name
    )


def _normalized_daily(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("日线缺少字段:" + ",".join(missing))
    result = frame.loc[:, required].copy()
    result.index = pd.to_datetime(result.index, errors="coerce")
    result = result.loc[~result.index.isna()].sort_index()
    result = result.loc[~result.index.duplicated(keep="last")]
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def evaluate_candidate(snapshot: Mapping[str, Any], daily: pd.DataFrame) -> dict[str, Any]:
    """逐条执行已批准的13项严格筛选，返回完整漏斗审计。"""
    code = str(snapshot.get("code", "")).split(".")[0].zfill(6)
    name = str(snapshot.get("name", "")).strip()
    result: dict[str, Any] = {
        "strategy_id": TAIL_STRATEGY_ID,
        "code": code,
        "name": name,
        "timestamp": str(snapshot.get("timestamp", "")),
        "price": _number(snapshot.get("price")),
        "change_pct": _number(snapshot.get("change_pct")),
        "amplitude": _number(snapshot.get("amplitude")),
        "turnover": _number(snapshot.get("turnover")),
        "float_market_cap": _number(snapshot.get("float_market_cap")),
        "volume": _number(snapshot.get("volume")),
    }
    failures: list[str] = []
    if not is_main_board(code, name):
        failures.append("非沪深主板或ST/退市")

    required_snapshot = ("price", "change_pct", "amplitude", "turnover", "float_market_cap", "volume")
    missing_snapshot = [field for field in required_snapshot if not math.isfinite(result[field])]
    if missing_snapshot:
        failures.append("实时字段缺失:" + ",".join(missing_snapshot))

    try:
        history = _normalized_daily(daily)
    except Exception as exc:
        history = pd.DataFrame()
        failures.append(str(exc))
    if len(history) < 60:
        failures.append(f"历史不足60日:{len(history)}")

    derived = {
        "ma10": math.nan,
        "return_6d": math.nan,
        "return_20d": math.nan,
        "return_30d": math.nan,
        "return_60d": math.nan,
        "today_volume_ratio": math.nan,
        "week_volume_ratio": math.nan,
        "recent_limit_up_count": 0,
    }
    if len(history) >= 60 and not missing_snapshot:
        price = result["price"]
        derived["ma10"] = float(history.close.tail(10).mean())
        for sessions in (6, 20, 30, 60):
            base = _number(history.close.iloc[-sessions])
            derived[f"return_{sessions}d"] = (price / base - 1) * 100 if base > 0 else math.nan
        yesterday_volume = _number(history.volume.iloc[-1])
        derived["today_volume_ratio"] = result["volume"] / yesterday_volume if yesterday_volume > 0 else math.nan

        current_time = pd.to_datetime(snapshot.get("timestamp"), errors="coerce")
        if pd.isna(current_time):
            failures.append("筛选时间缺失")
        else:
            current_period = current_time.to_period("W-FRI")
            periods = history.index.to_period("W-FRI")
            completed_periods = periods[periods < current_period]
            if len(completed_periods):
                previous_period = completed_periods.max()
                previous_week_volume = float(history.loc[periods == previous_period, "volume"].sum())
                current_week_volume = float(history.loc[periods == current_period, "volume"].sum()) + result["volume"]
                derived["week_volume_ratio"] = current_week_volume / previous_week_volume if previous_week_volume > 0 else math.nan
            else:
                failures.append("缺少上一完整交易周")

        recent_returns = history.close.pct_change().tail(10)
        derived["recent_limit_up_count"] = int((recent_returns >= 0.098 - 1e-12).sum())

        comparisons = (
            (price < 13.0, "股价不小于13元"),
            (result["float_market_cap"] < 20_000_000_000.0, "流通市值不小于200亿元"),
            (price > derived["ma10"], "股价不高于MA10"),
            (result["change_pct"] < 9.0, "今日涨幅不小于9%"),
            (result["amplitude"] < 6.0, "振幅不小于6%"),
            (result["turnover"] < 10.0, "换手率不小于10%"),
            (derived["return_60d"] < 100.0 - 1e-9, "60日涨幅不小于100%"),
            (derived["return_30d"] < 28.0 - 1e-9, "30日涨幅不小于28%"),
            (derived["return_20d"] < 16.0 - 1e-9, "20日涨幅不小于16%"),
            (derived["return_6d"] < 7.0 - 1e-9, "6日涨幅不小于7%"),
            (derived["today_volume_ratio"] > 0.9 + 1e-12, "成交量未大于昨日0.9倍"),
            (derived["week_volume_ratio"] > 0.5 + 1e-12, "当周量未大于上周0.5倍"),
            (derived["recent_limit_up_count"] == 0, "最近10个完成交易日存在涨停"),
        )
        for passed, reason in comparisons:
            if not bool(passed):
                failures.append(reason)

    result.update(derived)
    result["failures"] = failures
    result["passed"] = not failures
    return result


def rank_candidates(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            -_number(row.get("change_pct")) if math.isfinite(_number(row.get("change_pct"))) else math.inf,
            -_number(row.get("today_volume_ratio")) if math.isfinite(_number(row.get("today_volume_ratio"))) else math.inf,
            str(row.get("code", "")),
        ),
    )


def _normalized_minutes(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("分钟线缺少字段:" + ",".join(missing))
    result = frame.copy()
    if "time" in result.columns:
        result.index = pd.to_datetime(result.pop("time"), errors="coerce")
    else:
        result.index = pd.to_datetime(result.index, errors="coerce")
    result = result.loc[~result.index.isna()].sort_index()
    result = result.loc[~result.index.duplicated(keep="last")]
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "tradable" not in result.columns:
        result["tradable"] = True
    result["tradable"] = result["tradable"].fillna(False).astype(bool)
    return result


def _bar_tradable(row: pd.Series) -> bool:
    return bool(
        row.get("tradable", True)
        and _number(row.get("volume")) > 0
        and all(_number(row.get(field)) > 0 for field in ("open", "high", "low", "close"))
    )


def entry_fill(minute_frame: pd.DataFrame, at_or_after: str = "14:55", slippage: float = 0.0) -> dict[str, Any] | None:
    """返回尾盘第一个可成交分钟；价格采用该分钟收盘并计入买入滑点。"""
    bars = _normalized_minutes(minute_frame)
    cutoff = time.fromisoformat(at_or_after)
    for timestamp, row in bars.iterrows():
        if timestamp.time() < cutoff or timestamp.time() >= time(14, 57) or not _bar_tradable(row):
            continue
        return {"time": timestamp, "price": float(row.close) * (1 + float(slippage))}
    return None


def next_trading_sessions(calendar: Iterable[Any], buy_date: date | datetime | pd.Timestamp) -> tuple[date, date]:
    sessions = sorted({pd.Timestamp(item).date() for item in calendar})
    bought = pd.Timestamp(buy_date).date()
    future = [session for session in sessions if session > bought]
    if len(future) < 2:
        raise ValueError("交易日历不足以确定T+1和T+2")
    return future[0], future[1]


def _sell_fees(amount: float, config: Mapping[str, Any]) -> float:
    commission = max(_number(config.get("min_commission", 5.0)), amount * _number(config.get("commission", 0.0003)))
    return commission + amount * _number(config.get("stamp", 0.0005))


def _buy_fee(amount: float, config: Mapping[str, Any]) -> float:
    return max(_number(config.get("min_commission", 5.0)), amount * _number(config.get("commission", 0.0003)))


def simulate_position(
    position: Mapping[str, Any],
    minute_by_day: Mapping[Any, pd.DataFrame],
    calendar: Iterable[Any],
    costs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """以1分钟OHLC保守模拟单笔T+1/T+2交易。"""
    config = dict(costs or {})
    entry_time = pd.Timestamp(position["entry_time"])
    entry_price = _number(position["entry_price"])
    shares = int(position["shares"])
    if entry_price <= 0 or shares <= 0:
        raise ValueError("买入价格和股数必须为正")
    t1, t2 = next_trading_sessions(calendar, entry_time)
    peak = max(entry_price, _number(position.get("peak", entry_price)))
    trailing_armed = bool(position.get("trailing_armed", peak >= entry_price * 1.05))
    stop_price = entry_price * 0.95
    slippage = _number(config.get("slippage", 0.0))
    if not math.isfinite(slippage):
        slippage = 0.0

    day_map: dict[date, pd.DataFrame] = {}
    for day_key, frame in minute_by_day.items():
        day_map[pd.Timestamp(day_key).date()] = _normalized_minutes(frame)
    sessions = sorted({pd.Timestamp(item).date() for item in calendar if pd.Timestamp(item).date() >= t1})
    saw_t2 = False

    for session in sessions:
        if session < t1:
            continue
        if session >= t2:
            saw_t2 = True
        bars = day_map.get(session)
        if bars is None or bars.empty:
            continue
        for timestamp, row in bars.iterrows():
            if not _bar_tradable(row):
                continue
            opened, high, low, close = (float(row[field]) for field in ("open", "high", "low", "close"))
            trailing_price = peak * (1 - 0.003) if trailing_armed else math.nan
            stop_hit = low <= stop_price
            trailing_hit = trailing_armed and low <= trailing_price
            reason = ""
            raw_exit = math.nan
            if stop_hit:
                reason = "止损"
                raw_exit = min(opened, stop_price)
            elif trailing_hit:
                reason = "5%后回落0.3%"
                raw_exit = min(opened, trailing_price)
            elif (session == t2 and timestamp.time() >= time(14, 55)) or session > t2:
                reason = "T+2到期" if session == t2 else "到期顺延卖出"
                raw_exit = close
            if reason:
                exit_price = raw_exit * (1 - slippage)
                entry_amount = entry_price * shares
                exit_amount = exit_price * shares
                buy_fee = _buy_fee(entry_amount, config)
                sell_fee = _sell_fees(exit_amount, config)
                return {
                    "status": "已卖出",
                    "code": str(position.get("code", "")),
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "exit_time": timestamp,
                    "exit_price": exit_price,
                    "shares": shares,
                    "reason": reason,
                    "peak": peak,
                    "trailing_armed": trailing_armed,
                    "buy_fee": buy_fee,
                    "sell_fee": sell_fee,
                    "fees": buy_fee + sell_fee,
                    "net_pnl": exit_amount - sell_fee - entry_amount - buy_fee,
                    "extra_hold_days": max(0, sessions.index(session) - sessions.index(t2)),
                    "t1": t1,
                    "t2": t2,
                }
            peak = max(peak, high)
            if not trailing_armed and peak >= entry_price * 1.05:
                trailing_armed = True

    return {
        "status": "到期未成交" if saw_t2 else "仍持有",
        "code": str(position.get("code", "")),
        "entry_time": entry_time,
        "entry_price": entry_price,
        "exit_time": None,
        "exit_price": math.nan,
        "shares": shares,
        "reason": "到期未成交" if saw_t2 else "未到T+2",
        "peak": peak,
        "trailing_armed": trailing_armed,
        "buy_fee": _buy_fee(entry_price * shares, config),
        "sell_fee": 0.0,
        "fees": _buy_fee(entry_price * shares, config),
        "net_pnl": math.nan,
        "extra_hold_days": max(0, len([session for session in sessions if session > t2])),
        "t1": t1,
        "t2": t2,
    }


def _atomic_csv(frame: pd.DataFrame, target: Path, index_label: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    frame.to_csv(temporary, index=True, index_label=index_label, encoding="utf-8-sig")
    temporary.replace(target)


class TailCache:
    """尾盘策略独立、增量、原子写入的数据目录。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.daily_dir = self.root / "daily"
        self.minute_dir = self.root / "minute"
        self.snapshot_dir = self.root / "snapshots"
        for folder in (self.daily_dir, self.minute_dir, self.snapshot_dir):
            folder.mkdir(parents=True, exist_ok=True)

    def merge_daily(self, code: str, frame: pd.DataFrame) -> Path:
        code = str(code).zfill(6)
        target = self.daily_dir / f"{code}.csv"
        incoming = _normalized_daily(frame)
        if target.exists():
            existing = pd.read_csv(target, parse_dates=["date"]).set_index("date")
            existing = _normalized_daily(existing)
            incoming = pd.concat([existing, incoming])
        incoming = incoming.loc[~incoming.index.duplicated(keep="last")].sort_index()
        _atomic_csv(incoming, target, "date")
        return target

    def load_daily(self, code: str) -> pd.DataFrame:
        target = self.daily_dir / f"{str(code).zfill(6)}.csv"
        if not target.exists():
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return _normalized_daily(pd.read_csv(target, parse_dates=["date"]).set_index("date"))

    def merge_minutes(self, code: str, frame: pd.DataFrame) -> list[Path]:
        code = str(code).zfill(6)
        incoming = _normalized_minutes(frame)
        incoming["code"] = code
        written: list[Path] = []
        for session, group in incoming.groupby(incoming.index.date):
            target = self.minute_dir / session.isoformat() / f"{code}.csv"
            merged = group.copy()
            if target.exists():
                existing = _normalized_minutes(pd.read_csv(target, parse_dates=["time"]).set_index("time"))
                existing["code"] = code
                merged = pd.concat([existing, merged])
            merged = merged.loc[~merged.index.duplicated(keep="last")].sort_index()
            ordered = [column for column in ("code", "open", "high", "low", "close", "volume", "amount", "tradable") if column in merged.columns]
            _atomic_csv(merged.loc[:, ordered], target, "time")
            written.append(target)
        return written

    def load_minutes(self, code: str, start: Any = None, end: Any = None) -> pd.DataFrame:
        code = str(code).zfill(6)
        frames: list[pd.DataFrame] = []
        for target in sorted(self.minute_dir.glob(f"*/{code}.csv")):
            frame = _normalized_minutes(pd.read_csv(target, parse_dates=["time"]).set_index("time"))
            frame["code"] = code
            frames.append(frame)
        if not frames:
            empty = pd.DataFrame(columns=["code", "open", "high", "low", "close", "volume", "amount", "tradable"])
            empty.index = pd.DatetimeIndex([], name="time")
            return empty
        result = pd.concat(frames).loc[lambda x: ~x.index.duplicated(keep="last")].sort_index()
        if start is not None:
            result = result.loc[result.index >= pd.Timestamp(start)]
        if end is not None:
            result = result.loc[result.index <= pd.Timestamp(end)]
        return result

    def save_snapshot(self, timestamp: Any, rows: Iterable[Mapping[str, Any]]) -> Path:
        stamp = pd.Timestamp(timestamp)
        target = self.snapshot_dir / f"{stamp:%Y-%m-%d_%H%M%S}.csv"
        frame = pd.DataFrame([dict(row) for row in rows])
        for column in frame.columns:
            if len(frame) and frame[column].map(lambda value: isinstance(value, (list, tuple, dict))).any():
                frame[column] = frame[column].map(lambda value: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple, dict)) else value)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        temporary.replace(target)
        return target

    def list_snapshots(self) -> list[Path]:
        return sorted(self.snapshot_dir.glob("*.csv"))

    def load_latest_snapshot(self) -> pd.DataFrame:
        paths = self.list_snapshots()
        return pd.read_csv(paths[-1], dtype={"code": str}) if paths else pd.DataFrame()

    def coverage(self) -> dict[str, Any]:
        day_dirs = sorted(path for path in self.minute_dir.glob("????-??-??") if path.is_dir() and any(path.glob("*.csv")))
        return {
            "strategy_id": TAIL_STRATEGY_ID,
            "minute_days": len(day_dirs),
            "first_minute_day": day_dirs[0].name if day_dirs else "",
            "last_minute_day": day_dirs[-1].name if day_dirs else "",
            "daily_symbols": len(list(self.daily_dir.glob("*.csv"))),
            "snapshot_count": len(self.list_snapshots()),
        }


SPOT_COLUMNS = {
    "代码": "code",
    "名称": "name",
    "最新价": "price",
    "涨跌幅": "change_pct",
    "振幅": "amplitude",
    "换手率": "turnover",
    "流通市值": "float_market_cap",
    "成交量": "volume",
}


def normalize_spot_frame(frame: pd.DataFrame, timestamp: Any = None) -> list[dict[str, Any]]:
    missing = [source for source in SPOT_COLUMNS if source not in frame.columns]
    if missing:
        raise ValueError("实时行情缺少字段:" + ",".join(missing))
    stamp = pd.Timestamp(timestamp or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    result: list[dict[str, Any]] = []
    for _, source in frame.iterrows():
        row: dict[str, Any] = {target: source[source_name] for source_name, target in SPOT_COLUMNS.items()}
        row["code"] = str(row["code"]).split(".")[0].zfill(6)
        row["name"] = str(row["name"]).strip()
        for field in ("price", "change_pct", "amplitude", "turnover", "float_market_cap", "volume"):
            row[field] = _number(row[field])
        row["timestamp"] = stamp
        row["source"] = "AKShare/东方财富实时"
        result.append(row)
    return result


MINUTE_ALIASES = {
    "时间": "time",
    "日期时间": "time",
    "代码": "code",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}


def normalize_minute_frame(frame: pd.DataFrame, code: str | None = None) -> pd.DataFrame:
    renamed = frame.rename(columns={column: MINUTE_ALIASES.get(str(column), str(column).lower()) for column in frame.columns}).copy()
    if "time" in renamed.columns:
        renamed.index = pd.to_datetime(renamed.pop("time"), errors="coerce")
    else:
        renamed.index = pd.to_datetime(renamed.index, errors="coerce")
    renamed.index.name = "time"
    required = ("open", "high", "low", "close", "volume")
    missing = [field for field in required if field not in renamed.columns]
    if missing:
        raise ValueError("分钟数据缺少字段:" + ",".join(missing))
    renamed = renamed.loc[~renamed.index.isna()].sort_index()
    renamed = renamed.loc[~renamed.index.duplicated(keep="last")]
    for field in required + ("amount",):
        if field not in renamed.columns:
            renamed[field] = np.nan
        renamed[field] = pd.to_numeric(renamed[field], errors="coerce")
    if code is not None:
        renamed["code"] = str(code).split(".")[0].zfill(6)
    elif "code" in renamed.columns:
        renamed["code"] = renamed["code"].astype(str).str.split(".").str[0].str.zfill(6)
    else:
        raise ValueError("分钟数据缺少代码")
    if "tradable" not in renamed.columns:
        renamed["tradable"] = renamed["volume"].fillna(0) > 0
    else:
        renamed["tradable"] = renamed["tradable"].fillna(False).astype(bool)
    return renamed.loc[:, ["code", "open", "high", "low", "close", "volume", "amount", "tradable"]]


def import_minute_csv(path: str | Path, cache: TailCache) -> dict[str, Any]:
    source = pd.read_csv(path, dtype={"代码": str, "code": str})
    code_column = "代码" if "代码" in source.columns else ("code" if "code" in source.columns else None)
    if code_column is None:
        raise ValueError("分钟CSV缺少代码列")
    rows = 0
    codes: set[str] = set()
    days: set[date] = set()
    for raw_code, group in source.groupby(code_column, dropna=False):
        code = str(raw_code).split(".")[0].zfill(6)
        normalized = normalize_minute_frame(group, code)
        if normalized.empty:
            continue
        cache.merge_minutes(code, normalized)
        rows += len(normalized)
        codes.add(code)
        days.update(normalized.index.date)
    if not rows:
        raise ValueError("分钟CSV没有可导入记录")
    return {"rows": rows, "codes": len(codes), "days": len(days)}


def _no_proxy_session(session: Any = None) -> Any:
    """创建不继承 Windows/系统代理的行情连接。"""
    if session is None:
        import requests

        session = requests.Session()
    session.trust_env = False
    return session


def _eastmoney_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data") or {}
    diff = data.get("diff") or []
    return list(diff.values()) if isinstance(diff, Mapping) else list(diff)


def _tencent_tail_spot(connection: Any, universe: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    codes = sorted(
        {
            str(item.get("code", "")).split(".")[0].zfill(6)
            for item in universe
            if str(item.get("code", "")).split(".")[0].zfill(6).startswith(MAIN_BOARD_PREFIXES)
        }
    )
    if not codes:
        raise ValueError("腾讯备用行情缺少可用的沪深主板股票池")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(codes), 60):
        batch = codes[offset : offset + 60]
        symbols = [("sh" if code.startswith("6") else "sz") + code for code in batch]
        response = connection.get(
            "https://qt.gtimg.cn/q=" + ",".join(symbols),
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
        )
        response.raise_for_status()
        response.encoding = "gbk"
        for line in response.text.splitlines():
            if '="' not in line:
                continue
            fields = line.split('="', 1)[1].rstrip('";').split("~")
            if len(fields) <= 44:
                continue
            code = str(fields[2]).zfill(6)
            if code not in batch:
                continue
            result[code] = {
                "code": code,
                "name": str(fields[1]).strip(),
                "price": _number(fields[3]),
                "change_pct": _number(fields[32]),
                "amplitude": _number(fields[43]),
                "turnover": _number(fields[38]),
                "float_market_cap": _number(fields[44]) * 100_000_000,
                "volume": _number(fields[36]),
                "timestamp": stamp,
                "source": "腾讯实时备用（不使用系统代理）",
            }
    minimum = max(1, math.ceil(len(codes) * 0.75))
    if len(result) < minimum:
        raise RuntimeError(f"腾讯备用行情覆盖不足:{len(result)}/{len(codes)}")
    return [result[code] for code in sorted(result)]


def fetch_tail_spot(session: Any = None, fallback_universe: Iterable[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """直连读取沪深实时字段；明确绕过失效的系统代理。"""
    connection = _no_proxy_session(session)
    endpoints = (
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
    )
    errors: list[str] = []
    # 该接口在实际运行中会把单页限制为100条；按真实上限分页，避免只取得第一页。
    page_size = 100
    for endpoint in endpoints:
        try:
            result: list[dict[str, Any]] = []
            page = 1
            total = page_size
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            seen_codes: set[str] = set()
            while page <= 100:
                params = {
                    "pn": page,
                    "pz": page_size,
                    "po": 1,
                    "np": 1,
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f3",
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                    "fields": "f2,f3,f5,f7,f8,f12,f14,f21",
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                }
                response = connection.get(
                    endpoint,
                    params=params,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data") or {}
                rows = _eastmoney_rows(payload)
                total = int(data.get("total") or len(rows))
                added = 0
                for source in rows:
                    code = str(source.get("f12", "")).split(".")[0].zfill(6)
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)
                    added += 1
                    result.append(
                        {
                            "code": code,
                            "name": str(source.get("f14", "")).strip(),
                            "price": _number(source.get("f2")),
                            "change_pct": _number(source.get("f3")),
                            "amplitude": _number(source.get("f7")),
                            "turnover": _number(source.get("f8")),
                            "float_market_cap": _number(source.get("f21")),
                            "volume": _number(source.get("f5")),
                            "timestamp": stamp,
                            "source": "东方财富直连（不使用系统代理）",
                        }
                    )
                if not rows or len(result) >= total:
                    break
                if not added:
                    raise RuntimeError(f"分页未推进:{len(result)}/{total}")
                page += 1
            expected_main = 0
            if fallback_universe is not None:
                expected_main = sum(
                    str(item.get("code", "")).split(".")[0].zfill(6).startswith(MAIN_BOARD_PREFIXES)
                    for item in fallback_universe
                )
            if result and (not expected_main or len(result) >= math.ceil(expected_main * 0.75)):
                return result
            if result:
                errors.append(endpoint + f":实时行情覆盖不足:{len(result)}/{expected_main}")
                continue
            errors.append(endpoint + ":返回空数据")
        except Exception as exc:
            errors.append(endpoint + ":" + str(exc)[:180])
    if fallback_universe is not None:
        try:
            return _tencent_tail_spot(connection, fallback_universe)
        except Exception as exc:
            errors.append("腾讯备用:" + str(exc)[:180])
    raise RuntimeError("全市场实时行情直连失败（已绕过系统代理）：" + "；".join(errors))


def fetch_tail_minutes(code: str, start: Any, end: Any, session: Any = None) -> pd.DataFrame:
    """直连读取近期1分钟K线；缓存调用方式保持不变。"""
    normalized_code = str(code).split(".")[0].zfill(6)
    connection = _no_proxy_session(session)
    endpoints = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "https://7.push2his.eastmoney.com/api/qt/stock/kline/get",
    )
    params = {
        "secid": ("1." if normalized_code.startswith("6") else "0.") + normalized_code,
        "klt": 1,
        "fqt": 0,
        "beg": pd.Timestamp(start).strftime("%Y%m%d%H%M%S"),
        "end": pd.Timestamp(end).strftime("%Y%m%d%H%M%S"),
        "lmt": 1000000,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    }
    errors: list[str] = []
    for endpoint in endpoints:
        try:
            response = connection.get(
                endpoint,
                params=params,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            klines = data.get("klines") or []
            records = []
            for raw in klines:
                fields = str(raw).split(",")
                if len(fields) < 7:
                    continue
                records.append(
                    {
                        "time": fields[0],
                        "open": fields[1],
                        "close": fields[2],
                        "high": fields[3],
                        "low": fields[4],
                        "volume": fields[5],
                        "amount": fields[6],
                    }
                )
            if records:
                frame = normalize_minute_frame(pd.DataFrame(records), normalized_code)
                frame.attrs["data_source"] = "东方财富分钟直连（不使用系统代理）"
                return frame
            empty = pd.DataFrame(columns=["code", "open", "high", "low", "close", "volume", "amount", "tradable"])
            empty.index = pd.DatetimeIndex([], name="time")
            empty.attrs["data_source"] = "东方财富分钟直连（无可用记录）"
            return empty
        except Exception as exc:
            errors.append(endpoint + ":" + str(exc)[:180])
    raise RuntimeError("1分钟行情直连失败（已绕过系统代理）：" + "；".join(errors))


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"无法序列化:{type(value).__name__}")


def save_tail_state(path: str | Path, state: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(state), ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    temporary.replace(target)
    return target


def load_tail_state(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"strategy_id": TAIL_STRATEGY_ID, "positions": {}, "transactions": []}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("strategy_id") not in (None, TAIL_STRATEGY_ID):
        raise ValueError("尾盘策略状态版本不兼容")
    payload["strategy_id"] = TAIL_STRATEGY_ID
    payload.setdefault("positions", {})
    payload.setdefault("transactions", [])
    return payload


def _minute_day_map(frame: pd.DataFrame) -> dict[date, pd.DataFrame]:
    if frame.empty:
        return {}
    return {session: group.copy() for session, group in frame.groupby(frame.index.date)}


def run_tail_backtest(
    candidate_snapshots: Iterable[Mapping[str, Any]],
    minute_store: TailCache,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """对已经冻结的每日候选快照运行共享现金、分钟精确回测。"""
    settings = {
        "initial_cash": 100_000.0,
        "top_n": 5,
        "max_position_pct": 20.0,
        "total_position_pct": 80.0,
        "commission": 0.0003,
        "min_commission": 5.0,
        "stamp": 0.0005,
        "slippage": 0.001,
    }
    settings.update(dict(config or {}))
    initial = float(settings["initial_cash"])
    if initial <= 0:
        raise ValueError("初始资金必须为正")
    top_n = max(1, int(settings["top_n"]))
    rows = [dict(row) for row in candidate_snapshots]
    groups: dict[date, list[dict[str, Any]]] = {}
    for row in rows:
        stamp = pd.to_datetime(row.get("timestamp"), errors="coerce")
        if pd.isna(stamp):
            continue
        groups.setdefault(stamp.date(), []).append(row)

    codes = sorted({str(row.get("code", "")).zfill(6) for row in rows if row.get("code")})
    minute_frames = {code: minute_store.load_minutes(code) for code in codes}
    calendar = sorted({session for frame in minute_frames.values() for session in frame.index.normalize().unique()})
    cash = initial
    minimum_cash = initial
    orders: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []

    def settle(before: pd.Timestamp | None = None, settle_all: bool = False) -> None:
        nonlocal cash, minimum_cash
        for order in orders:
            if order.get("settled") or not order.get("trade"):
                continue
            exit_time = order["trade"].get("exit_time")
            if exit_time is None:
                continue
            if settle_all or pd.Timestamp(exit_time) <= before:
                trade = dict(order["trade"])
                cash += trade["exit_price"] * trade["shares"] - trade["sell_fee"]
                order["settled"] = True
                trades.append(trade)
                minimum_cash = min(minimum_cash, cash)

    for session in sorted(groups):
        decision_time = pd.Timestamp.combine(session, time(14, 50))
        settle(before=decision_time)
        active = [order for order in orders if not order.get("settled")]
        active_exposure = sum(float(order["entry_amount"]) for order in active)
        estimated_equity = cash + active_exposure
        total_cap = estimated_equity * float(settings["total_position_pct"]) / 100
        per_name_pct = min(float(settings["max_position_pct"]), float(settings["total_position_pct"]) / top_n)
        ranked = rank_candidates(row for row in groups[session] if bool(row.get("passed", False)))[:top_n]
        for candidate in ranked:
            code = str(candidate["code"]).zfill(6)
            if any(order["code"] == code and not order.get("settled") for order in orders):
                errors.append({"code": code, "date": session.isoformat(), "error": "已有持仓"})
                continue
            frame = minute_frames.get(code, pd.DataFrame())
            buy_bars = frame.loc[frame.index.date == session] if not frame.empty else frame
            fill = entry_fill(buy_bars, slippage=float(settings["slippage"])) if not buy_bars.empty else None
            if fill is None:
                errors.append({"code": code, "date": session.isoformat(), "error": "14:55后无可成交分钟"})
                continue
            active = [order for order in orders if not order.get("settled")]
            active_exposure = sum(float(order["entry_amount"]) for order in active)
            estimated_equity = cash + active_exposure
            per_name_budget = estimated_equity * per_name_pct / 100
            remaining_cap = max(0.0, estimated_equity * float(settings["total_position_pct"]) / 100 - active_exposure)
            budget = min(cash, per_name_budget, remaining_cap)
            price = float(fill["price"])
            shares = int(budget / (price * 100)) * 100
            while shares > 0:
                amount = shares * price
                fee = _buy_fee(amount, settings)
                if amount + fee <= cash and amount <= budget + 1e-9:
                    break
                shares -= 100
            if shares <= 0:
                errors.append({"code": code, "date": session.isoformat(), "error": "资金不足100股"})
                continue
            entry_amount = shares * price
            buy_fee = _buy_fee(entry_amount, settings)
            cash -= entry_amount + buy_fee
            minimum_cash = min(minimum_cash, cash)
            try:
                trade = simulate_position(
                    {
                        "code": code,
                        "entry_time": fill["time"],
                        "entry_price": price,
                        "shares": shares,
                        "peak": price,
                        "trailing_armed": False,
                    },
                    _minute_day_map(frame),
                    calendar,
                    settings,
                )
            except Exception as exc:
                trade = None
                errors.append({"code": code, "date": session.isoformat(), "error": str(exc)})
            orders.append(
                {
                    "strategy_id": TAIL_STRATEGY_ID,
                    "code": code,
                    "name": candidate.get("name", ""),
                    "rank": ranked.index(candidate) + 1,
                    "signal_time": candidate.get("timestamp", ""),
                    "entry_time": fill["time"],
                    "entry_price": price,
                    "shares": shares,
                    "entry_amount": entry_amount,
                    "buy_fee": buy_fee,
                    "trade": trade,
                    "settled": False,
                }
            )
        open_cost = sum(float(order["entry_amount"]) for order in orders if not order.get("settled"))
        equity.append({"time": decision_time, "cash": cash, "open_cost": open_cost, "equity": cash + open_cost})

    settle(settle_all=True)
    for order in orders:
        if not order.get("settled"):
            trade = order.get("trade") or {}
            frame = minute_frames.get(order["code"], pd.DataFrame())
            last_price = float(frame.close.iloc[-1]) if not frame.empty else float(order["entry_price"])
            positions.append({
                "code": order["code"],
                "entry_time": order["entry_time"],
                "entry_price": order["entry_price"],
                "shares": order["shares"],
                "last_price": last_price,
                "market_value": last_price * int(order["shares"]),
                "status": trade.get("status", "仍持有"),
                "reason": trade.get("reason", "分钟数据不足"),
                "peak": trade.get("peak", order["entry_price"]),
                "trailing_armed": trade.get("trailing_armed", False),
            })
    open_value = sum(float(position["market_value"]) for position in positions)
    final_equity = cash + open_value
    public_orders = [{key: value for key, value in order.items() if key not in ("trade", "settled")} for order in orders]
    completed_returns = [trade["net_pnl"] for trade in trades]
    summary = {
        "strategy_id": TAIL_STRATEGY_ID,
        "exact_minute_only": True,
        "initial_cash": initial,
        "final_equity": final_equity,
        "net_profit": final_equity - initial,
        "return_pct": (final_equity / initial - 1) * 100,
        "minimum_cash": minimum_cash,
        "orders": len(public_orders),
        "completed_trades": len(trades),
        "open_positions": len(positions),
        "winning_trades": sum(value > 0 for value in completed_returns),
        "minute_calendar_days": len(calendar),
        "config": settings,
    }
    return {
        "summary": summary,
        "equity": equity,
        "orders": public_orders,
        "trades": trades,
        "positions": positions,
        "screen_audit": rows,
        "coverage": minute_store.coverage(),
        "errors": errors,
    }


def create_tail_audit_bundle(
    target: str | Path,
    result: Mapping[str, Any],
    cache_audit: Mapping[str, Any] | None = None,
) -> list[str]:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    manifest = {
        "strategy_id": TAIL_STRATEGY_ID,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary": result.get("summary", {}),
        "coverage": result.get("coverage", cache_audit or {}),
        "cache_audit": dict(cache_audit or {}),
    }
    files = {
        "tail_manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default),
        "tail_orders.csv": pd.DataFrame(result.get("orders", [])).to_csv(index=False),
        "tail_trades.csv": pd.DataFrame(result.get("trades", [])).to_csv(index=False),
        "tail_positions.csv": pd.DataFrame(result.get("positions", [])).to_csv(index=False),
        "tail_equity.csv": pd.DataFrame(result.get("equity", [])).to_csv(index=False),
        "tail_screen_audit.csv": pd.DataFrame(result.get("screen_audit", [])).to_csv(index=False),
        "tail_errors.csv": pd.DataFrame(result.get("errors", [])).to_csv(index=False),
    }
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8-sig") if name.endswith(".csv") else content.encode("utf-8"))
    temporary.replace(target)
    return list(files)
