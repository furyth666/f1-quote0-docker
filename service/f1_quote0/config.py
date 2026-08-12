from __future__ import annotations

import os
from dataclasses import dataclass


DASHBOARDS = (
    "latestAllSession",
    "latestRaceOrSprint",
    "nextSession",
    "countdown",
    "driverStanding",
    "driverLatestAll",
    "driverLatestRaceOrSprint",
    "teamStanding",
    "teamDriversStanding",
    "teamLatestAll",
    "teamLatestRaceOrSprint",
)

DASHBOARD_TITLES = {
    "latestAllSession": "全部比赛结果",
    "latestRaceOrSprint": "冲刺赛 / 正赛结果",
    "nextSession": "下一场比赛时间",
    "countdown": "下一站倒数日",
    "driverStanding": "车手年度积分",
    "driverLatestAll": "车手比赛结果",
    "driverLatestRaceOrSprint": "车手冲刺赛 / 正赛结果",
    "teamStanding": "车队年度积分",
    "teamDriversStanding": "车队车手排名",
    "teamLatestAll": "车队比赛结果",
    "teamLatestRaceOrSprint": "车队冲刺赛 / 正赛结果",
}


def _dashboards(env: dict[str, str] | os._Environ[str]) -> tuple[str, ...]:
    single = env.get("F1_DASHBOARD", "").strip()
    raw = single or env.get("F1_DASHBOARDS", "latestAllSession,nextSession")
    requested: list[str] = []
    for value in raw.split(","):
        item = value.strip()
        if item.lower() == "all":
            return DASHBOARDS
        if item in DASHBOARDS and item not in requested:
            requested.append(item)
    return tuple(requested) or ("latestAllSession", "nextSession")


def _interval(value: str | None, default: int, minimum: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        parsed = default
    return max(parsed, minimum)


@dataclass(frozen=True, slots=True)
class Config:
    api_key: str
    device_id: str
    task_key: str
    task_alias: str
    driver_id: str
    constructor_id: str
    dashboards: tuple[str, ...]
    push_interval: int
    data_refresh_interval: int
    live_refresh_interval: int
    state_path: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.device_id)

    @classmethod
    def from_env(cls, environment: dict[str, str] | None = None) -> "Config":
        env = os.environ if environment is None else environment
        return cls(
            api_key=env.get("DOT_API_KEY", "").strip(),
            device_id=env.get("QUOTE0_DEVICE_ID", "").strip(),
            task_key=env.get("CANVAS_TASK_KEY", "").strip(),
            task_alias=env.get("CANVAS_TASK_ALIAS", "F1 看板").strip() or "F1 看板",
            driver_id=env.get("F1_DRIVER_ID", "").strip(),
            constructor_id=env.get("F1_CONSTRUCTOR_ID", "").strip(),
            dashboards=_dashboards(env),
            push_interval=_interval(env.get("PUSH_INTERVAL_SECONDS"), 300, 60),
            data_refresh_interval=_interval(env.get("DATA_REFRESH_SECONDS"), 180, 60),
            live_refresh_interval=_interval(env.get("LIVE_REFRESH_SECONDS"), 15, 15),
            state_path=env.get("STATE_PATH", "/data/status.json"),
        )
