#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

from f1_quote0.canvas import CanvasRenderer
from f1_quote0.config import Config, DASHBOARDS
from f1_quote0.f1 import F1Data


def main() -> int:
    config = Config.from_env()
    data = F1Data()
    data.refresh(config.driver_id, config.constructor_id)
    renderer = CanvasRenderer()
    for name in DASHBOARDS:
        payload = renderer.payload(
            data.dashboard(name),
            "validation",
            "F1 看板",
            config.nfc_link,
            config.refresh_now,
        )
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        image_count = 0

        def count_images(value: object) -> None:
            nonlocal image_count
            if isinstance(value, dict):
                if value.get("type") == "img":
                    image_count += 1
                for child in value.values():
                    count_images(child)
            elif isinstance(value, list):
                for child in value:
                    count_images(child)

        count_images(payload["windowData"])
        print(f"{name}\tpayload={len(encoded)}\timages={image_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
