from __future__ import annotations

import signal
import sys
import threading
import time
from datetime import datetime

from .canvas import CanvasClient
from .config import Config, DASHBOARDS, DASHBOARD_TITLES
from .f1 import F1Data
from .state import State, StateStore, timestamp


def main() -> int:
    config = Config.from_env()
    if "--list-dashboards" in sys.argv:
        for name in DASHBOARDS:
            print(f"{name}\t{DASHBOARD_TITLES[name]}")
        return 0
    state_store = StateStore(config.state_path)
    if "--healthcheck" in sys.argv:
        return 0 if state_store.healthy() else 1

    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    print("F1 Quote/0 Python service starting", flush=True)
    print(f"Dashboards: {','.join(config.dashboards)}", flush=True)
    print(f"Push interval: {config.push_interval}s; data refresh: {config.data_refresh_interval}s", flush=True)
    print(f"Canvas immediate refresh: {'enabled' if config.refresh_now else 'disabled'}", flush=True)
    if not config.configured:
        print("Waiting for DOT_API_KEY and QUOTE0_DEVICE_ID; F1 data checks remain active", flush=True)

    data = F1Data()
    canvas = CanvasClient(
        config.api_key,
        config.device_id,
        config.task_key,
        config.task_alias,
        config.nfc_link,
        config.refresh_now,
    )
    next_refresh = 0.0
    next_push = 0.0
    cursor = 0
    last_push_at: datetime | None = None
    current_dashboard: str | None = None
    last_error: str | None = None

    while not stop.is_set():
        monotonic = time.monotonic()
        if monotonic >= next_refresh:
            try:
                data.refresh(config.driver_id, config.constructor_id)
                last_error = None
                print(
                    f"Data refreshed: {len(data.events)} events; "
                    f"driver={data.selected_driver_id or '-'}; constructor={data.selected_constructor_id or '-'}",
                    flush=True,
                )
            except Exception as error:
                last_error = f"比赛数据更新失败：{error}"
                print(last_error, flush=True)
            interval = config.live_refresh_interval if data.has_live_session else config.data_refresh_interval
            next_refresh = time.monotonic() + interval

        if config.configured and data.updated_at and monotonic >= next_push:
            current_dashboard = config.dashboards[cursor % len(config.dashboards)]
            cursor += 1
            try:
                canvas.push(data.dashboard(current_dashboard))
                last_push_at = datetime.now().astimezone()
                last_error = None
                print(f"Push succeeded: {current_dashboard}", flush=True)
            except Exception as error:
                last_error = f"推送失败：{error}"
                print(last_error, flush=True)
            next_push = time.monotonic() + config.push_interval

        if last_error:
            service_status = "degraded"
            message = last_error
        elif not data.updated_at:
            service_status = "starting"
            message = "正在加载 F1 数据"
        elif not config.configured:
            service_status = "waiting_for_configuration"
            message = "F1 数据正常；等待 Dot API Key 与 Quote/0 设备 ID"
        elif not last_push_at:
            service_status = "starting"
            message = "F1 数据正常；等待首次推送验证"
        else:
            service_status = "ready"
            message = "F1 数据与 Quote/0 推送正常"

        try:
            state_store.write(State(
                status=service_status,
                configured=config.configured,
                push_verified=last_push_at is not None,
                updated_at=timestamp(),
                last_data_update_at=timestamp(data.updated_at) if data.updated_at else None,
                last_push_at=timestamp(last_push_at) if last_push_at else None,
                current_dashboard=current_dashboard,
                message=message,
                selected_driver_id=data.selected_driver_id or None,
                selected_constructor_id=data.selected_constructor_id or None,
                enabled_dashboards=list(config.dashboards),
            ))
        except Exception as error:
            print(f"State write failed: {error}", flush=True)
        stop.wait(5)

    print("F1 Quote/0 service stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
