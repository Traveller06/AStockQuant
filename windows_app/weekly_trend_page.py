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
    QTabWidget, QVBoxLayout, QWidget)


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
        self.worker = None
        root = QVBoxLayout(self)
        root.addWidget(QLabel('周线趋势确认 · 独立 v8 回测'))
        root.addWidget(QLabel('研究/模拟用途，不连接真实券商；请先在“研究样本与数据准备”准备日线。'))
        controls = QGridLayout()
        self.codes = QLineEdit('600519,000001')
        self.start = QLineEdit('2018-01-01')
        self.end = QLineEdit(date.today().isoformat())
        self.adjustment = QComboBox(); self.adjustment.addItems(['qfq', 'hfq', 'none'])
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
