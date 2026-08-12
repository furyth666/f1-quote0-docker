from __future__ import annotations

import concurrent.futures
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .http import HTTPClient


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return "".join(character.lower() for character in folded if character.isalnum())


def same_person(left: str, right: str) -> bool:
    def tokens(value: str) -> list[str]:
        folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        return [part.lower() for part in re.findall(r"[A-Za-z0-9]+", folded)]

    lhs, rhs = tokens(left), tokens(right)
    if not lhs or not rhs:
        return False
    if "".join(lhs) == "".join(rhs):
        return True
    if lhs[-1] != rhs[-1]:
        return False
    return any(
        left == right or left.startswith(right) or right.startswith(left)
        for left in lhs[:-1]
        for right in rhs[:-1]
    )


def same_team(left: str, right: str) -> bool:
    lhs, rhs = normalize(left), normalize(right)
    return bool(lhs and rhs and (lhs == rhs or lhs in rhs or rhs in lhs))


def competition_family(competition: dict[str, Any]) -> str:
    code = str(competition.get("type", {}).get("abbreviation", "")).upper()
    if code == "RACE":
        return "race"
    if code in {"SR", "SPRINT"}:
        return "sprint"
    if code in {"QUAL", "Q"}:
        return "qualifying"
    if code.startswith("FP") or code in {"P1", "P2", "P3"}:
        return "practice"
    if code in {"SS", "SQ", "SPRINT SHOOTOUT"}:
        return "sprintQualifying"
    return "other"


def competition_name(competition: dict[str, Any]) -> str:
    family = competition_family(competition)
    code = str(competition.get("type", {}).get("abbreviation", "")).upper()
    if family == "practice":
        return {"FP1": "第一次练习赛", "P1": "第一次练习赛", "FP2": "第二次练习赛", "P2": "第二次练习赛", "FP3": "第三次练习赛", "P3": "第三次练习赛"}.get(code, "练习赛")
    return {
        "qualifying": "排位赛",
        "sprintQualifying": "冲刺排位赛",
        "sprint": "冲刺赛",
        "race": "正赛",
    }.get(family, code)


def is_live(competition: dict[str, Any]) -> bool:
    return competition.get("status", {}).get("type", {}).get("state") == "in"


def is_complete(competition: dict[str, Any]) -> bool:
    status = competition.get("status", {}).get("type", {})
    return bool(status.get("completed") or status.get("state") == "post")


def competition_date(competition: dict[str, Any]) -> datetime:
    return parse_date(competition.get("date") or competition.get("startDate"))


def sorted_competitors(competition: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(competition.get("competitors") or [], key=lambda item: item.get("order", 999))


def clean_race_name(value: str) -> str:
    sponsors = (
        "Qatar Airways ", "Heineken ", "Aramco ", "Gulf Air ", "STC ",
        "Crypto.com ", "Lenovo ", "MSC Cruises ", "Pirelli ",
        "Moët & Chandon ", "AWS ", "Tag Heuer ", "Singapore Airlines ", "Etihad ",
    )
    for sponsor in sponsors:
        if value.startswith(sponsor):
            value = value[len(sponsor):]
            break
    return re.sub(r"\s+", " ", value.replace("Grand Prix", "GP")).strip()


def local_date(value: datetime, style: str) -> str:
    local = value.astimezone()
    weekdays = "一二三四五六日"
    if style == "date_time":
        return f"{local.month}月{local.day}日 {local:%H:%M}"
    if style == "date_weekday":
        return f"{local.month}月{local.day}日 周{weekdays[local.weekday()]}"
    if style == "weekday_time":
        return f"周{weekdays[local.weekday()]} {local:%H:%M}"
    if style == "date":
        return f"{local.month}月{local.day}日"
    return local.strftime("%H:%M")


class F1Data:
    def __init__(self, client: HTTPClient | None = None, year: int | None = None):
        self.http = client or HTTPClient()
        self.year = year or now_utc().year
        self.events: list[dict[str, Any]] = []
        self.drivers: list[dict[str, Any]] = []
        self.constructors: list[dict[str, Any]] = []
        self.selected_driver_id = ""
        self.selected_constructor_id = ""
        self.updated_at: datetime | None = None
        self.supplemental_results: dict[str, dict[str, dict[str, Any]]] = {}
        self.supplemental_numbers: dict[str, dict[str, int]] = {}

    @property
    def has_live_session(self) -> bool:
        return any(is_live(comp) for event in self.events for comp in event.get("competitions", []))

    def refresh(self, driver_id: str = "", constructor_id: str = "") -> None:
        sessions_url = f"https://api.openf1.org/v1/sessions?year={self.year}"
        meetings_url = f"https://api.openf1.org/v1/meetings?year={self.year}"
        driver_url = f"https://api.jolpi.ca/ergast/f1/{self.year}/driverstandings.json"
        constructor_url = f"https://api.jolpi.ca/ergast/f1/{self.year}/constructorstandings.json"

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            sessions_future = pool.submit(self.http.json, sessions_url)
            meetings_future = pool.submit(self.http.json, meetings_url)
            drivers_future = pool.submit(self.http.json, driver_url)
            constructors_future = pool.submit(self.http.json, constructor_url)
            sessions = sessions_future.result()
            meetings = meetings_future.result()
            try:
                auxiliary_drivers = self._jolpica_drivers(drivers_future.result())
            except Exception:
                auxiliary_drivers = self.drivers
            try:
                auxiliary_constructors = self._jolpica_constructors(constructors_future.result())
            except Exception:
                auxiliary_constructors = self.constructors

        self.events = self._openf1_events(meetings, sessions)
        self.drivers = auxiliary_drivers
        self.constructors = auxiliary_constructors
        self.selected_driver_id = driver_id if any(item["id"] == driver_id for item in self.drivers) else (self.drivers[0]["id"] if self.drivers else "")
        self.selected_constructor_id = constructor_id if any(item["id"] == constructor_id for item in self.constructors) else (self.constructors[0]["id"] if self.constructors else "")
        self._hydrate_openf1_results()
        self.updated_at = now_utc()

    def _openf1_events(
        self,
        meetings: list[dict[str, Any]],
        sessions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        meeting_by_key = {item.get("meeting_key"): item for item in meetings}
        events: dict[Any, dict[str, Any]] = {}
        current = now_utc()
        for session in sessions:
            meeting_key = session.get("meeting_key")
            meeting = meeting_by_key.get(meeting_key, {})
            start = parse_date(session.get("date_start"))
            end = parse_date(session.get("date_end"))
            if end == datetime.min.replace(tzinfo=timezone.utc):
                end = start
            state = "pre"
            completed = False
            if current > end:
                state, completed = "post", True
            elif start <= current <= end:
                state = "in"

            event = events.setdefault(meeting_key, {
                "id": str(meeting_key),
                "name": meeting.get("meeting_name") or meeting.get("meeting_official_name") or session.get("location", "F1"),
                "shortName": meeting.get("meeting_name") or session.get("location", "F1"),
                "date": session.get("date_start"),
                "circuit": {
                    "fullName": session.get("circuit_short_name") or meeting.get("circuit_short_name") or session.get("location", ""),
                    "address": {
                        "city": session.get("location", ""),
                        "country": session.get("country_name") or meeting.get("country_name", ""),
                    },
                },
                "competitions": [],
            })
            competition = {
                "id": str(session.get("session_key")),
                "date": session.get("date_start"),
                "endDate": session.get("date_end"),
                "type": {"abbreviation": self._openf1_abbreviation(session)},
                "status": {"period": None, "type": {"state": state, "completed": completed}},
                "competitors": [],
                "openf1": session,
            }
            event["competitions"].append(competition)
            if start < parse_date(event.get("date")):
                event["date"] = session.get("date_start")

        for event in events.values():
            event["competitions"].sort(key=competition_date)
        return sorted(events.values(), key=lambda item: parse_date(item.get("date")))

    @staticmethod
    def _openf1_abbreviation(session: dict[str, Any]) -> str:
        name = str(session.get("session_name", "")).lower()
        session_type = str(session.get("session_type", "")).lower()
        text = f"{name} {session_type}"
        if "sprint" in text and ("qualifying" in text or "shootout" in text):
            return "SQ"
        if "sprint" in text:
            return "SR"
        if "qualifying" in text:
            return "QUAL"
        if "practice" in text:
            match = re.search(r"([123])", name)
            return f"FP{match.group(1)}" if match else "FP"
        if "race" in text:
            return "RACE"
        return str(session.get("session_name", "")).upper()

    def _candidate_context(self, race_or_sprint_only: bool) -> tuple[dict[str, Any], dict[str, Any]] | None:
        eligible = [
            item for item in self._all_contexts()
            if competition_family(item[1]) in {"practice", "qualifying", "sprint", "race"}
            and (not race_or_sprint_only or competition_family(item[1]) in {"sprint", "race"})
            and competition_date(item[1]) <= now_utc()
        ]
        return max(eligible, key=lambda item: competition_date(item[1]), default=None)

    def _hydrate_openf1_results(self) -> None:
        targets = [item for item in (self._candidate_context(False), self._candidate_context(True)) if item]
        unique = {str(competition.get("id")): competition for _, competition in targets}
        for competition_id, competition in unique.items():
            session_key = competition.get("openf1", {}).get("session_key")
            if not session_key:
                continue
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                    drivers_future = pool.submit(self.http.json, f"https://api.openf1.org/v1/drivers?session_key={session_key}")
                    if is_live(competition):
                        positions_future = pool.submit(self.http.json, f"https://api.openf1.org/v1/position?session_key={session_key}")
                        laps_future = pool.submit(self.http.json, f"https://api.openf1.org/v1/laps?session_key={session_key}")
                        results = self._latest_positions(positions_future.result())
                        laps = laps_future.result()
                    else:
                        results_future = pool.submit(self.http.json, f"https://api.openf1.org/v1/session_result?session_key={session_key}")
                        results = results_future.result()
                        laps = []
                    drivers = drivers_future.result()
                driver_by_number = {item.get("driver_number"): item for item in drivers}
                competitors = []
                outcomes: dict[str, dict[str, Any]] = {}
                numbers: dict[str, int] = {}
                for result in sorted(results, key=lambda item: item.get("position") or 999):
                    number = result.get("driver_number")
                    driver = driver_by_number.get(number, {})
                    name = driver.get("full_name") or driver.get("broadcast_name") or driver.get("name_acronym") or f"#{number}"
                    competitors.append({
                        "id": str(number),
                        "order": int(result.get("position") or len(competitors) + 1),
                        "athlete": {
                            "displayName": name,
                            "shortName": driver.get("broadcast_name"),
                            "abbreviation": driver.get("name_acronym"),
                        },
                    })
                    for candidate in (name, driver.get("broadcast_name"), driver.get("name_acronym")):
                        if candidate:
                            outcomes[normalize(candidate)] = result
                            numbers[normalize(candidate)] = number
                competition["competitors"] = competitors
                self.supplemental_results[competition_id] = outcomes
                self.supplemental_numbers[competition_id] = numbers
                if laps:
                    competition["status"]["period"] = max((int(item.get("lap_number") or 0) for item in laps), default=0) or None
            except Exception:
                continue

    @staticmethod
    def _latest_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest: dict[Any, dict[str, Any]] = {}
        for position in positions:
            number = position.get("driver_number")
            if number is not None:
                latest[number] = position
        return list(latest.values())

    def _jolpica_list(self, payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
        lists = payload.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
        return lists[0].get(key, []) if lists else []

    def _jolpica_drivers(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        values = []
        for item in self._jolpica_list(payload, "DriverStandings"):
            driver = item.get("Driver", {})
            constructor = (item.get("Constructors") or [{}])[0]
            values.append({
                "id": driver.get("driverId", ""),
                "position": int(item.get("position", 0)),
                "points": str(item.get("points", "0")),
                "wins": str(item.get("wins", "0")),
                "number": driver.get("permanentNumber", ""),
                "code": driver.get("code", ""),
                "given": driver.get("givenName", ""),
                "family": driver.get("familyName", ""),
                "name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip(),
                "constructor_id": constructor.get("constructorId", ""),
                "constructor_name": constructor.get("name", ""),
            })
        return values

    def _jolpica_constructors(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        values = []
        for item in self._jolpica_list(payload, "ConstructorStandings"):
            constructor = item.get("Constructor", {})
            values.append({
                "id": constructor.get("constructorId", ""),
                "position": int(item.get("position", 0)),
                "points": str(item.get("points", "0")),
                "wins": str(item.get("wins", "0")),
                "name": constructor.get("name", ""),
            })
        return values

    def _all_contexts(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return [(event, comp) for event in self.events for comp in event.get("competitions", [])]

    def latest_context(self, race_or_sprint_only: bool) -> tuple[dict[str, Any], dict[str, Any]] | None:
        eligible = [
            item for item in self._all_contexts()
            if competition_family(item[1]) in {"practice", "qualifying", "sprint", "race"}
            and (not race_or_sprint_only or competition_family(item[1]) in {"sprint", "race"})
        ]
        live = sorted((item for item in eligible if is_live(item[1])), key=lambda item: competition_date(item[1]), reverse=True)
        if live:
            return live[0]
        complete = sorted(
            (item for item in eligible if is_complete(item[1]) and sorted_competitors(item[1])),
            key=lambda item: competition_date(item[1]),
            reverse=True,
        )
        return complete[0] if complete else None

    def _selected_driver(self) -> dict[str, Any] | None:
        return next((item for item in self.drivers if item["id"] == self.selected_driver_id), None)

    def _selected_constructor(self) -> dict[str, Any] | None:
        return next((item for item in self.constructors if item["id"] == self.selected_constructor_id), None)

    def _team_drivers(self) -> list[dict[str, Any]]:
        team = self._selected_constructor()
        return sorted((item for item in self.drivers if team and same_team(item["constructor_name"], team["name"])), key=lambda item: item["position"])

    def _standing_for_competitor(self, competitor: dict[str, Any]) -> dict[str, Any] | None:
        athlete = competitor.get("athlete", {})
        name, abbreviation = athlete.get("displayName", ""), athlete.get("abbreviation", "")
        return next((item for item in self.drivers if same_person(item["name"], name) or (item["code"] and item["code"].lower() == abbreviation.lower())), None)

    def _result_label(self, competitor: dict[str, Any], competition: dict[str, Any]) -> str:
        fallback = int(competitor.get("order", 0))
        if not is_complete(competition):
            return f"P{fallback}"
        result = self.supplemental_results.get(str(competition.get("id")), {}).get(normalize(competitor.get("athlete", {}).get("displayName", "")))
        if not result:
            return f"P{fallback}"
        if result.get("dns"):
            return "DNS"
        if result.get("dsq"):
            return "DSQ"
        if result.get("dnf"):
            return "DNF"
        return f"P{result.get('position') or fallback}"

    def dashboard(self, kind: str) -> dict[str, Any]:
        if kind == "latestAllSession":
            return self._result_dashboard(False)
        if kind == "latestRaceOrSprint":
            return self._result_dashboard(True)
        if kind == "nextSession":
            return self._next_session_dashboard()
        if kind == "countdown":
            return self._countdown_dashboard()
        if kind == "driverStanding":
            return self._driver_standing_dashboard()
        if kind in {"driverLatestAll", "driverLatestRaceOrSprint"}:
            return self._driver_result_dashboard(kind.endswith("RaceOrSprint"))
        if kind == "teamStanding":
            return self._team_standing_dashboard()
        if kind == "teamDriversStanding":
            return self._team_drivers_dashboard()
        if kind in {"teamLatestAll", "teamLatestRaceOrSprint"}:
            return self._team_result_dashboard(kind.endswith("RaceOrSprint"))
        return unavailable("未知看板", kind)

    def _result_dashboard(self, race_only: bool) -> dict[str, Any]:
        context = self.latest_context(race_only)
        if not context:
            return unavailable("暂无比赛结果", "当前没有可用赛段")
        event, competition = context
        rows = []
        for competitor in sorted_competitors(competition)[:3]:
            standing = self._standing_for_competitor(competitor)
            name = competitor.get("athlete", {}).get("displayName", "")
            number = standing.get("number", "") if standing else self.supplemental_numbers.get(str(competition.get("id")), {}).get(normalize(name), "")
            team = standing.get("constructor_name", "") if standing else ("Mercedes" if "antonelli" in normalize(name) else "")
            rows.append(row(self._result_label(competitor, competition), name, " · ".join(item for item in (f"#{number}" if number else "", compact_team(team)) if item)))
        lap = competition.get("status", {}).get("period")
        return panel(
            competition_name(competition),
            clean_race_name(event.get("shortName", event.get("name", ""))),
            local_date(competition_date(competition), "date_time"),
            (f"进行中 · 第 {lap} 圈" if lap else "进行中") if is_live(competition) else "最终排名",
            rows,
            decoration_asset="f1-mark.png",
        )

    def _next_session_dashboard(self) -> dict[str, Any]:
        current = now_utc()
        contexts = sorted(
            (
                (event, comp) for event, comp in self._all_contexts()
                if competition_family(comp) != "other" and (is_live(comp) or competition_date(comp) >= current)
            ),
            key=lambda item: competition_date(item[1]),
        )[:2]
        if not contexts:
            return unavailable("本赛季赛程已结束", "新赛历发布后会自动更新")
        rows = []
        for index, (event, competition) in enumerate(contexts):
            circuit = event.get("circuit", {})
            circuit_name = circuit.get("fullName") or circuit.get("address", {}).get("city", "")
            rows.append(row(
                "进行" if is_live(competition) else f"{index + 1:02}",
                clean_race_name(event.get("shortName", event.get("name", ""))),
                circuit_name,
                local_date(competition_date(competition), "time"),
                f"{competition_name(competition)} · {local_date(competition_date(competition), 'date_weekday')}",
            ))
        zone = datetime.now().astimezone().tzname() or "Local"
        return panel("比赛赛程", "接下来两场", "", zone, rows, decoration_asset="f1-mark.png")

    def _countdown_dashboard(self) -> dict[str, Any]:
        current = now_utc()
        contexts = sorted(
            ((event, comp) for event, comp in self._all_contexts() if competition_family(comp) == "race" and (is_live(comp) or competition_date(comp) >= current)),
            key=lambda item: competition_date(item[1]),
        )
        if not contexts:
            return unavailable("本赛季赛程已结束", "等待新赛历")
        event, competition = contexts[0]
        days = max(0, (competition_date(competition).astimezone().date() - datetime.now().astimezone().date()).days)
        circuit = event.get("circuit", {})
        circuit_name = circuit.get("fullName") or circuit.get("address", {}).get("city", "")
        return panel(
            "下一站正赛",
            "比赛中" if is_live(competition) else ("今天" if days == 0 else f"{days} 天"),
            clean_race_name(event.get("shortName", event.get("name", ""))),
            "进行中" if is_live(competition) else local_date(competition_date(competition), "date"),
            [],
            presentation="hero",
            detail_primary=circuit_name,
            detail_secondary=local_date(competition_date(competition), "weekday_time"),
            track_asset=track_asset(circuit_name, event.get("name", ""), circuit.get("address", {}).get("country", "")),
        )

    def _driver_standing_dashboard(self) -> dict[str, Any]:
        driver = self._selected_driver()
        if not driver:
            return unavailable("请选择关注车手", "设置 F1_DRIVER_ID")
        team = compact_team(driver["constructor_name"])
        meta = " · ".join(item for item in (f"#{driver['number']}" if driver["number"] else "", driver["name"], team) if item)
        return panel("车手积分", f"P{driver['position']}", meta, str(self.year), [], presentation="hero", hero_metric=driver["points"], detail_primary=driver["name"], detail_secondary=" · ".join(item for item in (f"#{driver['number']}" if driver["number"] else "", team) if item))

    def _driver_result_dashboard(self, race_only: bool) -> dict[str, Any]:
        driver, context = self._selected_driver(), self.latest_context(race_only)
        if not driver:
            return unavailable("请选择关注车手", "设置 F1_DRIVER_ID")
        if not context:
            return unavailable(driver["name"], "暂无可用比赛结果")
        event, competition = context
        competitor = next((item for item in sorted_competitors(competition) if same_person(item.get("athlete", {}).get("displayName", ""), driver["name"])), None)
        if not competitor:
            return unavailable(driver["name"], "最近赛段中没有该车手的排名")
        lap = competition.get("status", {}).get("period")
        return panel(
            competition_name(competition), driver["name"],
            f"{clean_race_name(event.get('shortName', ''))} · {local_date(competition_date(competition), 'date')}",
            (f"进行中 · 第 {lap} 圈" if lap else "进行中") if is_live(competition) else "最终结果",
            [row(self._result_label(competitor, competition), f"#{driver['number']}" if driver["number"] else "车手", compact_team(driver["constructor_name"]))],
            presentation="spotlight",
        )

    def _team_standing_dashboard(self) -> dict[str, Any]:
        team = self._selected_constructor()
        if not team:
            return unavailable("请选择关注车队", "设置 F1_CONSTRUCTOR_ID")
        name = compact_team(team["name"])
        return panel("车队积分", f"P{team['position']}", name, str(self.year), [], presentation="hero", hero_metric=team["points"], detail_primary=name, side_asset=team_logo(team["name"]))

    def _team_drivers_dashboard(self) -> dict[str, Any]:
        team = self._selected_constructor()
        if not team:
            return unavailable("请选择关注车队", "设置 F1_CONSTRUCTOR_ID")
        rows = [row(f"P{driver['position']}", driver["name"], f"#{driver['number']}" if driver["number"] else "", f"{driver['points']} 分") for driver in self._team_drivers()[:2]]
        return panel("车队车手排名", compact_team(team["name"]), "", str(self.year), rows, presentation="ranking")

    def _team_result_dashboard(self, race_only: bool) -> dict[str, Any]:
        team, context = self._selected_constructor(), self.latest_context(race_only)
        if not team:
            return unavailable("请选择关注车队", "设置 F1_CONSTRUCTOR_ID")
        if not context:
            return unavailable(team["name"], "暂无可用比赛结果")
        event, competition = context
        drivers = self._team_drivers()
        rows = []
        for competitor in sorted_competitors(competition):
            driver = next((item for item in drivers if same_person(item["name"], competitor.get("athlete", {}).get("displayName", ""))), None)
            if driver:
                rows.append(row(self._result_label(competitor, competition), driver["name"], f"#{driver['number']}" if driver["number"] else ""))
        lap = competition.get("status", {}).get("period")
        return panel(
            competition_name(competition), compact_team(team["name"]),
            f"{clean_race_name(event.get('shortName', ''))} · {local_date(competition_date(competition), 'date')}",
            (f"进行中 · 第 {lap} 圈" if lap else "进行中") if is_live(competition) else "最终结果",
            rows, presentation="ranking",
        )


def row(rank: str, primary: str, secondary: str = "", value: str = "", tertiary: str = "") -> dict[str, str]:
    return {"rank": rank, "primary": primary, "secondary": secondary, "tertiary": tertiary, "value": value}


def panel(
    eyebrow: str,
    title: str,
    subtitle: str,
    status: str,
    rows: list[dict[str, str]],
    *,
    presentation: str = "standard",
    hero_metric: str | None = None,
    detail_primary: str | None = None,
    detail_secondary: str | None = None,
    decoration_asset: str | None = None,
    side_asset: str | None = None,
    track_asset: str | None = None,
) -> dict[str, Any]:
    return {
        "eyebrow": eyebrow,
        "title": title,
        "subtitle": subtitle,
        "status": status,
        "rows": rows,
        "presentation": presentation,
        "hero_metric": hero_metric,
        "detail_primary": detail_primary,
        "detail_secondary": detail_secondary,
        "decoration_asset": decoration_asset,
        "side_asset": side_asset,
        "track_asset": track_asset,
    }


def unavailable(title: str, detail: str) -> dict[str, Any]:
    return panel("比赛数据", title, detail, "等待数据", [], presentation="hero")


TEAM_ASSETS = {
    "mercedes": ("mercedes.png", "Mercedes"),
    "ferrari": ("ferrari.png", "Ferrari"),
    "mclaren": ("mclaren.png", "McLaren"),
    "redbull": ("red-bull.png", "Red Bull"),
    "racingbulls": ("racing-bulls.png", "Racing Bulls"),
    "haas": ("haas.png", "Haas"),
    "alpine": ("alpine.png", "Alpine"),
    "renault": ("alpine.png", "Alpine"),
    "audi": ("audi.png", "Audi"),
    "sauber": ("audi.png", "Audi"),
    "williams": ("williams.png", "Williams"),
    "astonmartin": ("aston-martin.png", "Aston Martin"),
    "cadillac": ("cadillac.png", "Cadillac"),
}


def team_asset(team_name: str) -> tuple[str, str] | None:
    value = normalize(team_name)
    return next((asset for token, asset in TEAM_ASSETS.items() if token in value), None)


def compact_team(team_name: str) -> str:
    asset = team_asset(team_name)
    return asset[1] if asset else team_name


def team_logo(team_name: str) -> str | None:
    asset = team_asset(team_name)
    return asset[0] if asset else None


TRACK_ALIASES = {
    "melbourne": "track-melbourne.png", "albertpark": "track-melbourne.png",
    "shanghai": "track-shanghai.png", "suzuka": "track-suzuka.png",
    "sakhir": "track-sakhir.png", "bahrain": "track-sakhir.png",
    "jeddah": "track-jeddah.png", "miami": "track-miami.png",
    "montreal": "track-montreal.png", "gillesvilleneuve": "track-montreal.png",
    "monaco": "track-montecarlo.png", "montecarlo": "track-montecarlo.png",
    "catalunya": "track-catalunya.png", "spielberg": "track-spielberg.png",
    "redbullring": "track-spielberg.png", "silverstone": "track-silverstone.png",
    "spafrancorchamps": "track-spafrancorchamps.png", "hungaroring": "track-hungaroring.png",
    "zandvoort": "track-zandvoort.png", "monza": "track-monza.png",
    "madrid": "track-madring.png", "madring": "track-madring.png",
    "baku": "track-baku.png", "sepang": "track-kualalumpur.png",
    "kualalumpur": "track-kualalumpur.png", "marinabay": "track-singapore.png",
    "singapore": "track-singapore.png", "austin": "track-austin.png",
    "circuitoftheamericas": "track-austin.png", "mexicocity": "track-mexicocity.png",
    "hermanosrodriguez": "track-mexicocity.png", "interlagos": "track-interlagos.png",
    "josecarlospace": "track-interlagos.png", "lasvegas": "track-lasvegas.png",
    "lusail": "track-lusail.png", "losail": "track-lusail.png",
    "yasmarina": "track-yasmarina.png", "abudhabi": "track-yasmarina.png",
    "imola": "track-imola.png",
}


def track_asset(circuit_name: str, race_name: str, country_name: str) -> str | None:
    value = normalize(f"{circuit_name} {race_name} {country_name}")
    if any(token in value for token in ("sepang", "kualalumpur", "malaysia")):
        return "track-kualalumpur.png"
    return next((asset for token, asset in TRACK_ALIASES.items() if token in value), None)
