# AStockQuant v8.0 Phase 1 Foundation and Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clean, single Git project with typed core models, Windows-safe data paths, v7.6.3 inventory/migration, and auditable run storage without changing any strategy.

**Architecture:** Create a `src`-layout modular monolith. Pure core models sit below file/network/UI code; migration copies and verifies legacy files into `%LOCALAPPDATA%\AStockQuant`; every mutation is atomic and rollback-safe.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, hashlib, json, shutil, pytest for development, existing pandas/NumPy/PySide6 runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-v8-modular-refactor-design.md`

## Global Constraints

- AStockQuant v7.6.3 is the behavioral baseline; its 63 existing tests pass before work begins.
- Do not alter, move, rename, or delete `astock_quant_v7_6` or any user cache/state file.
- Program files target `C:\AStockQuant`; personal data target `%LOCALAPPDATA%\AStockQuant`.
- Migration copies, hashes, verifies, and atomically promotes data; it never deletes legacy data.
- v8.0 must not connect to a real broker, install `xtquant`, or submit a real order.
- Production modules use explicit typed models and interfaces; `core` imports neither PySide6 nor network libraries.
- Every task starts with a failing test, ends with focused tests passing, and creates one reviewable commit.
- The new repository contains no personal cache, account, sample, state, or run output.

## Execution Root and Phase Gate

Create a new sibling directory named `astock_quant`. Do not initialize the workspace root or the legacy directory as Git repositories. All paths below are relative to `astock_quant/` unless explicitly prefixed with `../astock_quant_v7_6`.

Phase 1 is complete only when a fresh environment can import the package, inventory a copied v7 directory, migrate it twice without duplication, roll back an interrupted migration, and create/reopen a run manifest.

---

### Task 1: Create the clean project and record the legacy baseline

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `src/astock_quant/__init__.py`
- Create: `src/astock_quant/app/__init__.py`
- Create: `src/astock_quant/app/bootstrap.py`
- Create: `tests/test_package_smoke.py`
- Create: `docs/superpowers/specs/2026-09-12-v8-modular-refactor-design.md`
- Create: `docs/superpowers/plans/2026-09-12-v8-phase1-foundation-migration.md`

**Interfaces:**
- Consumes: approved v8 design and the read-only legacy source at `../astock_quant_v7_6`.
- Produces: importable package `astock_quant`, `astock_quant.__version__ == "8.0.0"`, and `create_application()` bootstrap placeholder.

- [ ] **Step 1: Verify and record the legacy baseline**

Run:

```bash
python -m unittest discover -s ../astock_quant_v7_6 -p 'test_*.py' -v
```

Expected: `Ran 63 tests` and `OK`. Save the command and result in the first commit message body; do not copy caches into the new repository.

- [ ] **Step 2: Initialize only the clean repository**

Run from the shared workspace:

```bash
mkdir astock_quant
cd astock_quant
git init -b main
```

Expected: an empty Git repository whose top level is `astock_quant`.

- [ ] **Step 3: Write the failing package smoke test**

```python
# tests/test_package_smoke.py
from astock_quant import __version__
from astock_quant.app.bootstrap import create_application


def test_package_version_and_bootstrap_contract():
    assert __version__ == "8.0.0"
    assert callable(create_application)
```

- [ ] **Step 4: Run the smoke test and confirm the expected failure**

Run:

```bash
python -m pytest tests/test_package_smoke.py -q
```

Expected: FAIL because `astock_quant` does not exist.

- [ ] **Step 5: Add packaging, bootstrap, and ignore rules**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "astock-quant"
version = "8.0.0"
requires-python = ">=3.10"
dependencies = [
  "PySide6>=6.8",
  "pyqtgraph>=0.13",
  "pandas>=2.2.3",
  "numpy>=2.0",
  "requests>=2.32",
  "akshare>=1.17",
  "baostock>=0.8.9",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-cov>=6", "pytest-qt>=4.4"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# src/astock_quant/__init__.py
__version__ = "8.0.0"
```

```python
# src/astock_quant/app/bootstrap.py
def create_application():
    """Build the application graph. Concrete wiring arrives in later phases."""
    return None
```

`.gitignore` must contain these exact categories:

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
build/
dist/
*.egg-info/
.idea/
.vscode/
data/
market/
state/
research/
runs/
reports/
logs/
cache/
tail_strategy_cache/
*.zip
paper_account.json
tail_strategy_state.json
research_sample.json
validation_snapshot_v1.json.gz
```

Copy the approved spec and this plan into the exact documentation paths listed above; do not copy other legacy release notes.

- [ ] **Step 6: Install editable development dependencies and pass the test**

Run:

```bash
python -m pip install -e '.[dev]'
python -m pytest tests/test_package_smoke.py -q
```

Expected: one test passes.

- [ ] **Step 7: Commit the clean baseline**

```bash
git add .gitignore pyproject.toml src tests docs
git commit -m "chore: initialize modular v8 project"
```

---

### Task 2: Define pure core types and domain errors

**Files:**
- Create: `src/astock_quant/core/__init__.py`
- Create: `src/astock_quant/core/enums.py`
- Create: `src/astock_quant/core/models.py`
- Create: `src/astock_quant/core/errors.py`
- Test: `tests/unit/core/test_models.py`
- Test: `tests/unit/core/test_errors.py`

**Interfaces:**
- Consumes: Python standard library only.
- Produces: `Market`, `Side`, `OrderStatus`, `RunStatus`, `DataHealth`, `Instrument`, `Bar`, `QuoteSnapshot`, `Signal`, `Order`, `Trade`, `Position`, `AccountSnapshot`, `RunManifest`, and `AStockQuantError` subclasses.

- [ ] **Step 1: Write failing enum and model tests**

```python
# tests/unit/core/test_models.py
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock_quant.core.enums import Market, OrderStatus, Side
from astock_quant.core.models import Bar, Order


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_bar_rejects_naive_timestamp_and_invalid_ohlc():
    with pytest.raises(ValueError, match="timezone-aware"):
        Bar("600000", datetime(2026, 9, 12, 14, 55), 10, 11, 9, 10.5, 100, 1050, "fixture")
    with pytest.raises(ValueError, match="OHLC"):
        Bar("600000", datetime(2026, 9, 12, 14, 55, tzinfo=SHANGHAI), 10, 9, 11, 10.5, 100, 1050, "fixture")


def test_order_has_explicit_initial_state():
    order = Order.new("run-1", "paper", "600000", Market.SSE, Side.BUY, 100, 10.2)
    assert order.status is OrderStatus.NEW
    assert order.quantity == 100
```

```python
# tests/unit/core/test_errors.py
from astock_quant.core.errors import DataIncompleteError


def test_domain_error_exposes_user_safe_context():
    error = DataIncompleteError(stage="strict_300", scope="600000", source="cache", detail="missing close")
    assert error.user_context() == {
        "category": "data_incomplete",
        "stage": "strict_300",
        "scope": "600000",
        "source": "cache",
        "detail": "missing close",
    }
```

- [ ] **Step 2: Run tests and confirm imports fail**

Run:

```bash
python -m pytest tests/unit/core -q
```

Expected: collection fails because `astock_quant.core` is missing.

- [ ] **Step 3: Implement enums and immutable models**

Use string enums with these exact values:

```python
class Market(str, Enum):
    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    NEW = "new"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RunStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    COMPLETED = "completed"


class DataHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    INCOMPLETE = "incomplete"
```

Implement frozen dataclasses. `Bar` validates timezone awareness, non-negative volume/amount, positive OHLC, and `low <= min(open, close) <= max(open, close) <= high`. `Order.new(...)` creates a UUID-backed order with `NEW` status and requires positive price, positive quantity, and quantity divisible by 100 for A-share stock orders.

`Order` fields are `order_id`, `source_run_id`, `broker_id`, `code`, `market`, `side`, `quantity`, `limit_price`, `status`, `created_at`, and `filled_quantity`. `Trade` fields are `trade_id`, `order_id`, `source_run_id`, `broker_id`, `code`, `side`, `quantity`, `price`, `commission`, `stamp_tax`, `slippage`, and `traded_at`. `Order.new(source_run_id, broker_id, code, market, side, quantity, limit_price)` fills the identity, timestamp, `NEW` status, and zero filled quantity.

`RunManifest` fields are exactly:

```python
@dataclass(frozen=True)
class RunManifest:
    run_id: str
    app_version: str
    strategy_id: str
    strategy_version: str
    parameters: Mapping[str, JSONValue]
    sample_sha256: str
    data_cutoff: str
    data_sha256: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    errors: tuple[Mapping[str, JSONValue], ...] = ()
```

- [ ] **Step 4: Implement typed domain errors**

Create `AStockQuantError` with `category`, `stage`, `scope`, `source`, `detail`, and `user_context()`. Add concrete subclasses with fixed categories: `NetworkDataError`, `DataIncompleteError`, `DataCorruptionError`, `ConfigurationError`, `StrategyInputError`, `MatchingConstraintError`, `MigrationError`, and `InternalApplicationError`.

- [ ] **Step 5: Run core tests and import-boundary check**

Run:

```bash
python -m pytest tests/unit/core -q
python - <<'PY'
import ast
from pathlib import Path
for path in Path('src/astock_quant/core').glob('*.py'):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {node.names[0].name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
    assert not ({'PySide6', 'requests', 'akshare', 'baostock'} & names), (path, names)
PY
```

Expected: all tests and boundary assertions pass.

- [ ] **Step 6: Commit core contracts**

```bash
git add src/astock_quant/core tests/unit/core
git commit -m "feat: define typed trading core contracts"
```

---

### Task 3: Separate program paths, data paths, and settings

**Files:**
- Create: `src/astock_quant/app/paths.py`
- Create: `src/astock_quant/app/settings.py`
- Test: `tests/unit/app/test_paths.py`
- Test: `tests/unit/app/test_settings.py`

**Interfaces:**
- Consumes: `ConfigurationError`.
- Produces: `AppPaths.resolve(program_dir, env)`, `AppPaths.ensure_data_tree()`, `Settings.load(path)`, and `Settings.save(path)`.

- [ ] **Step 1: Write failing path resolution tests**

```python
def test_windows_data_root_uses_localappdata(tmp_path):
    paths = AppPaths.resolve(program_dir=tmp_path / "program", env={"LOCALAPPDATA": str(tmp_path / "local")})
    assert paths.program_root == tmp_path / "program"
    assert paths.data_root == tmp_path / "local" / "AStockQuant"
    assert paths.market == paths.data_root / "market"
    assert paths.runs == paths.data_root / "runs"


def test_explicit_test_override_wins(tmp_path):
    paths = AppPaths.resolve(tmp_path / "program", {"ASTOCK_QUANT_DATA_DIR": str(tmp_path / "override")})
    assert paths.data_root == tmp_path / "override"
```

- [ ] **Step 2: Run path tests and verify failure**

```bash
python -m pytest tests/unit/app/test_paths.py -q
```

Expected: FAIL because `AppPaths` is undefined.

- [ ] **Step 3: Implement `AppPaths` without import-time directory creation**

`AppPaths` is a frozen dataclass with `program_root`, `data_root`, `market`, `state`, `research`, `runs`, `reports`, `logs`, `settings_file`, and `manifest_file`. `resolve()` uses `ASTOCK_QUANT_DATA_DIR` only as an explicit testing/portable override; otherwise it requires `LOCALAPPDATA` and appends `AStockQuant`. `ensure_data_tree()` creates only the data subdirectories and never writes under `program_root`.

- [ ] **Step 4: Write settings round-trip and corruption tests**

```python
def test_settings_round_trip_is_atomic(tmp_path):
    target = tmp_path / "settings.json"
    settings = Settings(schema_version=1, active_data_provider="eastmoney", real_trading_enabled=False)
    settings.save(target)
    assert Settings.load(target) == settings
    assert not target.with_suffix(".json.tmp").exists()


def test_settings_cannot_enable_real_trading_in_v8(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text('{"schema_version":1,"active_data_provider":"eastmoney","real_trading_enabled":true}', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="real trading is disabled"):
        Settings.load(target)
```

- [ ] **Step 5: Implement settings with an explicit schema and atomic replace**

Use this public model:

```python
@dataclass(frozen=True)
class Settings:
    schema_version: int = 1
    active_data_provider: str = "eastmoney"
    real_trading_enabled: bool = False

    @classmethod
    def load(cls, path: Path) -> "Settings": ...
    def save(self, path: Path) -> None: ...
```

`save()` writes UTF-8 JSON to a sibling temporary file, flushes and `os.fsync()`s it, then calls `os.replace()`. `load()` rejects unknown schema versions and any true `real_trading_enabled` value.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest tests/unit/app -q
git add src/astock_quant/app tests/unit/app
git commit -m "feat: separate program and personal data paths"
```

---

### Task 4: Inventory legacy v7 artifacts without mutating them

**Files:**
- Create: `src/astock_quant/compatibility/__init__.py`
- Create: `src/astock_quant/compatibility/legacy_v7.py`
- Create: `tests/unit/compatibility/test_legacy_inventory.py`

**Interfaces:**
- Consumes: `AppPaths`, `MigrationError`.
- Produces: `LegacyArtifact`, `LegacyInventory`, `discover_legacy(root)`, and `sha256_path(path)`.

- [ ] **Step 1: Write a failing deterministic inventory test**

```python
def test_inventory_finds_only_approved_legacy_artifacts(tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "600000.csv").write_text("date,close\n2026-09-11,10\n", encoding="utf-8")
    (tmp_path / "research_sample.json").write_text('{"stocks":[]}', encoding="utf-8")
    (tmp_path / "unknown.txt").write_text("ignore", encoding="utf-8")

    inventory = discover_legacy(tmp_path)

    assert [item.relative_path for item in inventory.artifacts] == ["cache", "research_sample.json"]
    assert inventory.legacy_root == tmp_path
    assert inventory.aggregate_sha256 == inventory.recalculate_sha256()
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/unit/compatibility/test_legacy_inventory.py -q
```

Expected: FAIL because the compatibility package is missing.

- [ ] **Step 3: Implement the approved artifact allowlist**

Use this exact allowlist:

```python
LEGACY_ARTIFACTS = (
    "cache",
    "tail_strategy_cache",
    "research_sample.json",
    "validation_snapshot_v1.json.gz",
    "research_data_checkpoint.json",
    "watchlist.json",
    "paper_account.json",
    "tail_strategy_state.json",
)
```

`sha256_path()` hashes a file directly. For a directory, it walks files in sorted relative-path order and hashes each relative path, a NUL byte, its size, a NUL byte, and its content. Symlinks are rejected with `MigrationError`. Inventory returns only existing allowlisted entries and records kind, byte size, file count, modified time, and SHA-256.

- [ ] **Step 4: Add no-mutation and repeatability tests**

Create a test that snapshots `(relative path, bytes, mtime_ns)` before and after two inventory calls and asserts equality. Add a symlink test when the platform supports symlinks.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/unit/compatibility/test_legacy_inventory.py -q
git add src/astock_quant/compatibility tests/unit/compatibility
git commit -m "feat: inventory legacy v7 data safely"
```

---

### Task 5: Implement copy-verify-promote migration and rollback

**Files:**
- Create: `src/astock_quant/data/__init__.py`
- Create: `src/astock_quant/data/migration.py`
- Create: `scripts/migrate_v7.py`
- Test: `tests/unit/data/test_migration.py`
- Test: `tests/integration/test_legacy_migration.py`

**Interfaces:**
- Consumes: `AppPaths`, `LegacyInventory`, `sha256_path`, `MigrationError`.
- Produces: `MigrationPlan`, `MigrationResult`, `MigrationService.plan()`, `execute()`, and `rollback()` plus a dry-run CLI.

- [ ] **Step 1: Write failing copy and idempotence tests**

```python
def test_migration_copies_verifies_and_keeps_legacy(tmp_path):
    legacy = build_legacy_fixture(tmp_path / "legacy")
    paths = build_paths(tmp_path / "new")
    service = MigrationService(paths)

    result = service.execute(service.plan(legacy))

    assert result.status == "completed"
    assert (legacy / "cache" / "600000.csv").exists()
    assert (paths.market / "legacy_daily" / "600000.csv").read_bytes() == (legacy / "cache" / "600000.csv").read_bytes()
    assert service.execute(service.plan(legacy)).status == "already_migrated"
```

- [ ] **Step 2: Write failing interruption rollback test**

Inject a copier that raises after the first file. Assert that no promoted destination exists, the staging directory is removed by `rollback()`, and every legacy byte and mtime remains unchanged.

- [ ] **Step 3: Run migration tests and verify failure**

```bash
python -m pytest tests/unit/data/test_migration.py tests/integration/test_legacy_migration.py -q
```

Expected: FAIL because `MigrationService` does not exist.

- [ ] **Step 4: Implement explicit destination mapping**

Use this mapping:

```python
DESTINATIONS = {
    "cache": Path("market/legacy_daily"),
    "tail_strategy_cache": Path("market/tail_strategy_cache"),
    "research_sample.json": Path("research/research_sample.json"),
    "validation_snapshot_v1.json.gz": Path("research/validation_snapshot_v1.json.gz"),
    "research_data_checkpoint.json": Path("state/research_data_checkpoint.json"),
    "watchlist.json": Path("state/watchlist.json"),
    "paper_account.json": Path("state/paper_account.json"),
    "tail_strategy_state.json": Path("state/tail_strategy_state.json"),
}
```

`plan()` creates a deterministic migration ID from the legacy aggregate hash and schema version. `execute()` copies the complete mapped tree into `data_root.parent/.AStockQuant-migration-<migration_id>`, verifies every artifact SHA-256, and writes `migration_manifest.json` inside that tree. For the first migration, `data_root` must not exist; one `os.replace(staging_root, data_root)` promotes the whole verified tree atomically. If `data_root` already exists with the same completed migration manifest, return `already_migrated`; if it exists without that exact manifest, abort without overwrite. `rollback()` removes only the resolved staging directory after confirming its name and parent; it never targets `data_root` or `legacy_root`.

- [ ] **Step 5: Implement dry-run CLI with no default write**

```python
# scripts/migrate_v7.py
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_root", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    service = MigrationService(AppPaths.resolve(Path.cwd(), os.environ))
    plan = service.plan(args.legacy_root)
    print(plan.to_json())
    if args.execute:
        print(service.execute(plan).to_json())
    return 0
```

Running without `--execute` must only print the plan.

- [ ] **Step 6: Run migration tests, CLI dry run, and commit**

```bash
python -m pytest tests/unit/data/test_migration.py tests/integration/test_legacy_migration.py -q
python scripts/migrate_v7.py ../astock_quant_v7_6
git add src/astock_quant/data src/astock_quant/compatibility scripts tests/unit/data tests/integration/test_legacy_migration.py
git commit -m "feat: migrate v7 data with verification and rollback"
```

Expected: tests pass; the dry run lists artifacts but does not create or change legacy files.

---

### Task 6: Add auditable run storage with completion markers

**Files:**
- Create: `src/astock_quant/reports/__init__.py`
- Create: `src/astock_quant/reports/run_store.py`
- Test: `tests/unit/reports/test_run_store.py`

**Interfaces:**
- Consumes: `RunManifest`, `RunStatus`, `AppPaths.runs`.
- Produces: `RunStore.start(manifest)`, `write_json()`, `write_table()`, `finish()`, `open_completed()`, and `list_recent()`.

- [ ] **Step 1: Write failing completion and incomplete-run tests**

```python
def test_only_finished_run_can_be_opened_as_completed(tmp_path):
    store = RunStore(tmp_path)
    manifest = fixture_manifest(run_id="run-001", status=RunStatus.RUNNING)
    store.start(manifest)
    with pytest.raises(DataIncompleteError, match="completion marker"):
        store.open_completed("run-001")

    store.write_json("run-001", "parameters.json", {"initial": 100000})
    store.finish("run-001", RunStatus.COMPLETED)
    reopened = store.open_completed("run-001")
    assert reopened.manifest.status is RunStatus.COMPLETED
    assert reopened.path.joinpath("_COMPLETE").exists()
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/unit/reports/test_run_store.py -q
```

Expected: FAIL because `RunStore` is missing.

- [ ] **Step 3: Implement atomic run writes**

`start()` creates `runs/<run_id>/manifest.json` with `RUNNING` status and rejects duplicate active IDs. `write_json()` and `write_table()` write via sibling temporary files and `os.replace()`. `finish()` rewrites the manifest with a terminal status and creates `_COMPLETE` last only for `COMPLETED` or `INCOMPLETE`. `FAILED` runs keep their evidence but do not receive `_COMPLETE`.

`open_completed()` requires `_COMPLETE`, parses the manifest, verifies the manifest run ID matches the directory, and rejects `RUNNING`, `PAUSED`, or `FAILED` status.

- [ ] **Step 4: Add path traversal and redaction tests**

Assert that output names containing `..`, absolute paths, or path separators are rejected. Assert that JSON values under keys `password`, `account_password`, `token`, and `secret` are replaced with `"<redacted>"` before writing.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/unit/reports/test_run_store.py -q
git add src/astock_quant/reports tests/unit/reports
git commit -m "feat: add atomic auditable run storage"
```

---

### Task 7: Wire the phase-1 application context and enforce boundaries

**Files:**
- Modify: `src/astock_quant/app/bootstrap.py`
- Create: `src/astock_quant/app/context.py`
- Create: `tests/integration/test_phase1_bootstrap.py`
- Create: `tests/contracts/test_import_boundaries.py`
- Create: `docs/phase1-verification.md`

**Interfaces:**
- Consumes: `AppPaths`, `Settings`, `MigrationService`, `RunStore`.
- Produces: immutable `ApplicationContext` and `create_application(program_dir, env, ensure_data=False)`.

- [ ] **Step 1: Write failing context construction test**

```python
def test_bootstrap_constructs_services_without_touching_disk(tmp_path):
    context = create_application(
        program_dir=tmp_path / "program",
        env={"ASTOCK_QUANT_DATA_DIR": str(tmp_path / "data")},
        ensure_data=False,
    )
    assert context.paths.data_root == tmp_path / "data"
    assert isinstance(context.migration, MigrationService)
    assert isinstance(context.run_store, RunStore)
    assert not context.paths.data_root.exists()
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/integration/test_phase1_bootstrap.py -q
```

Expected: FAIL because bootstrap still returns `None`.

- [ ] **Step 3: Implement the immutable application context**

```python
@dataclass(frozen=True)
class ApplicationContext:
    paths: AppPaths
    settings: Settings
    migration: MigrationService
    run_store: RunStore
```

`create_application()` resolves paths and returns services. With `ensure_data=True`, it creates the data tree and an absent default settings file. With `ensure_data=False`, it performs no writes.

- [ ] **Step 4: Add architecture tests**

Parse imports under `src/astock_quant/core` and reject `PySide6`, `requests`, `akshare`, and `baostock`. Parse imports under `src/astock_quant/ui` when it exists and later reject imports from concrete `data.providers`; the UI must depend on services only. Fail if any source module imports `astock_quant_v7_6`.

- [ ] **Step 5: Run the complete phase gate**

```bash
python -m pytest tests/unit tests/contracts tests/integration -q
python -m unittest discover -s ../astock_quant_v7_6 -p 'test_*.py' -q
git status --short
```

Expected: all new tests pass; legacy reports `Ran 63 tests ... OK`; Git status contains only the verification note before commit.

- [ ] **Step 6: Write verification evidence and commit**

Record exact commands, test counts, platform, Python version, and the fact that the legacy directory hash was unchanged in `docs/phase1-verification.md`.

```bash
git add src tests docs/phase1-verification.md
git commit -m "feat: complete v8 foundation and migration phase"
```

Tagging is deferred until all four phases pass. Do not create a release from Phase 1.
