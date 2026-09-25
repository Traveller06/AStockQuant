"""Plan or execute a verified copy of AStockQuant v7 personal data."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from astock_quant.app.paths import AppPaths
from astock_quant.data.migration import MigrationService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_root", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    service = MigrationService(AppPaths.resolve(Path.cwd(), os.environ))
    plan = service.plan(args.legacy_root)
    print(plan.to_json(), end="")
    if args.execute:
        print(service.execute(plan).to_json(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
