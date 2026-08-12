#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

from f1_quote0.http import HTTPClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the current Quote/0 render without printing credentials.")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    api_key = os.environ["DOT_API_KEY"]
    device_id = os.environ["QUOTE0_DEVICE_ID"]
    headers = {"Authorization": f"Bearer {api_key}"}
    endpoint = f"https://dot.mindreset.tech/api/authV2/open/device/{quote(device_id, safe='')}/status"
    status = json.loads(HTTPClient().request(endpoint, headers=headers).decode("utf-8"))
    images = status.get("renderInfo", {}).get("current", {}).get("image") or []
    if not images or not str(images[0]).startswith("https://"):
        raise RuntimeError("设备状态中没有可下载的当前渲染图")

    content = HTTPClient().request(str(images[0]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(content)
    print(f"render_bytes={len(content)} sha256={hashlib.sha256(content).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
