"""Independent Sina qfq daily fallback, with bounded proxy-free transport.

Protocol reference: akfamily/akshare stock_zh_a_sina.py. Only actual daily
bars are retained; factor dates never become synthetic trading sessions.
"""
from __future__ import annotations

import pandas as pd


def normalize_sina_daily(rows, factors, start_year: int) -> pd.DataFrame:
    columns = ['date', 'open', 'close', 'high', 'low', 'volume']
    bars = pd.DataFrame(rows)
    if bars.empty or not set(columns) <= set(bars.columns):
        raise ValueError('新浪未返回完整日线')
    adjustment = pd.DataFrame(factors)
    if adjustment.empty or len(adjustment.columns) != 2:
        raise ValueError('新浪未返回有效前复权因子')
    adjustment.columns = ['date', 'factor']
    bars = bars[columns].copy()
    for frame in (bars, adjustment):
        frame['date'] = pd.to_datetime(frame['date'], utc=True).dt.tz_convert(None).dt.normalize()
        if frame.date.duplicated().any():
            raise ValueError('新浪日期重复')
    for column in columns[1:]:
        bars[column] = pd.to_numeric(bars[column], errors='raise')
    adjustment['factor'] = pd.to_numeric(adjustment.factor, errors='raise')
    if adjustment.factor.isna().any() or (adjustment.factor <= 0).any():
        raise ValueError('新浪前复权因子非正数')
    joined = pd.merge_asof(bars.sort_values('date'), adjustment.sort_values('date'),
                           on='date', direction='backward')
    joined = joined[joined.date.dt.year >= start_year].copy()
    if joined.empty or joined.factor.isna().any():
        raise ValueError('新浪前复权因子未覆盖历史行情')
    for column in ('open', 'close', 'high', 'low'):
        joined[column] = (joined[column] / joined.factor).round(2)
    # Sina returns shares; Tencent and EastMoney daily bars use lots of 100 shares.
    joined['volume'] = joined.volume / 100
    if (joined[['open', 'close', 'high', 'low']] <= 0).any().any() or (joined.volume < 0).any():
        raise ValueError('新浪价格或成交量无效')
    return joined[columns].reset_index(drop=True)


def fetch_sina_daily(symbol: str, session, start_year: int) -> pd.DataFrame:
    from akshare.stock.cons import hk_js_decode, zh_sina_a_stock_hist_url, zh_sina_a_stock_qfq_url
    from akshare.utils import demjson
    import py_mini_racer

    session.trust_env = False
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'}
    history = session.get(zh_sina_a_stock_hist_url.format(symbol), timeout=18, headers=headers)
    history.raise_for_status()
    import json
    encoded = json.loads(history.text.partition('=')[2].strip().rstrip(';'))
    engine = py_mini_racer.MiniRacer()
    try:
        engine.eval(hk_js_decode)
        rows = engine.call('d', encoded)
    finally:
        del engine
    response = session.get(zh_sina_a_stock_qfq_url.format(symbol), timeout=18, headers=headers)
    response.raise_for_status()
    # Parse the assignment as data; never execute the provider's JavaScript.
    payload = demjson.decode(response.text.partition('=')[2].strip().rstrip(';'))
    return normalize_sina_daily(rows, payload.get('data', []), start_year)


def fetch_sina_index(symbol: str, session, start_year: int) -> pd.DataFrame:
    """Independent index history used only to verify the closing session."""
    import json
    import py_mini_racer
    from akshare.index.cons import zh_sina_index_stock_hist_url
    from akshare.stock.cons import hk_js_decode

    session.trust_env = False
    response = session.get(zh_sina_index_stock_hist_url.format(symbol),
        params={'d':'2020_2_4'}, timeout=18, headers={'User-Agent':'Mozilla/5.0'})
    response.raise_for_status()
    encoded = json.loads(response.text.partition('=')[2].strip().rstrip(';'))
    engine = py_mini_racer.MiniRacer()
    try:
        engine.eval(hk_js_decode)
        rows = engine.call('d', encoded)
    finally:
        del engine
    frame = pd.DataFrame(rows)
    columns = ['date','open','close','high','low','volume']
    if frame.empty or not set(columns) <= set(frame.columns):
        raise ValueError('新浪指数未返回完整日线')
    frame = frame[columns].copy()
    frame['date'] = pd.to_datetime(frame.date, utc=True).dt.tz_convert(None).dt.normalize()
    for column in columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors='raise')
    return frame[frame.date.dt.year >= start_year].sort_values('date').reset_index(drop=True)
