import hashlib
import gzip
import json
import random
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
import requests
from PySide6.QtCore import QRectF, Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPicture
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
    QFileDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

try:
    from .tail_strategy import (
        TAIL_STRATEGY_ID, TailCache, create_tail_audit_bundle, entry_fill,
        evaluate_candidate, fetch_tail_minutes, fetch_tail_spot, import_minute_csv,
        is_main_board, load_tail_state, rank_candidates, run_tail_backtest,
        save_tail_state, simulate_position,
    )
except ImportError:
    from tail_strategy import (
        TAIL_STRATEGY_ID, TailCache, create_tail_audit_bundle, entry_fill,
        evaluate_candidate, fetch_tail_minutes, fetch_tail_spot, import_minute_csv,
        is_main_board, load_tail_state, rank_candidates, run_tail_backtest,
        save_tail_state, simulate_position,
    )

APP_DIR = Path(__file__).resolve().parent
CACHE_DIR = APP_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)
WATCH_FILE = APP_DIR / "watchlist.json"
PAPER_FILE = APP_DIR / "paper_account.json"
UNIVERSE_FILE = APP_DIR / "a_share_universe.json"
SCAN_CHECKPOINT = APP_DIR / "market_scan_checkpoint.json"
RESEARCH_SAMPLE_FILE = APP_DIR / "research_sample.json"
DATA_PREP_CHECKPOINT = APP_DIR / "research_data_checkpoint.json"
VALIDATION_SNAPSHOT_FILE = APP_DIR / "validation_snapshot_v1.json.gz"
VALIDATION_ENGINE_VERSION = "7.5-worldquant-ranking-v1"
TAIL_CACHE_DIR = APP_DIR / "tail_strategy_cache"
TAIL_STATE_FILE = APP_DIR / "tail_strategy_state.json"
APP_VERSION = "8.3.2"
ENTRY_RULES = ("1 推荐", "2 严格", "3 折中", "4 世坤因子")

INDUSTRY_MAP = {
    "600519":"白酒","000858":"白酒","000568":"白酒","600809":"白酒",
    "600036":"银行","601166":"银行","601398":"银行","601288":"银行","000001":"银行",
    "601318":"保险","600030":"券商","000776":"券商","600276":"医药",
    "601857":"能源","601088":"能源","603993":"有色","601899":"有色","600900":"电力",
    "600309":"化工","600887":"食品","600690":"家电","000333":"家电","000651":"家电",
    "600104":"汽车","601012":"光伏","600438":"光伏","000725":"面板","000938":"计算机",
    "002594":"汽车","300750":"电池","300014":"机器人","300015":"医疗器械",
    "300059":"互联网金融","300122":"医疗服务","300124":"半导体","002156":"半导体",
    "002050":"通信","002230":"软件","002241":"消费电子","002371":"安防",
    "002415":"安防","002475":"消费电子","002027":"零售","002142":"银行",
    "002179":"材料","002304":"食品","002352":"软件","002460":"锂资源",
    "002714":"食品","002812":"汽车零部件","001979":"地产"
}
SAMPLE_50 = ("600519,603993,601318,600036,600276,600030,601166,601398,601288,601857,"
             "601899,601088,600900,600309,600887,600809,600690,600104,601012,600438,"
             "000001,000333,000651,000858,000568,000725,000776,000938,001979,002027,"
             "002050,002142,002179,002230,002241,002304,002352,002371,002415,002460,"
             "002475,002594,002714,002812,300014,300015,300059,300122,300124,300750")

STYLE = """
QWidget { background:#0b1220; color:#dbeafe; font-family:'Microsoft YaHei'; font-size:14px; }
QFrame#card { background:#111c2e; border:1px solid #20304a; border-radius:10px; }
QLabel#title { font-size:22px; font-weight:700; color:#f8fafc; }
QLabel#good { color:#ef4444; font-size:16px; font-weight:700; }
QLabel#bad { color:#22c55e; font-size:16px; font-weight:700; }
QListWidget { background:#0f1a2b; border:0; padding:8px; }
QListWidget::item { padding:13px; border-radius:7px; }
QListWidget::item:selected { background:#2563eb; color:white; }
QTableWidget { background:#111c2e; border:0; gridline-color:#20304a; }
QHeaderView::section { background:#162338; color:#dbeafe; padding:8px; border:0; }
QTabWidget::pane { background:#111c2e; border:1px solid #29405f; top:-1px; }
QTabBar::tab { background:#162338; color:#dbeafe; border:1px solid #29405f; padding:10px 16px; min-width:108px; font-weight:600; }
QTabBar::tab:hover { background:#1e3a5f; color:#ffffff; }
QTabBar::tab:selected { background:#2563eb; color:#ffffff; border-color:#3b82f6; }
QPushButton { background:#2563eb; color:white; padding:9px 16px; border:0; border-radius:7px; }
QPushButton:hover { background:#3b82f6; }
QPushButton#danger { background:#b91c1c; }
QPushButton#danger:hover { background:#dc2626; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QPlainTextEdit { background:#111c2e; border:1px solid #29405f; padding:8px; border-radius:6px; }
"""


def symbol(code):
    if code.startswith(("5", "6")): return "sh" + code
    if code.startswith(("0", "3")): return "sz" + code
    if code.startswith(("4", "8", "9")): return "bj" + code
    raise ValueError("不支持该股票代码")


def fetch_quotes(codes):
    """读取腾讯实时行情；单只解析失败时由调用方使用历史收盘价回退。"""
    valid = [c for c in codes if len(c) == 6 and c.isdigit()]
    if not valid:
        return {}
    session = requests.Session(); session.trust_env = False
    response = session.get("https://qt.gtimg.cn/q=" + ",".join(symbol(c) for c in valid),
                           timeout=15, headers={"User-Agent":"Mozilla/5.0"})
    response.raise_for_status(); response.encoding = "gbk"
    quotes = {}
    for line in response.text.splitlines():
        if '="' not in line:
            continue
        fields = line.split('="', 1)[1].rstrip('";').split("~")
        if len(fields) < 6 or len(fields[2]) != 6:
            continue
        try:
            price = float(fields[3]); previous = float(fields[4]); opened = float(fields[5])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        quotes[fields[2]] = {"name":fields[1], "price":price, "previous":previous,
                             "open":opened, "time":fields[30] if len(fields) > 30 else ""}
    return quotes


def valid_a_share(code):
    """仅保留沪、深、北交易所普通A股常见代码段。"""
    return len(code) == 6 and code.isdigit() and code.startswith((
        "600","601","603","605","688","689", "000","001","002","003","300","301",
        "4","8","9"))


def clean_universe(rows, *, include_st=False):
    cleaned = {}
    for row in rows:
        code = str(row.get("code", "")).split(".")[0].zfill(6)
        name = str(row.get("name", "")).strip()
        if not valid_a_share(code) or not name:
            continue
        upper = name.upper().replace(" ", "")
        if not include_st and ("ST" in upper or "退" in name):
            continue
        exchange = "沪" if code.startswith("6") else ("深" if code.startswith(("0","3")) else "北")
        cleaned[code] = {"code":code, "name":name, "exchange":exchange}
    return [cleaned[k] for k in sorted(cleaned)]


def fetch_sina_universe():
    """新浪行情中心作为无需密钥的沪深股票列表备用源。"""
    session = requests.Session(); session.trust_env = False; rows = []
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    for page in range(1, 80):
        response = session.get(url, params={"page":page,"num":100,"sort":"symbol","asc":1,
                               "node":"hs_a","symbol":"","_s_r_a":"page"},
                               timeout=20, headers={"User-Agent":"Mozilla/5.0"})
        response.raise_for_status(); data = response.json()
        if not data: break
        for item in data:
            code = str(item.get("code") or item.get("symbol", "")).replace("sh","").replace("sz","")
            rows.append({"code":code, "name":item.get("name", "")})
        if len(data) < 100: break
    return rows


def fetch_market_universe(force=False, *, include_st=False, persist=True):
    """获取全A列表并按日缓存；优先AKShare全A接口，失败后使用新浪沪深接口。"""
    today = datetime.now().strftime("%Y-%m-%d")
    if UNIVERSE_FILE.exists() and not force:
        try:
            payload = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
            stocks = clean_universe(payload.get("stocks", []), include_st=include_st)
            if stocks and payload.get("updated") == today and (not include_st or payload.get("includes_st")):
                return stocks, "今日本地股票池"
        except Exception:
            pass
    rows, sources, failures = [], [], []
    try:
        import akshare as ak
        frame = ak.stock_info_a_code_name()
        code_col = next((c for c in frame.columns if str(c) in ("code","代码","证券代码")), None)
        name_col = next((c for c in frame.columns if str(c) in ("name","名称","证券简称")), None)
        if code_col is None or name_col is None: raise ValueError("全A列表字段无法识别")
        rows.extend({"code":str(r[code_col]),"name":str(r[name_col])} for _,r in frame.iterrows())
        sources.append("AKShare全A")
        if not any(str(r["code"]).split(".")[0].zfill(6).startswith(("4","8","9")) for r in rows):
            try:
                bj=ak.stock_info_bj_name_code()
                bj_code=next((c for c in bj.columns if str(c) in ("code","代码","证券代码")),None)
                bj_name=next((c for c in bj.columns if str(c) in ("name","名称","证券简称")),None)
                if bj_code is not None and bj_name is not None:
                    rows.extend({"code":str(r[bj_code]),"name":str(r[bj_name])} for _,r in bj.iterrows()); sources.append("北交所列表")
            except Exception: pass
    except Exception as exc:
        failures.append("AKShare:" + str(exc)[:80])
    if not rows:
        try:
            rows.extend(fetch_sina_universe()); sources.append("新浪沪深")
        except Exception as exc:
            failures.append("新浪:" + str(exc)[:80])
    stocks = clean_universe(rows, include_st=True)
    if not stocks and UNIVERSE_FILE.exists():
        try:
            old = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8")); stocks = clean_universe(old.get("stocks", []), include_st=include_st)
            if stocks and not include_st: return stocks, "过期本地股票池（在线更新失败）"
        except Exception: pass
    if not stocks:
        raise RuntimeError("全市场股票列表读取失败：" + "；".join(failures))
    payload = {"updated":today, "source":"+".join(sources), "stocks":stocks, "includes_st":True}
    if persist:
        temporary = UNIVERSE_FILE.with_suffix(".tmp"); temporary.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8"); temporary.replace(UNIVERSE_FILE)
    return clean_universe(stocks, include_st=include_st), payload["source"]


def stratified_research_sample(stocks, size=300):
    """按板块轮转抽样，避免仅按代码排序集中在单一市场。"""
    groups=[[],[],[],[],[]]
    for item in stocks:
        code=item["code"]
        if code.startswith(("600","601","603","605")): groups[0].append(item)
        elif code.startswith(("000","001","002","003")): groups[1].append(item)
        elif code.startswith(("300","301")): groups[2].append(item)
        elif code.startswith("688"): groups[3].append(item)
        else: groups[4].append(item)
    chosen=[]; cursors=[0]*len(groups)
    while len(chosen)<min(size,sum(map(len,groups))):
        advanced=False
        for i,group in enumerate(groups):
            if cursors[i]<len(group) and len(chosen)<size:
                chosen.append(group[cursors[i]]); cursors[i]+=1; advanced=True
        if not advanced: break
    return chosen


def research_candidate_queue(stocks, size=300):
    """原始分层样本在前，其余股票作为确定性替补候选。"""
    primary=stratified_research_sample(stocks,size); primary_codes={x["code"] for x in primary}
    return primary+[x for x in stocks if x["code"] not in primary_codes],primary_codes


def strict_sample_gate(input_codes, sample_payload, loaded_codes=None, target=300):
    """Validate the immutable prepared-sample contract used by a strict research run."""
    input_codes=list(input_codes); input_unique=list(dict.fromkeys(input_codes))
    prepared=[str(row.get("代码", "")) for row in sample_payload.get("stocks", []) if row.get("代码")]
    prepared_unique=list(dict.fromkeys(prepared))
    if len(input_codes)!=len(input_unique):
        raise ValueError("严格300门禁失败：界面股票池包含重复代码")
    if not sample_payload.get("qualified") or int(sample_payload.get("target_success",0))!=target or len(prepared_unique)!=target:
        raise ValueError(f"严格300门禁失败：准备样本{len(prepared_unique)}/{target}，请先在数据准备中心补齐")
    if len(input_unique)!=target or set(input_unique)!=set(prepared_unique):
        missing=sorted(set(prepared_unique)-set(input_unique)); extra=sorted(set(input_unique)-set(prepared_unique))
        detail=f"缺少{','.join(missing[:8]) or '--'}；多出{','.join(extra[:8]) or '--'}"
        raise ValueError(f"严格300门禁失败：界面股票池与准备样本不一致（{detail}）")
    counts={"输入代码":len(input_unique),"准备样本":len(prepared_unique)}
    if loaded_codes is not None:
        loaded_unique=list(dict.fromkeys(loaded_codes)); missing=sorted(set(prepared_unique)-set(loaded_unique))
        if len(loaded_unique)!=target or set(loaded_unique)!=set(prepared_unique):
            raise ValueError(f"严格300门禁失败：信号成功{len(loaded_unique)}/{target}；缺失{','.join(missing[:12]) or '--'}")
        counts["信号成功"]=len(loaded_unique)
    return counts


def readable_eta(seconds):
    seconds=max(0,int(seconds))
    if seconds<60: return f"{seconds}秒"
    minutes,sec=divmod(seconds,60)
    if minutes<60: return f"{minutes}分{sec}秒"
    hours,minutes=divmod(minutes,60); return f"{hours}小时{minutes}分"


def market_regime(day, mode="严格"):
    """三档大盘过滤：关闭、宽松（站上20周线）、严格（均线多头）。"""
    if mode == "关闭":
        return True
    w = weekly_data(day)
    if len(w) < 21:
        return False
    cur, prev = w.iloc[-1], w.iloc[-2]
    if mode == "宽松":
        return bool(cur.close > cur.ma20)
    return bool(cur.close > cur.ma20 and cur.ma5 > cur.ma10 > cur.ma20 and cur.ma20 >= prev.ma20)


def indicators(day):
    d = day.copy()
    for n in (5, 10, 20, 60):
        d[f"ma{n}"] = d.close.rolling(n).mean()
    ema12, ema26 = d.close.ewm(span=12, adjust=False).mean(), d.close.ewm(span=26, adjust=False).mean()
    d["dif"] = ema12 - ema26
    d["dea"] = d.dif.ewm(span=9, adjust=False).mean()
    d["macd"] = 2 * (d.dif - d.dea)
    low9, high9 = d.low.rolling(9).min(), d.high.rolling(9).max()
    rsv = (d.close - low9) / (high9 - low9).replace(0, np.nan) * 100
    d["k"] = rsv.ewm(com=2, adjust=False).mean()
    d["d"] = d.k.ewm(com=2, adjust=False).mean()
    d["j"] = 3 * d.k - 2 * d.d
    return d


def weekly_data(day):
    w = day.resample("W-FRI").agg({"open":"first", "high":"max", "low":"min", "close":"last", "volume":"sum"}).dropna()
    for n in (5, 10, 20):
        w[f"ma{n}"] = w.close.rolling(n).mean()
    return w


def last_swings(w, span=2):
    highs, lows = [], []
    for i in range(span, len(w) - span):
        if w.high.iloc[i] >= w.high.iloc[i-span:i+span+1].max(): highs.append(float(w.high.iloc[i]))
        if w.low.iloc[i] <= w.low.iloc[i-span:i+span+1].min(): lows.append(float(w.low.iloc[i]))
            
    return highs[-2:], lows[-2:]


def evaluate(day):
    d, w = indicators(day), weekly_data(day)
    if len(d) < 65 or len(w) < 25:
        raise ValueError("历史数据不足，无法计算策略")
    cur, prev = w.iloc[-1], w.iloc[-2]
    ma_order = cur.ma5 > cur.ma10 > cur.ma20
    ma_up = cur.ma5 > prev.ma5 and cur.ma10 > prev.ma10 and cur.ma20 > prev.ma20
    above20 = bool((w.close.iloc[-2:] > w.ma20.iloc[-2:]).all())
    highs, lows = last_swings(w)
    waves = len(highs) == 2 and len(lows) == 2 and highs[1] > highs[0] and lows[1] > lows[0]
    trend = bool(ma_order and ma_up and above20 and waves)
    avg5 = float(w.volume.iloc[-6:-1].mean())
    ratio = float(cur.volume / avg5) if avg5 else 0
    prior_high = float(w.high.iloc[-21:-1].max())
    breakout = bool(cur.close > prior_high)
    breakout_volume = bool(breakout and ratio >= 1.5)
    golden = bool(cur.ma5 > cur.ma10 and prev.ma5 <= prev.ma10)
    support = max(float(cur.ma10), float(cur.ma20))
    pullback = bool(cur.low <= support * 1.02 and cur.close >= support)
    rising_volume = bool(cur.volume > prev.volume)
    last, yesterday = d.iloc[-1], d.iloc[-2]
    above_day_ma = bool(last.close > last.ma20 and last.close > last.ma5)
    engulf = bool(yesterday.close < yesterday.open and last.close > last.open and last.open <= yesterday.close and last.close >= yesterday.open)
    day_volume = bool(last.volume > d.volume.iloc[-6:-1].mean())
    buy_watch = bool(trend and above_day_ma and engulf)
    strong_buy = bool(buy_watch and day_volume and (breakout_volume or ((golden or pullback) and rising_volume)))
    ma5_down = bool(cur.ma5 < prev.ma5)
    below10 = bool(cur.close < cur.ma10)
    stop = float(min(lows[-1] if lows else w.low.iloc[-8:].min(), cur.close) * 0.97)
    return d, w, {
        "周线均线多头并向上": ma_order and ma_up,
        "连续两周站稳20周线": above20,
        "周线波峰波谷依次抬高": waves,
        "周线多头前提": trend,
        "突破前高": breakout,
        "突破量能≥5周均量1.5倍": breakout_volume,
        "周线金叉或回踩支撑": golden or pullback,
        "周线量能逐步放大": rising_volume,
        "日线站上MA5和MA20": above_day_ma,
        "日线阳包阴": engulf,
        "日线成交量高于5日均量": day_volume,
        "买入观察通知": buy_watch,
        "强确认买入通知": strong_buy,
        "逐步止盈信号": ma5_down or below10,
        "止损参考价": stop,
        "周量比": ratio,
        "MACD": float(last.macd),
        "KDJ": (float(last.k), float(last.d), float(last.j)),
    }


def eastmoney_secid(code, market_symbol=None):
    raw=(market_symbol or code).replace("sh","").replace("sz","").replace("bj","").replace("INDEX_","")
    return ("1." if (market_symbol or "").startswith("sh") or code.startswith("6") else "0.")+raw


def parse_eastmoney_klines(klines):
    return pd.DataFrame([x.split(",")[:6] for x in klines],columns=["date","open","close","high","low","volume"])


def fetch_history(code, count=1000, start_year=2018, market_symbol=None, force_refresh=False,
                  progress_callback=None, persist=True, min_rows=120):
    """多源读取前复权日线：缓存、腾讯、东方财富、AKShare、BaoStock。"""
    def report(**payload):
        if progress_callback:
            progress_callback(payload)

    cache_file = CACHE_DIR / f"{code}.csv"
    if cache_file.exists() and not force_refresh:
        try:
            cached = pd.read_csv(cache_file, parse_dates=["date"]).set_index("date").sort_index()
            recent_enough = (pd.Timestamp.now().normalize() - cached.index[-1]).days <= 10
            starts_early = cached.index[0].year <= start_year
            if recent_enough and starts_early and len(cached) >= 120:
                cached.attrs["data_source"]="本地缓存"
                report(stage="使用本地缓存", source="本地缓存")
                return cached
        except Exception:
            pass
    s = market_symbol or symbol(code)
    session = requests.Session(); session.trust_env = False; all_rows = []; source_used=""; source_errors=[]

    def usable(candidate, source):
        """Reject a truncated provider response so the next source can try."""
        try:
            candidate = candidate.copy()
            candidate['date'] = pd.to_datetime(candidate['date'])
            for column in ('open', 'close', 'high', 'low', 'volume'):
                candidate[column] = pd.to_numeric(candidate[column], errors='coerce')
            candidate = candidate.dropna().drop_duplicates('date').set_index('date').sort_index()
            if len(candidate) < min_rows:
                raise ValueError(f'有效历史行情不足：{len(candidate)}行')
            return candidate
        except (KeyError, ValueError, TypeError) as exc:
            source_errors.append(source + ':' + str(exc)[:100])
            report(stage='数据源结果不足，切换备用源', source=source, detail=str(exc)[:100])
            return None
    current_year = datetime.now().year
    try:
        for year in range(start_year, current_year + 1, 2):
            start, end = f"{year}-01-01", f"{min(year+1,current_year)}-12-31"
            for attempt in range(1, 4):
                try:
                    report(stage="请求腾讯行情", source="腾讯", attempt=attempt, request=1, detail=f"{start} 至 {end}")
                    response = session.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                        params={"param":f"{s},day,{start},{end},640,qfq"}, timeout=18,
                        headers={"User-Agent":"Mozilla/5.0", "Referer":"https://gu.qq.com/"})
                    response.raise_for_status(); block=response.json().get("data",{}).get(s,{})
                    rows=block.get("qfqday") or block.get("day") or []
                    if not rows: raise RuntimeError("腾讯接口未返回该时段数据")
                    all_rows.extend(rows); break
                except Exception as exc:
                    if attempt >= 3: raise
                    wait=(2,5)[attempt-1]+random.uniform(0,.8)
                    report(stage="接口限流退避", source="腾讯", retry=1, wait=wait, detail=f"{type(exc).__name__}，{wait:.1f}秒后重试")
                    time.sleep(wait)
            time.sleep(random.uniform(.35,.75))
    except Exception as exc:
        source_errors.append("腾讯:"+str(exc)[:100]); all_rows=[]

    frame = None
    if all_rows:
        frame = usable(pd.DataFrame([r[:6] for r in all_rows],
            columns=['date','open','close','high','low','volume']), '腾讯')
        if frame is not None: source_used = '腾讯'
    if frame is None:
        try:
            secid=eastmoney_secid(code,market_symbol)
            report(stage="切换第二数据源",source="东方财富直连",request=1,detail=f"查询 {secid} 的前复权日线")
            response=session.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",params={
                "secid":secid,"klt":"101","fqt":"1","beg":f"{start_year}0101","end":datetime.now().strftime("%Y%m%d"),
                "fields1":"f1,f2,f3,f4,f5,f6","fields2":"f51,f52,f53,f54,f55,f56"},
                timeout=22,headers={"User-Agent":"Mozilla/5.0","Referer":"https://quote.eastmoney.com/"})
            response.raise_for_status(); klines=(response.json().get("data") or {}).get("klines") or []
            if not klines: raise RuntimeError("东方财富直连接口未返回日线")
            frame=usable(parse_eastmoney_klines(klines), '东方财富直连')
            if frame is not None: source_used='东方财富直连'
        except Exception as exc:
            source_errors.append("东方财富直连:"+str(exc)[:100]); frame=None

    if frame is None:
        try:
            report(stage="切换第三数据源", source="AKShare兼容层", request=1, detail="使用AKShare标准历史接口")
            import akshare as ak
            if market_symbol:
                backup=ak.stock_zh_index_daily_em(symbol=market_symbol)
            else:
                backup=ak.stock_zh_a_hist(symbol=code, period="daily", start_date=f"{start_year}0101",
                                          end_date=datetime.now().strftime("%Y%m%d"), adjust="qfq")
            backup=backup.rename(columns={"date":"日期","open":"开盘","close":"收盘","high":"最高","low":"最低","volume":"成交量"})
            mapping={"日期":"date","开盘":"open","收盘":"close","最高":"high","最低":"low","成交量":"volume"}
            if backup is None or backup.empty or not set(mapping).issubset(backup.columns):
                raise RuntimeError("备用接口未返回完整日线")
            frame=usable(backup.rename(columns=mapping)[list(mapping.values())], 'AKShare兼容层')
            if frame is not None: source_used='AKShare兼容层'
        except Exception as exc:
            source_errors.append("AKShare:"+str(exc)[:100]); frame=None

    if frame is None and not market_symbol and code.startswith(("0","3","6")):
        bs=None
        try:
            report(stage="切换第四数据源",source="BaoStock",request=1,detail="使用独立证券宝历史接口")
            import baostock as bs
            login=bs.login()
            if str(login.error_code)!="0": raise RuntimeError("登录失败:"+str(login.error_msg))
            bs_code=("sh." if code.startswith("6") else "sz.")+code
            result=bs.query_history_k_data_plus(bs_code,"date,open,high,low,close,volume",start_date=f"{start_year}-01-01",end_date=datetime.now().strftime("%Y-%m-%d"),frequency="d",adjustflag="2")
            rows=[]
            while result.error_code=="0" and result.next(): rows.append(result.get_row_data())
            if not rows: raise RuntimeError("BaoStock未返回日线:"+str(result.error_msg))
            frame=usable(pd.DataFrame(rows,columns=["date","open","high","low","close","volume"])
                [["date","open","close","high","low","volume"]], 'BaoStock')
            if frame is not None: source_used='BaoStock'
        except Exception as exc:
            source_errors.append("BaoStock:"+str(exc)[:100]); frame=None
        finally:
            if bs is not None:
                try: bs.logout()
                except Exception: pass

    if frame is None:
        raise RuntimeError("｜".join(source_errors))
    frame.attrs["data_source"]=source_used; report(stage="数据源成功",source=source_used,detail=f"取得{len(frame)}行")
    if persist:
        frame.to_csv(cache_file)
    return frame


def fetch_market_history(start_year=2018):
    return fetch_history("INDEX_000300", start_year=start_year, market_symbol="sh000300")


def load_prepared_history(code, start_year=2018):
    """Read a qualified frozen cache without requiring pre-listing history."""
    cache_file=CACHE_DIR/f"{code}.csv"
    if not cache_file.exists():
        raise FileNotFoundError("准备缓存不存在")
    frame=pd.read_csv(cache_file,parse_dates=["date"]).drop_duplicates("date").set_index("date").sort_index()
    required={"open","close","high","low","volume"}; missing=required-set(frame.columns)
    if missing: raise ValueError("准备缓存缺少字段:"+",".join(sorted(missing)))
    for column in required: frame[column]=pd.to_numeric(frame[column],errors="coerce")
    frame=frame.dropna(subset=sorted(required))
    if len(frame)<260: raise ValueError(f"准备缓存历史不足260日：{len(frame)}行")
    frame.attrs["data_source"]="冻结准备缓存"
    frame.attrs["listed_after_research_start"]=frame.index.min().year>start_year
    return frame


def create_safe_upload_bundle(bundle_path, candidate_files):
    """Create a support bundle from audit outputs only; never include private account files."""
    bundle_path=Path(bundle_path)
    blocked={"paper_account.json","watchlist.json","broker_account.json","broker_config.json"}
    allowed=[]
    for value in candidate_files:
        path=Path(value)
        name=path.name
        if name in blocked or not path.is_file():
            continue
        if name=="research_sample.json" or name.startswith("dual_engine_validation_"):
            allowed.append(path)
    if not allowed:
        raise ValueError("没有找到可打包的验证结果")
    bundle_path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(bundle_path,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for path in allowed:
            archive.write(path,arcname=path.name)
    return [path.name for path in allowed]


def snapshot_cache_key(codes,config,cache_dir,engine_version):
    """Fingerprint every input that can change a validation result."""
    digest=hashlib.sha256()
    digest.update(str(engine_version).encode("utf-8"))
    digest.update(json.dumps(config,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8"))
    digest.update(("ordered_codes:"+",".join(codes)).encode("utf-8"))
    cache_dir=Path(cache_dir)
    for code in sorted(set(list(codes)+["INDEX_000300","510300"])):
        path=cache_dir/f"{code}.csv"
        if path.exists():
            stat=path.stat(); marker=f"{code}:{stat.st_size}:{stat.st_mtime_ns}"
        else:
            marker=f"{code}:missing"
        digest.update(marker.encode("utf-8"))
    return digest.hexdigest()


def _snapshot_encode(value):
    if isinstance(value,pd.DataFrame):
        return {"__snapshot_type__":"dataframe","index":_snapshot_encode(list(value.index)),"index_name":value.index.name,
                "columns":_snapshot_encode(list(value.columns)),"data":_snapshot_encode(value.to_numpy().tolist())}
    if isinstance(value,pd.Series):
        return {"__snapshot_type__":"series","index":_snapshot_encode(list(value.index)),"index_name":value.index.name,
                "name":value.name,"data":_snapshot_encode(value.tolist())}
    if isinstance(value,(pd.Timestamp,datetime)):
        return {"__snapshot_type__":"timestamp","value":pd.Timestamp(value).isoformat()}
    if isinstance(value,np.generic):
        return _snapshot_encode(value.item())
    if isinstance(value,dict):
        return {str(key):_snapshot_encode(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):
        return [_snapshot_encode(item) for item in value]
    return value


def _snapshot_decode(value):
    if isinstance(value,list):
        return [_snapshot_decode(item) for item in value]
    if not isinstance(value,dict):
        return value
    kind=value.get("__snapshot_type__")
    if kind=="timestamp":
        return pd.Timestamp(value["value"])
    if kind=="dataframe":
        frame=pd.DataFrame(_snapshot_decode(value["data"]),index=_snapshot_decode(value["index"]),columns=_snapshot_decode(value["columns"]))
        frame.index.name=value.get("index_name"); return frame
    if kind=="series":
        series=pd.Series(_snapshot_decode(value["data"]),index=_snapshot_decode(value["index"]),name=value.get("name"))
        series.index.name=value.get("index_name"); return series
    return {key:_snapshot_decode(item) for key,item in value.items()}


def save_validation_snapshot(path,payload,cache_key):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_name(path.name+".tmp")
    envelope={"format":1,"cache_key":cache_key,"saved_at":datetime.now().isoformat(timespec="seconds"),"payload":_snapshot_encode(payload)}
    with gzip.open(temporary,"wt",encoding="utf-8") as handle:
        json.dump(envelope,handle,ensure_ascii=False,separators=(",",":"),allow_nan=True)
    temporary.replace(path)


def load_validation_snapshot(path,expected_key):
    path=Path(path)
    if not path.exists(): raise FileNotFoundError("尚未保存验证快照，请先完整运行一次")
    with gzip.open(path,"rt",encoding="utf-8") as handle:
        envelope=json.load(handle)
    if envelope.get("format")!=1: raise ValueError("快照格式不兼容，请重新验证")
    if envelope.get("cache_key")!=expected_key: raise ValueError("快照条件已变化，请重新运行验证")
    return _snapshot_decode(envelope["payload"])


class HistoryWorker(QThread):
    success = Signal(str, object)
    failure = Signal(str)
    def __init__(self, code): super().__init__(); self.code = code
    def run(self):
        try: self.success.emit(self.code, fetch_history(self.code))
        except Exception as exc:
            cache = CACHE_DIR / f"{self.code}.csv"
            if cache.exists():
                try:
                    d = pd.read_csv(cache, parse_dates=["date"]).set_index("date")
                    self.success.emit(self.code, d); return
                except Exception: pass
            self.failure.emit(str(exc))


class CandleItem(pg.GraphicsObject):
    def __init__(self, data):
        super().__init__(); self.picture = QPicture(); self.data = data; self.generate()
    def generate(self):
        p = QPainter(self.picture); width = 0.32
        for i, row in enumerate(self.data.itertuples()):
            color = QColor("#ef4444" if row.close >= row.open else "#22c55e")
            p.setPen(pg.mkPen(color)); p.drawLine(i, row.low, i, row.high)
            p.setBrush(color); p.drawRect(QRectF(i-width, min(row.open,row.close), width*2, max(abs(row.close-row.open), .01)))
        p.end()
    def paint(self, painter, option, widget=None): painter.drawPicture(0, 0, self.picture)
    def boundingRect(self): return QRectF(self.picture.boundingRect())


def backtest(raw, initial=100000, position_pct=20, commission=0.0003, stamp=0.0005,
             slippage=0.001, require_strong=False, risk_pct=0.8,
             market=None, market_mode="严格", evaluation_start=None):
    """周末确认信号，下一交易日开盘成交；持仓按100股整数手。"""
    data = raw.copy().sort_index()
    cash, shares, entry, stop = float(initial), 0, 0.0, 0.0
    pending_buy = pending_exit = False
    setup_days, setup_stop = 0, 0.0
    weekly_candidates = daily_confirmations = 0
    weekly_trend_days = daily_ma_days = engulf_days = volume_days = strong_confirmations = 0
    trades, equity = [], []
    current_trade = None
    market_pass_weeks = market_blocked = raw_candidates = 0
    evaluation_start = pd.Timestamp(evaluation_start) if evaluation_start else data.index[0]
    for i in range(130, len(data)):
        row = data.iloc[i]
        date = data.index[i]
        if setup_days > 0: setup_days -= 1
        if pending_exit and shares:
            price = float(row.open) * (1 - slippage); amount = shares * price
            fee = max(5.0, amount * commission) + amount * stamp
            cash += amount - fee
            pnl = amount - fee - current_trade["cost"]
            trades.append({**current_trade, "sell_date":date, "sell_price":price,
                           "pnl":pnl, "return":(price-entry)/entry*100, "reason":"趋势离场",
                           "holding_days":i-current_trade["buy_i"]})
            shares = 0; current_trade = None; pending_exit = False
        if pending_buy and not shares:
            price = float(row.open) * (1 + slippage)
            per_share_risk = max(price - stop, price * 0.005)
            risk_qty = int((cash * risk_pct / 100) / per_share_risk / 100) * 100
            cap_qty = int((cash * position_pct / 100) / (price * 100)) * 100
            qty = min(risk_qty, cap_qty)
            if qty > 0:
                amount = qty * price; fee = max(5.0, amount * commission)
                if amount + fee <= cash:
                    reserved = cash - amount - fee; cash = reserved; shares = qty; entry = price
                    current_trade = {"buy_date":date, "buy_price":price, "shares":qty,
                                     "cost":amount + fee, "stop":stop, "buy_i":i,
                                     "planned_risk":qty * per_share_risk, "mae":0.0, "mfe":0.0}
            pending_buy = False
        if shares and float(row.low) <= stop:
            price = min(float(row.open), stop) * (1 - slippage); amount = shares * price
            fee = max(5.0, amount * commission) + amount * stamp; cash += amount - fee
            pnl = amount - fee - current_trade["cost"]
            trades.append({**current_trade, "sell_date":date, "sell_price":price,
                           "pnl":pnl, "return":(price-entry)/entry*100,
                           "reason":"跳空止损" if float(row.open) < stop else "周线低点止损",
                           "holding_days":i-current_trade["buy_i"]})
            shares = 0; current_trade = None; pending_exit = False
        if shares:
            current_trade["mae"] = min(current_trade["mae"], (float(row.low)/entry-1)*100)
            current_trade["mfe"] = max(current_trade["mfe"], (float(row.high)/entry-1)*100)
        equity.append((date, cash + shares * float(row.close)))
        is_week_end = i == len(data)-1 or data.index[i+1].to_period("W-FRI") != date.to_period("W-FRI")
        if is_week_end:
            try:
                _, _, result = evaluate(data.iloc[:i+1])
                in_validation = date >= evaluation_start
                if shares and result["逐步止盈信号"]: pending_exit = True
                if shares:
                    stop = max(stop, min(result["止损参考价"], float(row.close) * 0.99))
                    current_trade["stop"] = stop
                weekly_setup = result["周线多头前提"] and (
                    result["突破量能≥5周均量1.5倍"] or
                    (result["周线金叉或回踩支撑"] and result["周线量能逐步放大"])
                )
                if result["周线多头前提"] and in_validation: weekly_trend_days += 1
                if result["周线多头前提"] and in_validation:
                    raw_candidates += 1
                market_ok = market_mode == "关闭"
                if market_mode != "关闭" and market is not None:
                    ms = market.loc[:date]
                    market_ok = market_regime(ms, market_mode) if len(ms) >= 100 else False
                if result["周线多头前提"] and in_validation and market_ok: market_pass_weeks += 1
                elif result["周线多头前提"] and in_validation and not market_ok: market_blocked += 1
                if not result["周线多头前提"] or not market_ok: setup_days = 0
                elif not shares and date >= evaluation_start:
                    setup_days = 20; setup_stop = result["止损参考价"]
                    if weekly_setup: weekly_candidates += 1
            except ValueError: pass
        if not shares and not pending_buy and setup_days > 0:
            d = indicators(data.iloc[:i+1]); last, yesterday = d.iloc[-1], d.iloc[-2]
            above_ma = last.close > last.ma5 and last.close > last.ma20
            engulf = yesterday.close < yesterday.open and last.close > last.open and last.open <= yesterday.close and last.close >= yesterday.open
            volume_ok = last.volume > d.volume.iloc[-6:-1].mean()
            if above_ma: daily_ma_days += 1
            if engulf: engulf_days += 1
            if volume_ok: volume_days += 1
            if above_ma and engulf and (volume_ok or not require_strong):
                pending_buy = True; stop = setup_stop; setup_days = 0; daily_confirmations += 1
                if volume_ok: strong_confirmations += 1
    if shares:
        row=data.iloc[-1]; price=float(row.close)*(1-slippage); amount=shares*price
        fee=max(5.0,amount*commission)+amount*stamp; cash += amount-fee
        trades.append({**current_trade,"sell_date":data.index[-1],"sell_price":price,
                       "pnl":amount-fee-current_trade["cost"],
                       "return":(price-entry)/entry*100,"reason":"回测期末平仓",
                       "holding_days":len(data)-1-current_trade["buy_i"]})
        shares=0
    curve = pd.Series({d:v for d,v in equity}, name="equity")
    if curve.empty: curve = pd.Series([initial], index=[data.index[-1]], name="equity")
    total = (cash / initial - 1) * 100
    drawdown = ((curve / curve.cummax()) - 1).min() * 100
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    gross_win = sum(t["pnl"] for t in wins); gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_win / gross_loss if gross_loss else (float("inf") if gross_win else 0)
    avg_win = float(np.mean([t["return"] for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t["return"] for t in losses])) if losses else 0.0
    return curve, trades, {"期末资产":cash,"总收益率":total,"最大回撤":drawdown,
                           "交易次数":len(trades),"胜率":win_rate,"盈亏因子":profit_factor,
                           "盈利交易":len(wins),"亏损交易":len(losses),
                           "平均盈利":avg_win,"平均亏损":avg_loss,
                           "周线多头周数":weekly_trend_days,"周线候选":weekly_candidates,
                           "候选期站上日均线":daily_ma_days,"候选期阳包阴":engulf_days,
                           "候选期日线放量":volume_days,"日线确认":daily_confirmations,
                           "强确认":strong_confirmations,"大盘允许周数":market_pass_weeks,
                           "大盘过滤次数":market_blocked,"原始周线候选":raw_candidates,
                           "最终交易次数":len(trades)}


def build_signal_frame(raw):
    """一次性预计算个股信号，供多个组合方案复用。"""
    d = indicators(raw.copy().sort_index())
    d["week_end"] = False; d["week_trend"] = False; d["week_exit"] = False
    d["week_exit_ma10"] = False; d["week_exit_confirm2"] = False; d["week_exit_ma5"] = False
    d["stop_ref"] = np.nan; d["signal_score"] = 0.0
    d["above_ma"] = (d.close > d.ma5) & (d.close > d.ma20)
    prev = d.shift(1)
    d["engulf"] = (prev.close < prev.open) & (d.close > d.open) & (d.open <= prev.close) & (d.close >= prev.open)
    d["volume_ok"] = d.volume > d.volume.shift(1).rolling(5).mean()
    w = weekly_data(raw)
    swing_high=(w.high==w.high.rolling(5,center=True).max()).fillna(False).to_numpy()
    swing_low=(w.low==w.low.rolling(5,center=True).min()).fillna(False).to_numpy()
    confirmed_highs=[float(w.high.iloc[k]) for k in range(2,min(19,len(w)-2)) if swing_high[k]]
    confirmed_lows=[float(w.low.iloc[k]) for k in range(2,min(19,len(w)-2)) if swing_low[k]]
    for j in range(20, len(w)):
        cur, before = w.iloc[j], w.iloc[j-1]
        confirmed=j-2
        if j>20 and swing_high[confirmed]: confirmed_highs.append(float(w.high.iloc[confirmed]))
        if j>20 and swing_low[confirmed]: confirmed_lows.append(float(w.low.iloc[confirmed]))
        highs,lows=confirmed_highs[-2:],confirmed_lows[-2:]
        waves = len(highs)==2 and len(lows)==2 and highs[1]>highs[0] and lows[1]>lows[0]
        trend = bool(cur.ma5>cur.ma10>cur.ma20 and cur.ma5>before.ma5 and cur.ma10>before.ma10 and cur.ma20>before.ma20 and
                     (w.close.iloc[j-1:j+1] > w.ma20.iloc[j-1:j+1]).all() and waves)
        avg5=float(w.volume.iloc[max(0,j-5):j].mean()); ratio=float(cur.volume/avg5) if avg5 else 0
        slope=float((cur.ma5/before.ma5-1)*100) if before.ma5 else 0
        score=ratio + max(0,slope)*2 + max(0,float(cur.close/cur.ma20-1))*5
        period=w.index[j].to_period("W-FRI"); days=d.index[d.index.to_period("W-FRI")==period]
        if not len(days) or w.index[j] > d.index[-1]: continue
        date=days[-1]; d.at[date,"week_end"]=True; d.at[date,"week_trend"]=trend
        exit_now=bool(cur.ma5<before.ma5 or cur.close<cur.ma10)
        previous_exit=False
        if j>=2:
            two_before=w.iloc[j-2]
            previous_exit=bool(before.ma5<two_before.ma5 or before.close<before.ma10)
        d.at[date,"week_exit"]=exit_now
        d.at[date,"week_exit_ma10"]=bool(cur.close<cur.ma10)
        d.at[date,"week_exit_confirm2"]=bool(exit_now and previous_exit)
        d.at[date,"week_exit_ma5"]=bool(cur.ma5<before.ma5)
        d.at[date,"stop_ref"]=float(min(lows[-1] if lows else w.low.iloc[max(0,j-7):j+1].min(),cur.close)*.97)
        d.at[date,"signal_score"]=score
    return d


def entry_rule_signals(frame, entry_rule="1 推荐"):
    """Build causal entry timing signals; rule 3 fires only after both facts are observed."""
    if entry_rule not in ENTRY_RULES:
        raise ValueError(f"未知入场规则：{entry_rule}")
    base=(frame["above_ma"].fillna(False).astype(bool) & frame["engulf"].fillna(False).astype(bool))
    volume=frame["volume_ok"].fillna(False).astype(bool)
    if entry_rule=="1 推荐":
        signal=base
        confirmation=pd.Series(np.where(signal & volume,"强确认",np.where(signal,"买入观察","")),index=frame.index,dtype=object)
    elif entry_rule=="2 严格":
        signal=base & volume
        confirmation=pd.Series(np.where(signal,"强确认",""),index=frame.index,dtype=object)
    elif entry_rule=="3 折中":
        prior_volume=volume.shift(1).rolling(3,min_periods=1).max().fillna(0).astype(bool)
        prior_base=base.shift(1).rolling(3,min_periods=1).max().fillna(0).astype(bool)
        signal=(base & (volume | prior_volume)) | (volume & prior_base)
        confirmation=pd.Series(np.where(signal,"三日窗口确认",""),index=frame.index,dtype=object)
    else:
        # 世坤方案先保持规则1的触发时机，仅改变同日候选的横截面排序。
        signal=base
        confirmation=pd.Series(np.where(signal & volume,"世坤因子·强确认",np.where(signal,"世坤因子·买入观察","")),index=frame.index,dtype=object)
    return pd.DataFrame({"entry_signal":signal.astype(bool),"entry_confirmation":confirmation},index=frame.index)


def enrich_entry_quality(frame, market):
    """Create point-in-time entry features; every rolling input ends on signal day or earlier."""
    d=frame.copy(); market_close=market.close.reindex(d.index).ffill()
    d["entry_rs60"]=(d.close/d.close.shift(60)-1)-(market_close/market_close.shift(60)-1)
    d["entry_ma20_slope10"]=d.ma20/d.ma20.shift(10)-1
    prior_high20=d.high.shift(1).rolling(20).max()
    d["entry_near_high20"]=d.close>=prior_high20*.98
    d["entry_volume_ratio20"]=d.volume/d.volume.shift(1).rolling(20).mean()
    d["entry_quality_score"]=(d.entry_rs60>0).astype(int)+(d.entry_ma20_slope10>0).astype(int)+(d.entry_near_high20).astype(int)+(d.entry_volume_ratio20>=1.2).astype(int)
    return d


def enrich_worldquant_factors(frames):
    """用OHLCV构造六个因子并按交易日横截面排名；所有输入止于当日。"""
    if not frames:
        return {}
    scored={}; raw_components={}
    component_names=("wq_momentum20","wq_reversal5","wq_price_volume_corr10",
                     "wq_range_position20","wq_low_volatility20","wq_volume_impulse5")
    for code,source in frames.items():
        frame=source.copy(); close=frame.close.astype(float); volume=frame.volume.astype(float).replace(0,np.nan)
        returns=close.pct_change(); log_volume=np.log(volume).diff()
        rolling_low=frame.low.astype(float).rolling(20).min(); rolling_high=frame.high.astype(float).rolling(20).max()
        price_range=(rolling_high-rolling_low).replace(0,np.nan)
        volume_base=volume.shift(1).rolling(20).mean().replace(0,np.nan)
        raw_components[code]={
            "wq_momentum20":close.pct_change(20),
            "wq_reversal5":-close.pct_change(5),
            "wq_price_volume_corr10":-returns.rolling(10).corr(log_volume),
            "wq_range_position20":(close-rolling_low)/price_range,
            "wq_low_volatility20":-returns.rolling(20).std(),
            "wq_volume_impulse5":np.sign(close.pct_change(5))*np.log(volume/volume_base),
        }
        scored[code]=frame
    for name in component_names:
        panel=pd.concat({code:parts[name] for code,parts in raw_components.items()},axis=1)
        ranks=panel.rank(axis=1,pct=True,method="average")
        for code in scored:
            scored[code][name]=ranks[code].reindex(scored[code].index)
    for code,frame in scored.items():
        components=frame.loc[:,list(component_names)]
        frame["worldquant_score"]=components.mean(axis=1,skipna=True).where(components.notna().sum(axis=1)>=4).mul(100)
    return scored


def diagnostic_equal_weight_curve(frames, dates, initial=100000):
    """当前样本的等权价格指数；仅作偏差诊断，不模拟可成交组合。"""
    dates=pd.DatetimeIndex(dates).sort_values().unique()
    normalized=[]
    for frame in frames.values():
        close=frame.close.astype(float).reindex(dates).ffill()
        first=close.first_valid_index()
        if first is None: continue
        base=float(close.loc[first])
        if not np.isfinite(base) or base<=0: continue
        normalized.append((close/base).rename(str(len(normalized))))
    if not normalized: raise ValueError("等权诊断没有可用股票")
    # 尚未上市或尚无数据的股票不进入当日均值，避免用未来价格回填过去。
    return pd.concat(normalized,axis=1).mean(axis=1,skipna=True).mul(float(initial)).rename("equity")


def annual_curve_returns(series, initial=100000):
    """逐年收益，首年以初始资金为基点，之后以前一年年末为基点。"""
    s=pd.Series(series,dtype=float).dropna().sort_index(); result={}; previous=float(initial)
    for year,group in s.groupby(s.index.year):
        result[int(year)]=float((group.iloc[-1]/previous-1)*100)
        previous=float(group.iloc[-1])
    return result


def audit_price_frame(code, frame, market_dates):
    """对已载入日线做可复现的数据质量检查。"""
    d=frame.copy(); idx=pd.DatetimeIndex(d.index); required=["open","close","high","low","volume"]
    duplicate=int(idx.duplicated().sum())
    missing=int(d.reindex(columns=required).isna().sum().sum())
    nonpositive=int((d.reindex(columns=required)<=0).sum().sum())
    invalid_range=int(((d.low>d.high)|(d.open<d.low)|(d.open>d.high)|(d.close<d.low)|(d.close>d.high)).sum())
    jumps=int((d.close.astype(float).pct_change().abs()>.30).sum())
    if len(idx):
        expected=pd.DatetimeIndex(market_dates); expected=expected[(expected>=idx.min())&(expected<=idx.max())]
        missing_days=int(len(expected.difference(idx)))
        first,last=idx.min().strftime("%Y-%m-%d"),idx.max().strftime("%Y-%m-%d")
    else: missing_days=0; first=last="--"
    previous=d.close.shift(1).replace(0,np.nan)
    open_gap=(d.open/previous-1).abs()
    locked=(d.high.sub(d.low).abs()<=.001)
    suspicious=int(((open_gap>=.095)&locked).sum())
    issues=duplicate+missing+nonpositive+invalid_range+jumps
    verdict="需检查" if issues else "基础检查通过"
    return {"代码":code,"首日":first,"末日":last,"行数":len(d),"重复日期":duplicate,"缺失值":missing,
            "非正价格/量":nonpositive,"OHLC矛盾":invalid_range,"异常跳变>30%":jumps,
            "相对指数缺日":missing_days,"疑似一字涨跌停":suspicious,"基础结论":verdict}


def build_market_flags(market):
    flags={m:{} for m in ("关闭","宽松","严格")}; w=weekly_data(market)
    for j in range(20,len(w)):
        cur,prev=w.iloc[j],w.iloc[j-1]; date=w.index[j]
        flags["关闭"][date]=True
        flags["宽松"][date]=bool(cur.close>cur.ma20)
        flags["严格"][date]=bool(cur.close>cur.ma20 and cur.ma5>cur.ma10>cur.ma20 and cur.ma20>=prev.ma20)
    return flags


def stock_regime_limits(market, dates, profile="固定"):
    """用前一日沪深300状态确定今日允许的新开仓上限和单笔风险。"""
    close=market.close.astype(float).sort_index(); ma50=close.rolling(50).mean(); ma200=close.rolling(200).mean(); mom60=close/close.shift(60)-1
    strong=(close>ma200)&(ma50>ma200)&(mom60>0); normal=(close>ma200)
    state=pd.Series(np.where(strong,2,np.where(normal,1,0)),index=close.index).shift(1).reindex(pd.DatetimeIndex(dates)).ffill().fillna(0).astype(int)
    profiles={
        "固定":((80,.8),(80,.8),(80,.8)),
        "弱市半仓":((40,.4),(80,.8),(80,.8)),
        "弱市禁开":((0,0),(80,.8),(80,.8)),
        "只做强势":((0,0),(0,0),(80,.8)),
    }
    mapping=profiles[profile]; return pd.DataFrame({"state":state,"cap":[mapping[x][0] for x in state],"risk":[mapping[x][1] for x in state]},index=state.index)


def portfolio_backtest(frames, market_flags, initial=100000, evaluation_start="2024-01-01",
                       market_mode="关闭", require_strong=False, max_positions=5,
                       max_position_pct=20, total_position_pct=80, risk_pct=.8,
                       commission=.0003, stamp=.0005, slippage=.001, candidate_days=20,
                       market=None, regime_profile="固定", exit_profile="原规则", entry_profile="原始入场",
                       entry_rule="1 推荐"):
    """多股票共享资金、统一时间轴、次日成交的组合回测。"""
    start=pd.Timestamp(evaluation_start); dates=sorted(set().union(*(set(f.index[f.index>=start]) for f in frames.values())))
    if not dates: raise ValueError("样本外区间没有行情")
    cash=float(initial); positions={}; pending_buys=[]; pending_exits={}; trades=[]; equity_rows=[]
    timing_signals={code:entry_rule_signals(frame,entry_rule) for code,frame in frames.items()}
    limits=stock_regime_limits(market,dates,regime_profile) if market is not None else None
    setup={c:0 for c in frames}; setup_stop={c:0.0 for c in frames}; setup_score={c:0.0 for c in frames}; last_close={}

    def portfolio_value(date, at_open=False):
        value=cash; exposure=0.0
        for code,p in positions.items():
            f=frames[code]
            px=float(f.at[date,"open" if at_open else "close"]) if date in f.index else last_close.get(code,p["entry"])
            value += p["shares"]*px; exposure += p["shares"]*px
        return value,exposure

    for date in dates:
        for code in setup:
            if setup[code]>0: setup[code]-=1
        for code,exit_reason in list(pending_exits.items()):
            if code not in positions or date not in frames[code].index: continue
            row=frames[code].loc[date]; p=positions.pop(code); price=float(row.open)*(1-slippage); amount=p["shares"]*price
            fee=max(5.0,amount*commission)+amount*stamp; cash+=amount-fee; pnl=amount-fee-p["cost"]
            trades.append({**p,"code":code,"sell_date":date,"sell_price":price,"pnl":pnl,"return":(price/p["entry"]-1)*100,"reason":exit_reason}); pending_exits.pop(code,None)
        if pending_buys:
            candidates=sorted(pending_buys,key=lambda x:x[1],reverse=True); pending_buys=[]
            for code,score,stop,entry_features in candidates:
                if code in positions or date not in frames[code].index or len(positions)>=max_positions: continue
                industry=INDUSTRY_MAP.get(code,"其他-"+code)
                if sum(p["industry"]==industry for p in positions.values())>=2: continue
                row=frames[code].loc[date]; price=float(row.open)*(1+slippage); equity_now,exposure=portfolio_value(date,at_open=True)
                if not np.isfinite(stop) or stop<=0 or stop>=price: continue
                active_cap=float(limits.at[date,"cap"]) if limits is not None else float(total_position_pct)
                active_risk=float(limits.at[date,"risk"]) if limits is not None else float(risk_pct)
                capacity=max(0,equity_now*active_cap/100-exposure)
                cap_budget=min(cash,equity_now*max_position_pct/100,capacity)
                per_share_risk=max(price-stop,price*.005); risk_qty=int((equity_now*active_risk/100)/per_share_risk/100)*100
                cap_qty=int(cap_budget/(price*100))*100; qty=min(risk_qty,cap_qty)
                if qty<=0: continue
                amount=qty*price; fee=max(5.0,amount*commission)
                if amount+fee>cash: continue
                cash-=amount+fee; positions[code]={"buy_date":date,"entry":price,"shares":qty,"cost":amount+fee,
                    "stop":stop,"initial_stop":stop,"industry":industry,"score":score,"mae":0.0,"mfe":0.0,"planned_risk":qty*per_share_risk}
                positions[code].update(entry_features)
        for code in list(positions):
            if date not in frames[code].index: continue
            row=frames[code].loc[date]; p=positions[code]
            if date>p["buy_date"] and float(row.low)<=p["stop"]:
                price=min(float(row.open),p["stop"])*(1-slippage); amount=p["shares"]*price
                fee=max(5.0,amount*commission)+amount*stamp; cash+=amount-fee; pnl=amount-fee-p["cost"]
                trades.append({**p,"code":code,"sell_date":date,"sell_price":price,"pnl":pnl,"return":(price/p["entry"]-1)*100,
                    "reason":"跳空止损" if float(row.open)<p["stop"] else "周线低点止损"}); positions.pop(code); pending_exits.pop(code,None); continue
            p["mae"]=min(p["mae"],(float(row.low)/p["entry"]-1)*100); p["mfe"]=max(p["mfe"],(float(row.high)/p["entry"]-1)*100)
            last_close[code]=float(row.close)
        value,exposure=portfolio_value(date); target=float(limits.at[date,"cap"]) if limits is not None else float(total_position_pct); equity_rows.append((date,value,exposure,target,cash,len(positions)))
        next_buys=[]
        for code,f in frames.items():
            if date not in f.index: continue
            row=f.loc[date]
            if bool(row.week_end):
                flag_date=date.to_period("W-FRI").end_time.normalize()
                market_ok=market_flags[market_mode].get(flag_date,market_mode=="关闭")
                exit_columns={"原规则":"week_exit","跌破10周线":"week_exit_ma10","连续两周确认":"week_exit_confirm2","5周线拐头":"week_exit_ma5"}
                exit_column=exit_columns.get(exit_profile,"week_exit")
                if code in positions and bool(row[exit_column]): pending_exits[code]=exit_profile
                if bool(row.week_trend) and market_ok:
                    setup[code]=candidate_days; setup_stop[code]=float(row.stop_ref); setup_score[code]=float(row.signal_score)
                    if code in positions and np.isfinite(row.stop_ref): positions[code]["stop"]=max(positions[code]["stop"],float(row.stop_ref))
                else: setup[code]=0
            timing=timing_signals[code].loc[date]
            confirm=bool(timing.entry_signal and (bool(row.volume_ok) or not require_strong))
            if exit_profile=="跌破20日线" and code in positions and float(row.close)<float(row.ma20):
                pending_exits[code]="跌破20日线"
            quality_score=int(row.get("entry_quality_score",0)); rs60=float(row.get("entry_rs60",np.nan)); slope=float(row.get("entry_ma20_slope10",np.nan)); volume_ratio=float(row.get("entry_volume_ratio20",np.nan)); near_high=bool(row.get("entry_near_high20",False))
            quality_ok={"原始入场":True,"相对强度":bool(np.isfinite(rs60) and rs60>0),"均线斜率":bool(np.isfinite(slope) and slope>0),"量能确认":bool(np.isfinite(volume_ratio) and volume_ratio>=1.2),"质量≥2":quality_score>=2,"质量≥3":quality_score>=3}.get(entry_profile,True)
            if code not in positions and setup[code]>0 and confirm and quality_ok:
                worldquant_score=float(row.get("worldquant_score",np.nan))
                candidate_score=worldquant_score if entry_rule=="4 世坤因子" and np.isfinite(worldquant_score) else setup_score[code]
                features={"signal_date":date,"entry_profile":entry_profile,"entry_rule":entry_rule,"entry_confirmation":str(timing.entry_confirmation),"entry_rs60":rs60*100 if np.isfinite(rs60) else np.nan,"entry_ma20_slope10":slope*100 if np.isfinite(slope) else np.nan,"entry_near_high20":near_high,"entry_volume_ratio20":volume_ratio,"entry_quality_score":quality_score,
                          "worldquant_score":worldquant_score,
                          "wq_momentum20":float(row.get("wq_momentum20",np.nan)),
                          "wq_reversal5":float(row.get("wq_reversal5",np.nan)),
                          "wq_price_volume_corr10":float(row.get("wq_price_volume_corr10",np.nan)),
                          "wq_range_position20":float(row.get("wq_range_position20",np.nan)),
                          "wq_low_volatility20":float(row.get("wq_low_volatility20",np.nan)),
                          "wq_volume_impulse5":float(row.get("wq_volume_impulse5",np.nan))}
                next_buys.append((code,candidate_score,setup_stop[code],features)); setup[code]=0
        pending_buys=next_buys
    end=dates[-1]
    for code,p in list(positions.items()):
        f=frames[code]; available=f.loc[:end]
        if available.empty or available.index[-1]<=p["buy_date"]: continue
        row=available.iloc[-1]; price=float(row.close)*(1-slippage); amount=p["shares"]*price
        fee=max(5.0,amount*commission)+amount*stamp; cash+=amount-fee; pnl=amount-fee-p["cost"]
        trades.append({**p,"code":code,"sell_date":available.index[-1],"sell_price":price,"pnl":pnl,"return":(price/p["entry"]-1)*100,"reason":"期末平仓"})
        positions.pop(code)
    ending_value,ending_exposure=portfolio_value(end)
    for trade in trades:
        trade["holding_days"]=(trade["sell_date"]-trade["buy_date"]).days
        trade["net_return_pct"]=trade["pnl"]/trade["cost"]*100
        trade["initial_stop_pct"]=(1-trade["initial_stop"]/trade["entry"])*100
        trade["same_day_exit"]=trade["sell_date"]<=trade["buy_date"]
        trade["profit_giveback_pct"]=max(0.0,trade["mfe"]-trade["net_return_pct"])
    curve=pd.DataFrame(equity_rows,columns=["date","equity","exposure","target_stock","cash","position_count"]).drop_duplicates("date").set_index("date")
    if not curve.empty:
        curve.iloc[-1,curve.columns.get_loc("equity")]=ending_value
        curve.iloc[-1,curve.columns.get_loc("exposure")]=ending_exposure
        curve.iloc[-1,curve.columns.get_loc("cash")]=cash
        curve.iloc[-1,curve.columns.get_loc("position_count")]=len(positions)
    returns=curve.equity.pct_change().fillna(0); returns.iloc[0]=curve.equity.iloc[0]/initial-1; years=max((curve.index[-1]-curve.index[0]).days/365.25,1/365.25)
    total=(ending_value/initial-1)*100; cagr=((ending_value/initial)**(1/years)-1)*100 if ending_value>0 else -100
    maxdd=((curve.equity/curve.equity.cummax().clip(lower=initial))-1).min()*100; wins=[t for t in trades if t["pnl"]>0]; losses=[t for t in trades if t["pnl"]<0]
    gw=sum(t["pnl"] for t in wins); gl=abs(sum(t["pnl"] for t in losses)); pf=gw/gl if gl else (float("inf") if gw else 0)
    sharpe=float(returns.mean()/returns.std()*np.sqrt(252)) if returns.std()>0 else 0
    utilization=float((curve.exposure/curve.equity.replace(0,np.nan)).mean()*100)
    yearly={}; previous_year_end=float(initial)
    for y,g in curve.groupby(curve.index.year):
        yearly[str(y)]=float((g.equity.iloc[-1]/previous_year_end-1)*100)
        previous_year_end=float(g.equity.iloc[-1])
    return curve,trades,{"期末资产":ending_value,"总收益率":total,"年化收益":cagr,"最大回撤":maxdd,"夏普":sharpe,
        "交易次数":len(trades),"胜率":len(wins)/len(trades)*100 if trades else 0,"盈亏因子":pf,
        "资金利用率":utilization,"目标仓位均值":float(curve.target_stock.mean()),"盈利交易":len(wins),"亏损交易":len(losses),"年度收益":yearly}


def prepare_enhanced_frame(raw, market):
    """在原始周线规则上增加相对强度、流动性、ATR和突破确认字段。"""
    frame=build_signal_frame(raw)
    previous=frame.close.shift(1)
    true_range=pd.concat([(frame.high-frame.low),(frame.high-previous).abs(),(frame.low-previous).abs()],axis=1).max(axis=1)
    frame["atr14"]=true_range.rolling(14).mean()
    frame["amount_proxy"]=(frame.close*frame.volume).rolling(20).mean()
    market_close=market.close.reindex(frame.index).ffill()
    market60=market_close/market_close.shift(60)-1; market120=market_close/market_close.shift(120)-1
    frame["rs60"]=(frame.close/frame.close.shift(60)-1)-market60
    frame["rs120"]=(frame.close/frame.close.shift(120)-1)-market120
    frame["breakout20"]=frame.close>frame.high.shift(1).rolling(20).max()
    frame["enhanced_score"]=(frame.rs60.fillna(-1)*65+frame.rs120.fillna(-1)*35+
                              frame.signal_score.fillna(0))
    return frame


def market_exposure_series(market, dates):
    """弱势30%、站上20周线60%、完整周线多头80%。"""
    weekly=weekly_data(market); values={}
    for i in range(20,len(weekly)):
        row,prev=weekly.iloc[i],weekly.iloc[i-1]
        if row.close<=row.ma20: exposure=30.0
        elif row.ma5>row.ma10>row.ma20 and row.ma20>=prev.ma20: exposure=80.0
        else: exposure=60.0
        values[weekly.index[i]]=exposure
    series=pd.Series(values,dtype=float).reindex(pd.DatetimeIndex(dates),method="ffill").fillna(30.0)
    return series


def enhanced_portfolio_backtest(frames, market, initial=100000, evaluation_start="2024-01-01",
                                max_positions=8, candidate_days=30, atr_multiple=2.5,
                                time_stop_days=30, max_position_pct=20, risk_pct=.8,
                                commission=.0003, stamp=.0005, slippage=.001):
    """增强组合：相对强度排名、动态仓位、ATR/保本/时间止损，全部次日成交。"""
    start=pd.Timestamp(evaluation_start); dates=sorted(set().union(*(set(f.index[f.index>=start]) for f in frames.values())))
    if not dates: raise ValueError("增强回测区间没有行情")
    exposure_target=market_exposure_series(market,dates); cash=float(initial); positions={}; pending_buys=[]; pending_exits={}; trades=[]; equity_rows=[]
    setup={c:0 for c in frames}; setup_stop={c:0.0 for c in frames}; setup_score={c:0.0 for c in frames}; last_close={}
    diagnostics={"周线候选":0,"相对强度通过":0,"阳包阴确认":0,"突破确认":0,"流动性过滤":0,"风控拒绝":0}

    def portfolio_value(date):
        value=cash; exposure=0.0
        for code,p in positions.items():
            frame=frames[code]; price=float(frame.at[date,"close"]) if date in frame.index else last_close.get(code,p["entry"])
            value+=p["shares"]*price; exposure+=p["shares"]*price
        return value,exposure

    def close_position(code,date,row,price,reason):
        nonlocal cash
        p=positions.pop(code); amount=p["shares"]*price; fee=max(5.0,amount*commission)+amount*stamp; cash+=amount-fee
        pnl=amount-fee-p["cost"]; trades.append({**p,"code":code,"sell_date":date,"sell_price":price,"pnl":pnl,
            "return":(price/p["entry"]-1)*100,"reason":reason,"holding_days":(pd.Timestamp(date)-pd.Timestamp(p["buy_date"])).days})

    for date_index,date in enumerate(dates):
        for code in setup:
            if setup[code]>0: setup[code]-=1
        for code,reason in list(pending_exits.items()):
            if code not in positions or date not in frames[code].index: continue
            row=frames[code].loc[date]; close_position(code,date,row,float(row.open)*(1-slippage),reason); pending_exits.pop(code,None)
        if pending_buys:
            candidates=sorted(pending_buys,key=lambda x:x[1],reverse=True); pending_buys=[]
            for code,score,weekly_stop,signal_kind in candidates:
                if code in positions or date not in frames[code].index or len(positions)>=max_positions: continue
                industry=INDUSTRY_MAP.get(code,"其他-"+code)
                if sum(p["industry"]==industry for p in positions.values())>=2: diagnostics["风控拒绝"]+=1; continue
                row=frames[code].loc[date]; price=float(row.open)*(1+slippage); atr=float(row.atr14) if np.isfinite(row.atr14) else price*.04
                stop=max(float(weekly_stop),price-atr_multiple*atr); stop=min(stop,price*.995)
                equity_now,current_exposure=portfolio_value(date); target=equity_now*float(exposure_target.loc[date])/100
                capacity=max(0,target-current_exposure); budget=min(cash,equity_now*max_position_pct/100,capacity)
                per_share_risk=max(price-stop,price*.005); risk_qty=int((equity_now*risk_pct/100)/per_share_risk/100)*100
                cap_qty=int(budget/(price*100))*100; quantity=min(risk_qty,cap_qty)
                if quantity<=0: diagnostics["风控拒绝"]+=1; continue
                amount=quantity*price; fee=max(5.0,amount*commission)
                if amount+fee>cash: diagnostics["风控拒绝"]+=1; continue
                cash-=amount+fee; positions[code]={"buy_date":date,"entry":price,"shares":quantity,"cost":amount+fee,"stop":stop,
                    "initial_stop":stop,"initial_risk":price-stop,"highest":price,"industry":industry,"score":score,
                    "entry_signal":signal_kind,"mae":0.0,"mfe":0.0,"planned_risk":quantity*(price-stop)}
        for code in list(positions):
            if date not in frames[code].index: continue
            row=frames[code].loc[date]; p=positions[code]; last_close[code]=float(row.close)
            p["highest"]=max(p["highest"],float(row.high)); p["mae"]=min(p["mae"],(float(row.low)/p["entry"]-1)*100); p["mfe"]=max(p["mfe"],(float(row.high)/p["entry"]-1)*100)
            atr=float(row.atr14) if np.isfinite(row.atr14) else p["entry"]*.04
            if p["highest"]>=p["entry"]+p["initial_risk"]: p["stop"]=max(p["stop"],p["entry"])
            p["stop"]=max(p["stop"],p["highest"]-atr_multiple*atr)
            if pd.Timestamp(date)>pd.Timestamp(p["buy_date"]) and float(row.low)<=p["stop"]:
                price=min(float(row.open),p["stop"])*(1-slippage); reason="跳空止损" if float(row.open)<p["stop"] else ("保本止损" if p["stop"]>=p["entry"] else "ATR移动止损")
                close_position(code,date,row,price,reason); pending_exits.pop(code,None); continue
            holding_sessions=sum(1 for d in dates[:date_index+1] if d>=p["buy_date"] and d in frames[code].index)
            if holding_sessions>=time_stop_days and float(row.close)<=p["entry"]: pending_exits[code]="时间止损"
        value,current_exposure=portfolio_value(date); equity_rows.append((date,value,current_exposure,float(exposure_target.loc[date])))
        next_candidates=[]
        for code,frame in frames.items():
            if date not in frame.index: continue
            row=frame.loc[date]
            if bool(row.week_end):
                if code in positions and bool(row.week_exit): pending_exits[code]="周线趋势离场"
                if bool(row.week_trend):
                    setup[code]=candidate_days; setup_stop[code]=float(row.stop_ref); setup_score[code]=float(row.signal_score); diagnostics["周线候选"]+=1
                    if code in positions and np.isfinite(row.stop_ref): positions[code]["stop"]=max(positions[code]["stop"],min(float(row.stop_ref),float(row.close)*.99))
                else: setup[code]=0
            relative_ok=bool(np.isfinite(row.rs60) and np.isfinite(row.rs120) and row.rs60>0 and row.rs120>0)
            if setup[code]>0 and relative_ok: diagnostics["相对强度通过"]+=1
            engulf_confirm=bool(row.above_ma and row.engulf); breakout_confirm=bool(row.above_ma and row.breakout20 and row.volume_ok)
            if code not in positions and setup[code]>0 and relative_ok and (engulf_confirm or breakout_confirm):
                kind="阳包阴" if engulf_confirm else "放量突破"; diagnostics["阳包阴确认" if engulf_confirm else "突破确认"]+=1
                next_candidates.append((code,float(row.enhanced_score),setup_stop[code],kind,float(row.amount_proxy))); setup[code]=0
        if len(next_candidates)>=3:
            threshold=float(np.nanpercentile([x[4] for x in next_candidates],30)); before=len(next_candidates); next_candidates=[x for x in next_candidates if np.isfinite(x[4]) and x[4]>=threshold]; diagnostics["流动性过滤"]+=before-len(next_candidates)
        pending_buys=[x[:4] for x in next_candidates]
    end=dates[-1]
    for code in list(positions):
        available=frames[code].loc[:end]
        if available.empty: continue
        row=available.iloc[-1]; close_position(code,available.index[-1],row,float(row.close)*(1-slippage),"期末平仓")
    curve=pd.DataFrame(equity_rows,columns=["date","equity","exposure","target_exposure"]).drop_duplicates("date").set_index("date")
    if not curve.empty: curve.iloc[-1,curve.columns.get_loc("equity")]=cash; curve.iloc[-1,curve.columns.get_loc("exposure")]=0.0
    returns=curve.equity.pct_change().fillna(0); years=max((curve.index[-1]-curve.index[0]).days/365.25,1/365.25)
    total=(cash/initial-1)*100; cagr=((cash/initial)**(1/years)-1)*100 if cash>0 else -100; maxdd=((curve.equity/curve.equity.cummax())-1).min()*100
    wins=[t for t in trades if t["pnl"]>0]; losses=[t for t in trades if t["pnl"]<0]; gross_win=sum(t["pnl"] for t in wins); gross_loss=abs(sum(t["pnl"] for t in losses)); pf=gross_win/gross_loss if gross_loss else (float("inf") if gross_win else 0)
    sharpe=float(returns.mean()/returns.std()*np.sqrt(252)) if returns.std()>0 else 0; utilization=float((curve.exposure/curve.equity.replace(0,np.nan)).mean()*100)
    yearly={str(y):float((group.equity.iloc[-1]/group.equity.iloc[0]-1)*100) for y,group in curve.groupby(curve.index.year) if len(group)>1}
    stats={"期末资产":cash,"总收益率":total,"年化收益":cagr,"最大回撤":maxdd,"夏普":sharpe,"交易次数":len(trades),
           "胜率":len(wins)/len(trades)*100 if trades else 0,"盈亏因子":pf,"资金利用率":utilization,"盈利交易":len(wins),"亏损交易":len(losses),"年度收益":yearly,**diagnostics}
    return curve,trades,stats


def adaptive_index_overlay(base_curve, market, initial=100000, max_index_pct=40,
                           commission=.0003, tradable=None, slippage=.0005):
    """只把闲置现金用于510300；沪深300信号滞后一日，避免未来函数。"""
    if base_curve.empty: raise ValueError("股票策略资金曲线为空")
    dates=base_curve.index; full=market.copy().sort_index(); close=full.close.astype(float)
    ma50=close.rolling(50).mean(); ma200=close.rolling(200).mean()
    mom20=close/close.shift(20)-1; mom60=close/close.shift(60)-1
    strong=(close>ma200)&(ma50>ma200)&(mom60>0)
    recovery=(close>ma200)&(mom20>0)
    state=pd.Series(np.where(strong,1.0,np.where(recovery,.5,0.0)),index=full.index)
    # 今日持仓只能使用上一交易日收盘后已经确认的状态。
    state=state.shift(1).reindex(dates).ffill().fillna(0.0)
    trade_close=(tradable.close.astype(float) if tradable is not None else close).reindex(dates).ffill().bfill()
    index_return=trade_close.pct_change().fillna(0.0)
    base_return=base_curve.equity.pct_change().fillna(0.0)
    free_cash=(1-base_curve.exposure.shift(1).fillna(0)/base_curve.equity.shift(1).replace(0,np.nan)).clip(0,1).fillna(1)
    equity=float(initial); index_weight=0.0; rows=[]; events=[]; daily_pnl=[]
    for date in dates:
        combined_return=float(base_return.loc[date])+index_weight*float(index_return.loc[date])
        before=equity; equity*=max(0.0,1+combined_return)
        target=min(float(max_index_pct)/100*float(state.loc[date]),float(free_cash.loc[date]))
        turnover=abs(target-index_weight)*equity
        fee=(max(5.0,turnover*commission)+turnover*slippage) if turnover>1 else 0.0
        if abs(target-index_weight)>.005:
            events.append({"日期":date,"动作":"增持指数" if target>index_weight else "减持指数",
                           "原仓位":index_weight*100,"目标仓位":target*100,"调仓金额":turnover,"费用":fee})
        equity-=fee; daily_pnl.append(equity-before); index_weight=target
        stock_exposure=float(base_curve.at[date,"exposure"])/max(float(base_curve.at[date,"equity"]),1)
        rows.append((date,equity,stock_exposure*100,index_weight*100,(stock_exposure+index_weight)*100,float(state.loc[date])))
    curve=pd.DataFrame(rows,columns=["date","equity","stock_exposure","index_exposure","total_exposure","market_state"]).set_index("date")
    returns=curve.equity.pct_change().fillna(0); years=max((dates[-1]-dates[0]).days/365.25,1/365.25)
    total=(equity/initial-1)*100; cagr=((equity/initial)**(1/years)-1)*100 if equity>0 else -100
    maxdd=((curve.equity/curve.equity.cummax())-1).min()*100
    positive=sum(x for x in daily_pnl if x>0); negative=abs(sum(x for x in daily_pnl if x<0)); pf=positive/negative if negative else (float("inf") if positive else 0)
    sharpe=float(returns.mean()/returns.std()*np.sqrt(252)) if returns.std()>0 else 0
    yearly={str(y):float((g.equity.iloc[-1]/g.equity.iloc[0]-1)*100) for y,g in curve.groupby(curve.index.year) if len(g)>1}
    stats={"期末资产":equity,"总收益率":total,"年化收益":cagr,"最大回撤":maxdd,"夏普":sharpe,
           "盈亏因子":pf,"指数调仓":len(events),"平均股票仓位":float(curve.stock_exposure.mean()),
           "平均指数仓位":float(curve.index_exposure.mean()),"平均总仓位":float(curve.total_exposure.mean()),
           "年度收益":yearly}
    return curve,events,stats


def dual_engine_from_base(base, trades, stock_stats, market, etf, initial, index_cap):
    """在已计算的股票资金曲线上叠加指数，避免五档指数仓位重复跑股票撮合。"""
    curve,events,overlay=adaptive_index_overlay(base,market,initial,index_cap,tradable=etf)
    curve["exposure"]=curve.total_exposure.div(100).mul(curve.equity)
    curve["stock_cash"]=base.cash.reindex(curve.index).ffill()
    curve["stock_position_count"]=base.position_count.reindex(curve.index).ffill().fillna(0).astype(int)
    overlay.update({"交易次数":stock_stats["交易次数"],"胜率":stock_stats["胜率"],
                    "盈利交易":stock_stats["盈利交易"],"亏损交易":stock_stats["亏损交易"],
                    "资金利用率":overlay["平均总仓位"]})
    return curve,trades,events,overlay


def dual_engine_backtest(frames, market_flags, market, etf, initial, start, end=None, index_cap=0,
                         entry_rule="1 推荐"):
    """固定股票引擎叠加强市ETF引擎；市场状态只使用前一交易日数据。"""
    limited_frames={code:(frame.loc[:end] if end else frame) for code,frame in frames.items()}
    market_limited=market.loc[:end] if end else market
    etf_limited=etf.loc[:end] if end else etf
    base,trades,stock_stats=portfolio_backtest(
        limited_frames,market_flags,initial,start,"关闭",False,max_positions=8,
        max_position_pct=20,total_position_pct=80,risk_pct=.8,candidate_days=30,
        exit_profile="原规则",entry_profile="原始入场",entry_rule=entry_rule)
    return dual_engine_from_base(base,trades,stock_stats,market_limited,etf_limited,initial,index_cap)


def stability_rank(rows):
    """先保护最差年度，再看正收益年、目标区间接近程度和中位收益。"""
    returns=[float(r["总收益率"]) for r in rows]
    positive=sum(v>0 for v in returns); worst=min(returns,default=-999)
    average=float(np.mean(returns)) if returns else -999; median=float(np.median(returns)) if returns else -999
    drawdown=min((float(r["最大回撤"]) for r in rows),default=-999)
    target_distance=0.0 if 2<=average<=5 else min(abs(average-2),abs(average-5))
    return positive,worst,average,median,drawdown,target_distance


def evaluate_entry_rules(frames, market_flags, initial, historical_years, forward_start, progress=None):
    """同一数据和撮合口径并列计算四种入场规则；不按前向收益自动选规则。"""
    summary=[]; annual=[]; cache={}; total=max(1,len(ENTRY_RULES)*(len(historical_years)+1)); completed=0
    for entry_rule in ENTRY_RULES:
        historical=[]
        for year in historical_years:
            limited={code:frame.loc[:f"{year}-12-31"] for code,frame in frames.items()}
            curve,trades,stats=portfolio_backtest(
                limited,market_flags,initial,f"{year}-01-01","关闭",False,max_positions=8,
                max_position_pct=20,total_position_pct=80,risk_pct=.8,candidate_days=30,
                exit_profile="原规则",entry_profile="原始入场",entry_rule=entry_rule)
            cache[(entry_rule,str(year))]=(curve,trades,stats)
            row={"入场规则":entry_rule,"年份":year,**stats}; annual.append(row); historical.append(row)
            completed+=1
            if progress: progress(completed,total,f"{entry_rule} 历史{year}")
        forward=portfolio_backtest(
            frames,market_flags,initial,forward_start,"关闭",False,max_positions=8,
            max_position_pct=20,total_position_pct=80,risk_pct=.8,candidate_days=30,
            exit_profile="原规则",entry_profile="原始入场",entry_rule=entry_rule)
        cache[(entry_rule,"forward")]=forward; _,_,forward_stats=forward
        positive,worst,average,median,drawdown,distance=stability_rank(historical)
        qualified=len(historical)>=3 and positive>=((2*len(historical)+2)//3) and worst>=-1 and average>=2
        summary.append({"入场规则":entry_rule,"历史合格":"是" if qualified else "否","历史正收益年":positive,
                        "历史年数":len(historical),"历史最差":worst,"历史平均":average,"历史中位":median,
                        "历史最差回撤":drawdown,"前向收益":forward_stats["总收益率"],
                        "前向最大回撤":forward_stats["最大回撤"],"前向盈亏因子":forward_stats["盈亏因子"],
                        "前向交易":forward_stats["交易次数"],"前向胜率":forward_stats["胜率"],
                        "前向资金利用率":forward_stats["资金利用率"]})
        completed+=1
        if progress: progress(completed,total,f"{entry_rule} 前向回放")
    return {"summary":summary,"annual":annual,"cache":cache}


class FullMarketWorker(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, scanner):
        super().__init__()
        self.scanner = scanner
        self.pause_requested = False

    def run(self):
        stage = '核实沪深300收盘日'
        try:
            from astock_quant.desktop.weekly_trend_scanner import _safe_date
            cutoff = _safe_date()
            self.progress_changed.emit(0, '正在核实沪深300指数最近收盘日…')
            index = fetch_history('INDEX_000300', start_year=max(2018, cutoff.year-1),
                market_symbol='sh000300', force_refresh=True, persist=False, min_rows=2)
            days = pd.to_datetime(index.index, errors='coerce')
            candidates = [stamp.date() for stamp in days if not pd.isna(stamp) and stamp.date() <= cutoff]
            if not candidates:
                raise ValueError('未核实到最近已收盘交易日，无法以实时价代替收盘数据')
            target = max(candidates)
            if (cutoff - target).days > 15:
                raise ValueError(f'沪深300指数最新行情仅到 {target}，距离预期收盘日过久，已停止全市场检测')
            stage = '读取全A股股票池并逐只检测'
            result = self.scanner.scan(target=target,
                progress=lambda count, msg: self.progress_changed.emit(count, msg),
                should_pause=lambda: self.pause_requested)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(f'v{APP_VERSION} {stage}失败：{exc}')


class KlinePage(QWidget):
    def __init__(self):
        super().__init__(); self.worker = None
        root = QVBoxLayout(self)
        top = QHBoxLayout(); title = QLabel("行情与策略确认中心"); title.setObjectName("title")
        top.addWidget(title); top.addStretch(); self.code = QLineEdit("600519"); self.code.setMaximumWidth(130)
        top.addWidget(self.code); self.period = QComboBox(); self.period.addItems(["日线", "周线"]); top.addWidget(self.period)
        self.load_btn = QPushButton("加载并分析"); self.load_btn.clicked.connect(self.load); top.addWidget(self.load_btn); root.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        chart_box = QWidget(); chart_layout = QVBoxLayout(chart_box); self.chart = pg.GraphicsLayoutWidget(); self.chart.setBackground("#111c2e")
        chart_layout.addWidget(self.chart); split.addWidget(chart_box)
        side = QFrame(); side.setObjectName("card"); side_layout = QVBoxLayout(side)
        self.signal = QLabel("等待分析"); self.signal.setObjectName("title"); side_layout.addWidget(self.signal)
        self.rules = QTableWidget(0, 2); self.rules.setHorizontalHeaderLabels(["策略条件", "结果"]); self.rules.horizontalHeader().setStretchLastSection(True)
        self.rules.verticalHeader().setVisible(False); self.rules.setColumnWidth(0, 255); side_layout.addWidget(self.rules); split.addWidget(side); split.setSizes([760, 440]); root.addWidget(split)
        self.status = QLabel("输入股票代码后加载历史行情"); root.addWidget(self.status)
        from astock_quant.desktop.full_market_scanner import FullMarketScanner
        self.full_scanner = FullMarketScanner(APP_DIR,
            universe_loader=lambda: fetch_market_universe(force=True, include_st=True, persist=False),
            history_fetcher=lambda code: fetch_history(code, start_year=max(2018, datetime.now().year-2),
                force_refresh=True, persist=False))
        self.full_worker = None
        full_controls = QHBoxLayout()
        self.full_scan_btn = QPushButton('一键检测全A股（9月8日规则1）')
        self.full_pause_btn = QPushButton('暂停检测'); self.full_pause_btn.setEnabled(False)
        self.full_open_btn = QPushButton('打开上次全A股结果')
        self.full_export_btn = QPushButton('导出全A股 CSV')
        for button, callback in ((self.full_scan_btn, self.start_full_scan),
                                 (self.full_pause_btn, self.pause_full_scan),
                                 (self.full_open_btn, self.open_full_scan),
                                 (self.full_export_btn, self.export_full_scan)):
            button.clicked.connect(callback); full_controls.addWidget(button)
        root.addLayout(full_controls)
        self.full_progress = QProgressBar(); self.full_progress.setRange(0, 100); root.addWidget(self.full_progress)
        self.full_status = QLabel('全A股检测会先核实股票列表和最新收盘日，逐只保存进度；完成前结果标为部分结果。')
        self.full_status.setWordWrap(True); root.addWidget(self.full_status)
        self.full_table = QTableWidget(0, 6)
        self.full_table.setHorizontalHeaderLabels(['股票代码', '股票简称', '分级', '行情日期', '收盘价', '筛选说明'])
        self.full_table.verticalHeader().setVisible(False)
        self.full_table.horizontalHeader().setStretchLastSection(True)
        self.full_table.setMaximumHeight(230)
        self.full_table.cellDoubleClicked.connect(self.open_full_stock)
        root.addWidget(self.full_table)
        self.period.currentIndexChanged.connect(self.redraw); self.day = self.week = self.result = None

    def start_full_scan(self):
        if self.full_worker is not None and self.full_worker.isRunning():
            return
        self.full_scan_btn.setEnabled(False); self.full_pause_btn.setEnabled(True)
        self.full_progress.setRange(0, 0)
        self.full_status.setText('正在核实全A股列表和指数收盘日…')
        self.full_worker = FullMarketWorker(self.full_scanner)
        self.full_worker.progress_changed.connect(self.full_progress_update)
        self.full_worker.completed.connect(self.full_scan_completed)
        self.full_worker.failed.connect(self.full_scan_failed)
        self.full_worker.start()

    def pause_full_scan(self):
        if self.full_worker is not None:
            self.full_worker.pause_requested = True
            self.full_status.setText('正在保存当前股票结果并暂停…')

    def full_progress_update(self, count, message):
        import re
        progress = re.search(r'已检查 (\d+)/(\d+)', message)
        if progress:
            self.full_progress.setRange(0, int(progress.group(2)))
            self.full_progress.setValue(int(progress.group(1)))
        self.full_status.setText(message)

    def full_scan_completed(self, result):
        self.full_scan_btn.setEnabled(True); self.full_pause_btn.setEnabled(False)
        self.full_scan_btn.setText('继续检测全A股' if result.paused else '检查并重试失败股票')
        self.show_full_result(result)

    def full_scan_failed(self, message):
        self.full_scan_btn.setEnabled(True); self.full_pause_btn.setEnabled(False)
        self.full_progress.setRange(0, 100)
        self.full_status.setText('全A股检测中断：' + message + '；已保存的股票可再次点击续跑。')
        QMessageBox.warning(self, '全A股检测中断', message)

    def show_full_result(self, result):
        counts = {status: sum(row.status == status for row in result.rows)
                  for status in ('strong', 'confirm', 'preconfirm', 'stale')}
        self.full_progress.setRange(0, result.total)
        self.full_progress.setValue(result.completed)
        label = '已暂停，结果未完成' if result.paused else ('已完成，有数据缺口' if result.failed else '已完成')
        self.full_status.setText(
            f'{label}｜股票池 {result.total} 只｜已处理 {result.completed} 只｜'
            f'强确认 {counts["strong"]}、确认 {counts["confirm"]}、预确认 {counts["preconfirm"]}｜'
            f'ST/退市排除 {result.excluded}｜数据失败 {result.failed}（含过期 {counts["stale"]}）｜'
            f'截止日 {result.target}｜来源 {result.source}。双击入选股票查看K线；仅供研究，不自动下单。')
        labels = {'strong': '强确认', 'confirm': '确认', 'preconfirm': '预确认'}
        selected = [row for row in result.rows if row.status in labels]
        self.full_table.setRowCount(len(selected))
        for index, row in enumerate(selected):
            for column, value in enumerate((row.symbol, row.name, labels[row.status],
                                             row.latest_date, str(row.close or ''), row.reason_zh)):
                self.full_table.setItem(index, column, QTableWidgetItem(value))

    def open_full_scan(self):
        try:
            self.show_full_result(self.full_scanner.open_last())
        except Exception as exc:
            QMessageBox.warning(self, '无法打开上次全A股结果', str(exc))

    def export_full_scan(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出全A股逐只检查结果',
            str(APP_DIR / '全A股规则1筛选.csv'), 'CSV (*.csv)')
        if path:
            try:
                self.full_scanner.export_csv(Path(path))
                self.full_status.setText('已导出：' + path)
            except Exception as exc:
                QMessageBox.warning(self, '导出失败', str(exc))

    def open_full_stock(self, row, column):
        item = self.full_table.item(row, 0)
        if item is not None:
            self.code.setText(item.text())
            self.load()

    def load(self):
        code = self.code.text().strip()
        if len(code) != 6 or not code.isdigit(): QMessageBox.warning(self,"代码错误","请输入6位A股代码"); return
        self.load_btn.setEnabled(False); self.status.setText("正在下载前复权历史行情并计算策略…")
        self.worker = HistoryWorker(code); self.worker.success.connect(self.loaded); self.worker.failure.connect(self.failed); self.worker.start()

    def loaded(self, code, raw):
        try: self.day, self.week, self.result = evaluate(raw); self.redraw(); self.show_rules(code)
        except Exception as exc: self.failed(str(exc)); return
        self.load_btn.setEnabled(True); self.status.setText(f"{code} 分析完成 | {datetime.now():%Y-%m-%d %H:%M:%S} | 数据已缓存")
        if self.result["强确认买入通知"]: QMessageBox.information(self,"强确认买入通知",f"{code} 同时通过周线趋势、量能与日线确认。请结合风险承受能力人工复核。")
        elif self.result["买入观察通知"]: QMessageBox.information(self,"买入观察通知",f"{code} 周线趋势通过，且日线站上MA5/MA20并出现阳包阴。量能尚需复核。")

    def failed(self, msg): self.load_btn.setEnabled(True); self.status.setText("加载失败"); QMessageBox.warning(self,"加载失败",msg)

    def redraw(self):
        if self.day is None: return
        df = self.week if self.period.currentText() == "周线" else self.day
        df = df.tail(120).copy(); self.chart.clear(); price = self.chart.addPlot(row=0,col=0); price.showGrid(x=True,y=True,alpha=.15)
        price.addItem(CandleItem(df)); colors = {5:"#fbbf24",10:"#60a5fa",20:"#e879f9",60:"#e5e7eb"}
        x = np.arange(len(df))
        positions = sorted(set(np.linspace(0, len(df)-1, min(7, len(df)), dtype=int)))
        ticks = [(int(i), df.index[int(i)].strftime("%Y-%m-%d")) for i in positions]
        price.getAxis("bottom").setTicks([ticks])
        for n, color in colors.items():
            col = f"ma{n}"
            if col in df: price.plot(x, df[col].to_numpy(), pen=pg.mkPen(color,width=1.4), name=col.upper())
        volume = self.chart.addPlot(row=1,col=0); volume.setMaximumHeight(150); volume.setXLink(price)
        brushes = ["#ef4444" if c>=o else "#22c55e" for o,c in zip(df.open,df.close)]
        volume.addItem(pg.BarGraphItem(x=x,height=df.volume.to_numpy(),width=.65,brushes=brushes))
        if self.period.currentText() == "日线":
            macd = self.chart.addPlot(row=2,col=0); macd.setMaximumHeight(150); macd.setXLink(price)
            macd.plot(x,df.dif.to_numpy(),pen=pg.mkPen("#fbbf24")); macd.plot(x,df.dea.to_numpy(),pen=pg.mkPen("#60a5fa"))
            macd.addItem(pg.BarGraphItem(x=x,height=df.macd.to_numpy(),width=.65,brush="#94a3b8"))

    def show_rules(self, code):
        r = self.result; keys = [k for k in r if k not in ("止损参考价","周量比","MACD","KDJ")]
        self.rules.setRowCount(len(keys)+4)
        for row,key in enumerate(keys):
            value = "通过" if r[key] else "未通过"; a,b = QTableWidgetItem(key),QTableWidgetItem(value); b.setForeground(QColor("#ef4444" if r[key] else "#22c55e")); self.rules.setItem(row,0,a); self.rules.setItem(row,1,b)
        k,d,j = r["KDJ"]; extras = [("止损参考价",f'{r["止损参考价"]:.2f}'),("周成交量/5周均量",f'{r["周量比"]:.2f}倍'),("MACD",f'{r["MACD"]:.3f}'),("KDJ",f"K {k:.1f} / D {d:.1f} / J {j:.1f}")]
        for row,(key,value) in enumerate(extras,start=len(keys)): self.rules.setItem(row,0,QTableWidgetItem(key)); self.rules.setItem(row,1,QTableWidgetItem(value))
        if r["强确认买入通知"]: text,color="强确认买入","#ef4444"
        elif r["买入观察通知"]: text,color="买入观察","#f59e0b"
        elif r["逐步止盈信号"]: text,color="逐步止盈","#22c55e"
        else: text,color="宁可错过，暂不操作","#94a3b8"
        self.signal.setText(f"{code}：{text}"); self.signal.setStyleSheet(f"color:{color};font-size:20px;font-weight:700")


class BacktestPage(QWidget):
    def __init__(self):
        super().__init__(); self.worker = None
        root=QVBoxLayout(self); top=QHBoxLayout(); title=QLabel("单股策略历史回测"); title.setObjectName("title"); top.addWidget(title); top.addStretch()
        self.code=QLineEdit("600519"); self.code.setMaximumWidth(100); top.addWidget(QLabel("代码")); top.addWidget(self.code)
        self.capital=QSpinBox(); self.capital.setRange(10000,100000000); self.capital.setValue(100000); self.capital.setSingleStep(10000); top.addWidget(QLabel("初始资金")); top.addWidget(self.capital)
        self.position=QSpinBox(); self.position.setRange(5,50); self.position.setValue(20); self.position.setSuffix("%"); top.addWidget(QLabel("仓位上限")); top.addWidget(self.position)
        self.market_mode=QComboBox(); self.market_mode.addItems(["关闭","宽松","严格"]); self.market_mode.setCurrentText("严格"); top.addWidget(QLabel("大盘过滤")); top.addWidget(self.market_mode)
        self.commission=QDoubleSpinBox(); self.commission.setRange(0,20); self.commission.setValue(3); self.commission.setSuffix("‱"); top.addWidget(QLabel("佣金")); top.addWidget(self.commission)
        self.slippage=QDoubleSpinBox(); self.slippage.setRange(0,2); self.slippage.setValue(.1); self.slippage.setSuffix("%"); self.slippage.setSingleStep(.05); top.addWidget(QLabel("滑点")); top.addWidget(self.slippage)
        self.run_btn=QPushButton("开始回测"); self.run_btn.clicked.connect(self.run); top.addWidget(self.run_btn); root.addLayout(top)
        cards=QGridLayout(); self.metrics={}
        for col,name in enumerate(["期末资产","总收益率","最大回撤","交易次数","胜率","盈亏因子"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); cards.addWidget(card,0,col); self.metrics[name]=value
        root.addLayout(cards)
        self.diagnostic=QLabel("等待回测：完成后将在这里显示信号漏斗"); self.diagnostic.setStyleSheet("color:#fbbf24;padding:6px"); root.addWidget(self.diagnostic)
        self.curve=pg.PlotWidget(); self.curve.setBackground("#111c2e"); self.curve.showGrid(x=True,y=True,alpha=.15); self.curve.setLabel("left","标准化资金"); self.curve.setMaximumHeight(300); self.curve.addLegend(); root.addWidget(self.curve)
        self.trades=QTableWidget(0,13); self.trades.setHorizontalHeaderLabels(["买入日期","买入价","止损价","计划风险","卖出日期","卖出价","股数","收益额","收益率","MAE","MFE","持有日","离场原因"]); self.trades.horizontalHeader().setStretchLastSection(True); self.trades.verticalHeader().setVisible(False); root.addWidget(self.trades)
        self.status=QLabel("参数可修改；印花税默认按卖出金额0.05%计算"); root.addWidget(self.status)

    def run(self):
        code=self.code.text().strip()
        if len(code)!=6 or not code.isdigit(): QMessageBox.warning(self,"代码错误","请输入6位A股代码"); return
        self.run_btn.setEnabled(False); self.status.setText("正在读取历史数据并回测…")
        self.worker=HistoryWorker(code); self.worker.success.connect(self.loaded); self.worker.failure.connect(self.failed); self.worker.start()

    def loaded(self, code, raw):
        try:
            market=fetch_market_history(max(2018,raw.index[0].year))
            curve,trades,stats=backtest(raw,self.capital.value(),self.position.value(),self.commission.value()/10000,0.0005,self.slippage.value()/100,risk_pct=.8,market=market,market_mode=self.market_mode.currentText())
            formats={"期末资产":lambda x:f"¥{x:,.2f}","总收益率":lambda x:f"{x:.2f}%","最大回撤":lambda x:f"{x:.2f}%","交易次数":lambda x:str(x),"胜率":lambda x:f"{x:.1f}%","盈亏因子":lambda x:"∞" if np.isinf(x) else f"{x:.2f}"}
            for name,label in self.metrics.items(): label.setText(formats[name](stats[name]))
            self.curve.clear(); x=np.arange(len(curve)); self.curve.plot(x,curve.to_numpy(),pen=pg.mkPen("#60a5fa",width=2),name="策略资金")
            prices=raw.close.reindex(curve.index).ffill(); benchmark=self.capital.value()*prices/prices.iloc[0]
            self.curve.plot(x,benchmark.to_numpy(),pen=pg.mkPen("#94a3b8",width=1.5,style=Qt.DashLine),name="买入持有基准")
            positions=sorted(set(np.linspace(0,len(curve)-1,min(7,len(curve)),dtype=int))); self.curve.getAxis("bottom").setTicks([[(int(i),curve.index[int(i)].strftime("%Y-%m-%d")) for i in positions]])
            self.trades.setRowCount(len(trades))
            for row,t in enumerate(trades):
                values=[t["buy_date"].strftime("%Y-%m-%d"),f'{t["buy_price"]:.2f}',f'{t["stop"]:.2f}',f'{t["planned_risk"]:.2f}',t["sell_date"].strftime("%Y-%m-%d"),f'{t["sell_price"]:.2f}',str(t["shares"]),f'{t["pnl"]:.2f}',f'{t["return"]:.2f}%',f'{t["mae"]:.2f}%',f'{t["mfe"]:.2f}%',str(t["holding_days"]),t["reason"]]
                for col,value in enumerate(values): self.trades.setItem(row,col,QTableWidgetItem(value))
            self.diagnostic.setText(f"信号漏斗：原始周线候选 {stats['原始周线候选']}次｜大盘过滤 {stats['大盘过滤次数']}次｜日线确认 {stats['日线确认']}次｜最终交易 {stats['最终交易次数']}笔｜强确认 {stats['强确认']}次")
            self.status.setText(f"{code} 回测完成 | 蓝线=策略资金，灰色虚线=买入持有基准 | 共{len(raw)}个交易日")
        except Exception as exc: self.failed(str(exc)); return
        self.run_btn.setEnabled(True)

    def failed(self,msg): self.run_btn.setEnabled(True); self.status.setText("回测失败"); QMessageBox.warning(self,"回测失败",msg)


class BatchWorker(QThread):
    progress = Signal(int, str)
    success = Signal(list)
    failure = Signal(str)
    def __init__(self, codes, start_year, validation_year, initial, position, commission, slippage):
        super().__init__(); self.codes=codes; self.start_year=start_year; self.validation_year=validation_year; self.args=(initial,position,commission,0.0005,slippage)
    def run(self):
        results=[]
        try:
            market=fetch_market_history(self.start_year)
            for i,code in enumerate(self.codes,1):
                self.progress.emit(int((i-1)/len(self.codes)*100),f"正在处理 {code}（{i}/{len(self.codes)}）")
                try:
                    raw=fetch_history(code,start_year=self.start_year)
                    jumps=int((raw.close.pct_change().abs()>0.25).sum())
                    validation=raw.loc[f"{self.validation_year}-01-01":]
                    if len(validation)<60: raise ValueError("样本外数据不足60个交易日")
                    benchmark=(validation.close.iloc[-1]/validation.close.iloc[0]-1)*100
                    for market_mode in ("关闭","宽松","严格"):
                        for entry_mode,strong in (("买入观察",False),("放量强确认",True)):
                            curve,trades,stats=backtest(raw,*self.args,require_strong=strong,risk_pct=.8,market=market,market_mode=market_mode,evaluation_start=f"{self.validation_year}-01-01")
                            results.append({"代码":code,"入场模式":entry_mode,"大盘模式":market_mode,"起始":validation.index[0].strftime("%Y-%m-%d"),"结束":validation.index[-1].strftime("%Y-%m-%d"),
                                "原始候选":stats["原始周线候选"],"过滤候选":stats["大盘过滤次数"],"日线确认":stats["日线确认"],
                                "交易次数":stats["交易次数"],"收益率":stats["总收益率"],"最大回撤":stats["最大回撤"],"胜率":stats["胜率"],
                                "盈利交易":stats["盈利交易"],"亏损交易":stats["亏损交易"],"平均盈利":stats["平均盈利"],"平均亏损":stats["平均亏损"],
                                "盈亏因子":stats["盈亏因子"],"买入持有":benchmark,"异常跳变":jumps,"状态":"正常"})
                except Exception as exc:
                    results.append({"代码":code,"入场模式":"--","大盘模式":"--","起始":"--","结束":"--","原始候选":0,"过滤候选":0,"日线确认":0,"交易次数":0,"收益率":0,"最大回撤":0,"胜率":0,"盈利交易":0,"亏损交易":0,"平均盈利":0,"平均亏损":0,"盈亏因子":0,"买入持有":0,"异常跳变":0,"状态":str(exc)[:40]})
            self.progress.emit(100,"批量回测完成"); self.success.emit(results)
        except Exception as exc: self.failure.emit(str(exc))


class BatchPage(QWidget):
    def __init__(self):
        super().__init__(); self.worker=None; self.results=[]
        root=QVBoxLayout(self); top=QHBoxLayout(); title=QLabel("批量策略与等权组合回测"); title.setObjectName("title"); top.addWidget(title); top.addStretch()
        self.start_year=QSpinBox(); self.start_year.setRange(2005,datetime.now().year-1); self.start_year.setValue(2018); top.addWidget(QLabel("起始年份")); top.addWidget(self.start_year)
        self.validation_year=QSpinBox(); self.validation_year.setRange(2010,datetime.now().year); self.validation_year.setValue(2024); top.addWidget(QLabel("样本外起始")); top.addWidget(self.validation_year)
        self.initial=QSpinBox(); self.initial.setRange(10000,100000000); self.initial.setValue(100000); top.addWidget(QLabel("每股初始资金")); top.addWidget(self.initial)
        self.position=QSpinBox(); self.position.setRange(5,50); self.position.setValue(20); self.position.setSuffix("%"); top.addWidget(QLabel("仓位上限")); top.addWidget(self.position)
        self.run_btn=QPushButton("运行批量回测"); self.run_btn.clicked.connect(self.run); top.addWidget(self.run_btn)
        self.export_btn=QPushButton("导出CSV"); self.export_btn.clicked.connect(self.export); self.export_btn.setEnabled(False); top.addWidget(self.export_btn); root.addLayout(top)
        input_row=QHBoxLayout(); input_row.addWidget(QLabel("股票代码（逗号、空格或换行分隔）")); self.codes=QPlainTextEdit("600519,603993,002156,688333,000001,300750"); self.codes.setMaximumHeight(62); input_row.addWidget(self.codes,1)
        self.sample_btn=QPushButton("载入50只样本"); self.sample_btn.clicked.connect(self.load_sample); input_row.addWidget(self.sample_btn); root.addLayout(input_row)
        cards=QGridLayout(); self.summary={}
        for col,name in enumerate(["股票数量","关闭过滤平均收益","宽松过滤平均收益","严格过滤平均收益","最差最大回撤"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); cards.addWidget(card,0,col); self.summary[name]=value
        root.addLayout(cards)
        quality=QGridLayout(); self.quality={}
        for col,name in enumerate(["组合交易总数","盈利交易","亏损交易","平均单笔盈利","平均单笔亏损","收益集中提示"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); quality.addWidget(card,0,col); self.quality[name]=value
        root.addLayout(quality)
        charts=QSplitter(Qt.Horizontal); self.chart=pg.PlotWidget(); self.benchmark_chart=pg.PlotWidget()
        for chart,title in ((self.chart,"策略收益率 %"),(self.benchmark_chart,"买入持有 %")):
            chart.setBackground("#111c2e"); chart.showGrid(x=True,y=True,alpha=.15); chart.setLabel("left",title); chart.getAxis("left").enableAutoSIPrefix(False); chart.setMaximumHeight(250); charts.addWidget(chart)
        self.chart.addLegend()
        root.addWidget(charts)
        self.table=QTableWidget(0,20); self.table.setHorizontalHeaderLabels(["代码","入场模式","大盘模式","起始日期","结束日期","原始候选","过滤候选","日线确认","交易","盈利","亏损","平均盈利","平均亏损","收益率","最大回撤","胜率","盈亏因子","买入持有","异常跳变","状态"]); self.table.horizontalHeader().setStretchLastSection(True); self.table.verticalHeader().setVisible(False); root.addWidget(self.table)
        self.status=QLabel("提示：异常跳变指前复权序列中单日涨跌超过25%，需人工核对公司行为或数据质量"); root.addWidget(self.status)

    def parsed_codes(self):
        text=self.codes.toPlainText()
        for ch in ",，;；\n\t": text=text.replace(ch," ")
        return list(dict.fromkeys(x for x in text.split() if len(x)==6 and x.isdigit()))

    def load_sample(self):
        self.codes.setPlainText(SAMPLE_50); self.status.setText("已载入50只跨行业研究样本；首次运行时间较长，建议先用6只确认程序正常。")

    def run(self):
        codes=self.parsed_codes()
        if not codes: QMessageBox.warning(self,"没有代码","请输入至少一个6位股票代码"); return
        if len(codes)>100: QMessageBox.warning(self,"数量过多","单次最多回测100只股票"); return
        self.run_btn.setEnabled(False); self.export_btn.setEnabled(False); self.status.setText("正在开始批量回测…")
        if self.validation_year.value() <= self.start_year.value(): QMessageBox.warning(self,"年份错误","样本外起始年份必须晚于历史数据起始年份"); self.run_btn.setEnabled(True); return
        self.worker=BatchWorker(codes,self.start_year.value(),self.validation_year.value(),self.initial.value(),self.position.value(),0.0003,0.001)
        self.worker.progress.connect(lambda pct,msg:self.status.setText(f"{msg} | {pct}%")); self.worker.success.connect(self.loaded); self.worker.failure.connect(self.failed); self.worker.start()

    def loaded(self,results):
        self.results=results; self.table.setRowCount(len(results))
        for row,r in enumerate(results):
            pf="∞" if np.isinf(r["盈亏因子"]) else f'{r["盈亏因子"]:.2f}'
            vals=[r["代码"],r["入场模式"],r["大盘模式"],r["起始"],r["结束"],str(r["原始候选"]),str(r["过滤候选"]),str(r["日线确认"]),str(r["交易次数"]),str(r["盈利交易"]),str(r["亏损交易"]),f'{r["平均盈利"]:.2f}%',f'{r["平均亏损"]:.2f}%',f'{r["收益率"]:.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["胜率"]:.1f}%',pf,f'{r["买入持有"]:.2f}%',str(r["异常跳变"]),r["状态"]]
            for col,val in enumerate(vals): self.table.setItem(row,col,QTableWidgetItem(val))
        valid=[r for r in results if r["状态"]=="正常"]
        mean=lambda rows,key: float(np.mean([r[key] for r in rows])) if rows else 0
        self.summary["股票数量"].setText(str(len(set(r["代码"] for r in valid))))
        mode_rows={}
        for mode,label in (("关闭","关闭过滤平均收益"),("宽松","宽松过滤平均收益"),("严格","严格过滤平均收益")):
            rows=[r for r in valid if r["大盘模式"]==mode and r["入场模式"]=="买入观察"]
            mode_rows[mode]=rows
            self.summary[label].setText(f'{mean(rows,"收益率"):.2f}%')
        self.summary["最差最大回撤"].setText(f'{min([r["最大回撤"] for r in valid],default=0):.2f}%')
        best_mode=max(mode_rows,key=lambda m:mean(mode_rows[m],"收益率")) if mode_rows else "关闭"
        best=mode_rows.get(best_mode,[]); total_trades=sum(r["交易次数"] for r in best); wins=sum(r["盈利交易"] for r in best); losses=sum(r["亏损交易"] for r in best)
        avg_win=(sum(r["平均盈利"]*r["盈利交易"] for r in best)/wins) if wins else 0
        avg_loss=(sum(r["平均亏损"]*r["亏损交易"] for r in best)/losses) if losses else 0
        positive_codes=len({r["代码"] for r in best if r["收益率"]>0})
        self.quality["组合交易总数"].setText(str(total_trades)); self.quality["盈利交易"].setText(str(wins)); self.quality["亏损交易"].setText(str(losses))
        self.quality["平均单笔盈利"].setText(f"{avg_win:.2f}%"); self.quality["平均单笔亏损"].setText(f"{avg_loss:.2f}%")
        self.quality["收益集中提示"].setText("仅1只贡献" if positive_codes<=1 else f"{positive_codes}只贡献")
        self.chart.clear(); self.benchmark_chart.clear(); codes=sorted(set(r["代码"] for r in valid)); x=np.arange(len(codes)); width=.34
        get=lambda mode:[next((r["收益率"] for r in valid if r["代码"]==c and r["大盘模式"]==mode and r["入场模式"]=="买入观察"),0) for c in codes]
        bench=[next((r["买入持有"] for r in valid if r["代码"]==c),0) for c in codes]
        width=.24
        self.chart.addItem(pg.BarGraphItem(x=x-width,height=get("关闭"),width=width,brush="#60a5fa"),name="关闭过滤"); self.chart.addItem(pg.BarGraphItem(x=x,height=get("宽松"),width=width,brush="#f59e0b"),name="宽松过滤"); self.chart.addItem(pg.BarGraphItem(x=x+width,height=get("严格"),width=width,brush="#22c55e"),name="严格过滤"); self.chart.getAxis("bottom").setTicks([[*zip(x,codes)]])
        self.benchmark_chart.addItem(pg.BarGraphItem(x=x,height=bench,width=.6,brush="#94a3b8")); self.benchmark_chart.getAxis("bottom").setTicks([[*zip(x,codes)]])
        failed=len([r for r in results if r["状态"]!="正常"]); no_trade=len([r for r in valid if r["交易次数"]==0])
        self.run_btn.setEnabled(True); self.export_btn.setEnabled(True); self.status.setText(f"三档过滤对照完成：{len(codes)}只股票、{len(valid)}组结果｜当前平均收益最高：{best_mode}过滤｜失败{failed}组｜无交易{no_trade}组。")

    def failed(self,msg): self.run_btn.setEnabled(True); self.status.setText("批量回测失败"); QMessageBox.warning(self,"批量回测失败",msg)

    def export(self):
        if not self.results: return
        path,_=QFileDialog.getSaveFileName(self,"导出回测结果",str(APP_DIR/"batch_backtest.csv"),"CSV (*.csv)")
        if path:
            pd.DataFrame(self.results).to_csv(path,index=False,encoding="utf-8-sig"); self.status.setText(f"已导出：{path}")


class PortfolioWorker(QThread):
    progress=Signal(int,str); success=Signal(object); failure=Signal(str)
    def __init__(self,codes,start_year,validation_year,initial):
        super().__init__(); self.codes=codes; self.start_year=start_year; self.validation_year=validation_year; self.initial=initial
    def run(self):
        try:
            self.progress.emit(1,"读取沪深300数据")
            market=fetch_market_history(self.start_year); flags=build_market_flags(market); frames={}; raw_frames={}; errors=[]
            for i,code in enumerate(self.codes,1):
                self.progress.emit(int(i/len(self.codes)*70),f"读取并预计算 {code}（{i}/{len(self.codes)}）")
                try: frames[code]=build_signal_frame(fetch_history(code,start_year=self.start_year))
                except Exception as exc: errors.append(f"{code}:{str(exc)[:30]}")
            if not frames: raise RuntimeError("所有股票均取数失败")
            summaries=[]; curves={}; all_trades=[]; combos=[(m,e,s) for m in ("关闭","宽松","严格") for e,s in (("买入观察",False),("放量强确认",True))]
            for i,(market_mode,entry_mode,strong) in enumerate(combos,1):
                self.progress.emit(70+int(i/len(combos)*29),f"组合撮合：{market_mode}/{entry_mode}")
                curve,trades,stats=portfolio_backtest(frames,flags,self.initial,f"{self.validation_year}-01-01",market_mode,strong)
                key=f"{market_mode}-{entry_mode}"; curves[key]=curve
                summaries.append({"大盘模式":market_mode,"入场模式":entry_mode,**{k:v for k,v in stats.items() if k!="年度收益"},"年度收益":json.dumps(stats["年度收益"],ensure_ascii=False)})
                all_trades.extend([{"组合":key,**t} for t in trades])
            experiments=[]
            for candidate_days in (20,30,40):
                for max_positions in (5,8):
                    _,_,stats=portfolio_backtest(frames,flags,self.initial,f"{self.validation_year}-01-01","关闭",False,max_positions=max_positions,candidate_days=candidate_days)
                    experiments.append({"候选期":candidate_days,"最大持仓":max_positions,**{k:v for k,v in stats.items() if k!="年度收益"}})
            segments=[]; robustness=[]; current_year=datetime.now().year
            segment_specs=(("训练 2020-2021",2020,2021),("验证 2022-2023",2022,2023),(f"前向观察 2024-{current_year}",2024,current_year))
            for label,begin,end in segment_specs:
                if begin<self.start_year or begin>current_year: continue
                sliced={c:f.loc[:f"{end}-12-31"] for c,f in frames.items()}
                if not any(len(f.loc[f"{begin}-01-01":])>=60 for f in sliced.values()): continue
                bm=market.loc[f"{begin}-01-01":f"{end}-12-31"]
                benchmark_return=float((bm.close.iloc[-1]/bm.close.iloc[0]-1)*100) if len(bm)>1 else 0
                for candidate_days in (20,30,40):
                    for max_positions in (5,8):
                        _,_,stats=portfolio_backtest(sliced,flags,self.initial,f"{begin}-01-01","关闭",False,candidate_days=candidate_days,max_positions=max_positions)
                        item={"区间":label,"候选期":candidate_days,"最大持仓":max_positions,"基准收益":benchmark_return,
                              "超额收益":stats["总收益率"]-benchmark_return,**{k:v for k,v in stats.items() if k!="年度收益"}}
                        robustness.append(item)
                        if candidate_days==20 and max_positions==5: segments.append(item.copy())
            stability=[]
            for candidate_days in (20,30,40):
                for max_positions in (5,8):
                    rs=[r for r in robustness if r["候选期"]==candidate_days and r["最大持仓"]==max_positions]
                    historical=[r for r in rs if r["区间"].startswith(("训练","验证"))]
                    forward=next((r for r in rs if r["区间"].startswith("前向")),None)
                    positive=sum(r["总收益率"]>0 for r in historical); worst=min((r["总收益率"] for r in historical),default=0); avg=float(np.mean([r["总收益率"] for r in historical])) if historical else 0
                    stability.append({"候选期":candidate_days,"最大持仓":max_positions,"历史正收益段":positive,"历史段数":len(historical),"历史最差收益":worst,
                        "历史平均收益":avg,"前向收益":forward["总收益率"] if forward else 0,"前向超额":forward["超额收益"] if forward else 0})
            stability.sort(key=lambda r:(r["历史正收益段"],r["历史最差收益"],r["历史平均收益"]),reverse=True)
            for rank,r in enumerate(stability,1): r["稳健排名"]=rank
            benchmark_raw=market.loc[f"{self.validation_year}-01-01":]
            benchmark=self.initial*benchmark_raw.close/benchmark_raw.close.iloc[0]
            benchmark_total=float((benchmark_raw.close.iloc[-1]/benchmark_raw.close.iloc[0]-1)*100)
            for r in summaries: r["基准收益"]=benchmark_total; r["超额收益"]=r["总收益率"]-benchmark_total
            self.progress.emit(100,"共享资金组合回测完成")
            self.success.emit({"summaries":summaries,"curves":curves,"trades":all_trades,"experiments":experiments,"segments":segments,
                "robustness":robustness,"stability":stability,
                "benchmark":benchmark,"errors":errors,"stock_count":len(frames)})
        except Exception as exc: self.failure.emit(str(exc))


class PortfolioPage(QWidget):
    def __init__(self):
        super().__init__(); self.worker=None; self.payload=None
        root=QVBoxLayout(self); top=QHBoxLayout(); title=QLabel("共享资金组合回测"); title.setObjectName("title"); top.addWidget(title); top.addStretch()
        self.start_year=QSpinBox(); self.start_year.setRange(2005,datetime.now().year-1); self.start_year.setValue(2018); top.addWidget(QLabel("数据起始")); top.addWidget(self.start_year)
        self.validation_year=QSpinBox(); self.validation_year.setRange(2010,datetime.now().year); self.validation_year.setValue(2024); top.addWidget(QLabel("样本外起始")); top.addWidget(self.validation_year)
        self.initial=QSpinBox(); self.initial.setRange(10000,100000000); self.initial.setValue(100000); top.addWidget(QLabel("共享资金")); top.addWidget(self.initial)
        self.run_btn=QPushButton("运行组合回测"); self.run_btn.clicked.connect(self.run); top.addWidget(self.run_btn)
        self.export_btn=QPushButton("导出结果"); self.export_btn.clicked.connect(self.export); self.export_btn.setEnabled(False); top.addWidget(self.export_btn); root.addLayout(top)
        row=QHBoxLayout(); row.addWidget(QLabel("股票池")); self.codes=QPlainTextEdit("600519,603993,002156,688333,000001,300750"); self.codes.setMaximumHeight(58); row.addWidget(self.codes,1)
        sample=QPushButton("载入50只样本"); sample.clicked.connect(lambda:self.codes.setPlainText(SAMPLE_50)); row.addWidget(sample); root.addLayout(row)
        cards=QGridLayout(); self.metrics={}
        for col,name in enumerate(["最佳组合","期末资产","总收益率","超额收益","年化收益","最大回撤","交易次数","盈亏因子","资金利用率"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); cards.addWidget(card,col//5,col%5); self.metrics[name]=value
        root.addLayout(cards)
        charts=QSplitter(Qt.Vertical)
        self.chart=pg.PlotWidget(); self.chart.setBackground("#111c2e"); self.chart.showGrid(x=True,y=True,alpha=.15); self.chart.setLabel("left","共享资金"); self.chart.getAxis("left").enableAutoSIPrefix(False); self.chart.addLegend(); charts.addWidget(self.chart)
        self.exposure_chart=pg.PlotWidget(); self.exposure_chart.setBackground("#111c2e"); self.exposure_chart.showGrid(x=True,y=True,alpha=.15); self.exposure_chart.setLabel("left","仓位 %"); self.exposure_chart.setMaximumHeight(120); charts.addWidget(self.exposure_chart); charts.setSizes([220,90]); root.addWidget(charts)
        self.tabs=QTabWidget(); self.tabs.setMinimumHeight(245); self.table=QTableWidget(0,15); self.table.setHorizontalHeaderLabels(["大盘模式","入场模式","期末资产","收益率","基准收益","超额收益","年化","最大回撤","夏普","交易","胜率","盈亏因子","资金利用率","盈利/亏损","年度收益"])
        self.attribution=QTableWidget(0,8); self.attribution.setHorizontalHeaderLabels(["分组","代码","交易","盈利","亏损","累计盈亏","平均收益","离场原因"])
        self.exit_table=QTableWidget(0,6); self.exit_table.setHorizontalHeaderLabels(["离场原因","交易","盈利","亏损","累计盈亏","平均收益"]); self.exit_table.setMaximumHeight(115)
        attr_page=QWidget(); attr_layout=QVBoxLayout(attr_page); attr_layout.setContentsMargins(0,0,0,0); attr_layout.addWidget(self.attribution); attr_layout.addWidget(self.exit_table)
        self.segments=QTableWidget(0,11); self.segments.setHorizontalHeaderLabels(["区间","收益率","基准收益","超额收益","年化","最大回撤","夏普","交易","胜率","盈亏因子","资金利用率"])
        self.experiments=QTableWidget(0,9); self.experiments.setHorizontalHeaderLabels(["候选期","最多持仓","收益率","年化","最大回撤","交易","胜率","盈亏因子","资金利用率"])
        self.robustness=QTableWidget(0,12); self.robustness.setHorizontalHeaderLabels(["区间","候选期","最多持仓","收益率","基准","超额","最大回撤","交易","胜率","盈亏因子","资金利用率","结果"])
        self.stability=QTableWidget(0,8); self.stability.setHorizontalHeaderLabels(["排名","候选期","最多持仓","历史正收益段","历史最差","历史平均","前向收益","前向超额"])
        for table in (self.table,self.attribution,self.exit_table,self.segments,self.experiments,self.robustness,self.stability): table.horizontalHeader().setStretchLastSection(True); table.verticalHeader().setVisible(False)
        self.tabs.addTab(self.table,"组合对比"); self.tabs.addTab(attr_page,"股票与离场归因"); self.tabs.addTab(self.segments,"固定基线分段"); self.tabs.addTab(self.experiments,"当前区间实验"); self.tabs.addTab(self.robustness,"滚动参数矩阵"); self.tabs.addTab(self.stability,"稳健性排名"); root.addWidget(self.tabs)
        self.status=QLabel("真实共享10万元；最多5只、单股20%、总仓位80%、每笔风险0.8%、同行业最多2只"); root.addWidget(self.status)

    def parsed_codes(self):
        text=self.codes.toPlainText()
        for ch in ",，;；\n\t": text=text.replace(ch," ")
        return list(dict.fromkeys(x for x in text.split() if len(x)==6 and x.isdigit()))

    def run(self):
        codes=self.parsed_codes()
        if not codes: QMessageBox.warning(self,"没有代码","请输入至少一个6位股票代码"); return
        if len(codes)>100: QMessageBox.warning(self,"数量过多","单次最多100只股票"); return
        if self.validation_year.value()<=self.start_year.value(): QMessageBox.warning(self,"年份错误","样本外起始年份必须晚于数据起始年份"); return
        self.run_btn.setEnabled(False); self.export_btn.setEnabled(False); self.status.setText("正在读取缓存并预计算信号…")
        self.worker=PortfolioWorker(codes,self.start_year.value(),self.validation_year.value(),self.initial.value()); self.worker.progress.connect(lambda p,m:self.status.setText(f"{m} | {p}%")); self.worker.success.connect(self.loaded); self.worker.failure.connect(self.failed); self.worker.start()

    def loaded(self,payload):
        self.payload=payload; rows=payload["summaries"]; best=max(rows,key=lambda r:r["总收益率"])
        pf=lambda x:"∞" if np.isinf(x) else f"{x:.2f}"
        values={"最佳组合":f'{best["大盘模式"]}/{best["入场模式"]}',"期末资产":f'¥{best["期末资产"]:,.2f}',"总收益率":f'{best["总收益率"]:.2f}%',"超额收益":f'{best["超额收益"]:.2f}%',"年化收益":f'{best["年化收益"]:.2f}%',"最大回撤":f'{best["最大回撤"]:.2f}%',"交易次数":str(best["交易次数"]),"盈亏因子":pf(best["盈亏因子"]),"资金利用率":f'{best["资金利用率"]:.1f}%'}
        for k,v in values.items(): self.metrics[k].setText(v)
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            yearly=json.loads(r["年度收益"]); yearly_text="｜".join(f"{y}:{v:+.2f}%" for y,v in yearly.items())
            vals=[r["大盘模式"],r["入场模式"],f'{r["期末资产"]:.2f}',f'{r["总收益率"]:.2f}%',f'{r["基准收益"]:.2f}%',f'{r["超额收益"]:.2f}%',f'{r["年化收益"]:.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',str(r["交易次数"]),f'{r["胜率"]:.1f}%',pf(r["盈亏因子"]),f'{r["资金利用率"]:.1f}%',f'{r["盈利交易"]}/{r["亏损交易"]}',yearly_text]
            for j,v in enumerate(vals): self.table.setItem(i,j,QTableWidgetItem(v))
        self.chart.clear(); colors={"关闭":"#60a5fa","宽松":"#f59e0b","严格":"#22c55e"}
        for mode in ("关闭","宽松","严格"):
            curve=payload["curves"][f"{mode}-买入观察"]; self.chart.plot(np.arange(len(curve)),curve.equity.to_numpy(),pen=pg.mkPen(colors[mode],width=2),name=f"{mode}过滤")
        curve=payload["curves"]["关闭-买入观察"]; benchmark=payload["benchmark"].reindex(curve.index).ffill().bfill(); self.chart.plot(np.arange(len(curve)),benchmark.to_numpy(),pen=pg.mkPen("#e5e7eb",width=1.5,style=Qt.DashLine),name="沪深300基准"); self.chart.plot(np.arange(len(curve)),np.full(len(curve),self.initial.value()),pen=pg.mkPen("#64748b",width=1,style=Qt.DotLine),name="现金基线")
        ticks=sorted(set(np.linspace(0,len(curve)-1,min(7,len(curve)),dtype=int))); axis_ticks=[(int(i),curve.index[int(i)].strftime("%Y-%m-%d")) for i in ticks]; self.chart.getAxis("bottom").setTicks([axis_ticks])
        self.exposure_chart.clear()
        for mode in ("关闭","宽松","严格"):
            c=payload["curves"][f"{mode}-买入观察"]; exposure=(c.exposure/c.equity.replace(0,np.nan)*100).fillna(0); self.exposure_chart.plot(np.arange(len(c)),exposure.to_numpy(),pen=pg.mkPen(colors[mode],width=1.5))
        self.exposure_chart.getAxis("bottom").setTicks([axis_ticks])
        best_key=f'{best["大盘模式"]}-{best["入场模式"]}'; best_trades=[t for t in payload["trades"] if t["组合"]==best_key]
        attribution=[]
        for code in sorted({t["code"] for t in best_trades}):
            ts=[t for t in best_trades if t["code"]==code]; wins=sum(t["pnl"]>0 for t in ts); losses=sum(t["pnl"]<0 for t in ts); reasons={}
            for t in ts: reasons[t["reason"]]=reasons.get(t["reason"],0)+1
            attribution.append({"代码":code,"交易":len(ts),"盈利":wins,"亏损":losses,"累计盈亏":sum(t["pnl"] for t in ts),"平均收益":float(np.mean([t["return"] for t in ts])),"离场原因":"/".join(f"{k}:{v}" for k,v in reasons.items())})
        attribution.sort(key=lambda x:x["累计盈亏"],reverse=True); top=attribution[:10]; top_codes={r["代码"] for r in top}; bottom=[r for r in attribution[-10:] if r["代码"] not in top_codes]; shown=[("贡献前10",r) for r in top]+[("拖累后10",r) for r in bottom]; self.attribution.setRowCount(len(shown))
        for i,(group,r) in enumerate(shown):
            for j,v in enumerate([group,r["代码"],r["交易"],r["盈利"],r["亏损"],f'{r["累计盈亏"]:.2f}',f'{r["平均收益"]:.2f}%',r["离场原因"]]): self.attribution.setItem(i,j,QTableWidgetItem(str(v)))
        exit_rows=[]
        for reason in sorted({t["reason"] for t in best_trades}):
            ts=[t for t in best_trades if t["reason"]==reason]; exit_rows.append((reason,len(ts),sum(t["pnl"]>0 for t in ts),sum(t["pnl"]<0 for t in ts),sum(t["pnl"] for t in ts),float(np.mean([t["return"] for t in ts]))))
        self.exit_table.setRowCount(len(exit_rows))
        for i,r in enumerate(exit_rows):
            for j,v in enumerate([r[0],r[1],r[2],r[3],f'{r[4]:.2f}',f'{r[5]:.2f}%']): self.exit_table.setItem(i,j,QTableWidgetItem(str(v)))
        self.segments.setRowCount(len(payload["segments"]))
        for i,r in enumerate(payload["segments"]):
            vals=[r["区间"],f'{r["总收益率"]:.2f}%',f'{r["基准收益"]:.2f}%',f'{r["超额收益"]:.2f}%',f'{r["年化收益"]:.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',r["交易次数"],f'{r["胜率"]:.1f}%',pf(r["盈亏因子"]),f'{r["资金利用率"]:.1f}%']
            for j,v in enumerate(vals): self.segments.setItem(i,j,QTableWidgetItem(str(v)))
        self.experiments.setRowCount(len(payload["experiments"]))
        for i,r in enumerate(payload["experiments"]):
            vals=[r["候选期"],r["最大持仓"],f'{r["总收益率"]:.2f}%',f'{r["年化收益"]:.2f}%',f'{r["最大回撤"]:.2f}%',r["交易次数"],f'{r["胜率"]:.1f}%',pf(r["盈亏因子"]),f'{r["资金利用率"]:.1f}%']
            for j,v in enumerate(vals): self.experiments.setItem(i,j,QTableWidgetItem(str(v)))
        self.robustness.setRowCount(len(payload["robustness"]))
        for i,r in enumerate(payload["robustness"]):
            result="正收益" if r["总收益率"]>0 else "亏损"
            vals=[r["区间"],r["候选期"],r["最大持仓"],f'{r["总收益率"]:.2f}%',f'{r["基准收益"]:.2f}%',f'{r["超额收益"]:.2f}%',f'{r["最大回撤"]:.2f}%',r["交易次数"],f'{r["胜率"]:.1f}%',pf(r["盈亏因子"]),f'{r["资金利用率"]:.1f}%',result]
            for j,v in enumerate(vals): self.robustness.setItem(i,j,QTableWidgetItem(str(v)))
        self.stability.setRowCount(len(payload["stability"]))
        for i,r in enumerate(payload["stability"]):
            vals=[r["稳健排名"],r["候选期"],r["最大持仓"],f'{r["历史正收益段"]}/{r["历史段数"]}',f'{r["历史最差收益"]:.2f}%',f'{r["历史平均收益"]:.2f}%',f'{r["前向收益"]:.2f}%',f'{r["前向超额"]:.2f}%']
            for j,v in enumerate(vals): self.stability.setItem(i,j,QTableWidgetItem(str(v)))
        for table in (self.table,self.attribution,self.exit_table,self.segments,self.experiments,self.robustness,self.stability): table.resizeColumnsToContents()
        self.run_btn.setEnabled(True); self.export_btn.setEnabled(True); err=f"｜取数失败{len(payload['errors'])}只" if payload["errors"] else ""
        self.status.setText(f"完成：{payload['stock_count']}只股票共用一笔资金{err}。白虚线=沪深300；下图=每日仓位。最佳仅指本次样本外结果。")

    def failed(self,msg): self.run_btn.setEnabled(True); self.status.setText("组合回测失败"); QMessageBox.warning(self,"组合回测失败",msg)

    def export(self):
        if not self.payload: return
        path,_=QFileDialog.getSaveFileName(self,"导出组合结果",str(APP_DIR/"portfolio_summary.csv"),"CSV (*.csv)")
        if not path: return
        p=Path(path); pd.DataFrame(self.payload["summaries"]).to_csv(p,index=False,encoding="utf-8-sig")
        trades=pd.DataFrame(self.payload["trades"]); trade_path=p.with_name(p.stem+"_trades.csv"); trades.to_csv(trade_path,index=False,encoding="utf-8-sig")
        exp_path=p.with_name(p.stem+"_experiments.csv"); seg_path=p.with_name(p.stem+"_segments.csv")
        pd.DataFrame(self.payload["experiments"]).to_csv(exp_path,index=False,encoding="utf-8-sig"); pd.DataFrame(self.payload["segments"]).to_csv(seg_path,index=False,encoding="utf-8-sig")
        robust_path=p.with_name(p.stem+"_robustness.csv"); rank_path=p.with_name(p.stem+"_stability.csv")
        pd.DataFrame(self.payload["robustness"]).to_csv(robust_path,index=False,encoding="utf-8-sig"); pd.DataFrame(self.payload["stability"]).to_csv(rank_path,index=False,encoding="utf-8-sig")
        self.status.setText(f"已导出：{p.name}及交易、实验、分段、滚动矩阵、稳健排名")


class EnhancedWorker(QThread):
    progress=Signal(int,str); success=Signal(object); failure=Signal(str)
    def __init__(self,codes,start_year,validation_year,initial):
        super().__init__(); self.codes=codes; self.start_year=start_year; self.validation_year=validation_year; self.initial=initial

    def run(self):
        try:
            self.progress.emit(2,"读取沪深300并准备市场状态")
            market=fetch_market_history(self.start_year); flags=build_market_flags(market); frames={}; raw_frames={}; errors=[]
            for i,code in enumerate(self.codes,1):
                self.progress.emit(3+int(i/len(self.codes)*42),f"准备增强指标 {code}（{i}/{len(self.codes)}）")
                try:
                    raw=fetch_history(code,start_year=self.start_year)
                    if len(raw)<260: raise ValueError("历史不足260日")
                    frames[code]=prepare_enhanced_frame(raw,market)
                except Exception as exc: errors.append(f"{code}:{str(exc)[:50]}")
            if not frames:
                detail="；".join(errors[:5]) if errors else "没有返回错误明细"
                raise RuntimeError(f"所有股票均取数失败。前5项：{detail}")
            historical_end=min(self.validation_year-1,2023); configurations=[]
            for idx,max_positions in enumerate((5,8,10),1):
                segment_results=[]
                for label,begin,end in (("训练2020-2021",2020,2021),("验证2022-2023",2022,historical_end)):
                    if end<begin: continue
                    sliced={c:f.loc[:f"{end}-12-31"] for c,f in frames.items()}
                    _,_,stats=enhanced_portfolio_backtest(sliced,market.loc[:f"{end}-12-31"],self.initial,f"{begin}-01-01",max_positions=max_positions)
                    segment_results.append({"区间":label,"最多持仓":max_positions,**stats})
                positive=sum(r["总收益率"]>0 for r in segment_results); worst=min((r["总收益率"] for r in segment_results),default=-999); average=float(np.mean([r["总收益率"] for r in segment_results])) if segment_results else -999
                configurations.append({"最多持仓":max_positions,"正收益段":positive,"历史最差":worst,"历史平均":average,"历史分段":segment_results})
                self.progress.emit(45+idx*8,f"历史区间验证：最多持仓{max_positions}只")
            configurations.sort(key=lambda r:(r["正收益段"],r["历史最差"],r["历史平均"]),reverse=True); selected=configurations[0]["最多持仓"]
            rows=[]; curves={}; all_trades=[]; forward_start=f"{self.validation_year}-01-01"
            benchmark_raw=market.loc[forward_start:]
            if len(benchmark_raw)<2: raise ValueError("前向观察区间缺少沪深300数据")
            benchmark=self.initial*benchmark_raw.close/benchmark_raw.close.iloc[0]; benchmark_return=float((benchmark_raw.close.iloc[-1]/benchmark_raw.close.iloc[0]-1)*100)
            for idx,max_positions in enumerate((5,8,10),1):
                base_curve,base_trades,base_stats=portfolio_backtest(frames,flags,self.initial,forward_start,"关闭",False,max_positions=max_positions,candidate_days=30)
                enhanced_curve,enhanced_trades,enhanced_stats=enhanced_portfolio_backtest(frames,market,self.initial,forward_start,max_positions=max_positions)
                for strategy,curve,trades,stats in (("原策略",base_curve,base_trades,base_stats),("增强策略",enhanced_curve,enhanced_trades,enhanced_stats)):
                    key=f"{strategy}-{max_positions}"; curves[key]=curve; all_trades.extend([{"策略":key,**t} for t in trades])
                    rows.append({"策略":strategy,"最多持仓":max_positions,"历史选定":"是" if strategy=="增强策略" and max_positions==selected else "否",
                                 "基准收益":benchmark_return,"超额收益":stats["总收益率"]-benchmark_return,**{k:v for k,v in stats.items() if k!="年度收益"},"年度收益":json.dumps(stats["年度收益"],ensure_ascii=False)})
                self.progress.emit(70+idx*7,f"前向对照：最多持仓{max_positions}只")
            forward_selected=next(r for r in rows if r["策略"]=="增强策略" and r["最多持仓"]==selected)
            historical_segments=next(c["历史分段"] for c in configurations if c["最多持仓"]==selected)
            segment_payload=[]
            for label,begin,end in (("训练2020-2021",2020,2021),("验证2022-2023",2022,historical_end),(f"前向{self.validation_year}-{datetime.now().year}",self.validation_year,datetime.now().year)):
                if end<begin: continue
                if begin>=self.validation_year:
                    stats=forward_selected; bm=benchmark_return
                else:
                    existing=next((r for r in historical_segments if r["区间"]==label),None)
                    if existing is None: continue
                    stats=existing; m=market.loc[f"{begin}-01-01":f"{end}-12-31"]; bm=float((m.close.iloc[-1]/m.close.iloc[0]-1)*100) if len(m)>1 else 0
                segment_payload.append({"区间":label,"基准收益":bm,"超额收益":stats["总收益率"]-bm,**{k:v for k,v in stats.items() if k not in ("区间","最多持仓","年度收益")}})
            selected_key=f"增强策略-{selected}"; selected_curve=curves[selected_key]; selected_trades=[t for t in all_trades if t["策略"]==selected_key]
            diagnostics={k:forward_selected.get(k,0) for k in ("周线候选","相对强度通过","阳包阴确认","突破确认","流动性过滤","风控拒绝")}
            self.progress.emit(100,"增强策略对照完成")
            self.success.emit({"rows":rows,"curves":curves,"benchmark":benchmark,"selected":selected,"segments":segment_payload,
                               "configurations":configurations,"trades":selected_trades,"diagnostics":diagnostics,"errors":errors,"stock_count":len(frames)})
        except Exception as exc: self.failure.emit(str(exc))


class EnhancedResearchPage(QWidget):
    def __init__(self):
        super().__init__(); self.worker=None; self.payload=None
        root=QVBoxLayout(self); top=QHBoxLayout(); title=QLabel("策略增强与样本外验证"); title.setObjectName("title"); top.addWidget(title); top.addStretch()
        self.start_year=QSpinBox(); self.start_year.setRange(2008,2020); self.start_year.setValue(2018); top.addWidget(QLabel("数据起始")); top.addWidget(self.start_year)
        self.validation_year=QSpinBox(); self.validation_year.setRange(2024,datetime.now().year); self.validation_year.setValue(2024); top.addWidget(QLabel("前向起始")); top.addWidget(self.validation_year)
        self.initial=QSpinBox(); self.initial.setRange(10000,100000000); self.initial.setValue(100000); top.addWidget(QLabel("初始资金")); top.addWidget(self.initial)
        self.run_btn=QPushButton("运行增强对照"); self.run_btn.clicked.connect(self.run); top.addWidget(self.run_btn)
        self.export_btn=QPushButton("导出研究结果"); self.export_btn.clicked.connect(self.export); self.export_btn.setEnabled(False); top.addWidget(self.export_btn); root.addLayout(top)
        row=QHBoxLayout(); row.addWidget(QLabel("研究股票池")); self.codes=QPlainTextEdit(SAMPLE_50); self.codes.setMaximumHeight(58); row.addWidget(self.codes,1); root.addLayout(row)
        notice=QLabel("参数选择只使用2020—2023历史区间；2024年至今只做前向观察。模拟交易入口已暂停。")
        notice.setStyleSheet("color:#fbbf24;padding:4px"); root.addWidget(notice)
        cards=QGridLayout(); self.metrics={}
        for col,name in enumerate(["历史选定持仓数","增强期末资产","增强总收益","沪深300基准","增强超额收益","增强最大回撤","增强盈亏因子","增强交易数"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); cards.addWidget(card,col//4,col%4); self.metrics[name]=value
        root.addLayout(cards)
        charts=QSplitter(Qt.Vertical); self.chart=pg.PlotWidget(); self.chart.setBackground("#111c2e"); self.chart.showGrid(x=True,y=True,alpha=.15); self.chart.setLabel("left","账户资产"); self.chart.getAxis("left").enableAutoSIPrefix(False); self.chart.addLegend(); charts.addWidget(self.chart)
        self.exposure=pg.PlotWidget(); self.exposure.setBackground("#111c2e"); self.exposure.showGrid(x=True,y=True,alpha=.15); self.exposure.setLabel("left","仓位 %"); self.exposure.setMaximumHeight(110); charts.addWidget(self.exposure); charts.setSizes([230,90]); root.addWidget(charts)
        self.tabs=QTabWidget(); self.tabs.setMinimumHeight(245)
        self.comparison=QTableWidget(0,15); self.comparison.setHorizontalHeaderLabels(["策略","最多持仓","历史选定","期末资产","收益率","基准","超额","年化","最大回撤","夏普","交易","胜率","盈亏因子","资金利用率","盈利/亏损"])
        self.segments=QTableWidget(0,11); self.segments.setHorizontalHeaderLabels(["区间","收益率","基准","超额","年化","最大回撤","夏普","交易","胜率","盈亏因子","资金利用率"])
        self.diagnostics=QTableWidget(0,2); self.diagnostics.setHorizontalHeaderLabels(["增强信号漏斗","次数"])
        self.trades=QTableWidget(0,10); self.trades.setHorizontalHeaderLabels(["代码","入场信号","买入日期","买入价","止损初值","卖出日期","卖出价","收益额","收益率","离场原因"])
        for table in (self.comparison,self.segments,self.diagnostics,self.trades): table.horizontalHeader().setStretchLastSection(True); table.verticalHeader().setVisible(False)
        self.tabs.addTab(self.comparison,"原策略/增强策略"); self.tabs.addTab(self.segments,"分段验证"); self.tabs.addTab(self.diagnostics,"信号漏斗"); self.tabs.addTab(self.trades,"增强交易审计"); root.addWidget(self.tabs)
        self.status=QLabel("等待运行；增强策略固定使用相对强度、ATR 2.5倍、30日时间止损和动态仓位。")
        self.status.setStyleSheet("color:#93c5fd;padding:4px"); root.addWidget(self.status)

    def parsed_codes(self):
        text=self.codes.toPlainText()
        for ch in ",，;；\n\t": text=text.replace(ch," ")
        return list(dict.fromkeys(x for x in text.split() if len(x)==6 and x.isdigit()))

    def run(self):
        codes=self.parsed_codes()
        if not codes: QMessageBox.warning(self,"没有代码","请输入股票代码"); return
        if len(codes)>100: QMessageBox.warning(self,"数量过多","单次研究最多100只股票"); return
        self.run_btn.setEnabled(False); self.export_btn.setEnabled(False); self.status.setText("正在加载历史数据…")
        self.worker=EnhancedWorker(codes,self.start_year.value(),self.validation_year.value(),self.initial.value()); self.worker.progress.connect(lambda p,m:self.status.setText(f"{m} | {p}%")); self.worker.success.connect(self.loaded); self.worker.failure.connect(self.failed); self.worker.start()

    def loaded(self,payload):
        self.payload=payload; selected=payload["selected"]; chosen=next(r for r in payload["rows"] if r["策略"]=="增强策略" and r["最多持仓"]==selected); pf=lambda x:"∞" if np.isinf(x) else f"{x:.2f}"
        values={"历史选定持仓数":f"{selected}只","增强期末资产":f'¥{chosen["期末资产"]:,.2f}',"增强总收益":f'{chosen["总收益率"]:+.2f}%',"沪深300基准":f'{chosen["基准收益"]:+.2f}%',"增强超额收益":f'{chosen["超额收益"]:+.2f}%',"增强最大回撤":f'{chosen["最大回撤"]:.2f}%',"增强盈亏因子":pf(chosen["盈亏因子"]),"增强交易数":str(chosen["交易次数"])}
        for key,value in values.items(): self.metrics[key].setText(value)
        rows=payload["rows"]; self.comparison.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=[r["策略"],r["最多持仓"],r["历史选定"],f'{r["期末资产"]:.2f}',f'{r["总收益率"]:+.2f}%',f'{r["基准收益"]:+.2f}%',f'{r["超额收益"]:+.2f}%',f'{r["年化收益"]:+.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',r["交易次数"],f'{r["胜率"]:.1f}%',pf(r["盈亏因子"]),f'{r["资金利用率"]:.1f}%',f'{r["盈利交易"]}/{r["亏损交易"]}']
            for j,v in enumerate(vals): self.comparison.setItem(i,j,QTableWidgetItem(str(v)))
        self.segments.setRowCount(len(payload["segments"]))
        for i,r in enumerate(payload["segments"]):
            vals=[r["区间"],f'{r["总收益率"]:+.2f}%',f'{r["基准收益"]:+.2f}%',f'{r["超额收益"]:+.2f}%',f'{r["年化收益"]:+.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',r["交易次数"],f'{r["胜率"]:.1f}%',pf(r["盈亏因子"]),f'{r["资金利用率"]:.1f}%']
            for j,v in enumerate(vals): self.segments.setItem(i,j,QTableWidgetItem(str(v)))
        items=list(payload["diagnostics"].items()); self.diagnostics.setRowCount(len(items))
        for i,(key,value) in enumerate(items): self.diagnostics.setItem(i,0,QTableWidgetItem(key)); self.diagnostics.setItem(i,1,QTableWidgetItem(str(value)))
        trades=payload["trades"]; self.trades.setRowCount(len(trades))
        for i,t in enumerate(trades):
            vals=[t["code"],t.get("entry_signal","--"),pd.Timestamp(t["buy_date"]).strftime("%Y-%m-%d"),f'{t["entry"]:.2f}',f'{t["initial_stop"]:.2f}',pd.Timestamp(t["sell_date"]).strftime("%Y-%m-%d"),f'{t["sell_price"]:.2f}',f'{t["pnl"]:+.2f}',f'{t["return"]:+.2f}%',t["reason"]]
            for j,v in enumerate(vals): self.trades.setItem(i,j,QTableWidgetItem(str(v)))
        for table in (self.comparison,self.segments,self.diagnostics,self.trades): table.resizeColumnsToContents()
        self.chart.clear(); enhanced=payload["curves"][f"增强策略-{selected}"]; baseline=payload["curves"][f"原策略-{selected}"]; benchmark=payload["benchmark"].reindex(enhanced.index).ffill().bfill()
        x=np.arange(len(enhanced)); self.chart.plot(x,baseline.equity.reindex(enhanced.index).ffill().to_numpy(),pen=pg.mkPen("#94a3b8",width=1.5),name="原策略"); self.chart.plot(x,enhanced.equity.to_numpy(),pen=pg.mkPen("#60a5fa",width=2.2),name="增强策略"); self.chart.plot(x,benchmark.to_numpy(),pen=pg.mkPen("#f8fafc",width=1.3,style=Qt.DashLine),name="沪深300")
        ticks=sorted(set(np.linspace(0,len(enhanced)-1,min(7,len(enhanced)),dtype=int))); axis_ticks=[(int(i),enhanced.index[int(i)].strftime("%Y-%m-%d")) for i in ticks]; self.chart.getAxis("bottom").setTicks([axis_ticks])
        self.exposure.clear(); self.exposure.plot(x,(enhanced.exposure/enhanced.equity.replace(0,np.nan)*100).fillna(0).to_numpy(),pen=pg.mkPen("#60a5fa",width=1.7)); self.exposure.plot(x,enhanced.target_exposure.to_numpy(),pen=pg.mkPen("#f59e0b",width=1.2,style=Qt.DashLine)); self.exposure.getAxis("bottom").setTicks([axis_ticks])
        self.run_btn.setEnabled(True); self.export_btn.setEnabled(True); error=f"；取数失败{len(payload['errors'])}只" if payload["errors"] else ""
        self.status.setText(f"完成：{payload['stock_count']}只股票；最多持仓{selected}只由2020—2023分段表现选定{error}。2024年至今未参与选参。")

    def failed(self,message): self.run_btn.setEnabled(True); self.status.setText("增强回测失败"); QMessageBox.warning(self,"增强回测失败",message)

    def export(self):
        if not self.payload: return
        path,_=QFileDialog.getSaveFileName(self,"导出增强研究",str(APP_DIR/"enhanced_backtest.csv"),"CSV (*.csv)")
        if not path: return
        target=Path(path); pd.DataFrame(self.payload["rows"]).to_csv(target,index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["segments"]).to_csv(target.with_name(target.stem+"_segments.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["trades"]).to_csv(target.with_name(target.stem+"_trades.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["configurations"]).drop(columns=["历史分段"],errors="ignore").to_csv(target.with_name(target.stem+"_selection.csv"),index=False,encoding="utf-8-sig")
        self.status.setText("已导出策略对照、分段验证、增强交易和历史选参结果。")


class AdaptiveWorker(QThread):
    progress=Signal(int,str); success=Signal(object); failure=Signal(str)
    def __init__(self,codes,start_year,validation_year,initial):
        super().__init__(); self.codes=codes; self.start_year=start_year; self.validation_year=validation_year; self.initial=initial

    def run(self):
        try:
            self.progress.emit(2,"读取沪深300与510300真实行情")
            market=fetch_market_history(self.start_year); etf=fetch_history("510300",start_year=self.start_year); flags=build_market_flags(market); frames={}; errors=[]
            if len(etf)<260: raise RuntimeError("510300历史数据不足，无法进行真实ETF验证")
            for i,code in enumerate(self.codes,1):
                self.progress.emit(3+int(i/len(self.codes)*42),f"准备原策略指标 {code}（{i}/{len(self.codes)}）")
                try:
                    raw=fetch_history(code,start_year=self.start_year)
                    if len(raw)<260: raise ValueError("历史不足260日")
                    frames[code]=build_signal_frame(raw)
                except Exception as exc: errors.append(f"{code}:{str(exc)[:50]}")
            if not frames: raise RuntimeError("所有股票均取数失败")
            historical_end=min(self.validation_year-1,2023); caps=(0,10,20,30); selection=[]
            for cap_index,cap in enumerate(caps,1):
                segments=[]
                for label,begin,end in (("训练2018-2019",2018,2019),("验证2020-2021",2020,2021),("验证2022-2023",2022,historical_end)):
                    if end<begin: continue
                    sliced={c:f.loc[:f"{end}-12-31"] for c,f in frames.items()}
                    base,_,_=portfolio_backtest(sliced,flags,self.initial,f"{begin}-01-01","关闭",False,max_positions=8,candidate_days=30)
                    curve,_,stats=adaptive_index_overlay(base,market.loc[:f"{end}-12-31"],self.initial,cap,tradable=etf.loc[:f"{end}-12-31"])
                    segments.append({"区间":label,"指数上限":cap,**stats})
                positive=sum(r["总收益率"]>0 for r in segments); worst=min((r["总收益率"] for r in segments),default=-999)
                average=float(np.mean([r["总收益率"] for r in segments])) if segments else -999
                drawdown=min((r["最大回撤"] for r in segments),default=-999)
                median=float(np.median([r["总收益率"] for r in segments])) if segments else -999
                selection.append({"指数上限":cap,"正收益段":positive,"历史最差":worst,"历史中位":median,"历史平均":average,"历史最差回撤":drawdown,"历史分段":segments})
                self.progress.emit(45+cap_index*8,f"历史选参：指数仓上限{cap}%")
            selection.sort(key=lambda r:(r["正收益段"],r["历史最差"],r["历史中位"],r["历史最差回撤"]),reverse=True)
            selected=selection[0]["指数上限"]; forward=f"{self.validation_year}-01-01"
            base_curve,base_trades,base_stats=portfolio_backtest(frames,flags,self.initial,forward,"关闭",False,max_positions=8,candidate_days=30)
            market_forward=market.loc[forward:]; benchmark=self.initial*market_forward.close/market_forward.close.iloc[0]
            benchmark_return=float((market_forward.close.iloc[-1]/market_forward.close.iloc[0]-1)*100)
            rows=[{"策略":"原策略8只","指数上限":0,"历史选定":"否","基准收益":benchmark_return,"超额收益":base_stats["总收益率"]-benchmark_return,
                   **{k:v for k,v in base_stats.items() if k!="年度收益"},"平均股票仓位":base_stats["资金利用率"],"平均指数仓位":0.0,"平均总仓位":base_stats["资金利用率"],"指数调仓":0}]
            curves={"原策略8只":base_curve}; events={}; adaptive_stats={}
            for idx,cap in enumerate(caps,1):
                curve,event,stats=adaptive_index_overlay(base_curve,market,self.initial,cap,tradable=etf)
                key=f"自适应{cap}%"; curves[key]=curve; events[key]=event; adaptive_stats[cap]=stats
                rows.append({"策略":"自适应组合","指数上限":cap,"历史选定":"是" if cap==selected else "否","基准收益":benchmark_return,
                             "超额收益":stats["总收益率"]-benchmark_return,**{k:v for k,v in stats.items() if k!="年度收益"}})
                self.progress.emit(70+idx*7,f"前向检验：指数仓上限{cap}%")
            chosen=adaptive_stats[selected]; base_return=base_stats["总收益率"]
            passed=bool(chosen["总收益率"]>0 and chosen["总收益率"]>base_return and chosen["盈亏因子"]>1 and chosen["最大回撤"]>=-12)
            forward_best=max(caps,key=lambda cap:(adaptive_stats[cap]["总收益率"],adaptive_stats[cap]["最大回撤"]))
            historical=next(r["历史分段"] for r in selection if r["指数上限"]==selected)
            chosen_row=next(r for r in rows if r["策略"]=="自适应组合" and r["指数上限"]==selected)
            segments=[]
            for r in historical: segments.append(r)
            segments.append({"区间":f"前向{self.validation_year}-{datetime.now().year}","指数上限":selected,"基准收益":benchmark_return,
                             "超额收益":chosen["总收益率"]-benchmark_return,**{k:v for k,v in chosen.items() if k!="年度收益"}})
            self.progress.emit(100,"自适应组合检验完成")
            self.success.emit({"rows":rows,"curves":curves,"benchmark":benchmark,"selected":selected,"segments":segments,
                               "selection":selection,"events":events[f"自适应{selected}%"],"base_trades":base_trades,
                               "passed":passed,"forward_best":forward_best,"errors":errors,"stock_count":len(frames),"chosen":chosen_row})
        except Exception as exc: self.failure.emit(str(exc))


class RegimeWorker(QThread):
    progress=Signal(int,str); success=Signal(object); failure=Signal(str)
    def __init__(self,codes,start_year,validation_year,initial):
        super().__init__(); self.codes=codes; self.start_year=start_year; self.validation_year=validation_year; self.initial=initial

    def run(self):
        try:
            self.progress.emit(2,"读取沪深300并建立股票风险状态")
            market=fetch_market_history(self.start_year); flags=build_market_flags(market); frames={}; errors=[]
            for i,code in enumerate(self.codes,1):
                self.progress.emit(3+int(i/len(self.codes)*42),f"准备原策略指标 {code}（{i}/{len(self.codes)}）")
                try:
                    raw=fetch_history(code,start_year=self.start_year)
                    if len(raw)<260: raise ValueError("历史不足260日")
                    frames[code]=build_signal_frame(raw)
                except Exception as exc: errors.append(f"{code}:{str(exc)[:50]}")
            if not frames: raise RuntimeError("所有股票均取数失败")
            historical_end=min(self.validation_year-1,2023); profiles=("固定","弱市半仓","弱市禁开","只做强势"); selection=[]
            for profile_index,profile in enumerate(profiles,1):
                segments=[]
                for label,begin,end in (("训练2018-2019",2018,2019),("验证2020-2021",2020,2021),("验证2022-2023",2022,historical_end)):
                    if end<begin: continue
                    sliced={c:f.loc[:f"{end}-12-31"] for c,f in frames.items()}
                    curve,trades,stats=portfolio_backtest(sliced,flags,self.initial,f"{begin}-01-01","关闭",False,max_positions=8,candidate_days=30,market=market.loc[:f"{end}-12-31"],regime_profile=profile)
                    segments.append({"区间":label,"风控模式":profile,**stats})
                positive=sum(r["总收益率"]>0 for r in segments); worst=min((r["总收益率"] for r in segments),default=-999); average=float(np.mean([r["总收益率"] for r in segments])) if segments else -999; median=float(np.median([r["总收益率"] for r in segments])) if segments else -999; drawdown=min((r["最大回撤"] for r in segments),default=-999)
                selection.append({"风控模式":profile,"正收益段":positive,"历史最差":worst,"历史中位":median,"历史平均":average,"历史最差回撤":drawdown,"历史分段":segments})
                self.progress.emit(45+profile_index*8,f"历史选参：{profile}风控")
            selection.sort(key=lambda r:(r["正收益段"],r["历史最差"],r["历史中位"],r["历史最差回撤"]),reverse=True); selected=selection[0]["风控模式"]
            forward=f"{self.validation_year}-01-01"; market_forward=market.loc[forward:]; benchmark=self.initial*market_forward.close/market_forward.close.iloc[0]; benchmark_return=float((market_forward.close.iloc[-1]/market_forward.close.iloc[0]-1)*100)
            rows=[]; curves={}; trades_by_profile={}
            for idx,profile in enumerate(profiles,1):
                curve,trades,stats=portfolio_backtest(frames,flags,self.initial,forward,"关闭",False,max_positions=8,candidate_days=30,market=market,regime_profile=profile)
                curves[profile]=curve; trades_by_profile[profile]=trades
                rows.append({"风控模式":profile,"历史选定":"是" if profile==selected else "否","基准收益":benchmark_return,"超额收益":stats["总收益率"]-benchmark_return,**{k:v for k,v in stats.items() if k!="年度收益"}})
                self.progress.emit(70+idx*7,f"前向检验：{profile}风控")
            chosen=next(r for r in rows if r["风控模式"]==selected); baseline=next(r for r in rows if r["风控模式"]=="固定")
            passed=bool(chosen["总收益率"]>0 and chosen["总收益率"]>=baseline["总收益率"] and chosen["盈亏因子"]>1 and chosen["最大回撤"]>=baseline["最大回撤"]-1)
            forward_best=max(profiles,key=lambda profile:(next(r for r in rows if r["风控模式"]==profile)["总收益率"],next(r for r in rows if r["风控模式"]==profile)["最大回撤"]))
            segments=list(next(r["历史分段"] for r in selection if r["风控模式"]==selected)); segments.append({"区间":f"前向{self.validation_year}-{datetime.now().year}",**chosen})
            state_counts=stock_regime_limits(market,curves[selected].index,selected).state.value_counts().to_dict(); states={"弱势天数":state_counts.get(0,0),"普通天数":state_counts.get(1,0),"强势天数":state_counts.get(2,0)}
            self.progress.emit(100,"股票动态风控验证完成")
            self.success.emit({"rows":rows,"curves":curves,"benchmark":benchmark,"selected":selected,"segments":segments,"selection":selection,"trades":trades_by_profile[selected],"states":states,"passed":passed,"forward_best":forward_best,"errors":errors,"stock_count":len(frames),"chosen":chosen})
        except Exception as exc: self.failure.emit(str(exc))


class RiskBudgetWorker(QThread):
    progress=Signal(int,str); success=Signal(object); failure=Signal(str)
    def __init__(self,codes,start_year,validation_year,initial):
        super().__init__(); self.codes=codes; self.start_year=start_year; self.validation_year=validation_year; self.initial=initial

    def run(self):
        try:
            self.progress.emit(2,"读取沪深300并准备入场质量矩阵")
            market=fetch_market_history(self.start_year); flags=build_market_flags(market); frames={}; raw_frames={}; errors=[]
            for i,code in enumerate(self.codes,1):
                self.progress.emit(3+int(i/len(self.codes)*40),f"准备原策略指标 {code}（{i}/{len(self.codes)}）")
                try:
                    raw=fetch_history(code,start_year=self.start_year)
                    if len(raw)<260: raise ValueError("历史不足260日")
                    raw_frames[code]=raw
                    frames[code]=enrich_entry_quality(build_signal_frame(raw),market)
                except Exception as exc: errors.append(f"{code}:{str(exc)[:50]}")
            if not frames:
                detail="；".join(errors[:5]) if errors else "没有返回错误明细"
                raise RuntimeError(f"所有股票均取数失败。前5项：{detail}")
            configs=["原始入场","相对强度","均线斜率","量能确认","质量≥2","质量≥3"]; selection=[]; annual_rows=[]; historical_end=min(self.validation_year-1,2023); years=list(range(2018,historical_end+1))
            for index,label in enumerate(configs,1):
                risk=.8; cap=20; segments=[]
                for year in years:
                    sliced={c:f.loc[:f"{year}-12-31"] for c,f in frames.items()}
                    _,_,stats=portfolio_backtest(sliced,flags,self.initial,f"{year}-01-01","关闭",False,max_positions=8,max_position_pct=cap,total_position_pct=80,risk_pct=risk,candidate_days=30,exit_profile="原规则",entry_profile=label)
                    record={"区间":f"历史{year}","年份":year,"风控模式":label,"单笔风险":risk,"单股上限":cap,**stats}; segments.append(record); annual_rows.append(record)
                positive=sum(r["总收益率"]>0 for r in segments); required=(2*len(segments)+2)//3; worst=min((r["总收益率"] for r in segments),default=-999); average=float(np.mean([r["总收益率"] for r in segments])) if segments else -999; median=float(np.median([r["总收益率"] for r in segments])) if segments else -999; drawdown=min((r["最大回撤"] for r in segments),default=-999); eligible=len(segments)>=3 and positive>=required and drawdown>=-10
                selection.append({"风控模式":label,"单笔风险":risk,"单股上限":cap,"合格":"是" if eligible else "否","正收益段":positive,"历史最差":worst,"历史中位":median,"历史平均":average,"历史最差回撤":drawdown,"历史分段":segments})
                self.progress.emit(43+int(index/len(configs)*30),f"逐年入场质量验证：{label}")
            eligible=[r for r in selection if r["合格"]=="是"]
            has_qualified=bool(eligible)
            ranked=sorted(eligible,key=lambda r:(r["正收益段"],r["历史中位"],r["历史平均"],r["历史最差回撤"]),reverse=True)
            selected=ranked[0]["风控模式"] if ranked else "原始入场"
            selection.sort(key=lambda r:(r["风控模式"]==selected,r["合格"]=="是",r["历史中位"],r["历史平均"]),reverse=True)
            rolling=[]
            for test_year in range(2020,historical_end+1):
                candidates=[]
                for label in configs:
                    history=[r for r in annual_rows if r["风控模式"]==label and r["年份"]<test_year]
                    needed=(2*len(history)+2)//3; positive=sum(r["总收益率"]>0 for r in history); worst_dd=min((r["最大回撤"] for r in history),default=-999)
                    if history and positive>=needed and worst_dd>=-10:
                        candidates.append((label,positive,float(np.median([r["总收益率"] for r in history])),float(np.mean([r["总收益率"] for r in history])),worst_dd))
                rolling_selected=max(candidates,key=lambda x:(x[1],x[2],x[3],x[4]))[0] if candidates else "原始入场"
                test=next(r for r in annual_rows if r["风控模式"]==rolling_selected and r["年份"]==test_year)
                rolling.append({"训练截止":test_year-1,"检验年度":test_year,"选定入场":rolling_selected,"检验收益":test["总收益率"],"最大回撤":test["最大回撤"],"盈亏因子":test["盈亏因子"],"胜率":test["胜率"],"交易":test["交易次数"]})
            forward=f"{self.validation_year}-01-01"; market_forward=market.loc[forward:]; benchmark=self.initial*market_forward.close/market_forward.close.iloc[0]; benchmark_return=float((market_forward.close.iloc[-1]/market_forward.close.iloc[0]-1)*100)
            equal_full=diagnostic_equal_weight_curve(raw_frames,market.index,self.initial)
            equal_forward=equal_full.loc[forward:]
            equal_forward=self.initial*equal_forward/equal_forward.iloc[0]
            equal_return=float((equal_forward.iloc[-1]/self.initial-1)*100)
            rows=[]; curves={}; trades_by_config={}
            for index,label in enumerate(configs,1):
                risk=.8; cap=20; curve,trades,stats=portfolio_backtest(frames,flags,self.initial,forward,"关闭",False,max_positions=8,max_position_pct=cap,total_position_pct=80,risk_pct=risk,candidate_days=30,exit_profile="原规则",entry_profile=label)
                curves[label]=curve; trades_by_config[label]=trades; rows.append({"风控模式":label,"单笔风险":risk,"单股上限":cap,"历史选定":("是" if label==selected else "否") if has_qualified else ("回退" if label==selected else "否"),"基准收益":benchmark_return,"超额收益":stats["总收益率"]-benchmark_return,**{k:v for k,v in stats.items() if k!="年度收益"}})
                self.progress.emit(73+int(index/len(configs)*25),f"研究回放入场质量：{label}")
            chosen=next(r for r in rows if r["风控模式"]==selected); baseline=next(r for r in rows if r["风控模式"]=="原始入场")
            passed=False  # 6.7 is research replay; no untouched holdout remains.
            forward_best=max((r["风控模式"] for r in rows),key=lambda label:(next(x for x in rows if x["风控模式"]==label)["总收益率"],next(x for x in rows if x["风控模式"]==label)["最大回撤"]))
            segments=list(next(r["历史分段"] for r in selection if r["风控模式"]==selected)); segments.append({"区间":f"研究回放{self.validation_year}-{datetime.now().year}",**chosen})
            selected_info=next(r for r in selection if r["风控模式"]==selected)
            selection_label=selected if has_qualified else "无合格，回退原始"
            info={"历史选择结论":selection_label,"历史正收益年":f'{selected_info["正收益段"]}/{len(years)}',"离场规则":"原规则","单笔风险":"0.8%","最多持仓":"8只",
                  "样本偏差":"当前50股，存在幸存者偏差","复权口径":"请求前复权；缓存一致性未证实","费用口径":"固定简化费率，非逐年精确","成交限制":"日线无法证明涨跌停/停牌可成交"}
            csi_year=annual_curve_returns(self.initial*market.close/market.close.iloc[0],self.initial)
            equal_year=annual_curve_returns(equal_full,self.initial)
            benchmark_audit=[]
            for year in years:
                strategy=next(r for r in annual_rows if r["风控模式"]==selected and r["年份"]==year)["总收益率"]
                benchmark_audit.append({"区间":str(year),"策略收益":strategy,"现金收益":0.0,"沪深300":csi_year.get(year,np.nan),"当前样本等权":equal_year.get(year,np.nan),"策略减沪深300":strategy-csi_year.get(year,np.nan),"策略减等权":strategy-equal_year.get(year,np.nan)})
            benchmark_audit.append({"区间":f"研究回放{self.validation_year}-{datetime.now().year}","策略收益":chosen["总收益率"],"现金收益":0.0,"沪深300":benchmark_return,"当前样本等权":equal_return,"策略减沪深300":chosen["总收益率"]-benchmark_return,"策略减等权":chosen["总收益率"]-equal_return})
            data_audit=[audit_price_frame(code,raw,market.index) for code,raw in raw_frames.items()]
            self.progress.emit(100,"研究可信度审计完成")
            self.success.emit({"rows":rows,"curves":curves,"benchmark":benchmark,"equal_benchmark":equal_forward,"selected":selected,"has_qualified":has_qualified,"selection_label":selection_label,"segments":segments,"annual_rows":annual_rows,"rolling":rolling,"benchmark_audit":benchmark_audit,"data_audit":data_audit,"historical_years":len(years),"historical_selected":selected_info,"selection":selection,"trades":trades_by_config[selected],"baseline_trades":trades_by_config["原始入场"],"states":info,"passed":passed,"forward_best":forward_best,"errors":errors,"stock_count":len(frames),"chosen":chosen})
        except Exception as exc: self.failure.emit(str(exc))


class DualEngineWorker(QThread):
    progress=Signal(int,str); success=Signal(object); failure=Signal(str)
    def __init__(self,codes,start_year,validation_year,initial,entry_rule="1 推荐",strict_sample=True):
        super().__init__(); self.codes=list(dict.fromkeys(codes)); self.start_year=start_year; self.validation_year=validation_year; self.initial=initial
        self.entry_rule=entry_rule; self.strict_sample=strict_sample

    def run(self):
        try:
            stage_counts={"输入代码":len(self.codes),"准备样本":0,"缓存载入":0,"信号成功":0,"因子评分":0,"质量审计":0}
            sample_payload={}
            if self.strict_sample:
                if not RESEARCH_SAMPLE_FILE.exists(): raise ValueError("严格300门禁失败：未找到研究样本，请先完成300只数据准备")
                sample_payload=json.loads(RESEARCH_SAMPLE_FILE.read_text(encoding="utf-8"))
                stage_counts.update(strict_sample_gate(self.codes,sample_payload))
            self.progress.emit(2,f"样本门禁通过：输入{len(self.codes)}只；读取沪深300与510300")
            market=fetch_market_history(self.start_year); etf=fetch_history("510300",start_year=self.start_year); flags=build_market_flags(market)
            if len(etf)<260: raise RuntimeError("510300历史数据不足")
            frames={}; raw_frames={}; errors=[]
            for i,code in enumerate(self.codes,1):
                self.progress.emit(3+int(i/len(self.codes)*17),f"冻结缓存载入 {code}（{i}/{len(self.codes)}）｜成功{len(raw_frames)}｜失败{len(errors)}")
                try:
                    raw=load_prepared_history(code,self.start_year) if self.strict_sample else fetch_history(code,start_year=self.start_year)
                    if len(raw)<260: raise ValueError("历史不足260日")
                    raw_frames[code]=raw
                except Exception as exc: errors.append(f"{code}:{str(exc)[:80]}")
            stage_counts["缓存载入"]=len(raw_frames)
            if self.strict_sample and errors:
                missing=sorted(set(self.codes)-set(raw_frames))
                raise RuntimeError(f"严格300门禁失败：缓存载入{len(raw_frames)}/300；缺失{','.join(missing[:12]) or '--'}；前5项错误：{'；'.join(errors[:5])}")
            if not raw_frames: raise RuntimeError("所有股票均取数失败。前5项："+"；".join(errors[:5]))
            common_asof=min([market.index.max(),etf.index.max()]+[raw.index.max() for raw in raw_frames.values()])
            market=market.loc[:common_asof]; etf=etf.loc[:common_asof]; flags=build_market_flags(market)
            signal_errors=[]
            for i,(code,raw) in enumerate(raw_frames.items(),1):
                self.progress.emit(20+int(i/len(raw_frames)*18),f"计算入场规则与指标 {code}（{i}/{len(raw_frames)}）｜规则{self.entry_rule}")
                try: frames[code]=enrich_entry_quality(build_signal_frame(raw.loc[:common_asof]),market)
                except Exception as exc: signal_errors.append(f"{code}:{str(exc)[:80]}")
            errors.extend(signal_errors); stage_counts["信号成功"]=len(frames)
            if self.strict_sample: stage_counts.update(strict_sample_gate(self.codes,sample_payload,frames.keys()))
            if not frames: raise RuntimeError("所有股票均取数失败。前5项："+"；".join(errors[:5]))
            self.progress.emit(38,"计算世坤六因子横截面排名；不重新下载行情")
            frames=enrich_worldquant_factors(frames); stage_counts["因子评分"]=len(frames)
            profiles={"纯股票":0,"强市指数10%":10,"强市指数20%":20,"强市指数30%":30,"强市指数40%":40}
            historical_end=min(self.validation_year-1,2023); years=list(range(2018,historical_end+1)); annual_rows=[]; selection=[]
            def entry_progress(done,total,message):
                self.progress.emit(38+int(done/total*30),f"四种入场对照：{message}（{done}/{total}）")
            entry_evaluation=evaluate_entry_rules(frames,flags,self.initial,years,f"{self.validation_year}-01-01",entry_progress)
            for pos,(label,index_cap) in enumerate(profiles.items(),1):
                segments=[]
                for year in years:
                    base,trades,stock_stats=entry_evaluation["cache"][(self.entry_rule,str(year))]
                    _,_,_,stats=dual_engine_from_base(base,trades,stock_stats,market.loc[:f"{year}-12-31"],etf.loc[:f"{year}-12-31"],self.initial,index_cap)
                    record={"区间":f"历史{year}","年份":year,"风控模式":label,"指数上限":index_cap,"单笔风险":.8,"单股上限":20,**stats}
                    segments.append(record); annual_rows.append(record)
                positive,worst,average,median,drawdown,distance=stability_rank(segments)
                qualified=len(segments)>=3 and positive>=((2*len(segments)+2)//3) and worst>=-1 and average>=2
                selection.append({"风控模式":label,"指数上限":index_cap,"合格":"是" if qualified else "否","正收益段":positive,"历史最差":worst,"历史中位":median,"历史平均":average,"历史最差回撤":drawdown,"目标距离":distance,"历史分段":segments})
                self.progress.emit(68+int(pos/len(profiles)*14),f"指数仓位逐年验证：{label}")
            qualified=[r for r in selection if r["合格"]=="是"]
            pool=qualified or selection
            ranked=sorted(pool,key=lambda r:(r["历史最差"],r["正收益段"],-r["目标距离"],r["历史中位"],r["历史最差回撤"]),reverse=True)
            selected_info=ranked[0]; selected=selected_info["风控模式"]; has_qualified=bool(qualified)
            selection.sort(key=lambda r:(r["风控模式"]==selected,r["合格"]=="是",r["历史最差"],r["正收益段"]),reverse=True)
            rolling=[]
            for test_year in range(2020,historical_end+1):
                candidates=[]
                for label in profiles:
                    history=[r for r in annual_rows if r["风控模式"]==label and r["年份"]<test_year]
                    positive,worst,average,median,drawdown,distance=stability_rank(history)
                    candidates.append((label,worst,positive,-distance,median,drawdown))
                rolling_selected=max(candidates,key=lambda x:x[1:])[0]
                test=next(r for r in annual_rows if r["风控模式"]==rolling_selected and r["年份"]==test_year)
                rolling.append({"训练截止":test_year-1,"检验年度":test_year,"选定入场":rolling_selected,"检验收益":test["总收益率"],"最大回撤":test["最大回撤"],"盈亏因子":test["盈亏因子"],"胜率":test["胜率"],"交易":test["交易次数"]})
            forward=f"{self.validation_year}-01-01"; market_forward=market.loc[forward:]
            benchmark=self.initial*market_forward.close/market_forward.close.iloc[0]; benchmark_return=float((benchmark.iloc[-1]/self.initial-1)*100)
            equal_full=diagnostic_equal_weight_curve(raw_frames,market.index,self.initial); equal_forward=equal_full.loc[forward:]; equal_forward=self.initial*equal_forward/equal_forward.iloc[0]; equal_return=float((equal_forward.iloc[-1]/self.initial-1)*100)
            rows=[]; curves={}; trades_by_config={}; events_by_config={}
            for pos,(label,index_cap) in enumerate(profiles.items(),1):
                base,trades,stock_stats=entry_evaluation["cache"][(self.entry_rule,"forward")]
                curve,trades,events,stats=dual_engine_from_base(base,trades,stock_stats,market,etf,self.initial,index_cap)
                curves[label]=curve; trades_by_config[label]=trades; events_by_config[label]=events
                rows.append({"风控模式":label,"单笔风险":.8,"单股上限":20,"历史选定":("是" if label==selected else "否") if has_qualified else ("候选" if label==selected else "否"),"基准收益":benchmark_return,"超额收益":stats["总收益率"]-benchmark_return,**{k:v for k,v in stats.items() if k!="年度收益"}})
                self.progress.emit(82+int(pos/len(profiles)*13),f"研究回放：{label}")
            chosen=next(r for r in rows if r["风控模式"]==selected); baseline=next(r for r in rows if r["风控模式"]=="纯股票")
            forward_best=max((r["风控模式"] for r in rows),key=lambda label:next(x for x in rows if x["风控模式"]==label)["总收益率"])
            segments=list(selected_info["历史分段"]); segments.append({"区间":f"研究回放{self.validation_year}-{datetime.now().year}",**chosen})
            selection_label=selected if has_qualified else f"未达标，历史候选：{selected}"
            info={"历史选择结论":selection_label,"参考目标":"年化2%—5%，亏损年≥-1%","入场时机":self.entry_rule,"世坤因子":"六个OHLCV因子横截面等权排名；只用于同日候选排序","股票引擎":"R0.8/P20/最多8只","指数引擎":"仅强市使用510300，信号滞后1日","样本门禁":"严格300" if self.strict_sample else "自定义","统一数据截止":common_asof.strftime("%Y-%m-%d"),"选参区间":"2018—2023","回放区间":f"{self.validation_year}年至今（不选参）","模拟交易":"继续暂停"}
            csi_year=annual_curve_returns(self.initial*market.close/market.close.iloc[0],self.initial); equal_year=annual_curve_returns(equal_full,self.initial); benchmark_audit=[]
            for year in years:
                strategy=next(r for r in annual_rows if r["风控模式"]==selected and r["年份"]==year)["总收益率"]
                benchmark_audit.append({"区间":str(year),"策略收益":strategy,"现金收益":0.0,"沪深300":csi_year.get(year,np.nan),"当前样本等权":equal_year.get(year,np.nan),"策略减沪深300":strategy-csi_year.get(year,np.nan),"策略减等权":strategy-equal_year.get(year,np.nan)})
            benchmark_audit.append({"区间":f"研究回放{self.validation_year}-{datetime.now().year}","策略收益":chosen["总收益率"],"现金收益":0.0,"沪深300":benchmark_return,"当前样本等权":equal_return,"策略减沪深300":chosen["总收益率"]-benchmark_return,"策略减等权":chosen["总收益率"]-equal_return})
            data_audit=[audit_price_frame(code,raw,market.index) for code,raw in raw_frames.items()]
            stage_counts["质量审计"]=len(data_audit)
            if self.strict_sample and len(data_audit)!=300: raise RuntimeError(f"严格300门禁失败：质量审计{len(data_audit)}/300")
            code_hash=hashlib.sha256("\n".join(self.codes).encode("utf-8")).hexdigest()
            run_id=f"v75-{datetime.now():%Y%m%dT%H%M%S}-{code_hash[:8]}"
            manifest={"run_id":run_id,"app_version":APP_VERSION,"created_at":datetime.now().isoformat(timespec="seconds"),"entry_rule":self.entry_rule,"entry_rules_compared":list(ENTRY_RULES),"sample_mode":"严格300" if self.strict_sample else "自定义1-500","sample_sha256":code_hash,"data_start_year":self.start_year,"validation_start_year":self.validation_year,"data_as_of":common_asof.strftime("%Y-%m-%d"),"stage_counts":stage_counts,"parameters":{"stock_max_positions":8,"single_stock_cap_pct":20,"single_trade_risk_pct":.8,"stock_total_cap_pct":80,"index_caps_pct":[0,10,20,30,40],"entry_quality_profile":"原始入场","exit_profile":"原规则","worldquant_factor_components":["20日动量","5日反转","价量相关","20日区间位置","20日低波动","5日量能冲击"],"worldquant_use":"仅同日候选排序"},"errors":errors}
            self.progress.emit(100,"牛熊双引擎稳定性验证完成")
            self.success.emit({"rows":rows,"curves":curves,"benchmark":benchmark,"equal_benchmark":equal_forward,"selected":selected,"has_qualified":has_qualified,"selection_label":selection_label,"segments":segments,"annual_rows":annual_rows,"rolling":rolling,"benchmark_audit":benchmark_audit,"data_audit":data_audit,"entry_rule_comparison":entry_evaluation["summary"],"entry_rule_annual":entry_evaluation["annual"],"historical_years":len(years),"historical_selected":selected_info,"selection":selection,"trades":trades_by_config[selected],"baseline_trades":trades_by_config["纯股票"],"states":info,"passed":has_qualified,"forward_best":forward_best,"errors":errors,"stock_count":len(frames),"chosen":chosen,"baseline":baseline,"events":events_by_config[selected],"entry_rule":self.entry_rule,"stage_counts":stage_counts,"manifest":manifest})
        except Exception as exc: self.failure.emit(str(exc))


class AdaptiveResearchPage(QWidget):
    def __init__(self):
        super().__init__(); self.worker=None; self.payload=None; self.run_started=None; self.progress_message="等待运行"; self.loading_snapshot=False
        root=QVBoxLayout(self); top=QHBoxLayout(); title=QLabel("严格样本与世坤因子验证 v7.5"); title.setObjectName("title"); top.addWidget(title); top.addStretch()
        self.start_year=QSpinBox(); self.start_year.setRange(2008,2020); self.start_year.setValue(2018); top.addWidget(QLabel("数据起始")); top.addWidget(self.start_year)
        self.validation_year=QSpinBox(); self.validation_year.setRange(2024,datetime.now().year); self.validation_year.setValue(2024); top.addWidget(QLabel("前向起始")); top.addWidget(self.validation_year)
        self.initial=QSpinBox(); self.initial.setRange(10000,100000000); self.initial.setValue(100000); top.addWidget(QLabel("初始资金")); top.addWidget(self.initial)
        self.entry_rule=QComboBox(); self.entry_rule.addItems(ENTRY_RULES); top.addWidget(QLabel("入场规则")); top.addWidget(self.entry_rule)
        self.sample_requirement=QComboBox(); self.sample_requirement.addItems(["严格300","自定义1—500"]); top.addWidget(QLabel("样本")); top.addWidget(self.sample_requirement)
        self.snapshot_btn=QPushButton("打开上次结果"); self.snapshot_btn.clicked.connect(self.open_last_result); self.snapshot_btn.setEnabled(VALIDATION_SNAPSHOT_FILE.exists()); top.addWidget(self.snapshot_btn)
        self.run_btn=QPushButton("运行7.5验证"); self.run_btn.clicked.connect(self.run); top.addWidget(self.run_btn)
        self.export_btn=QPushButton("导出验证结果"); self.export_btn.clicked.connect(self.export); self.export_btn.setEnabled(False); top.addWidget(self.export_btn); root.addLayout(top)
        self.upload_btn=QPushButton("一键生成核实包"); self.upload_btn.clicked.connect(self.make_upload_bundle); self.upload_btn.setEnabled(False); top.addWidget(self.upload_btn)
        row=QHBoxLayout(); row.addWidget(QLabel("研究股票池")); self.codes=QPlainTextEdit(SAMPLE_50); self.codes.setMaximumHeight(58); row.addWidget(self.codes,1); root.addLayout(row)
        notice=QLabel("取消大盘过滤，恢复原策略8只。历史比较R=单笔风险0.8/1.0/1.2%，P=单股上限20/25%；先限制历史回撤，再选择收益。")
        notice.setStyleSheet("color:#fbbf24;padding:4px"); root.addWidget(notice)
        cards=QGridLayout(); self.metrics={}
        for col,name in enumerate(["历史资格结论","历史正收益年","策略回放收益","沪深300回放","当前样本等权","历史最差年度","策略最大回撤","滚动正收益"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); cards.addWidget(card,col//4,col%4); self.metrics[name]=value
        root.addLayout(cards)
        charts=QSplitter(Qt.Vertical); self.chart=pg.PlotWidget(); self.chart.setBackground("#111c2e"); self.chart.showGrid(x=True,y=True,alpha=.15); self.chart.setLabel("left","账户资产"); self.chart.getAxis("left").enableAutoSIPrefix(False); self.chart.addLegend(); charts.addWidget(self.chart)
        self.exposure=pg.PlotWidget(); self.exposure.setBackground("#111c2e"); self.exposure.showGrid(x=True,y=True,alpha=.15); self.exposure.setLabel("left","仓位 %"); self.exposure.setMaximumHeight(115); self.exposure.addLegend(); charts.addWidget(self.exposure); charts.setSizes([230,95]); root.addWidget(charts)
        self.tabs=QTabWidget(); self.tabs.setMinimumHeight(245)
        self.comparison=QTableWidget(0,15); self.comparison.setHorizontalHeaderLabels(["双引擎方案","历史状态","期末资产","收益率","基准","超额","年化","最大回撤","夏普","交易","胜率","盈亏因子","实际仓位","单笔风险","单股上限"])
        self.segments=QTableWidget(0,11); self.segments.setHorizontalHeaderLabels(["区间","双引擎方案","收益率","年化","最大回撤","夏普","交易","胜率","盈亏因子","实际仓位","盈利/亏损"])
        self.selection=QTableWidget(0,8); self.selection.setHorizontalHeaderLabels(["双引擎方案","达到参考目标","正收益年","历史最差","历史中位","历史平均","最差回撤","采用状态"])
        self.events=QTableWidget(0,2); self.events.setHorizontalHeaderLabels(["选定参数","数值"])
        for table in (self.comparison,self.segments,self.selection,self.events): table.horizontalHeader().setStretchLastSection(True); table.verticalHeader().setVisible(False)
        self.tabs.addTab(self.comparison,"双引擎方案"); self.tabs.addTab(self.segments,"分段验证"); self.tabs.addTab(self.selection,"历史选参审计"); self.tabs.addTab(self.events,"规则说明"); root.addWidget(self.tabs)
        self.entry_comparison=QTableWidget(0,13)
        self.entry_comparison.setHorizontalHeaderLabels(["入场规则","历史合格","正收益年","历史最差","历史平均","历史中位","最差回撤","前向收益","前向回撤","前向盈亏因子","前向交易","前向胜率","前向仓位"])
        self.entry_comparison.horizontalHeader().setStretchLastSection(True); self.tabs.insertTab(1,self.entry_comparison,"四种入场对照")
        self.audit=QTableWidget(0,17)
        self.audit.setHorizontalHeaderLabels(["代码","信号日","买入日","卖出日","入场规则","确认等级","质量分","世坤综合分","RS60%","MA20斜率%","近20日新高","20日量比","最大浮盈%","最大浮亏%","净盈亏元","净收益%","离场原因"])
        self.audit.verticalHeader().setVisible(False); self.audit.horizontalHeader().setStretchLastSection(True)
        self.attribution=QTableWidget(0,5)
        self.attribution.setHorizontalHeaderLabels(["离场原因","交易数","盈利数","累计净盈亏元","平均净收益%"])
        self.attribution.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.audit,"选定交易审计"); self.tabs.addTab(self.attribution,"离场归因")
        self.stock_attr=QTableWidget(0,8); self.stock_attr.setHorizontalHeaderLabels(["代码","交易数","盈利数","累计净盈亏元","平均净收益%","平均持有日","平均最大浮盈%","平均回吐%"])
        self.stock_attr.horizontalHeader().setStretchLastSection(True); self.tabs.addTab(self.stock_attr,"股票盈亏归因")
        self.quality_attr=QTableWidget(0,6); self.quality_attr.setHorizontalHeaderLabels(["原始信号质量分","交易数","盈利数","累计净盈亏元","平均净收益%","盈亏因子"]); self.quality_attr.horizontalHeader().setStretchLastSection(True); self.tabs.addTab(self.quality_attr,"质量分归因")
        self.feature_attr=QTableWidget(0,7); self.feature_attr.setHorizontalHeaderLabels(["原始信号特征","分组","交易数","盈利数","累计净盈亏元","平均净收益%","盈亏因子"]); self.feature_attr.horizontalHeader().setStretchLastSection(True); self.tabs.addTab(self.feature_attr,"特征归因")
        self.annual=QTableWidget(0,9); self.annual.setHorizontalHeaderLabels(["年度","入场过滤","收益率","最大回撤","夏普","交易","胜率","盈亏因子","实际仓位"]); self.annual.horizontalHeader().setStretchLastSection(True); self.tabs.addTab(self.annual,"逐年矩阵")
        self.rolling=QTableWidget(0,8); self.rolling.setHorizontalHeaderLabels(["训练截止","检验年度","当年选定入场","检验收益","最大回撤","盈亏因子","胜率","交易"]); self.rolling.horizontalHeader().setStretchLastSection(True); self.tabs.addTab(self.rolling,"滚动审计")
        self.benchmarks=QTableWidget(0,7); self.benchmarks.setHorizontalHeaderLabels(["区间","策略","现金","沪深300","当前样本等权","策略-沪深300","策略-等权"]); self.benchmarks.horizontalHeader().setStretchLastSection(True); self.tabs.addTab(self.benchmarks,"基准审计")
        self.data_quality=QTableWidget(0,12); self.data_quality.setHorizontalHeaderLabels(["代码","首日","末日","行数","重复日期","缺失值","非正价格/量","OHLC矛盾","异常跳变>30%","相对指数缺日","疑似一字板","基础结论"]); self.data_quality.horizontalHeader().setStretchLastSection(True); self.tabs.addTab(self.data_quality,"数据质量")
        notice.setText("7.5复用本地300只原始行情，一次并列比较规则1/2/3和世坤因子；运行后自动保存结果快照。")
        self.start_year.setMaximum(2018)
        self.run_progress=QProgressBar(); self.run_progress.setRange(0,100); self.run_progress.setValue(0); self.run_progress.setFormat("等待运行"); root.addWidget(self.run_progress)
        self.status=QLabel("等待运行。参考目标不强制制造结果；未达到时仅显示历史候选并继续暂停模拟交易。")
        self.status.setStyleSheet("color:#93c5fd;padding:4px"); root.addWidget(self.status)
        self.run_timer=QTimer(self); self.run_timer.setInterval(1000); self.run_timer.timeout.connect(self.tick_run)

    def parsed_codes(self):
        text=self.codes.toPlainText()
        for ch in ",，;；\n\t": text=text.replace(ch," ")
        return list(dict.fromkeys(x for x in text.split() if len(x)==6 and x.isdigit()))

    def snapshot_key(self):
        config={"start_year":self.start_year.value(),"validation_year":self.validation_year.value(),"initial":self.initial.value(),
                "entry_rule":self.entry_rule.currentText(),"strict":self.sample_requirement.currentText()=="严格300"}
        return snapshot_cache_key(self.parsed_codes(),config,CACHE_DIR,VALIDATION_ENGINE_VERSION)

    def open_last_result(self):
        try:
            payload=load_validation_snapshot(VALIDATION_SNAPSHOT_FILE,self.snapshot_key())
            self.loading_snapshot=True; self.loaded(payload)
            saved=payload.get("manifest",{}).get("created_at","时间未知")
            self.status.setText(f"已直接打开上次验证结果（{saved}）；未重新读取300只或执行回测。")
        except Exception as exc:
            QMessageBox.warning(self,"无法使用上次结果",str(exc)+"\n\n请点击“运行7.5验证”，完成后会自动保存新快照。")
        finally:
            self.loading_snapshot=False

    def run(self):
        codes=self.parsed_codes()
        if not codes: QMessageBox.warning(self,"没有代码","请输入股票代码"); return
        if len(codes)>500: QMessageBox.warning(self,"数量过多","单次验证最多500只股票；全市场请先准备数据，再分批研究。"); return
        strict=self.sample_requirement.currentText()=="严格300"
        if strict:
            try:
                if not RESEARCH_SAMPLE_FILE.exists(): raise ValueError("未找到已完成的300只研究样本")
                strict_sample_gate(codes,json.loads(RESEARCH_SAMPLE_FILE.read_text(encoding="utf-8")))
            except Exception as exc: QMessageBox.warning(self,"严格300门禁",str(exc)+"\n\n请先在“研究样本与数据准备”完成300只，再保持股票池不变运行。"); return
        self.run_btn.setEnabled(False); self.export_btn.setEnabled(False); self.upload_btn.setEnabled(False); self.run_progress.setValue(0); self.run_progress.setFormat("启动中 0%")
        self.progress_message="正在进行样本、逐年、滚动、基准和数据质量审计"; self.run_started=time.perf_counter(); self.run_timer.start(); self.tick_run()
        self.worker=DualEngineWorker(codes,self.start_year.value(),self.validation_year.value(),self.initial.value(),self.entry_rule.currentText(),strict); self.worker.progress.connect(self.update_run_progress); self.worker.success.connect(self.loaded); self.worker.failure.connect(self.failed); self.worker.start()

    def update_run_progress(self,percent,message):
        self.progress_message=message; self.run_progress.setValue(percent); self.run_progress.setFormat(f"{percent}%  {message}"); self.tick_run()

    def tick_run(self):
        if self.run_started is None: return
        elapsed=readable_eta(time.perf_counter()-self.run_started); self.status.setText(f"{self.progress_message}｜实时进程 {self.run_progress.value()}%｜已运行 {elapsed}")

    def loaded_legacy(self,payload):
        self.payload=payload; chosen=payload["chosen"]; base=next(r for r in payload["rows"] if r["策略"]=="原策略8只"); pf=lambda x:"∞" if np.isinf(x) else f"{x:.2f}"
        best=next(r for r in payload["rows"] if r["策略"]=="自适应组合" and r["指数上限"]==payload["forward_best"])
        values={"历史选定ETF上限":f'{payload["selected"]}%',"前向验收":"通过" if payload["passed"] else "未通过","自适应期末资产":f'¥{chosen["期末资产"]:,.2f}',"自适应总收益":f'{chosen["总收益率"]:+.2f}%',"前向最佳仅观察":f'{payload["forward_best"]}% / {best["总收益率"]:+.2f}%',"沪深300基准":f'{chosen["基准收益"]:+.2f}%',"自适应最大回撤":f'{chosen["最大回撤"]:.2f}%',"组合盈亏因子":pf(chosen["盈亏因子"])}
        for k,v in values.items(): self.metrics[k].setText(v)
        self.metrics["前向验收"].setStyleSheet("color:#ef4444" if payload["passed"] else "color:#22c55e")
        self.comparison.setRowCount(len(payload["rows"]))
        for i,r in enumerate(payload["rows"]):
            vals=[r["策略"],f'{r["指数上限"]}%',r["历史选定"],f'{r["期末资产"]:.2f}',f'{r["总收益率"]:+.2f}%',f'{r["基准收益"]:+.2f}%',f'{r["超额收益"]:+.2f}%',f'{r["年化收益"]:+.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',pf(r["盈亏因子"]),f'{r["平均股票仓位"]:.1f}%',f'{r["平均指数仓位"]:.1f}%',f'{r["平均总仓位"]:.1f}%']
            for j,v in enumerate(vals): self.comparison.setItem(i,j,QTableWidgetItem(str(v)))
        self.segments.setRowCount(len(payload["segments"]))
        for i,r in enumerate(payload["segments"]):
            vals=[r["区间"],f'{r["指数上限"]}%',f'{r["总收益率"]:+.2f}%',f'{r["年化收益"]:+.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',pf(r["盈亏因子"]),f'{r["平均股票仓位"]:.1f}%',f'{r["平均指数仓位"]:.1f}%',f'{r["平均总仓位"]:.1f}%']
            for j,v in enumerate(vals): self.segments.setItem(i,j,QTableWidgetItem(str(v)))
        self.selection.setRowCount(len(payload["selection"]))
        for i,r in enumerate(payload["selection"]):
            vals=[f'{r["指数上限"]}%',f'{r["正收益段"]}/3',f'{r["历史最差"]:+.2f}%',f'{r["历史中位"]:+.2f}%',f'{r["历史平均"]:+.2f}%',f'{r["历史最差回撤"]:.2f}%',"是" if r["指数上限"]==payload["selected"] else "否"]
            for j,v in enumerate(vals): self.selection.setItem(i,j,QTableWidgetItem(str(v)))
        self.events.setRowCount(len(payload["events"]))
        for i,r in enumerate(payload["events"]):
            vals=[pd.Timestamp(r["日期"]).strftime("%Y-%m-%d"),r["动作"],f'{r["原仓位"]:.1f}%',f'{r["目标仓位"]:.1f}%',f'{r["调仓金额"]:.2f}',f'{r["费用"]:.2f}']
            for j,v in enumerate(vals): self.events.setItem(i,j,QTableWidgetItem(str(v)))
        for table in (self.comparison,self.segments,self.selection,self.events): table.resizeColumnsToContents()
        selected=payload["selected"]; curve=payload["curves"][f"自适应{selected}%"]; base_curve=payload["curves"]["原策略8只"]; benchmark=payload["benchmark"].reindex(curve.index).ffill().bfill(); x=np.arange(len(curve))
        base_values=base_curve.equity.reindex(curve.index).ffill().to_numpy(dtype=float); adaptive_values=curve.equity.to_numpy(dtype=float); benchmark_values=benchmark.to_numpy(dtype=float)
        self.chart.clear(); self.chart.plot(x,base_values,pen=pg.mkPen("#94a3b8",width=1.5),name="原策略8只"); self.chart.plot(x,adaptive_values,pen=pg.mkPen("#60a5fa",width=2.2),name="自适应组合"); self.chart.plot(x,benchmark_values,pen=pg.mkPen("#f8fafc",width=1.2,style=Qt.DashLine),name="沪深300")
        finite=np.concatenate([base_values[np.isfinite(base_values)],adaptive_values[np.isfinite(adaptive_values)],benchmark_values[np.isfinite(benchmark_values)]]); low=float(finite.min()); high=float(finite.max()); padding=max((high-low)*.06,self.initial.value()*.01); self.chart.setYRange(low-padding,high+padding,padding=0)
        ticks=sorted(set(np.linspace(0,len(curve)-1,min(7,len(curve)),dtype=int))); axis_ticks=[(int(i),curve.index[int(i)].strftime("%Y-%m-%d")) for i in ticks]; self.chart.getAxis("bottom").setTicks([axis_ticks])
        self.exposure.clear(); self.exposure.plot(x,curve.stock_exposure.to_numpy(),pen=pg.mkPen("#60a5fa",width=1.5),name="股票"); self.exposure.plot(x,curve.index_exposure.to_numpy(),pen=pg.mkPen("#f59e0b",width=1.5),name="指数"); self.exposure.plot(x,curve.total_exposure.to_numpy(),pen=pg.mkPen("#22c55e",width=1.3),name="合计"); self.exposure.getAxis("bottom").setTicks([axis_ticks])
        self.run_btn.setEnabled(True); self.export_btn.setEnabled(True); self.upload_btn.setEnabled(True); err=f"；取数失败{len(payload['errors'])}只" if payload["errors"] else ""
        result="通过正向验收，可继续扩大股票池复核" if payload["passed"] else "未通过，禁止进入模拟交易并继续调整"
        self.status.setText(f"完成：{payload['stock_count']}只股票；{result}{err}。ETF使用510300前复权历史行情；前向最佳只展示、不参与选参。")

    def loaded(self,payload):
        self.run_timer.stop(); self.run_started=None; self.run_progress.setValue(100); self.run_progress.setFormat("验证完成 100%")
        trades=payload["trades"]; self.audit.setRowCount(len(trades))
        for i,t in enumerate(trades):
            vals=[t["code"],str(t.get("signal_date",""))[:10],str(t["buy_date"])[:10],str(t["sell_date"])[:10],t.get("entry_rule",payload.get("entry_rule","--")),t.get("entry_confirmation","--"),t.get("entry_quality_score",0),f'{t.get("worldquant_score",np.nan):.2f}',f'{t.get("entry_rs60",np.nan):.2f}',f'{t.get("entry_ma20_slope10",np.nan):.2f}',"是" if t.get("entry_near_high20",False) else "否",f'{t.get("entry_volume_ratio20",np.nan):.2f}',f'{t["mfe"]:.2f}',f'{t["mae"]:.2f}',f'{t["pnl"]:.2f}',f'{t["net_return_pct"]:.2f}',t["reason"]]
            for j,v in enumerate(vals): self.audit.setItem(i,j,QTableWidgetItem(str(v)))
        reasons=sorted(set(t["reason"] for t in trades)); self.attribution.setRowCount(len(reasons))
        for i,reason in enumerate(reasons):
            group=[t for t in trades if t["reason"]==reason]
            vals=[reason,len(group),sum(t["pnl"]>0 for t in group),f'{sum(t["pnl"] for t in group):.2f}',f'{np.mean([t["net_return_pct"] for t in group]):.2f}']
            for j,v in enumerate(vals): self.attribution.setItem(i,j,QTableWidgetItem(str(v)))
        codes=sorted(set(t["code"] for t in trades)); self.stock_attr.setRowCount(len(codes))
        for i,code in enumerate(codes):
            group=[t for t in trades if t["code"]==code]
            vals=[code,len(group),sum(t["pnl"]>0 for t in group),f'{sum(t["pnl"] for t in group):.2f}',f'{np.mean([t["net_return_pct"] for t in group]):.2f}',f'{np.mean([t["holding_days"] for t in group]):.1f}',f'{np.mean([t["mfe"] for t in group]):.2f}',f'{np.mean([t["profit_giveback_pct"] for t in group]):.2f}']
            for j,v in enumerate(vals): self.stock_attr.setItem(i,j,QTableWidgetItem(str(v)))
        def group_stats(group):
            wins=sum(t["pnl"]>0 for t in group); gain=sum(t["pnl"] for t in group if t["pnl"]>0); loss=abs(sum(t["pnl"] for t in group if t["pnl"]<0)); factor=gain/loss if loss else (float("inf") if gain else 0)
            return wins,sum(t["pnl"] for t in group),float(np.mean([t["net_return_pct"] for t in group])) if group else 0,factor
        raw=payload["baseline_trades"]; scores=sorted(set(int(t.get("entry_quality_score",0)) for t in raw)); self.quality_attr.setRowCount(len(scores))
        for i,score in enumerate(scores):
            group=[t for t in raw if int(t.get("entry_quality_score",0))==score]; wins,pnl,mean_ret,factor=group_stats(group); vals=[score,len(group),wins,f'{pnl:.2f}',f'{mean_ret:.2f}',"∞" if np.isinf(factor) else f'{factor:.2f}']
            for j,v in enumerate(vals): self.quality_attr.setItem(i,j,QTableWidgetItem(str(v)))
        feature_defs=[("RS60","entry_rs60",lambda v:np.isfinite(v) and v>0),("MA20斜率","entry_ma20_slope10",lambda v:np.isfinite(v) and v>0),("近20日新高","entry_near_high20",bool),("20日量比≥1.2","entry_volume_ratio20",lambda v:np.isfinite(v) and v>=1.2)]
        feature_rows=[]
        for name,key,predicate in feature_defs:
            for label,passed in (("通过",True),("未通过",False)):
                group=[t for t in raw if bool(predicate(t.get(key,np.nan)))==passed]; wins,pnl,mean_ret,factor=group_stats(group); feature_rows.append([name,label,len(group),wins,f'{pnl:.2f}',f'{mean_ret:.2f}',"∞" if np.isinf(factor) else f'{factor:.2f}'])
        self.feature_attr.setRowCount(len(feature_rows))
        for i,vals in enumerate(feature_rows):
            for j,v in enumerate(vals): self.feature_attr.setItem(i,j,QTableWidgetItem(str(v)))
        self.annual.setRowCount(len(payload["annual_rows"]))
        for i,r in enumerate(payload["annual_rows"]):
            vals=[r["年份"],r["风控模式"],f'{r["总收益率"]:+.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',r["交易次数"],f'{r["胜率"]:.1f}%',"∞" if np.isinf(r["盈亏因子"]) else f'{r["盈亏因子"]:.2f}',f'{r["资金利用率"]:.1f}%']
            for j,v in enumerate(vals): self.annual.setItem(i,j,QTableWidgetItem(str(v)))
        self.rolling.setRowCount(len(payload["rolling"]))
        for i,r in enumerate(payload["rolling"]):
            vals=[r["训练截止"],r["检验年度"],r["选定入场"],f'{r["检验收益"]:+.2f}%',f'{r["最大回撤"]:.2f}%',"∞" if np.isinf(r["盈亏因子"]) else f'{r["盈亏因子"]:.2f}',f'{r["胜率"]:.1f}%',r["交易"]]
            for j,v in enumerate(vals): self.rolling.setItem(i,j,QTableWidgetItem(str(v)))
        self.benchmarks.setRowCount(len(payload.get("benchmark_audit",[])))
        for i,r in enumerate(payload.get("benchmark_audit",[])):
            vals=[r["区间"],f'{r["策略收益"]:+.2f}%',f'{r["现金收益"]:+.2f}%',f'{r["沪深300"]:+.2f}%',f'{r["当前样本等权"]:+.2f}%',f'{r["策略减沪深300"]:+.2f}%',f'{r["策略减等权"]:+.2f}%']
            for j,v in enumerate(vals): self.benchmarks.setItem(i,j,QTableWidgetItem(str(v)))
        self.data_quality.setRowCount(len(payload.get("data_audit",[])))
        for i,r in enumerate(payload.get("data_audit",[])):
            vals=[r[k] for k in ["代码","首日","末日","行数","重复日期","缺失值","非正价格/量","OHLC矛盾","异常跳变>30%","相对指数缺日","疑似一字涨跌停","基础结论"]]
            for j,v in enumerate(vals): self.data_quality.setItem(i,j,QTableWidgetItem(str(v)))
        self.entry_comparison.setRowCount(len(payload.get("entry_rule_comparison",[])))
        for i,r in enumerate(payload.get("entry_rule_comparison",[])):
            factor=lambda value:"∞" if np.isinf(value) else f"{value:.2f}"
            vals=[r["入场规则"],r["历史合格"],f'{r["历史正收益年"]}/{r["历史年数"]}',f'{r["历史最差"]:+.2f}%',f'{r["历史平均"]:+.2f}%',f'{r["历史中位"]:+.2f}%',f'{r["历史最差回撤"]:.2f}%',f'{r["前向收益"]:+.2f}%',f'{r["前向最大回撤"]:.2f}%',factor(r["前向盈亏因子"]),r["前向交易"],f'{r["前向胜率"]:.1f}%',f'{r["前向资金利用率"]:.1f}%']
            for j,v in enumerate(vals): self.entry_comparison.setItem(i,j,QTableWidgetItem(str(v)))
        self.audit.resizeColumnsToContents(); self.attribution.resizeColumnsToContents(); self.stock_attr.resizeColumnsToContents(); self.quality_attr.resizeColumnsToContents(); self.feature_attr.resizeColumnsToContents(); self.annual.resizeColumnsToContents(); self.rolling.resizeColumnsToContents(); self.benchmarks.resizeColumnsToContents(); self.data_quality.resizeColumnsToContents(); self.entry_comparison.resizeColumnsToContents()
        self.payload=payload; chosen=payload["chosen"]; baseline=next(r for r in payload["rows"] if r["风控模式"]=="纯股票"); pf=lambda x:"∞" if np.isinf(x) else f"{x:.2f}"
        best=next(r for r in payload["rows"] if r["风控模式"]==payload["forward_best"])
        history=payload["historical_selected"]
        rolling_positive=sum(r["检验收益"]>0 for r in payload["rolling"])
        values={"历史资格结论":payload.get("selection_label",payload["selected"]),"历史正收益年":f'{history["正收益段"]}/{payload["historical_years"]}',"策略回放收益":f'{chosen["总收益率"]:+.2f}%',"沪深300回放":f'{chosen["基准收益"]:+.2f}%',"当前样本等权":f'{payload["benchmark_audit"][-1]["当前样本等权"]:+.2f}%',"历史最差年度":f'{history["历史最差"]:+.2f}%',"策略最大回撤":f'{chosen["最大回撤"]:.2f}%',"滚动正收益":f'{rolling_positive}/{len(payload["rolling"])}'}
        for k,v in values.items(): self.metrics[k].setText(v)
        self.comparison.setRowCount(len(payload["rows"]))
        for i,r in enumerate(payload["rows"]):
            vals=[r["风控模式"],r["历史选定"],f'{r["期末资产"]:.2f}',f'{r["总收益率"]:+.2f}%',f'{r["基准收益"]:+.2f}%',f'{r["超额收益"]:+.2f}%',f'{r["年化收益"]:+.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',r["交易次数"],f'{r["胜率"]:.1f}%',pf(r["盈亏因子"]),f'{r["资金利用率"]:.1f}%',f'{r["单笔风险"]:.1f}%',f'{r["单股上限"]}%']
            for j,v in enumerate(vals): self.comparison.setItem(i,j,QTableWidgetItem(str(v)))
        self.segments.setRowCount(len(payload["segments"]))
        for i,r in enumerate(payload["segments"]):
            vals=[r["区间"],r["风控模式"],f'{r["总收益率"]:+.2f}%',f'{r["年化收益"]:+.2f}%',f'{r["最大回撤"]:.2f}%',f'{r["夏普"]:.2f}',r["交易次数"],f'{r["胜率"]:.1f}%',pf(r["盈亏因子"]),f'{r["资金利用率"]:.1f}%',f'{r["盈利交易"]}/{r["亏损交易"]}']
            for j,v in enumerate(vals): self.segments.setItem(i,j,QTableWidgetItem(str(v)))
        self.selection.setRowCount(len(payload["selection"]))
        for i,r in enumerate(payload["selection"]):
            vals=[r["风控模式"],r["合格"],f'{r["正收益段"]}/{payload["historical_years"]}',f'{r["历史最差"]:+.2f}%',f'{r["历史中位"]:+.2f}%',f'{r["历史平均"]:+.2f}%',f'{r["历史最差回撤"]:.2f}%',("历史候选" if not payload.get("has_qualified",True) and r["风控模式"]==payload["selected"] else ("采用" if r["风控模式"]==payload["selected"] else "否"))]
            for j,v in enumerate(vals): self.selection.setItem(i,j,QTableWidgetItem(str(v)))
        states=list(payload["states"].items()); self.events.setRowCount(len(states))
        for i,(name,count) in enumerate(states): self.events.setItem(i,0,QTableWidgetItem(name)); self.events.setItem(i,1,QTableWidgetItem(str(count)))
        for table in (self.comparison,self.segments,self.selection,self.events): table.resizeColumnsToContents()
        selected=payload["selected"]; curve=payload["curves"][selected]; base_curve=payload["curves"]["纯股票"]; benchmark=payload["benchmark"].reindex(curve.index).ffill().bfill(); x=np.arange(len(curve))
        base_values=base_curve.equity.reindex(curve.index).ffill().to_numpy(dtype=float); dynamic_values=curve.equity.to_numpy(dtype=float); benchmark_values=benchmark.to_numpy(dtype=float)
        equal=payload.get("equal_benchmark",pd.Series(index=curve.index,dtype=float)).reindex(curve.index).ffill().bfill(); equal_values=equal.to_numpy(dtype=float)
        self.chart.clear(); self.chart.plot(x,base_values,pen=pg.mkPen("#94a3b8",width=1.5),name="纯股票"); self.chart.plot(x,dynamic_values,pen=pg.mkPen("#60a5fa",width=2.2),name=f"历史方案-{selected}"); self.chart.plot(x,benchmark_values,pen=pg.mkPen("#f8fafc",width=1.2,style=Qt.DashLine),name="沪深300"); self.chart.plot(x,equal_values,pen=pg.mkPen("#f59e0b",width=1.1,style=Qt.DotLine),name="当前样本等权")
        finite=np.concatenate([base_values[np.isfinite(base_values)],dynamic_values[np.isfinite(dynamic_values)],benchmark_values[np.isfinite(benchmark_values)]]); low=float(finite.min()); high=float(finite.max()); padding=max((high-low)*.06,self.initial.value()*.01); self.chart.setYRange(low-padding,high+padding,padding=0)
        ticks=sorted(set(np.linspace(0,len(curve)-1,min(7,len(curve)),dtype=int))); axis_ticks=[(int(i),curve.index[int(i)].strftime("%Y-%m-%d")) for i in ticks]; self.chart.getAxis("bottom").setTicks([axis_ticks])
        self.exposure.clear(); actual=(curve.exposure/curve.equity.replace(0,np.nan)*100).fillna(0); base_actual=(base_curve.exposure/base_curve.equity.replace(0,np.nan)*100).fillna(0); self.exposure.plot(x,base_actual.reindex(curve.index).fillna(0).to_numpy(),pen=pg.mkPen("#94a3b8",width=1.2),name="股票基线仓位"); self.exposure.plot(x,actual.to_numpy(),pen=pg.mkPen("#60a5fa",width=1.7),name="双引擎总仓位"); self.exposure.getAxis("bottom").setTicks([axis_ticks])
        self.chart.setXRange(0,max(1,len(curve)-1),padding=.01)
        self.exposure.getAxis("left").enableAutoSIPrefix(False)
        self.exposure.setXRange(0,max(1,len(curve)-1),padding=.01)
        self.exposure.setYRange(0,max(10,float(actual.max())*1.1),padding=0)
        self.run_btn.setEnabled(True); self.export_btn.setEnabled(True); self.upload_btn.setEnabled(True); err=f"；取数失败{len(payload['errors'])}只" if payload["errors"] else ""
        rolling_positive=sum(r["检验收益"]>0 for r in payload["rolling"])
        conclusion="达到参考目标" if payload.get("has_qualified") else f"未达到参考目标；历史候选={selected}（不得视为通过）"
        stages=" / ".join(f"{k}{v}" for k,v in payload.get("stage_counts",{}).items())
        self.status.setText(f"完成：{payload['stock_count']}只股票；规则{payload.get('entry_rule','--')}；{stages}；{conclusion}；滚动正收益{rolling_positive}/{len(payload['rolling'])}{err}。模拟交易继续暂停。")
        if not self.loading_snapshot:
            try:
                save_validation_snapshot(VALIDATION_SNAPSHOT_FILE,payload,self.snapshot_key()); self.snapshot_btn.setEnabled(True)
                self.status.setText(self.status.text()+" 验证快照已自动保存，下次可直接打开。")
            except Exception as exc:
                self.status.setText(self.status.text()+f" 快照保存失败：{exc}")

    def failed(self,message):
        self.run_timer.stop(); self.run_started=None; self.run_btn.setEnabled(True); self.run_progress.setFormat("验证失败"); self.status.setText("7.5验证失败："+message); QMessageBox.warning(self,"7.5验证失败",message)

    def export_legacy(self):
        if not self.payload: return
        path,_=QFileDialog.getSaveFileName(self,"导出6.0验证",str(APP_DIR/"adaptive_validation_v6.csv"),"CSV (*.csv)")
        if not path: return
        target=Path(path); pd.DataFrame(self.payload["rows"]).to_csv(target,index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["segments"]).to_csv(target.with_name(target.stem+"_segments.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["events"]).to_csv(target.with_name(target.stem+"_index_events.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["selection"]).drop(columns=["历史分段"],errors="ignore").to_csv(target.with_name(target.stem+"_selection.csv"),index=False,encoding="utf-8-sig")
        self.status.setText("已导出前向对照、分段验证、历史选参与指数调仓审计。")

    def export(self):
        if not self.payload: return
        path,_=QFileDialog.getSaveFileName(self,"导出7.5验证",str(APP_DIR/"dual_engine_validation_v7_5.csv"),"CSV (*.csv)")
        if not path: return
        self._write_validation_files(Path(path))
        self.status.setText("已导出运行清单、每日资金账、交易、指数调仓、逐年/滚动、基准、数据质量和错误明细。")

    def _write_validation_files(self,target):
        target=Path(target); pd.DataFrame(self.payload["rows"]).to_csv(target,index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["segments"]).to_csv(target.with_name(target.stem+"_segments.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["trades"]).to_csv(target.with_name(target.stem+"_trades.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["baseline_trades"]).to_csv(target.with_name(target.stem+"_original_entries.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["selection"]).drop(columns=["历史分段"],errors="ignore").to_csv(target.with_name(target.stem+"_selection.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["annual_rows"]).to_csv(target.with_name(target.stem+"_annual_matrix.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload["rolling"]).to_csv(target.with_name(target.stem+"_rolling_audit.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload.get("benchmark_audit",[])).to_csv(target.with_name(target.stem+"_benchmark_audit.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload.get("data_audit",[])).to_csv(target.with_name(target.stem+"_data_quality.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload.get("entry_rule_comparison",[])).to_csv(target.with_name(target.stem+"_entry_rule_comparison.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload.get("entry_rule_annual",[])).to_csv(target.with_name(target.stem+"_entry_rule_annual.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload.get("curves",{}).get(self.payload.get("selected"),pd.DataFrame())).rename_axis("date").reset_index().to_csv(target.with_name(target.stem+"_daily_ledger.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame(self.payload.get("events",[])).to_csv(target.with_name(target.stem+"_index_events.csv"),index=False,encoding="utf-8-sig")
        pd.DataFrame({"错误":self.payload.get("errors",[])}).to_csv(target.with_name(target.stem+"_errors.csv"),index=False,encoding="utf-8-sig")
        target.with_name(target.stem+"_run_manifest.json").write_text(json.dumps(self.payload.get("manifest",{}),ensure_ascii=False,indent=2),encoding="utf-8")
        trades=pd.DataFrame(self.payload["trades"])
        if not trades.empty:
            stock=trades.groupby("code").agg(交易数=("pnl","size"),盈利数=("pnl",lambda s:int((s>0).sum())),累计净盈亏元=("pnl","sum"),平均净收益百分比=("net_return_pct","mean"),平均持有日=("holding_days","mean"),平均最大浮盈百分比=("mfe","mean"),平均回吐百分比=("profit_giveback_pct","mean")).reset_index()
            stock.to_csv(target.with_name(target.stem+"_stock_attribution.csv"),index=False,encoding="utf-8-sig")
            exits=trades.groupby("reason").agg(交易数=("pnl","size"),盈利数=("pnl",lambda s:int((s>0).sum())),累计净盈亏元=("pnl","sum"),平均净收益百分比=("net_return_pct","mean")).reset_index()
            exits.to_csv(target.with_name(target.stem+"_exit_attribution.csv"),index=False,encoding="utf-8-sig")
        return sorted(target.parent.glob(target.stem+"*"))

    def make_upload_bundle(self):
        if not self.payload: return
        try:
            base=APP_DIR/"dual_engine_validation_v7_5.csv"
            files=self._write_validation_files(base)
            if RESEARCH_SAMPLE_FILE.exists(): files.append(RESEARCH_SAMPLE_FILE)
            bundle=APP_DIR/f"AStockQuant核实上传包_{datetime.now():%Y%m%d_%H%M%S}.zip"
            included=create_safe_upload_bundle(bundle,files)
            self.status.setText(f"核实包已生成：{bundle.name}，共{len(included)}个安全文件。请拖入聊天框。")
            try:
                if sys.platform.startswith("win"):
                    subprocess.Popen(["explorer.exe","/select,",str(bundle)])
            except Exception:
                pass
            QMessageBox.information(self,"核实包已生成",f"已生成：\n{bundle}\n\n文件夹已打开，请把这个ZIP拖入聊天框发送。")
        except Exception as exc:
            QMessageBox.warning(self,"生成核实包失败",str(exc))


class UniverseWorker(QThread):
    success = Signal(object, str)
    failure = Signal(str)
    def __init__(self, force=False): super().__init__(); self.force=force
    def run(self):
        try:
            stocks, source=fetch_market_universe(self.force); self.success.emit(stocks,source)
        except Exception as exc: self.failure.emit(str(exc))


class PaperScanWorker(QThread):
    progress = Signal(int, str)
    success = Signal(object)
    failure = Signal(str)

    def __init__(self, entries, market_mode, full_market=False, resume_payload=None):
        super().__init__(); self.entries=entries; self.codes=[e["code"] for e in entries]
        self.market_mode=market_mode; self.full_market=full_market; self.resume_payload=resume_payload or {}

    def save_checkpoint(self, next_index, rows, errors, eligible, short_history):
        if not self.full_market: return
        payload={"version":1,"signature":hashlib.sha1((self.market_mode+",".join(self.codes)).encode()).hexdigest(),
                 "market_mode":self.market_mode,"entries":self.entries,"next_index":next_index,
                 "rows":rows,"errors":errors[-200:],"error_count":len(errors),
                 "eligible":eligible,"short_history":short_history,"updated":datetime.now().isoformat(timespec="seconds")}
        temporary=SCAN_CHECKPOINT.with_suffix(".tmp"); temporary.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8"); temporary.replace(SCAN_CHECKPOINT)

    def run(self):
        try:
            market = None
            if self.market_mode != "关闭":
                try: market = fetch_market_history(2018)
                except Exception: market = None
            rows=list(self.resume_payload.get("rows",[])); errors=list(self.resume_payload.get("errors",[]))
            eligible=int(self.resume_payload.get("eligible",0)); short_history=int(self.resume_payload.get("short_history",0))
            start_index=int(self.resume_payload.get("next_index",0)); processed=start_index; stopped=False; quote_count=0
            for batch_start in range(start_index,len(self.entries),40):
                if self.isInterruptionRequested(): stopped=True; break
                batch=self.entries[batch_start:batch_start+40]; batch_codes=[e["code"] for e in batch]
                try: quotes=fetch_quotes(batch_codes); quote_count+=len(quotes)
                except Exception: quotes={}
                for offset,entry in enumerate(batch):
                    index=batch_start+offset; code=entry["code"]
                    if self.isInterruptionRequested(): stopped=True; break
                    self.progress.emit(int(index/max(1,len(self.entries))*100),f"正在扫描 {code}（{index+1}/{len(self.entries)}）｜候选{len(rows)}只")
                    try:
                        raw=fetch_history(code,start_year=max(2018,datetime.now().year-2))
                        if len(raw)<120:
                            short_history+=1; processed=index+1; continue
                        eligible+=1
                        frame=build_signal_frame(raw)
                        if len(frame)<30: raise ValueError("指标数据不足")
                        latest=frame.iloc[-1]; recent=frame.tail(21)
                        setups=recent[recent.week_end & recent.week_trend]; week_rows=frame[frame.week_end]
                        last_week=week_rows.iloc[-1] if not week_rows.empty else latest; candidate=not setups.empty
                        setup=setups.iloc[-1] if candidate else None; stop_row=setup if candidate else last_week
                        stop=float(stop_row.stop_ref) if np.isfinite(stop_row.stop_ref) else 0.0; score=float(setup.signal_score) if candidate else 0.0
                        market_ok=self.market_mode=="关闭"
                        if not market_ok and market is not None:
                            sample=market.loc[:frame.index[-1]]; market_ok=market_regime(sample,self.market_mode) if len(sample)>=100 else False
                        above=bool(latest.above_ma); engulf=bool(latest.engulf); volume=bool(latest.volume_ok); watch=bool(candidate and market_ok and above and engulf)
                        signal_text="强确认" if watch and volume else ("买入观察" if watch else ("候选等待" if candidate and market_ok else "暂不操作"))
                        quote=quotes.get(code,{}); price=float(quote.get("price",raw.close.iloc[-1])); name=quote.get("name") or entry.get("name") or "--"
                        result={"code":code,"name":name,"date":frame.index[-1].strftime("%Y-%m-%d"),"price":price,"source":"实时" if code in quotes else "历史收盘",
                                "market_ok":market_ok,"candidate":candidate,"above_ma":above,"engulf":engulf,"volume":volume,"signal":signal_text,
                                "stop":stop,"score":score,"week_exit":bool(last_week.week_exit),"industry":INDUSTRY_MAP.get(code,"其他-"+code)}
                        if not self.full_market or candidate or entry.get("held"): rows.append(result)
                    except Exception as exc:
                        if len(errors)<200: errors.append(f"{code}: {str(exc)[:60]}")
                    processed=index+1
                self.save_checkpoint(processed,rows,errors,eligible,short_history)
                if stopped: break
            order = {"强确认":0, "买入观察":1, "候选等待":2, "暂不操作":3}
            rows.sort(key=lambda r:(order.get(r["signal"], 9), -r["score"], r["code"]))
            if self.full_market and not stopped and SCAN_CHECKPOINT.exists():
                try: SCAN_CHECKPOINT.unlink()
                except Exception: pass
            self.progress.emit(int(processed/max(1,len(self.entries))*100),"扫描已暂停" if stopped else "信号扫描完成")
            self.success.emit({"rows":rows,"errors":errors,"quote_count":quote_count,"processed":processed,"total":len(self.entries),
                               "eligible":eligible,"short_history":short_history,"stopped":stopped,"full_market":self.full_market})
        except Exception as exc:
            self.failure.emit(str(exc))


class PaperTradePage(QWidget):
    """完全本地的模拟账户；所有买卖均需人工确认，不连接券商。"""

    def __init__(self):
        super().__init__(); self.worker=None; self.universe_worker=None; self.scan_rows=[]; self.scan_map={}; self.alerts={}
        self.state = self.load_state()
        root = QVBoxLayout(self)
        top = QHBoxLayout(); title = QLabel("本地模拟交易"); title.setObjectName("title"); top.addWidget(title); top.addStretch()
        self.initial = QSpinBox(); self.initial.setRange(10000, 100000000); self.initial.setSingleStep(10000); self.initial.setValue(int(self.state["initial_cash"])); top.addWidget(QLabel("重置本金")); top.addWidget(self.initial)
        self.market_mode = QComboBox(); self.market_mode.addItems(["关闭","宽松","严格"]); top.addWidget(QLabel("大盘过滤")); top.addWidget(self.market_mode)
        self.scan_btn = QPushButton("扫描并更新行情"); self.scan_btn.clicked.connect(self.scan); top.addWidget(self.scan_btn)
        self.buy_btn = QPushButton("买入选中信号"); self.buy_btn.clicked.connect(self.buy_selected); top.addWidget(self.buy_btn)
        self.sell_btn = QPushButton("卖出选中持仓"); self.sell_btn.clicked.connect(self.sell_selected); top.addWidget(self.sell_btn)
        self.reset_btn = QPushButton("重置模拟账户"); self.reset_btn.setObjectName("danger"); self.reset_btn.clicked.connect(self.reset_account); top.addWidget(self.reset_btn); root.addLayout(top)
        code_row = QHBoxLayout(); code_row.addWidget(QLabel("自选股票池")); self.codes = QPlainTextEdit("600519,603993,002156,688333,000001,300750"); self.codes.setMaximumHeight(58); code_row.addWidget(self.codes, 1)
        sample = QPushButton("载入50只样本"); sample.clicked.connect(lambda:self.codes.setPlainText(SAMPLE_50)); code_row.addWidget(sample)
        self.full_btn=QPushButton("全市场扫描"); self.full_btn.clicked.connect(self.full_market_scan); code_row.addWidget(self.full_btn)
        self.resume_btn=QPushButton("继续上次扫描"); self.resume_btn.clicked.connect(self.resume_scan); self.resume_btn.setEnabled(SCAN_CHECKPOINT.exists()); code_row.addWidget(self.resume_btn)
        self.stop_btn=QPushButton("暂停扫描"); self.stop_btn.clicked.connect(self.stop_scan); self.stop_btn.setEnabled(False); code_row.addWidget(self.stop_btn); root.addLayout(code_row)
        self.pool_info=QLabel("全市场股票池每天更新一次；自动排除ST、退市整理，历史不足120个交易日的股票在扫描时排除。")
        self.pool_info.setStyleSheet("color:#93c5fd;padding:2px 6px"); root.addWidget(self.pool_info)
        cards = QGridLayout(); self.metrics = {}
        for col, name in enumerate(["账户总资产","可用现金","持仓市值","累计收益","当前仓位","持仓数量","止损预警","已完成交易"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); cards.addWidget(card,col//4,col%4); self.metrics[name]=value
        root.addLayout(cards)
        self.tabs = QTabWidget(); self.tabs.setMinimumHeight(350)
        self.signals = QTableWidget(0,13); self.signals.setHorizontalHeaderLabels(["代码","名称","数据日期","参考价","价格源","大盘","周线候选","MA5/20","阳包阴","放量","信号","止损参考","评分"])
        self.holdings = QTableWidget(0,12); self.holdings.setHorizontalHeaderLabels(["代码","名称","行业","股数","成本价","最新价","市值","浮动盈亏","收益率","止损价","风险状态","买入日期"])
        self.history = QTableWidget(0,11); self.history.setHorizontalHeaderLabels(["时间","方向","代码","名称","股数","成交价","成交额","费用","实现盈亏","原因","价格源"])
        for table in (self.signals,self.holdings,self.history):
            table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers); table.horizontalHeader().setStretchLastSection(True); table.verticalHeader().setVisible(False)
        self.tabs.addTab(self.signals,"今日信号"); self.tabs.addTab(self.holdings,"模拟持仓"); self.tabs.addTab(self.history,"成交记录"); root.addWidget(self.tabs)
        self.status = QLabel("本页仅模拟成交，不连接国泰海通或任何券商；价格仅供研究，请在交易时段人工复核。")
        self.status.setStyleSheet("color:#fbbf24;padding:6px"); root.addWidget(self.status)
        self.refresh_tables()

    @staticmethod
    def default_state(initial=100000):
        return {"version":1, "initial_cash":float(initial), "cash":float(initial),
                "positions":{}, "transactions":[], "updated_at":""}

    def load_state(self):
        try:
            state = json.loads(PAPER_FILE.read_text(encoding="utf-8"))
            if not isinstance(state.get("positions"), dict) or not isinstance(state.get("transactions"), list):
                raise ValueError("模拟账户文件格式错误")
            return state
        except FileNotFoundError:
            return self.default_state()
        except Exception:
            broken = PAPER_FILE.with_name(f"paper_account_broken_{datetime.now():%Y%m%d_%H%M%S}.json")
            try: PAPER_FILE.replace(broken)
            except Exception: pass
            return self.default_state()

    def save_state(self):
        self.state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        temporary = PAPER_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(PAPER_FILE)

    def parsed_codes(self):
        value = self.codes.toPlainText()
        for ch in ",，;；\n\t": value = value.replace(ch, " ")
        codes = [x for x in value.split() if len(x)==6 and x.isdigit()]
        return list(dict.fromkeys(codes + list(self.state["positions"])))

    def scan(self):
        codes = self.parsed_codes()
        if not codes: QMessageBox.warning(self,"没有代码","请输入至少一个6位股票代码"); return
        if len(codes) > 100: QMessageBox.warning(self,"数量过多","模拟盘单次最多扫描100只股票"); return
        entries=[{"code":c,"name":"","held":c in self.state["positions"]} for c in codes]
        self.start_scan(entries,False)

    def set_running(self, running):
        self.scan_btn.setEnabled(not running); self.full_btn.setEnabled(not running); self.resume_btn.setEnabled(not running and SCAN_CHECKPOINT.exists())
        self.stop_btn.setEnabled(running); self.buy_btn.setEnabled(not running); self.sell_btn.setEnabled(not running); self.reset_btn.setEnabled(not running)

    def start_scan(self, entries, full_market, resume_payload=None):
        self.set_running(True); self.status.setText("正在读取行情并扫描信号…")
        self.worker=PaperScanWorker(entries,self.market_mode.currentText(),full_market,resume_payload)
        self.worker.progress.connect(lambda p,m:self.status.setText(f"{m} | {p}%")); self.worker.success.connect(self.scan_loaded); self.worker.failure.connect(self.scan_failed); self.worker.start()

    def full_market_scan(self):
        self.set_running(True); self.status.setText("正在更新沪深京股票列表…")
        self.universe_worker=UniverseWorker(False); self.universe_worker.success.connect(self.universe_loaded); self.universe_worker.failure.connect(self.universe_failed); self.universe_worker.start()

    def universe_loaded(self, stocks, source):
        held=set(self.state["positions"])
        for entry in stocks: entry["held"]=entry["code"] in held
        counts={m:sum(s["exchange"]==m for s in stocks) for m in ("沪","深","北")}
        self.pool_info.setText(f"股票池 {len(stocks)}只（沪{counts['沪']}／深{counts['深']}／北{counts['北']}），来源：{source}；已排除ST和退市整理。")
        self.start_scan(stocks,True)

    def universe_failed(self, message):
        self.set_running(False); self.status.setText("全市场股票池读取失败"); QMessageBox.warning(self,"股票池读取失败",message+"\n\n可先继续使用自选股票池扫描。")

    def stop_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); self.stop_btn.setEnabled(False); self.status.setText("正在保存进度并暂停，请稍候…")

    def resume_scan(self):
        try:
            payload=json.loads(SCAN_CHECKPOINT.read_text(encoding="utf-8")); entries=payload["entries"]
            if not entries or payload.get("next_index",0)>=len(entries): raise ValueError("没有未完成任务")
            saved_mode=payload.get("market_mode","关闭"); self.market_mode.setCurrentText(saved_mode)
            self.start_scan(entries,True,payload)
        except Exception as exc:
            self.resume_btn.setEnabled(False); QMessageBox.warning(self,"无法继续",f"上次扫描记录不可用：{exc}")

    def scan_loaded(self, payload):
        self.scan_rows=payload["rows"]; self.scan_map={r["code"]:r for r in self.scan_rows}; self.alerts={}
        for code, position in self.state["positions"].items():
            row = self.scan_map.get(code)
            if not row: continue
            position["last_price"] = row["price"]; position["name"] = row["name"] if row["name"] != "--" else position.get("name","--")
            if row["stop"] > 0: position["stop"] = max(float(position.get("stop",0)), min(row["stop"], row["price"]*.99))
            reasons = []
            if row["price"] <= float(position.get("stop",0)): reasons.append("跌破止损")
            if row["week_exit"]: reasons.append("周线趋势离场")
            if reasons: self.alerts[code] = "、".join(reasons)
        self.save_state(); self.refresh_tables(); self.set_running(False)
        signal_count = sum(r["signal"] in ("买入观察","强确认") for r in self.scan_rows)
        error_text=f"；至少{len(payload['errors'])}只读取失败" if payload["errors"] else ""
        if payload.get("stopped"):
            self.status.setText(f"已暂停并保存：完成{payload['processed']}/{payload['total']}只，发现候选{len(self.scan_rows)}只；点击“继续上次扫描”可接着运行。")
        elif payload.get("full_market"):
            self.status.setText(f"全市场扫描完成：处理{payload['processed']}只，历史合格{payload['eligible']}只，历史不足120日{payload['short_history']}只，候选{len(self.scan_rows)}只，入场信号{signal_count}只{error_text}。")
        else:
            self.status.setText(f"自选扫描完成：{len(self.scan_rows)}只，{signal_count}只出现入场信号，{len(self.alerts)}只持仓触发风险提示；实时价{payload['quote_count']}只{error_text}。")
        if self.alerts:
            QMessageBox.warning(self,"模拟持仓风险提示","\n".join(f"{c}：{v}" for c,v in self.alerts.items()) + "\n\n系统不会自动卖出，请人工复核后操作。")

    def scan_failed(self, message):
        self.set_running(False); self.status.setText("扫描失败"); QMessageBox.warning(self,"扫描失败",message)

    @staticmethod
    def money(value): return f"¥{value:,.2f}"

    def account_values(self):
        market_value = sum(float(p["shares"]) * float(p.get("last_price",p["avg_cost"])) for p in self.state["positions"].values())
        total = float(self.state["cash"]) + market_value
        return total, market_value

    def refresh_tables(self):
        self.signals.setRowCount(len(self.scan_rows))
        for i,r in enumerate(self.scan_rows):
            vals=[r["code"],r["name"],r["date"],f'{r["price"]:.2f}',r["source"],"通过" if r["market_ok"] else "拦截","是" if r["candidate"] else "否","通过" if r["above_ma"] else "未过","是" if r["engulf"] else "否","是" if r["volume"] else "否",r["signal"],f'{r["stop"]:.2f}' if r["stop"] else "--",f'{r["score"]:.2f}']
            for j,v in enumerate(vals):
                item=QTableWidgetItem(str(v)); self.signals.setItem(i,j,item)
                if j==10: item.setForeground(QColor("#ef4444" if r["signal"] in ("买入观察","强确认") else "#94a3b8"))
        positions=list(self.state["positions"].items()); self.holdings.setRowCount(len(positions))
        for i,(code,p) in enumerate(positions):
            price=float(p.get("last_price",p["avg_cost"])); value=p["shares"]*price; pnl=value-float(p["cost"]); rate=(price/p["avg_cost"]-1)*100
            risk=self.alerts.get(code,"正常"); vals=[code,p.get("name","--"),p.get("industry","--"),p["shares"],f'{p["avg_cost"]:.2f}',f'{price:.2f}',f'{value:.2f}',f'{pnl:.2f}',f'{rate:.2f}%',f'{p["stop"]:.2f}',risk,p["buy_date"]]
            for j,v in enumerate(vals):
                item=QTableWidgetItem(str(v)); self.holdings.setItem(i,j,item)
                if j in (7,8): item.setForeground(QColor("#ef4444" if pnl>=0 else "#22c55e"))
                if j==10 and risk!="正常": item.setForeground(QColor("#fbbf24"))
        transactions=list(reversed(self.state["transactions"])); self.history.setRowCount(len(transactions))
        for i,t in enumerate(transactions):
            vals=[t["time"],t["side"],t["code"],t.get("name","--"),t["shares"],f'{t["price"]:.2f}',f'{t["amount"]:.2f}',f'{t["fee"]:.2f}',f'{t.get("pnl",0):.2f}',t["reason"],t.get("source","--")]
            for j,v in enumerate(vals): self.history.setItem(i,j,QTableWidgetItem(str(v)))
        for table in (self.signals,self.holdings,self.history): table.resizeColumnsToContents()
        total, market_value = self.account_values(); initial=float(self.state["initial_cash"]); result=(total/initial-1)*100 if initial else 0; exposure=market_value/total*100 if total else 0
        completed=sum(t["side"]=="卖出" for t in self.state["transactions"])
        metrics={"账户总资产":self.money(total),"可用现金":self.money(float(self.state["cash"])),"持仓市值":self.money(market_value),"累计收益":f"{result:+.2f}%","当前仓位":f"{exposure:.1f}%","持仓数量":str(len(positions)),"止损预警":str(len(self.alerts)),"已完成交易":str(completed)}
        for key,value in metrics.items(): self.metrics[key].setText(value)

    def buy_selected(self):
        row_index=self.signals.currentRow()
        if row_index < 0: QMessageBox.information(self,"请选择信号","先在“今日信号”中选择一行"); return
        code=self.signals.item(row_index,0).text(); row=self.scan_map.get(code)
        if not row or row["signal"] not in ("买入观察","强确认"):
            QMessageBox.warning(self,"未满足条件","只能买入当前标记为“买入观察”或“强确认”的信号"); return
        if code in self.state["positions"]: QMessageBox.information(self,"已有持仓",f"{code} 已在模拟持仓中"); return
        if len(self.state["positions"]) >= 5: QMessageBox.warning(self,"风控拦截","最多同时持有5只股票"); return
        if sum(p.get("industry")==row["industry"] for p in self.state["positions"].values()) >= 2: QMessageBox.warning(self,"风控拦截",f'{row["industry"]}行业已有2只持仓'); return
        total, market_value=self.account_values(); price=row["price"]*1.001; stop=row["stop"]
        if stop <= 0 or stop >= price: QMessageBox.warning(self,"止损无效","当前信号没有低于成交参考价的有效止损位"); return
        capacity=max(0,total*.8-market_value); budget=min(float(self.state["cash"]),total*.2,capacity)
        risk_per_share=max(price-stop,price*.005); risk_qty=int((total*.008)/risk_per_share/100)*100; cap_qty=int(budget/(price*100))*100; qty=min(risk_qty,cap_qty)
        if qty <= 0: QMessageBox.warning(self,"风控拦截","按单笔风险0.8%、单股20%和100股整数手计算，可买数量为0"); return
        amount=qty*price; fee=max(5.0,amount*.0003)
        message=f"代码：{code} {row['name']}\n数量：{qty}股\n模拟成交价：{price:.2f}元（含0.1%滑点）\n止损参考：{stop:.2f}元\n计划风险：{qty*(price-stop):.2f}元\n\n确认写入本地模拟账户？"
        if QMessageBox.question(self,"确认模拟买入",message,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        self.state["cash"]-=amount+fee; self.state["positions"][code]={"name":row["name"],"industry":row["industry"],"shares":qty,"avg_cost":price,"cost":amount+fee,"stop":stop,"last_price":row["price"],"buy_date":datetime.now().strftime("%Y-%m-%d")}
        self.state["transactions"].append({"time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"side":"买入","code":code,"name":row["name"],"shares":qty,"price":price,"amount":amount,"fee":fee,"pnl":0,"reason":row["signal"],"source":row["source"]})
        self.save_state(); self.refresh_tables(); self.tabs.setCurrentWidget(self.holdings); self.status.setText(f"已模拟买入 {code} {qty}股。该记录不会发送到券商。")

    def sell_selected(self):
        row_index=self.holdings.currentRow()
        if row_index < 0: QMessageBox.information(self,"请选择持仓","先在“模拟持仓”中选择一行"); return
        code=self.holdings.item(row_index,0).text(); p=self.state["positions"].get(code)
        if not p: return
        price=float(p.get("last_price",p["avg_cost"]))*0.999; amount=p["shares"]*price; fee=max(5.0,amount*.0003)+amount*.0005; pnl=amount-fee-float(p["cost"])
        reason=self.alerts.get(code,"人工卖出")
        message=f"代码：{code} {p.get('name','--')}\n数量：{p['shares']}股\n模拟成交价：{price:.2f}元（含0.1%滑点）\n预计实现盈亏：{pnl:+.2f}元\n原因：{reason}\n\n确认卖出全部模拟持仓？"
        if QMessageBox.question(self,"确认模拟卖出",message,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        self.state["cash"]+=amount-fee; self.state["transactions"].append({"time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"side":"卖出","code":code,"name":p.get("name","--"),"shares":p["shares"],"price":price,"amount":amount,"fee":fee,"pnl":pnl,"reason":reason,"source":self.scan_map.get(code,{}).get("source","最近保存价")}); self.state["positions"].pop(code); self.alerts.pop(code,None)
        self.save_state(); self.refresh_tables(); self.status.setText(f"已模拟卖出 {code}，实现盈亏 {pnl:+.2f}元。")

    def reset_account(self):
        if QMessageBox.warning(self,"确认重置",f"将清空全部模拟持仓和成交记录，并以 {self.initial.value():,} 元重新开始。此操作不可撤销。",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        self.state=self.default_state(self.initial.value()); self.scan_rows=[]; self.scan_map={}; self.alerts={}; self.save_state(); self.refresh_tables(); self.status.setText("模拟账户已重置；未影响任何回测缓存或策略参数。")


class ResearchDataWorker(QThread):
    progress=Signal(object); success=Signal(object); failure=Signal(str)
    def __init__(self,mode,start_year,resume=False):
        super().__init__(); self.mode=mode; self.start_year=start_year; self.resume=resume; self.pause_requested=False

    def request_pause(self): self.pause_requested=True

    def _save(self,payload,path):
        temporary=path.with_suffix(".tmp"); temporary.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8"); temporary.replace(path)

    def run(self):
        try:
            self.progress.emit({"kind":"phase","stage":"正在读取股票列表","detail":"正在取得股票代码与交易所信息…"})
            stocks,source=fetch_market_universe(False)
            if self.mode=="50只快速样本":
                wanted=set(SAMPLE_50.split(",")); entries=[x for x in stocks if x["code"] in wanted]
                known={x["code"] for x in entries}; entries.extend({"code":c,"name":"样本股","exchange":"--"} for c in wanted-known)
                entries.sort(key=lambda x:x["code"]); target_success=len(entries); primary_codes={x["code"] for x in entries}
            elif self.mode=="300只分层样本":
                entries,primary_codes=research_candidate_queue(stocks,300); target_success=300
            else:
                entries=stocks; target_success=len(entries); primary_codes={x["code"] for x in entries}
            self.progress.emit({"kind":"phase","stage":"股票列表已就绪","detail":f"目标有效数据 {target_success} 只，候选池 {len(entries)} 只，正在核对断点…","total":target_success})
            signature=hashlib.sha1((self.mode+str(self.start_year)+",".join(x["code"] for x in entries)).encode()).hexdigest()
            start_index=0; success_rows=[]; errors=[]; cache_count=0; requests_count=0; retries_count=0; consecutive_failures=0; attempted_count=0
            pending_entries=entries
            if self.resume and DATA_PREP_CHECKPOINT.exists():
                saved=json.loads(DATA_PREP_CHECKPOINT.read_text(encoding="utf-8"))
                if saved.get("signature")!=signature:
                    if saved.get("mode")!=self.mode or int(saved.get("start_year",0))!=self.start_year: raise ValueError("断点任务与当前样本档位或年份不一致")
                    success_rows=list(saved.get("success_rows",[])); completed={r.get("代码") for r in success_rows}; pending_entries=[x for x in entries if x["code"] not in completed]; start_index=0; errors=[]
                else:
                    start_index=int(saved.get("next_index",0)); success_rows=list(saved.get("success_rows",[])); errors=list(saved.get("errors",[])); pending_entries=list(saved.get("pending_entries",entries))
                cache_count=int(saved.get("cache_count",0)); requests_count=int(saved.get("requests_count",0)); retries_count=int(saved.get("retries_count",0)); target_success=int(saved.get("target_success",target_success)); attempted_count=int(saved.get("attempted_count",0))
            elif RESEARCH_SAMPLE_FILE.exists():
                try:
                    previous=json.loads(RESEARCH_SAMPLE_FILE.read_text(encoding="utf-8"))
                    if previous.get("mode")==self.mode and int(previous.get("start_year",0))==self.start_year:
                        valid_codes={x["code"] for x in entries}; success_rows=[r for r in previous.get("stocks",[]) if r.get("代码") in valid_codes]
                        completed={r["代码"] for r in success_rows}; pending_entries=[x for x in entries if x["code"] not in completed]
                        self.progress.emit({"kind":"phase","stage":"补抓并自动替补","detail":f"已保留 {len(success_rows)} 只有效数据，还需 {max(0,target_success-len(success_rows))} 只","processed":len(success_rows),"total":target_success})
                except Exception: pass
            started=time.perf_counter(); total=target_success; initial_success=len(success_rows)

            def checkpoint_payload(next_index):
                return {"version":3,"signature":signature,"mode":self.mode,"start_year":self.start_year,"source":source,"entries":entries,"pending_entries":pending_entries,"target_success":target_success,"next_index":next_index,"success_rows":success_rows,"errors":errors,"cache_count":cache_count,"requests_count":requests_count,"retries_count":retries_count,"attempted_count":attempted_count,"updated":datetime.now().isoformat(timespec="seconds")}

            for index in range(start_index,len(pending_entries)):
                if len(success_rows)>=target_success: break
                if self.pause_requested:
                    payload=checkpoint_payload(index); self._save(payload,DATA_PREP_CHECKPOINT)
                    self.success.emit({**payload,"processed":len(success_rows),"total":total,"paused":True,"pause_reason":"用户暂停"}); return
                item=pending_entries[index]; code=item["code"]; cache_file=CACHE_DIR/f"{code}.csv"; used_cache=False
                current=f'{code} {item.get("name","")}'
                processed_before=len(success_rows); attempted_count+=1
                self.progress.emit({"kind":"phase","stage":"正在检查缓存","detail":f"有效 {processed_before}/{total}，尝试第{attempted_count}只：{current}","processed":processed_before,"total":total,"current":current,"requests":requests_count,"retries":retries_count,"consecutive_failures":consecutive_failures})
                try:
                    if cache_file.exists():
                        cached=pd.read_csv(cache_file,parse_dates=["date"])
                        if len(cached)>=260 and cached.date.min().year<=self.start_year and (pd.Timestamp.now().normalize()-cached.date.max()).days<=10: used_cache=True
                    def data_event(event):
                        nonlocal requests_count,retries_count
                        requests_count+=int(event.get("request",0)); retries_count+=int(event.get("retry",0))
                        detail=event.get("detail",current)
                        self.progress.emit({"kind":"phase","stage":event.get("stage","正在读取历史行情"),"detail":f"{current}；{detail}","processed":processed_before,"total":total,"current":current,"source":event.get("source","--"),"requests":requests_count,"retries":retries_count,"consecutive_failures":consecutive_failures})
                    raw=fetch_history(code,start_year=self.start_year,progress_callback=data_event)
                    if len(raw)<260: raise ValueError("历史不足260日")
                    data_source=raw.attrs.get("data_source","本地缓存" if used_cache else "自动选择")
                    role="原始样本" if code in primary_codes else "自动替补"
                    row={"代码":code,"名称":item.get("name","--"),"交易所":item.get("exchange","--"),"状态":"缓存" if used_cache else "已下载","样本角色":role,"数据源":data_source,"行数":len(raw),"首日":raw.index.min().strftime("%Y-%m-%d"),"末日":raw.index.max().strftime("%Y-%m-%d"),"错误":""}
                    success_rows.append(row); cache_count+=int(used_cache); consecutive_failures=0
                except Exception as exc:
                    row={"代码":code,"名称":item.get("name","--"),"交易所":item.get("exchange","--"),"状态":"失败","样本角色":"原始样本" if code in primary_codes else "替补候选","数据源":"全部失败","行数":0,"首日":"--","末日":"--","错误":str(exc)[:260]}; errors.append(row)
                    if item.get("exchange")=="北": consecutive_failures=0
                    else: consecutive_failures+=1
                processed=len(success_rows); elapsed=max(time.perf_counter()-started,.01); gained=max(0,processed-initial_success); rate=gained/elapsed; eta=(target_success-processed)/rate if rate>0 else 0
                self._save(checkpoint_payload(index+1),DATA_PREP_CHECKPOINT)
                self.progress.emit({"kind":"row","processed":processed,"total":total,"attempted":attempted_count,"success":len(success_rows),"failed":len(errors),"cached":cache_count,"current":current,"eta":readable_eta(eta),"row":row,"requests":requests_count,"retries":retries_count,"consecutive_failures":consecutive_failures,"source":row.get("数据源","--")})
                if consecutive_failures>=8:
                    payload=checkpoint_payload(index+1); self._save(payload,DATA_PREP_CHECKPOINT)
                    self.success.emit({**payload,"processed":processed,"total":total,"paused":True,"pause_reason":"连续8只非北交所股票的全部数据源均失败，已自动暂停保护"}); return
                time.sleep(random.uniform(.6,1.2))
            sample={"updated":datetime.now().isoformat(timespec="seconds"),"mode":self.mode,"start_year":self.start_year,"source":source,"target_success":target_success,"qualified":len(success_rows)>=target_success,"stocks":success_rows[:target_success],"errors":errors,"requests_count":requests_count,"retries_count":retries_count,"attempted_count":attempted_count}
            self._save(sample,RESEARCH_SAMPLE_FILE)
            if DATA_PREP_CHECKPOINT.exists(): DATA_PREP_CHECKPOINT.unlink()
            self.success.emit({**sample,"processed":min(len(success_rows),target_success),"total":target_success,"success_rows":success_rows[:target_success],"errors":errors,"cache_count":cache_count,"paused":False})
        except Exception as exc: self.failure.emit(str(exc))


class ResearchDataPage(QWidget):
    sample_ready=Signal(object)
    def __init__(self):
        super().__init__(); self.worker=None; self.run_started=None; self.activity_stage="等待开始"; self.activity_detail=""
        root=QVBoxLayout(self); top=QHBoxLayout(); title=QLabel("有效样本补齐与全市场准备 v7.5"); title.setObjectName("title"); top.addWidget(title); top.addStretch()
        self.mode=QComboBox(); self.mode.addItems(["50只快速样本","300只分层样本","全市场"]); self.mode.setCurrentText("300只分层样本"); top.addWidget(QLabel("样本档位")); top.addWidget(self.mode)
        self.start_year=QSpinBox(); self.start_year.setRange(2008,2020); self.start_year.setValue(2018); top.addWidget(QLabel("数据起始")); top.addWidget(self.start_year)
        self.start_btn=QPushButton("开始准备数据"); self.start_btn.clicked.connect(lambda:self.start(False)); top.addWidget(self.start_btn)
        self.pause_btn=QPushButton("暂停"); self.pause_btn.setEnabled(False); self.pause_btn.clicked.connect(self.pause); top.addWidget(self.pause_btn)
        self.resume_btn=QPushButton("继续断点"); self.resume_btn.clicked.connect(lambda:self.start(True)); top.addWidget(self.resume_btn); root.addLayout(top)
        note=QLabel("300只模式按有效数据验收：北交所映射不完整时自动从候选池替补，直至有效样本达到300只；全市场仍如实保留缺失清单。不会自动交易。")
        note.setStyleSheet("color:#fbbf24;padding:4px"); root.addWidget(note)
        self.bar=QProgressBar(); self.bar.setRange(0,100); self.bar.setValue(0); self.bar.setFormat("等待开始"); root.addWidget(self.bar)
        cards=QGridLayout(); self.stats={}
        for col,name in enumerate(["有效/目标","成功","失败","使用缓存","当前股票","当前数据源","请求次数","重试次数","连续失败","预计剩余","运行计时"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); cards.addWidget(card,col//4,col%4); self.stats[name]=value
        root.addLayout(cards)
        self.table=QTableWidget(0,11); self.table.setHorizontalHeaderLabels(["代码","名称","交易所","状态","样本角色","数据源","行数","首日","末日","错误","尝试序号"]); self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table,1)
        self.status=QLabel("等待开始。已存在且日期足够新的缓存会直接复用。"); self.status.setStyleSheet("color:#93c5fd;padding:4px"); root.addWidget(self.status)
        self.heartbeat=QTimer(self); self.heartbeat.setInterval(1000); self.heartbeat.timeout.connect(self.tick)
        self.restore_checkpoint_preview()

    def checkpoint(self):
        if not DATA_PREP_CHECKPOINT.exists(): return None
        return json.loads(DATA_PREP_CHECKPOINT.read_text(encoding="utf-8"))

    def restore_checkpoint_preview(self):
        try: saved=self.checkpoint()
        except Exception as exc:
            self.resume_btn.setEnabled(False); self.status.setText(f"发现无法读取的断点：{exc}"); return
        if not saved:
            self.resume_btn.setEnabled(False); return
        self.mode.setCurrentText(saved.get("mode",self.mode.currentText())); self.start_year.setValue(int(saved.get("start_year",self.start_year.value())))
        next_index=int(saved.get("next_index",0)); successes=list(saved.get("success_rows",[])); errors=list(saved.get("errors",[])); target=int(saved.get("target_success",len(saved.get("entries",[])))); total=target; pending=list(saved.get("pending_entries",saved.get("entries",[]))); done=len(successes) if saved.get("version",1)>=3 else next_index
        percent=int(done/max(total,1)*100); self.bar.setValue(percent); self.bar.setFormat(f"断点 {done}/{total}  {percent}%")
        next_item=pending[next_index] if next_index<len(pending) else {}
        values={"有效/目标":f"{done}/{total}","成功":str(len(successes)),"失败":str(len(errors)),"使用缓存":str(saved.get("cache_count",0)),"当前股票":next_item.get("code","等待继续"),"当前数据源":"等待继续","请求次数":str(saved.get("requests_count",0)),"重试次数":str(saved.get("retries_count",0)),"连续失败":"--","预计剩余":"继续后计算","运行计时":"已暂停"}
        for key,value in values.items(): self.stats[key].setText(value)
        for seq,row_data in enumerate((successes+errors)[-100:],max(1,done-len(successes+errors)+1)):
            row=self.table.rowCount(); self.table.insertRow(row)
            for col,key in enumerate(["代码","名称","交易所","状态","样本角色","数据源","行数","首日","末日","错误"]): self.table.setItem(row,col,QTableWidgetItem(str(row_data.get(key,""))))
            self.table.setItem(row,10,QTableWidgetItem(str(seq)))
        self.resume_btn.setEnabled(True); self.status.setText(f"已恢复断点显示：完成 {done}/{total}；点击“继续断点”或“开始准备数据”接着运行。")

    def tick(self):
        if self.run_started is None: return
        elapsed=int(time.perf_counter()-self.run_started); clock=readable_eta(elapsed)
        self.stats["运行计时"].setText(clock)
        self.status.setText(f"{self.activity_stage}｜{self.activity_detail}｜已运行 {clock}")

    def start(self,resume):
        if self.worker and self.worker.isRunning(): return
        if resume and not DATA_PREP_CHECKPOINT.exists(): QMessageBox.information(self,"没有断点","没有发现可继续的下载任务。"); return
        if not resume and DATA_PREP_CHECKPOINT.exists():
            try:
                saved=self.checkpoint(); same=saved.get("mode")==self.mode.currentText() and int(saved.get("start_year"))==self.start_year.value()
            except Exception: same=False
            if same: resume=True
            elif QMessageBox.question(self,"发现其他断点","现有断点与当前样本档位或年份不同。\n\n开始新任务会替换旧断点，是否继续？",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        if resume:
            try:
                saved=json.loads(DATA_PREP_CHECKPOINT.read_text(encoding="utf-8")); self.mode.setCurrentText(saved["mode"]); self.start_year.setValue(int(saved["start_year"]))
            except Exception as exc: QMessageBox.warning(self,"断点无效",str(exc)); return
        if not resume: self.table.setRowCount(0)
        self.start_btn.setEnabled(False); self.resume_btn.setEnabled(False); self.pause_btn.setEnabled(True); self.activity_stage="正在启动"; self.activity_detail="读取股票列表并准备历史数据…"; self.run_started=time.perf_counter(); self.heartbeat.start(); self.tick()
        self.worker=ResearchDataWorker(self.mode.currentText(),self.start_year.value(),resume); self.worker.progress.connect(self.updated); self.worker.success.connect(self.finished); self.worker.failure.connect(self.failed); self.worker.start()

    def pause(self):
        if self.worker and self.worker.isRunning(): self.worker.request_pause(); self.pause_btn.setEnabled(False); self.status.setText("已请求暂停；当前股票处理结束后保存断点…")

    def updated(self,p):
        if p.get("kind")=="phase":
            self.activity_stage=p.get("stage","正在运行"); self.activity_detail=p.get("detail","")
            if "current" in p: self.stats["当前股票"].setText(p["current"])
            if "source" in p: self.stats["当前数据源"].setText(str(p["source"]))
            if "requests" in p: self.stats["请求次数"].setText(str(p["requests"]))
            if "retries" in p: self.stats["重试次数"].setText(str(p["retries"]))
            if "consecutive_failures" in p: self.stats["连续失败"].setText(str(p["consecutive_failures"]))
            if "processed" in p and "total" in p:
                percent=int(p["processed"]/max(p["total"],1)*100); self.bar.setValue(percent); self.bar.setFormat(f'{p["processed"]}/{p["total"]}  {percent}%')
            self.tick(); return
        percent=int(p["processed"]/max(p["total"],1)*100); self.bar.setValue(percent); self.bar.setFormat(f'{p["processed"]}/{p["total"]}  {percent}%')
        values={"有效/目标":f'{p["processed"]}/{p["total"]}',"成功":str(p["success"]),"失败":str(p["failed"]),"使用缓存":str(p["cached"]),"当前股票":p["current"],"当前数据源":p.get("source","--"),"请求次数":str(p.get("requests",0)),"重试次数":str(p.get("retries",0)),"连续失败":str(p.get("consecutive_failures",0)),"预计剩余":p["eta"]}
        for k,v in values.items(): self.stats[k].setText(v)
        r=p["row"]; row=self.table.rowCount(); self.table.insertRow(row)
        for j,key in enumerate(["代码","名称","交易所","状态","样本角色","数据源","行数","首日","末日","错误"]): self.table.setItem(row,j,QTableWidgetItem(str(r.get(key,""))))
        self.table.setItem(row,10,QTableWidgetItem(str(p.get("attempted",p["processed"]))))
        if self.table.rowCount()>500: self.table.removeRow(0)
        self.table.scrollToBottom(); self.activity_stage="已保存断点"; self.activity_detail=f'{p["current"]} 已完成；预计剩余 {p["eta"]}'; self.tick()

    def finished(self,p):
        self.heartbeat.stop(); self.run_started=None; self.start_btn.setEnabled(True); self.pause_btn.setEnabled(False)
        if p.get("paused"):
            self.resume_btn.setEnabled(True); self.stats["运行计时"].setText("已暂停"); self.status.setText(f'{p.get("pause_reason","已暂停")}：完成{p["processed"]}/{p["total"]}；点击“继续断点”接着运行。'); return
        self.resume_btn.setEnabled(False)
        codes=[r["代码"] for r in p.get("success_rows",[])]
        self.sample_ready.emit(codes[:500]); target=max(int(p.get("total",len(codes))),1); percent=int(len(codes)/target*100); self.bar.setValue(min(percent,100))
        replacements=sum(1 for r in p.get("success_rows",[]) if r.get("样本角色")=="自动替补")
        if p.get("qualified"):
            self.bar.setFormat("有效样本已补齐")
            self.status.setText(f'完成：有效{len(codes)}/{target}只，其中自动替补{replacements}只；失败尝试{len(p.get("errors",[]))}次。已写入验证股票池。')
        else:
            self.bar.setFormat(f"有效样本未补齐 {len(codes)}/{target}")
            self.status.setText(f'候选池已处理完，但有效数据只有{len(codes)}/{target}只；失败{len(p.get("errors",[]))}只。结果已保存但标记为不合格。')

    def failed(self,message):
        self.heartbeat.stop(); self.run_started=None; self.start_btn.setEnabled(True); self.resume_btn.setEnabled(DATA_PREP_CHECKPOINT.exists()); self.pause_btn.setEnabled(False); self.stats["运行计时"].setText("已停止"); self.status.setText("数据准备失败"); QMessageBox.warning(self,"数据准备失败",message)


class TailScanWorker(QThread):
    progress=Signal(int,str); success=Signal(object); failure=Signal(str)
    def run(self):
        try:
            cache=TailCache(TAIL_CACHE_DIR)
            try: fallback_universe,_=fetch_market_universe(False)
            except Exception: fallback_universe=[]
            spot=fetch_tail_spot(fallback_universe=fallback_universe); audit=[]; errors=[]; eligible=[]
            basic=[]
            for row in spot:
                values=[row.get(key,np.nan) for key in ("price","change_pct","amplitude","turnover","float_market_cap","volume")]
                if not is_main_board(row.get("code",""),row.get("name","")): continue
                if not all(np.isfinite(float(value)) for value in values): continue
                if not (0<float(row["price"])<13 and float(row["float_market_cap"])<20_000_000_000 and
                        float(row["change_pct"])<9 and float(row["amplitude"])<6 and float(row["turnover"])<10): continue
                basic.append(row)
            for index,row in enumerate(basic):
                if self.isInterruptionRequested(): break
                code=row["code"]; self.progress.emit(int(index/max(1,len(basic))*100),f"检查 {code}（{index+1}/{len(basic)}）")
                try:
                    daily=cache.load_daily(code)
                    if len(daily)<60:
                        legacy=CACHE_DIR/f"{code}.csv"
                        if legacy.exists():
                            daily=pd.read_csv(legacy,parse_dates=["date"]).set_index("date").sort_index()
                            source="原有日线缓存"
                        else:
                            daily=fetch_history(code,count=500,start_year=max(2018,datetime.now().year-2))
                            source=str(daily.attrs.get("data_source","多源日线"))
                            if source=="BaoStock": daily=daily.assign(volume=daily.volume.astype(float)/100)
                        cache.merge_daily(code,daily)
                    else: source="尾盘永久缓存"
                    result=evaluate_candidate(row,daily); result["daily_source"]=source; audit.append(result)
                    if result["passed"]: eligible.append(result)
                except Exception as exc:
                    errors.append({"code":code,"error":str(exc)[:180]})
            ranked=rank_candidates(eligible); stamp=spot[0]["timestamp"] if spot else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            snapshot=cache.save_snapshot(stamp,audit)
            self.progress.emit(100,"尾盘筛选完成")
            self.success.emit({"rows":ranked,"audit":audit,"errors":errors,"total_spot":len(spot),"prefiltered":len(basic),"snapshot":str(snapshot),"coverage":cache.coverage()})
        except Exception as exc: self.failure.emit(str(exc))


class TailBacktestWorker(QThread):
    progress=Signal(int,str); success=Signal(object); failure=Signal(str)
    def __init__(self,rows,config): super().__init__(); self.rows=rows; self.config=config
    def run(self):
        try:
            cache=TailCache(TAIL_CACHE_DIR); codes=sorted({str(row.get("code","")).zfill(6) for row in self.rows if row.get("passed")})
            download_errors=[]; end=pd.Timestamp.now(); start=end-pd.Timedelta(days=8)
            for index,code in enumerate(codes):
                if self.isInterruptionRequested(): break
                self.progress.emit(int(index/max(1,len(codes))*70),f"更新分钟数据 {code}（{index+1}/{len(codes)}）")
                try:
                    fresh=fetch_tail_minutes(code,start,end)
                    if not fresh.empty: cache.merge_minutes(code,fresh)
                except Exception as exc: download_errors.append({"code":code,"error":"分钟数据:"+str(exc)[:160]})
            self.progress.emit(75,"运行分钟精确回测")
            result=run_tail_backtest(self.rows,cache,self.config); result["errors"].extend(download_errors)
            self.progress.emit(100,"分钟回测完成"); self.success.emit(result)
        except Exception as exc: self.failure.emit(str(exc))


class TailStrategyPage(QWidget):
    """独立尾盘两日短线模块；只研究和本地模拟，不连接券商。"""
    def __init__(self):
        super().__init__(); self.worker=None; self.scan_rows=[]; self.scan_audit=[]; self.last_result=None
        self.cache=TailCache(TAIL_CACHE_DIR); self.state=load_tail_state(TAIL_STATE_FILE)
        self.state.setdefault("initial_cash",100000.0); self.state.setdefault("cash",float(self.state["initial_cash"])); self.state.setdefault("positions",{}); self.state.setdefault("transactions",[])
        root=QVBoxLayout(self)
        first=QHBoxLayout(); title=QLabel("尾盘两日短线 TAIL_2D_V1"); title.setObjectName("title"); first.addWidget(title); first.addStretch()
        self.top_n=QSpinBox(); self.top_n.setRange(1,10); self.top_n.setValue(5); first.addWidget(QLabel("每日前N只")); first.addWidget(self.top_n)
        self.initial=QSpinBox(); self.initial.setRange(10000,100000000); self.initial.setValue(int(self.state["initial_cash"])); self.initial.setSingleStep(10000); first.addWidget(QLabel("初始资金")); first.addWidget(self.initial)
        self.scan_btn=QPushButton("扫描全市场"); self.scan_btn.clicked.connect(self.scan); first.addWidget(self.scan_btn)
        self.backtest_btn=QPushButton("更新分钟并回测"); self.backtest_btn.clicked.connect(self.run_backtest); first.addWidget(self.backtest_btn); root.addLayout(first)
        second=QHBoxLayout(); second.addStretch()
        self.paper_btn=QPushButton("保存前N只为模拟"); self.paper_btn.clicked.connect(self.add_paper); second.addWidget(self.paper_btn)
        self.refresh_btn=QPushButton("刷新模拟持仓"); self.refresh_btn.clicked.connect(self.refresh_paper); second.addWidget(self.refresh_btn)
        self.import_btn=QPushButton("导入分钟CSV"); self.import_btn.clicked.connect(self.import_csv); second.addWidget(self.import_btn)
        self.export_btn=QPushButton("一键生成核实包"); self.export_btn.clicked.connect(self.export_bundle); self.export_btn.setEnabled(False); second.addWidget(self.export_btn); root.addLayout(second)
        note=QLabel("14:30后扫描、14:50冻结、14:55首个可成交分钟买入；买入日不卖，T+1起执行+5%后回落0.3%止盈、-5%止损，最迟T+2尾盘退出。免费1分钟数据只覆盖近期，软件会永久增量保存。")
        note.setWordWrap(True); note.setStyleSheet("color:#fbbf24;padding:4px"); root.addWidget(note)
        cards=QGridLayout(); self.metrics={}
        for col,name in enumerate(["全市场","预筛剩余","最终候选","缓存分钟日","模拟现金","模拟持仓","回测收益","完成交易"]):
            card=QFrame(); card.setObjectName("card"); box=QVBoxLayout(card); box.addWidget(QLabel(name)); value=QLabel("--"); value.setObjectName("title"); box.addWidget(value); cards.addWidget(card,col//4,col%4); self.metrics[name]=value
        root.addLayout(cards)
        self.tabs=QTabWidget()
        self.screen=QTableWidget(0,7); self.screen.setHorizontalHeaderLabels(["股票代码","股票简称","最新价","涨跌幅","换手率","振幅","流通市值"])
        self.positions=QTableWidget(0,10); self.positions.setHorizontalHeaderLabels(["代码","名称","买入时间","买入价","股数","最高价","止盈激活","T+1","T+2","状态"])
        self.trades=QTableWidget(0,9); self.trades.setHorizontalHeaderLabels(["代码","买入时间","买入价","卖出时间","卖出价","股数","净盈亏","原因","费用"])
        data_page=QWidget(); data_layout=QVBoxLayout(data_page); self.data_text=QPlainTextEdit(); self.data_text.setReadOnly(True); data_layout.addWidget(self.data_text)
        for table in (self.screen,self.positions,self.trades):
            table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setEditTriggers(QAbstractItemView.NoEditTriggers); table.verticalHeader().setVisible(False); table.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.screen,"今日筛选"); self.tabs.addTab(self.positions,"模拟持仓"); self.tabs.addTab(self.trades,"分钟回测"); self.tabs.addTab(data_page,"数据管理"); root.addWidget(self.tabs,1)
        self.progress=QProgressBar(); self.progress.setRange(0,100); self.progress.setValue(0); self.progress.setFormat("等待操作"); root.addWidget(self.progress)
        self.status=QLabel("旧策略保持不变。本页不连接券商，不自动下单。"); self.status.setStyleSheet("color:#93c5fd;padding:4px"); root.addWidget(self.status)
        self.refresh_state_table(); self.refresh_coverage()

    def set_busy(self,busy):
        for button in (self.scan_btn,self.backtest_btn,self.paper_btn,self.refresh_btn,self.import_btn): button.setEnabled(not busy)

    def update_progress(self,value,message): self.progress.setValue(value); self.progress.setFormat(f"{message} {value}%"); self.status.setText(message)

    def scan(self):
        if self.worker and self.worker.isRunning(): return
        self.set_busy(True); self.progress.setValue(0); self.status.setText("正在读取全市场实时字段并筛选…")
        self.worker=TailScanWorker(); self.worker.progress.connect(self.update_progress); self.worker.success.connect(self.scan_loaded); self.worker.failure.connect(self.failed); self.worker.start()

    def scan_loaded(self,payload):
        self.set_busy(False); self.scan_rows=payload["rows"]; self.scan_audit=payload["audit"]; self.screen.setRowCount(0)
        for item in self.scan_rows:
            row=self.screen.rowCount(); self.screen.insertRow(row)
            values=[item["code"],item["name"],f'{item["price"]:.2f}',f'{item["change_pct"]:.2f}%',f'{item["turnover"]:.2f}%',f'{item["amplitude"]:.2f}%',f'{item["float_market_cap"]/1e8:.2f}亿']
            for col,value in enumerate(values): self.screen.setItem(row,col,QTableWidgetItem(str(value)))
        self.metrics["全市场"].setText(str(payload["total_spot"])); self.metrics["预筛剩余"].setText(str(payload["prefiltered"])); self.metrics["最终候选"].setText(str(len(self.scan_rows)))
        self.progress.setValue(100); self.progress.setFormat("筛选完成 100%"); self.status.setText(f'筛选完成：全市场{payload["total_spot"]}只，基础预筛{payload["prefiltered"]}只，最终候选{len(self.scan_rows)}只；错误{len(payload["errors"])}只。')
        self.refresh_coverage()

    def all_snapshot_rows(self):
        rows=[]
        for path in self.cache.list_snapshots():
            try:
                frame=pd.read_csv(path,dtype={"code":str})
                for item in frame.to_dict("records"):
                    item["code"]=str(item.get("code","")).zfill(6); item["passed"]=str(item.get("passed","")).lower() in ("true","1","yes")
                    rows.append(item)
            except Exception: pass
        return rows

    def run_backtest(self):
        if self.worker and self.worker.isRunning(): return
        rows=self.all_snapshot_rows()
        if not any(row.get("passed") for row in rows): QMessageBox.information(self,"没有候选快照","请先运行“扫描全市场”，形成14:50候选快照。 "); return
        config={"initial_cash":float(self.initial.value()),"top_n":int(self.top_n.value()),"max_position_pct":20,"total_position_pct":80,"commission":.0003,"min_commission":5,"stamp":.0005,"slippage":.001}
        self.set_busy(True); self.worker=TailBacktestWorker(rows,config); self.worker.progress.connect(self.update_progress); self.worker.success.connect(self.backtest_loaded); self.worker.failure.connect(self.failed); self.worker.start()

    def backtest_loaded(self,result):
        self.set_busy(False); self.last_result=result; summary=result["summary"]; self.trades.setRowCount(0)
        for item in result["trades"]:
            row=self.trades.rowCount(); self.trades.insertRow(row)
            values=[item.get("code",""),item.get("entry_time",""),f'{item.get("entry_price",0):.3f}',item.get("exit_time",""),f'{item.get("exit_price",0):.3f}',item.get("shares",0),f'{item.get("net_pnl",0):.2f}',item.get("reason",""),f'{item.get("fees",0):.2f}']
            for col,value in enumerate(values): self.trades.setItem(row,col,QTableWidgetItem(str(value)))
        self.metrics["回测收益"].setText(f'{summary["return_pct"]:+.2f}%'); self.metrics["完成交易"].setText(str(summary["completed_trades"])); self.export_btn.setEnabled(True)
        self.progress.setValue(100); self.progress.setFormat("分钟回测完成 100%"); self.status.setText(f'分钟精确回测完成：{summary["orders"]}笔买入，{summary["completed_trades"]}笔完成，仍持有{summary["open_positions"]}笔；缺口/错误{len(result["errors"])}项。')
        self.refresh_coverage()

    def add_paper(self):
        if not self.scan_rows: QMessageBox.information(self,"没有候选","请先扫描全市场。 "); return
        cash=float(self.state.get("cash",self.initial.value())); positions=self.state.setdefault("positions",{}); added=0; unavailable=[]
        budget=float(self.state.get("initial_cash",self.initial.value()))*.8/max(1,self.top_n.value())
        for item in self.scan_rows[:self.top_n.value()]:
            code=item["code"]
            if code in positions: continue
            frame=self.cache.load_minutes(code); stamp=pd.Timestamp(item["timestamp"]); bars=frame.loc[frame.index.date==stamp.date()] if not frame.empty else frame
            fill=entry_fill(bars,slippage=.001) if not bars.empty else None
            if not fill: unavailable.append(code); continue
            shares=int(min(budget,cash)/(fill["price"]*100))*100; amount=shares*fill["price"]; fee=max(5.0,amount*.0003) if shares else 0
            if shares<=0 or amount+fee>cash: unavailable.append(code); continue
            cash-=amount+fee; positions[code]={"code":code,"name":item.get("name",""),"entry_time":fill["time"].isoformat(),"entry_price":fill["price"],"shares":shares,"peak":fill["price"],"trailing_armed":False,"status":"持有"}; added+=1
        self.state["cash"]=cash; self.state["initial_cash"]=float(self.state.get("initial_cash",self.initial.value())); save_tail_state(TAIL_STATE_FILE,self.state); self.refresh_state_table()
        self.status.setText(f"已保存{added}只本地模拟持仓；无14:55分钟数据{len(unavailable)}只。先点“更新分钟并回测”可补近期分钟数据。")

    def refresh_paper(self):
        positions=self.state.setdefault("positions",{}); sold=[]; all_days=set()
        frames={}
        for code in positions:
            frame=self.cache.load_minutes(code); frames[code]=frame; all_days.update(frame.index.normalize().unique())
        calendar=sorted(all_days)
        for code,item in list(positions.items()):
            try:
                frame=frames[code]; day_map={day:group for day,group in frame.groupby(frame.index.date)}; result=simulate_position(item,day_map,calendar,{"commission":.0003,"min_commission":5,"stamp":.0005,"slippage":.001})
                item["peak"]=result["peak"]; item["trailing_armed"]=result["trailing_armed"]; item["status"]=result["status"]
                if result["status"]=="已卖出":
                    self.state["cash"]=float(self.state.get("cash",0))+result["exit_price"]*result["shares"]-result["sell_fee"]; self.state.setdefault("transactions",[]).append({key:(value.isoformat() if isinstance(value,pd.Timestamp) else value) for key,value in result.items()}); positions.pop(code); sold.append(code)
            except ValueError: item["status"]="等待足够交易日分钟数据"
            except Exception as exc: item["status"]="更新失败:"+str(exc)[:60]
        save_tail_state(TAIL_STATE_FILE,self.state); self.refresh_state_table(); self.status.setText(f"模拟持仓已刷新；本次卖出{len(sold)}只。")

    def refresh_state_table(self):
        self.positions.setRowCount(0)
        for code,item in self.state.get("positions",{}).items():
            row=self.positions.rowCount(); self.positions.insertRow(row); entry=pd.Timestamp(item["entry_time"])
            calendar=sorted({pd.Timestamp(path.name).date() for path in self.cache.minute_dir.glob("????-??-??") if path.is_dir()})
            t1=t2="待数据确认"
            future=[day for day in calendar if day>entry.date()]
            if len(future)>=2: t1,t2=future[0],future[1]
            values=[code,item.get("name",""),item.get("entry_time",""),f'{float(item.get("entry_price",0)):.3f}',item.get("shares",0),f'{float(item.get("peak",0)):.3f}',"是" if item.get("trailing_armed") else "否",t1,t2,item.get("status","持有")]
            for col,value in enumerate(values): self.positions.setItem(row,col,QTableWidgetItem(str(value)))
        self.metrics["模拟现金"].setText(f'{float(self.state.get("cash",0)):.2f}'); self.metrics["模拟持仓"].setText(str(len(self.state.get("positions",{}))))

    def import_csv(self):
        path,_=QFileDialog.getOpenFileName(self,"导入标准分钟CSV",str(APP_DIR),"CSV文件 (*.csv)")
        if not path: return
        try:
            result=import_minute_csv(path,self.cache); self.refresh_coverage(); QMessageBox.information(self,"导入完成",f'导入{result["rows"]}行、{result["codes"]}只股票、{result["days"]}个交易日。')
        except Exception as exc: QMessageBox.warning(self,"导入失败",str(exc))

    def refresh_coverage(self):
        coverage=self.cache.coverage(); self.metrics["缓存分钟日"].setText(str(coverage["minute_days"])); self.data_text.setPlainText("\n".join([f"策略编号：{TAIL_STRATEGY_ID}",f'分钟缓存交易日：{coverage["minute_days"]}',f'分钟覆盖：{coverage["first_minute_day"] or "--"} 至 {coverage["last_minute_day"] or "--"}',f'日线缓存股票：{coverage["daily_symbols"]}',f'14:50筛选快照：{coverage["snapshot_count"]}',"",f"缓存目录：{TAIL_CACHE_DIR}","升级覆盖程序文件时，请保留 tail_strategy_cache 和 tail_strategy_state.json。","免费1分钟接口仅有近期数据；更早精确历史请用标准CSV导入。"]));

    def export_bundle(self):
        if not self.last_result: QMessageBox.information(self,"没有回测结果","请先完成一次分钟回测。 "); return
        try:
            target=APP_DIR/f"AStockQuant尾盘策略核实包_{datetime.now():%Y%m%d_%H%M%S}.zip"; create_tail_audit_bundle(target,self.last_result,self.cache.coverage())
            if sys.platform.startswith("win"):
                try: subprocess.Popen(["explorer.exe","/select,",str(target)])
                except Exception: pass
            QMessageBox.information(self,"核实包已生成",f"已生成：\n{target}\n\n文件夹已打开，把这个ZIP拖进聊天框即可。")
        except Exception as exc: QMessageBox.warning(self,"生成失败",str(exc))

    def failed(self,message):
        self.set_busy(False); self.progress.setFormat("运行失败"); self.status.setText("尾盘策略运行失败"); QMessageBox.warning(self,"尾盘策略运行失败",message)


class MainWindow(QMainWindow):
    def closeEvent(self, event):
        full_worker = getattr(getattr(self, 'kline', None), 'full_worker', None)
        if full_worker is not None and full_worker.isRunning():
            full_worker.pause_requested = True
            event.ignore()
            QTimer.singleShot(800, self.close)
            return
        worker = getattr(getattr(self, 'weekly_trend', None), 'refresh_worker', None)
        if worker is not None and worker.isRunning():
            worker.pause_requested = True
            event.ignore()
            QTimer.singleShot(800, self.close)
            return
        super().closeEvent(event)

    def __init__(self):
        super().__init__(); self.setWindowTitle("A股个人量化交易系统 v8.3.2"); self.resize(1540,920)
        root=QWidget(); layout=QHBoxLayout(root); layout.setContentsMargins(0,0,0,0)
        self.menu=QListWidget(); self.menu.setFixedWidth(210); self.menu.addItems(["行情与K线","策略规则说明","单股历史回测","批量独立回测","共享资金组合","研究样本与数据准备","牛熊双引擎验证","尾盘两日短线","周线趋势确认","风险控制"]); layout.addWidget(self.menu)
        self.pages=QStackedWidget(); self.kline=KlinePage(); self.pages.addWidget(self.kline)
        notes=QLabel("策略规则已写入行情分析页。\n\n买入通知 ≠ 自动下单；所有信号均须人工复核。\n当前版本不连接券商账户。")
        notes.setAlignment(Qt.AlignCenter); self.pages.addWidget(notes); self.pages.addWidget(BacktestPage()); self.pages.addWidget(BatchPage()); self.pages.addWidget(PortfolioPage())
        self.data_prep=ResearchDataPage(); self.pages.addWidget(self.data_prep)
        self.adaptive=AdaptiveResearchPage(); self.pages.addWidget(self.adaptive); self.data_prep.sample_ready.connect(lambda codes:self.adaptive.codes.setPlainText(",".join(codes)))
        if RESEARCH_SAMPLE_FILE.exists():
            try:
                saved=json.loads(RESEARCH_SAMPLE_FILE.read_text(encoding="utf-8")); saved_codes=[r["代码"] for r in saved.get("stocks",[]) if r.get("代码")]
                if saved_codes: self.adaptive.codes.setPlainText(",".join(saved_codes[:500]))
            except Exception: pass
        self.tail_strategy=TailStrategyPage(); self.pages.addWidget(self.tail_strategy)
        try:
            try:
                from .weekly_trend_page import create_weekly_trend_page
            except ImportError:
                from weekly_trend_page import create_weekly_trend_page
            self.weekly_trend=create_weekly_trend_page(APP_DIR,APP_VERSION,history_fetcher=fetch_history)
        except Exception as exc:
            self.weekly_trend=QLabel("v8 内核加载失败："+str(exc)+"\n请检查安装组件，然后重新运行安装脚本。旧策略仍可使用。")
            self.weekly_trend.setWordWrap(True)
        self.pages.addWidget(self.weekly_trend)
        risk=QLabel("股票引擎：原始入场/离场、R0.8/P20、最多持仓8只\n指数引擎：仅使用闲置现金配置510300，上限0/10/20/30/40%\n市场状态：沪深300前一日MA50/MA200及20/60日动量\n参考目标：年化2%—5%，亏损年度不低于-1%\n历史选择：2018—2023；滚动审计只用过去年份选择下一年方案\n2024年至今仅研究回放，不参与选参\n\n模拟交易继续暂停；本版本不会产生真实订单。")
        risk.setAlignment(Qt.AlignCenter); self.pages.addWidget(risk)
        self.menu.currentRowChanged.connect(self.pages.setCurrentIndex); self.menu.setCurrentRow(0); layout.addWidget(self.pages,1); self.setCentralWidget(root)


if __name__ == "__main__":
    pg.setConfigOptions(antialias=True)
    app=QApplication(sys.argv); app.setStyleSheet(STYLE); win=MainWindow(); win.show(); sys.exit(app.exec())
