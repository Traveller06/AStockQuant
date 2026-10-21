import ast
from pathlib import Path


SOURCE_ROOT = Path(__file__).parents[2] / "src" / "astock_quant"
FORBIDDEN_CORE_ROOTS = {"PySide6", "requests", "akshare", "baostock"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_core_has_no_ui_or_network_dependencies() -> None:
    violations: list[tuple[str, str]] = []
    for path in sorted((SOURCE_ROOT / "core").glob("*.py")):
        for imported in _imports(path):
            if imported.split(".", 1)[0] in FORBIDDEN_CORE_ROOTS:
                violations.append((str(path.relative_to(SOURCE_ROOT)), imported))
    assert violations == []


def test_v8_source_never_imports_a_legacy_v7_package() -> None:
    violations = [
        (str(path.relative_to(SOURCE_ROOT)), imported)
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
        for imported in _imports(path)
        if imported == "astock_quant_v7_6" or imported.startswith("astock_quant_v7_6.")
    ]
    assert violations == []


def test_ui_depends_on_services_not_concrete_data_providers() -> None:
    ui_root = SOURCE_ROOT / "ui"
    if not ui_root.exists():
        return
    violations = [
        (str(path.relative_to(SOURCE_ROOT)), imported)
        for path in sorted(ui_root.rglob("*.py"))
        for imported in _imports(path)
        if imported.startswith("astock_quant.data.providers")
    ]
    assert violations == []
