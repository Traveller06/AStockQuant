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
    def __init__(self, facade, cache_dir):
        super().__init__()
        self.facade, self.cache_dir = facade, Path(cache_dir)
        from astock_quant.desktop.weekly_trend_scanner import WeeklyTrendScanner
        self.scanner = WeeklyTrendScanner(self.cache_dir.parent)
        self.screen_worker = None
        self.screen_result = None
        self.worker = None
        root = QVBoxLayout(self)
        root.addWidget(QLabel('周线趋势确认 · 股票池筛选与独立回测'))
        root.addWidget(QLabel('研究/模拟用途，不连接真实券商；请先在“研究样本与数据准备”准备日线。筛选只读取本地已有股票缓存。'))
        screen_controls = QHBoxLayout()
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
        self.screen_status.setText('正在读取本地股票池并计算周线形态…')
        self.screen_worker = WeeklyScreenWorker(self.scanner, cutoff)
        self.screen_worker.progress_changed.connect(
            lambda pct, msg: (self.progress.setValue(pct), self.screen_status.setText(msg)))
        self.screen_worker.completed.connect(self._screen_finished)
        self.screen_worker.failed.connect(self._screen_failed)
        self.screen_worker.start()

    def _screen_finished(self, result):
        self.scan_button.setEnabled(True)
        self.show_screen_result(result)

    def _screen_failed(self, message):
        self.scan_button.setEnabled(True)
        self.screen_status.setText('筛选失败：' + message)
        QMessageBox.warning(self, '筛选失败', message)

    def show_screen_result(self, result):
        self.screen_result = result
        stale = result.pool_size - result.fresh_count - result.error_count
        self.screen_status.setText(
            f'本地缓存股票池 {result.pool_size} 只；筛选截至 {result.data_as_of}；'
            f'数据齐全 {result.fresh_count} 只、当日确认 {result.signal_count} 只、'
            f'等待确认 {result.watch_count} 只、行情过期 {stale} 只、数据错误 {result.error_count} 只。'
            '筛选信号仅供研究，买入须等待下一交易日并核对涨跌停/停牌。')
        candidates = [row for row in result.rows if row.status in ('signal', 'watch')]
        self.screen_table.setRowCount(len(candidates))
        for index, row in enumerate(candidates):
            fields = (row.symbol, row.name,
                      '当日确认' if row.status == 'signal' else '等待确认',
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
            self.show_screen_result(self.scanner.open_last_screen())
        except Exception as exc:
            QMessageBox.warning(self, '无法打开上次筛选', str(exc))

    def export_screen(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出选股结果', '周线趋势筛选.csv', 'CSV (*.csv)')
        if path:
            try:
                self.scanner.export_csv(Path(path))
                self.screen_status.setText('选股结果已导出：' + path)
            except Exception as exc:
                QMessageBox.warning(self, '导出失败', str(exc))

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


def create_weekly_trend_page(app_dir, app_version):
    from astock_quant.desktop.weekly_trend_facade import WeeklyTrendFacade
    return WeeklyTrendPage(WeeklyTrendFacade(Path(app_dir), app_version), Path(app_dir) / 'cache')
