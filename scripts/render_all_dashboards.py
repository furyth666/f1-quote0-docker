#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

from f1_quote0.canvas import Assets
from f1_quote0.config import Config, DASHBOARDS
from f1_quote0.f1 import F1Data
from f1_quote0.raster import DashboardRasterRenderer


def main() -> int:
    parser = argparse.ArgumentParser(description="Render every F1 dashboard with current normalized data.")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    config = Config.from_env()
    data = F1Data()
    data.refresh(config.driver_id, config.constructor_id)
    renderer = DashboardRasterRenderer(Assets())
    args.output.mkdir(parents=True, exist_ok=True)
    for name in DASHBOARDS:
        content = renderer.png(data.dashboard(name))
        target = args.output / f"{name}.png"
        target.write_bytes(content)
        print(f"{name}\t{len(content)}\t{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
