"""Pure strategy and indicator modules never depend on the desktop shell."""

import ast
from pathlib import Path

from astock_quant.strategies.registry import StrategyRegistry


ROOT = Path(__file__).parents[2] / "src" / "astock_quant"
FORBIDDEN = {"PySide6", "requests", "akshare", "baostock", "main", "tail_strategy"}


def test_strategy_and_indicators_have_no_ui_network_or_v7_imports():
    for directory in (ROOT / "strategies", ROOT / "indicators"):
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            roots = {node.module.split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.module}
            roots |= {alias.name.split(".")[0] for node in ast.walk(tree)
                      if isinstance(node, ast.Import) for alias in node.names}
            assert roots.isdisjoint(FORBIDDEN), path


def test_legacy_registry_default_is_unchanged():
    assert StrategyRegistry.with_builtins().default_strategy_id == "legacy_v7"
