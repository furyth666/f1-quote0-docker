from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(slots=True)
class State:
    status: str
    configured: bool
    push_verified: bool
    updated_at: str
    last_data_update_at: str | None
    last_push_at: str | None
    current_dashboard: str | None
    message: str
    selected_driver_id: str | None
    selected_constructor_id: str | None
    enabled_dashboards: list[str] | None = None


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)

    def write(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    def read(self) -> State:
        return State(**json.loads(self.path.read_text(encoding="utf-8")))

    def healthy(self) -> bool:
        try:
            state = self.read()
            updated = parse_timestamp(state.updated_at)
            data_updated = parse_timestamp(state.last_data_update_at)
            now = datetime.now(timezone.utc)
            return bool(
                state.status in {"ready", "waiting_for_configuration", "starting"}
                and updated and (now - updated).total_seconds() < 30
                and data_updated and (now - data_updated).total_seconds() < 900
            )
        except (OSError, ValueError, TypeError, KeyError):
            return False
