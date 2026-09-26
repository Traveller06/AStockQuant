"""Opt-in v8 research page; all matching and strategy logic lives in astock_quant."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re

import pandas as pd
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


class WeeklyScreenWorker(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, scanner, as_of):
        super().__init__()
        self.scanner, self.as_of = scanner, as_of

    def run(self):
        try:
            result = self.scanner.scan_cache(adjustment_basis='qfq', as_of=self.as_of,
                progress=lambda pct, message: self.progress_changed.emit(pct, message))
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class WeeklyRefreshWorker(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, app_dir, history_fetcher, as_of):
        super().__init__()
        self.app_dir, self.history_fetcher, self.as_of = app_dir, history_fetcher, as_of
        self.pause_requested = False

    def run(self):
        try:
            from astock_quant.desktop.weekly_trend_updater import CachedHistoryUpdater
            from astock_quant.desktop.weekly_trend_scanner import _safe_date
            cutoff = min(self.as_of, _safe_date()) if self.as_of else _safe_date()
            if self.as_of is None:
                self.progress_changed.emit(0, '正在核实指数最近收盘日…')
                index = self.history_fetcher('INDEX_000300', start_year=max(2018, cutoff.year-1),
                    market_symbol='sh000300', force_refresh=True, persist=False, min_rows=2)
                days = pd.to_datetime(index.index, errors='coerce')
                candidates = [value.date() for value in days if not pd.isna(value) and value.date() <= cutoff]
                if not candidates:
                    raise ValueError('指数日线没有已收盘交易日；可以填写明确的历史截止日重试')
                target = max(candidates)
                if (cutoff - target).days > 15:
                    raise ValueError(f'沪深300指数最新行情仅到 {target}，距离预期收盘日过久，已停止行情更新')
                cutoff = target
            self.progress_changed.emit(0, f'目标收盘日 {cutoff}，开始补齐本地股票池…')
            updater = CachedHistoryUpdater(self.app_dir)
            result = updater.refresh(target=cutoff,
                fetcher=lambda code: self.history_fetcher(code,
                    start_year=max(2018, cutoff.year-1), force_refresh=True, persist=False),
                progress=lambda pct, msg: self.progress_changed.emit(pct, msg),
                should_pause=lambda: self.pause_requested)
            self.completed.emit((cutoff, result))
        except Exception as exc:
            self.failed.emit(str(exc))


class WeeklyRunWorker(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, facade, codes, options, cache_dir):
        super().__init__()
        self.facade, self.codes, self.options, self.cache_dir = facade, codes, options, cache_dir

    def run(self):
        try:
            frames = {}
            failures = []
            for code in self.codes:
                file = self.cache_dir / (code + '.csv')
                if not file.is_file():
                    failures.append(code + ': 无本地日线缓存')
                    continue
                try:
                    frames[code] = pd.read_csv(file, parse_dates=['date']).set_index('date')
                except (OSError, ValueError, KeyError) as exc:
                    failures.append(code + ': ' + str(exc))
            summary = self.facade.run(frames, self.options,
                                      progress=lambda pct, msg: self.progress_changed.emit(pct, msg))
            self.completed.emit((summary, failures))
        except Exception as exc:
            self.failed.emit(str(exc))


class WeeklyTrendPage(QWidget):
    def __init__(self, facade, cache_dir, history_fetcher=None):
        super().__init__()
        self.facade, self.cache_dir = facade, Path(cache_dir)
        from astock_quant.desktop.weekly_trend_scanner import WeeklyTrendScanner
        self.scanner = WeeklyTrendScanner(self.cache_dir.parent)
        self.three_tier_scanner = WeeklyTrendScanner(self.cache_dir.parent, three_tier=True)
        self.screen_worker = None
        self.screen_result = None
        self.history_fetcher = history_fetcher
        self.refresh_worker = None
        self.worker = None
        root = QVBoxLayout(self)
        root.addWidget(QLabel('周线趋势确认 · 股票池筛选与独立回测'))
        root.addWidget(QLabel('研究/模拟用途，不连接真实券商；请先在“研究样本与数据准备”准备日线。筛选只读取本地已有股票缓存。'))
        screen_controls = QHBoxLayout()
        self.screen_mode = QComboBox()
        self.screen_mode.addItems(['9月8日规则1：强确认 / 确认 / 预确认', 'v8.1 周线策略：当日确认 / 等待确认'])
        self.screen_mode.currentIndexChanged.connect(self._mode_changed)
        screen_controls.addWidget(self.screen_mode)
        screen_controls.addWidget(QLabel('筛选截止日（留空＝最新已收盘日）'))
        self.screen_date = QLineEdit('')
        self.screen_date.setPlaceholderText('如 2026-09-25，留空自动判断')
        screen_controls.addWidget(self.screen_date)
        self.scan_button = QPushButton('筛选本地股票池')
        self.last_screen_button = QPushButton('打开上次筛选')
        self.export_screen_button = QPushButton('导出选股 CSV')
        for button, callback in ((self.scan_button, self.start_screen),
                                 (self.last_screen_button, self.open_last_screen),
                                 (self.export_screen_button, self.export_screen)):
            button.clicked.connect(callback); screen_controls.addWidget(button)
        root.addLayout(screen_controls)
        refresh_controls = QHBoxLayout()
        self.refresh_button = QPushButton('更新过期行情（可续跑）')
        self.pause_refresh_button = QPushButton('暂停更新')
        self.pause_refresh_button.setEnabled(False)
        self.refresh_button.setEnabled(self.history_fetcher is not None)
        self.refresh_button.clicked.connect(self.start_refresh)
        self.pause_refresh_button.clicked.connect(self.pause_refresh)
        refresh_controls.addWidget(self.refresh_button)
        refresh_controls.addWidget(self.pause_refresh_button)
        refresh_controls.addWidget(QLabel('只更新本机 cache 已有股票；逐只保存增量，不改原始缓存。'))
        root.addLayout(refresh_controls)
        self.screen_status = QLabel('等待筛选。结果只覆盖已有日线缓存，并标明实际筛选日期和样本数量。')
        self.screen_status.setWordWrap(True); root.addWidget(self.screen_status)
        self.screen_table = QTableWidget(0, 7)
        self.screen_table.setHorizontalHeaderLabels(['股票代码', '股票简称', '状态', '行情日期', '收盘价', '形态', '原因'])
        self.screen_table.verticalHeader().setVisible(False)
        self.screen_table.horizontalHeader().setStretchLastSection(True)
        self.screen_table.itemSelectionChanged.connect(self.show_screen_checks)
        self.screen_details = QPlainTextEdit()
        self.screen_details.setReadOnly(True)
        self.screen_tabs = QTabWidget()
        self.screen_tabs.addTab(self.screen_table, '入选与待确认')
        self.screen_tabs.addTab(self.screen_details, '选中股票规则检查')
        root.addWidget(self.screen_tabs)
        controls = QGridLayout()
        self.codes = QLineEdit('600519,000001')
        self.start = QLineEdit('2018-01-01')
        self.end = QLineEdit(date.today().isoformat())
        self.adjustment = QComboBox(); self.adjustment.addItems(['qfq'])
        self.initial = QLineEdit('100000')
        self.commission = QLineEdit('0.0003')
        self.minimum = QLineEdit('5')
        self.stamp_tax = QLineEdit('0.0005')
        self.slippage = QLineEdit('0.001')
        for index, (label, widget) in enumerate([
            ('股票代码，逗号分隔', self.codes), ('开始日期', self.start), ('结束日期', self.end),
            ('复权方式', self.adjustment), ('初始资金', self.initial),
            ('佣金费率', self.commission), ('最低佣金', self.minimum),
            ('卖出印花税', self.stamp_tax), ('滑点费率', self.slippage)]):
            controls.addWidget(QLabel(label), index // 3, index % 3 * 2)
            controls.addWidget(widget, index // 3, index % 3 * 2 + 1)
        root.addLayout(controls)
        actions = QHBoxLayout()
        self.run_button = QPushButton('运行回测')
        self.open_button = QPushButton('打开上次结果')
        self.export_button = QPushButton('导出审计包')
        for button, callback in ((self.run_button, self.run_backtest),
                                 (self.open_button, self.open_last),
                                 (self.export_button, self.export_audit)):
            button.clicked.connect(callback); actions.addWidget(button)
        root.addLayout(actions)
        self.progress = QProgressBar(); self.progress.setRange(0, 100); root.addWidget(self.progress)
        self.status = QLabel('等待运行。仅从本地历史日线缓存读取，不自动交易。')
        self.status.setWordWrap(True); root.addWidget(self.status)
        self.metrics = {}
        metric_row = QHBoxLayout()
        for name in ('收益', '最大回撤', '交易次数', '胜率', '盈亏因子', '平均仓位'):
            value = QLabel(name + ': —'); metric_row.addWidget(value); self.metrics[name] = value
        root.addLayout(metric_row)
        self.tabs = QTabWidget()
        self.tables = {}
        for name, label in (('signals','信号'), ('orders','订单'), ('trades','成交'),
                            ('events','未成交/事件'), ('checks','验证'), ('errors','数据错误')):
            display = QPlainTextEdit(); display.setReadOnly(True)
            self.tables[name] = display; self.tabs.addTab(display, label)
        root.addWidget(self.tabs)

    def start_screen(self):
        try:
            cutoff = date.fromisoformat(self.screen_date.text().strip()) if self.screen_date.text().strip() else None
        except ValueError:
            QMessageBox.warning(self, '日期有误', '请使用 YYYY-MM-DD 格式，或留空自动选择最新交易日。')
            return
        self.scan_button.setEnabled(False)
        self.screen_mode.setEnabled(False)
        self.screen_status.setText('正在读取本地股票池并计算周线形态…')
        self.screen_worker = WeeklyScreenWorker(self._active_scanner(), cutoff)
        self.screen_worker.progress_changed.connect(
            lambda pct, msg: (self.progress.setValue(pct), self.screen_status.setText(msg)))
        self.screen_worker.completed.connect(self._screen_finished)
        self.screen_worker.failed.connect(self._screen_failed)
        self.screen_worker.start()

    def _screen_finished(self, result):
        self.scan_button.setEnabled(True)
        self.screen_mode.setEnabled(True)
        self.show_screen_result(result)

    def _screen_failed(self, message):
        self.scan_button.setEnabled(True)
        self.screen_mode.setEnabled(True)
        self.screen_status.setText('筛选失败：' + message)
        QMessageBox.warning(self, '筛选失败', message)

    def show_screen_result(self, result):
        self.screen_result = result
        stale = result.pool_size - result.fresh_count - result.error_count
        tier = self.screen_mode.currentIndex() == 0
        if tier:
            counts = {key: sum(row.status == key for row in result.rows)
                      for key in ('strong', 'confirm', 'preconfirm')}
            summary = (f'强确认 {counts["strong"]} 只、确认 {counts["confirm"]} 只、'
                       f'预确认 {counts["preconfirm"]} 只')
        else:
            summary = f'当日确认 {result.signal_count} 只、等待确认 {result.watch_count} 只'
        self.screen_status.setText(
            f'本地缓存股票池 {result.pool_size} 只；筛选截至 {result.data_as_of}；'
            f'数据齐全 {result.fresh_count} 只、{summary}、'
            f'行情过期 {stale} 只、数据错误 {result.error_count} 只。'
            '筛选信号仅供研究，买入须等待下一交易日并核对涨跌停/停牌。')
        labels = {'strong': '强确认', 'confirm': '确认', 'preconfirm': '预确认',
                  'signal': '当日确认', 'watch': '等待确认'}
        candidates = [row for row in result.rows if row.status in labels]
        self.screen_table.setRowCount(len(candidates))
        for index, row in enumerate(candidates):
            fields = (row.symbol, row.name,
                      labels[row.status],
                      row.latest_date, str(row.close or ''), row.setup, row.reason_zh)
            for column, value in enumerate(fields):
                self.screen_table.setItem(index, column, QTableWidgetItem(value))
        self.screen_details.setPlainText(
            '点击入选股票查看全部规则。其余股票未通过、缓存日期落后或数据有误；'
            '可导出 CSV 查看每只股票的状态和原因。')

    def show_screen_checks(self):
        if self.screen_result is None:
            return
        selected = self.screen_table.currentRow()
        if selected < 0:
            return
        item = self.screen_table.item(selected, 0)
        if item is None:
            return
        row = next((entry for entry in self.screen_result.rows if entry.symbol == item.text()), None)
        if row is not None:
            self.screen_details.setPlainText('\n'.join(
                f'{"通过" if check["passed"] else "未通过"}｜{check["reason_zh"]}｜'
                f'实际 {check["actual"]}｜要求 {check["threshold"]}'
                for check in row.checks) or row.reason_zh)

    def open_last_screen(self):
        try:
            self.show_screen_result(self._active_scanner().open_last_screen())
        except Exception as exc:
            QMessageBox.warning(self, '无法打开上次筛选', str(exc))

    def export_screen(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出选股结果', '周线趋势筛选.csv', 'CSV (*.csv)')
        if path:
            try:
                self._active_scanner().export_csv(Path(path))
                self.screen_status.setText('选股结果已导出：' + path)
            except Exception as exc:
                QMessageBox.warning(self, '导出失败', str(exc))

    def _active_scanner(self):
        return self.three_tier_scanner if self.screen_mode.currentIndex() == 0 else self.scanner

    def start_refresh(self):
        if self.history_fetcher is None:
            QMessageBox.warning(self, '未配置数据源', '本机程序未提供历史行情更新入口。')
            return
        try:
            cutoff = date.fromisoformat(self.screen_date.text().strip()) if self.screen_date.text().strip() else None
        except ValueError:
            QMessageBox.warning(self, '日期有误', '请使用 YYYY-MM-DD 格式，或留空读取指数最新收盘日。')
            return
        self.refresh_button.setEnabled(False)
        self.pause_refresh_button.setEnabled(True)
        self.scan_button.setEnabled(False)
        self.last_screen_button.setEnabled(False)
        self.export_screen_button.setEnabled(False)
        self.screen_result = None
        self.screen_table.setRowCount(0)
        self.screen_status.setText('正在补齐行情；关闭窗口前请先暂停，已成功的股票会保留。')
        self.refresh_worker = WeeklyRefreshWorker(self.cache_dir.parent, self.history_fetcher, cutoff)
        self.refresh_worker.progress_changed.connect(
            lambda pct, msg: (self.progress.setValue(pct), self.screen_status.setText(msg)))
        self.refresh_worker.completed.connect(self._refresh_finished)
        self.refresh_worker.failed.connect(self._refresh_failed)
        self.refresh_worker.start()

    def pause_refresh(self):
        if self.refresh_worker:
            self.refresh_worker.pause_requested = True
            self.pause_refresh_button.setEnabled(False)
            self.screen_status.setText('正在暂停：等待当前股票请求结束。成功更新的股票已保存，稍后可继续。')

    def _refresh_controls_ready(self):
        self.refresh_button.setEnabled(True)
        self.pause_refresh_button.setEnabled(False)
        self.scan_button.setEnabled(True)
        self.last_screen_button.setEnabled(True)
        self.export_screen_button.setEnabled(True)

    def _refresh_finished(self, result):
        cutoff, outcome = result
        self._refresh_controls_ready()
        if not self.screen_date.text().strip():
            self.screen_date.setText(cutoff.isoformat())
        state = '已暂停' if outcome.paused else '已完成'
        self.screen_status.setText(f'{state}：目标收盘日 {cutoff}；'
            f'更新 {outcome.updated} 只、原已最新 {outcome.skipped} 只、'
            f'失败 {outcome.failed} 只。再次点击可续跑；完成后点击“筛选本地股票池”。')
        if outcome.errors:
            self.screen_details.setPlainText('行情更新错误（最多显示100只）：\n' + '\n'.join(outcome.errors))

    def _refresh_failed(self, message):
        self._refresh_controls_ready()
        self.screen_status.setText('行情更新失败：' + message)
        QMessageBox.warning(self, '行情更新失败', message)

    def _mode_changed(self):
        self.screen_result = None
        self.screen_table.setRowCount(0)
        self.screen_details.clear()
        self.screen_status.setText('已切换筛选方案。点击“筛选本地股票池”或“打开上次筛选”。')

    def run_backtest(self):
        try:
            from astock_quant.desktop.weekly_trend_facade import DesktopBacktestOptions
            codes = [code for code in re.split(r'[,，\s]+', self.codes.text()) if code]
            if not codes or any(not re.fullmatch(r'\d{6}', code) for code in codes):
                raise ValueError('请输入逗号分隔的六位股票代码')
            options = DesktopBacktestOptions(date.fromisoformat(self.start.text()),
                date.fromisoformat(self.end.text()), self.adjustment.currentText(),
                Decimal(self.initial.text()), Decimal(self.commission.text()),
                Decimal(self.minimum.text()), Decimal(self.stamp_tax.text()),
                Decimal(self.slippage.text()))
            self.run_button.setEnabled(False)
            self.worker = WeeklyRunWorker(self.facade, codes, options, self.cache_dir)
            self.worker.progress_changed.connect(lambda pct, msg: (self.progress.setValue(pct), self.status.setText(msg)))
            self.worker.completed.connect(self._finished)
            self.worker.failed.connect(self._failed)
            self.worker.start()
        except (ValueError, ArithmeticError) as exc:
            QMessageBox.warning(self, '输入有误', str(exc))

    def _finished(self, result):
        summary, failures = result
        self.run_button.setEnabled(True)
        self.display_summary(summary)
        if failures:
            self.tables['errors'].appendPlainText('\n'.join(failures))
            self.status.setText(self.status.text() + f'；{len(failures)}只未读取，详见数据错误页')

    def _failed(self, message):
        self.run_button.setEnabled(True)
        self.status.setText('回测失败：' + message)
        QMessageBox.warning(self, '回测失败', message)

    def display_summary(self, summary):
        self.status.setText(f'运行 {summary.run_id}；数据截至 {summary.data_as_of}；{summary.warning_zh}')
        for key, widget in self.metrics.items():
            widget.setText(f'{key}: {summary.metrics[key]}')
        for key, widget in self.tables.items():
            widget.setPlainText(json.dumps(summary.tables[key], ensure_ascii=False, indent=2, default=str))

    def open_last(self):
        try:
            self.display_summary(self.facade.open_last_result())
        except Exception as exc:
            QMessageBox.warning(self, '无法打开上次结果', str(exc))

    def export_audit(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存审计包', 'weekly-trend-audit.zip', 'ZIP (*.zip)')
        if path:
            try:
                self.facade.export_audit_bundle(Path(path))
                self.status.setText('审计包已保存：' + path)
            except Exception as exc:
                QMessageBox.warning(self, '导出失败', str(exc))


def create_weekly_trend_page(app_dir, app_version, history_fetcher=None):
    from astock_quant.desktop.weekly_trend_facade import WeeklyTrendFacade
    return WeeklyTrendPage(WeeklyTrendFacade(Path(app_dir), app_version),
                           Path(app_dir) / 'cache', history_fetcher=history_fetcher)
