from __future__ import annotations

import json
import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from f1_quote0.canvas import CanvasClient, CanvasContractError, CanvasRenderer, Assets
from f1_quote0.config import Config, DASHBOARDS
from f1_quote0.f1 import F1Data, competition_family, same_person, track_asset
from f1_quote0 import raster


def sample_dashboard() -> dict:
    return {
        "eyebrow": "正赛",
        "title": "英国 GP",
        "subtitle": "8月12日 20:00",
        "status": "最终排名",
        "rows": [
            {"rank": "P1", "primary": "Lando Norris", "secondary": "#4 · McLaren", "tertiary": "", "value": ""},
            {"rank": "P2", "primary": "Oscar Piastri", "secondary": "#81 · McLaren", "tertiary": "", "value": ""},
            {"rank": "P3", "primary": "George Russell", "secondary": "#63 · Mercedes", "tertiary": "", "value": ""},
        ],
        "presentation": "standard",
        "hero_metric": None,
        "detail_primary": None,
        "detail_secondary": None,
        "decoration_asset": None,
        "side_asset": None,
        "track_asset": None,
    }


class ConfigTests(unittest.TestCase):
    def test_invalid_dashboard_names_fall_back_to_safe_defaults(self) -> None:
        config = Config.from_env({"F1_DASHBOARDS": "bad,alsoBad", "PUSH_INTERVAL_SECONDS": "1"})
        self.assertEqual(config.dashboards, ("latestAllSession", "nextSession"))
        self.assertEqual(config.push_interval, 60)
        self.assertFalse(config.configured)

    def test_single_dashboard_overrides_rotation(self) -> None:
        config = Config.from_env({
            "F1_DASHBOARD": "driverStanding",
            "F1_DASHBOARDS": "latestAllSession,nextSession",
        })
        self.assertEqual(config.dashboards, ("driverStanding",))

    def test_all_dashboard_alias_enables_upstream_order(self) -> None:
        config = Config.from_env({"F1_DASHBOARD": "all"})
        self.assertEqual(config.dashboards, DASHBOARDS)

    def test_rotation_deduplicates_and_keeps_declared_order(self) -> None:
        config = Config.from_env({
            "F1_DASHBOARDS": "countdown,latestAllSession,countdown,bad,nextSession",
        })
        self.assertEqual(config.dashboards, ("countdown", "latestAllSession", "nextSession"))


class F1LogicTests(unittest.TestCase):
    def test_driver_name_matching_handles_accents_and_middle_names(self) -> None:
        self.assertTrue(same_person("Gabriel Bortoleto", "G. Bortoleto"))
        self.assertTrue(same_person("Nico Hülkenberg", "Nico Hulkenberg"))
        self.assertFalse(same_person("Lando Norris", "George Russell"))

    def test_competition_family_mapping(self) -> None:
        self.assertEqual(competition_family({"type": {"abbreviation": "RACE"}}), "race")
        self.assertEqual(competition_family({"type": {"abbreviation": "SQ"}}), "sprintQualifying")
        self.assertEqual(competition_family({"type": {"abbreviation": "FP2"}}), "practice")

    def test_track_asset_mapping(self) -> None:
        self.assertEqual(track_asset("Suzuka International Racing Course", "Japanese GP", "Japan"), "track-suzuka.png")
        self.assertEqual(track_asset("Sepang International Circuit", "Bahrain GP in Malaysia", "Malaysia"), "track-kualalumpur.png")

    def test_dashboard_is_built_from_normalized_provider_shape(self) -> None:
        data = F1Data(year=2026)
        data.events = [{
            "id": "event",
            "name": "British Grand Prix",
            "shortName": "British Grand Prix",
            "date": "2026-07-05T14:00:00Z",
            "competitions": [{
                "id": "race",
                "date": "2026-07-05T14:00:00Z",
                "type": {"abbreviation": "RACE"},
                "status": {"period": 52, "type": {"state": "post", "completed": True}},
                "competitors": [{"order": 1, "athlete": {"displayName": "Lando Norris", "abbreviation": "NOR"}}],
            }],
        }]
        data.drivers = [{"id": "norris", "name": "Lando Norris", "code": "NOR", "number": "4", "constructor_name": "McLaren"}]
        dashboard = data.dashboard("latestRaceOrSprint")
        self.assertEqual(dashboard["rows"][0]["rank"], "P1")
        self.assertIn("McLaren", dashboard["rows"][0]["secondary"])

    def test_all_upstream_dashboard_kinds_build_from_normalized_data(self) -> None:
        data = F1Data(year=2026)
        completed = {
            "id": "race-complete",
            "date": "2026-07-05T14:00:00Z",
            "type": {"abbreviation": "RACE"},
            "status": {"period": 52, "type": {"state": "post", "completed": True}},
            "competitors": [
                {"order": 1, "athlete": {"displayName": "Lando Norris", "abbreviation": "NOR"}},
                {"order": 2, "athlete": {"displayName": "Oscar Piastri", "abbreviation": "PIA"}},
                {"order": 3, "athlete": {"displayName": "George Russell", "abbreviation": "RUS"}},
            ],
        }
        future = {
            "id": "race-future",
            "date": "2099-08-23T13:00:00Z",
            "type": {"abbreviation": "RACE"},
            "status": {"period": None, "type": {"state": "pre", "completed": False}},
            "competitors": [],
        }
        data.events = [
            {
                "id": "completed",
                "name": "British Grand Prix",
                "shortName": "British Grand Prix",
                "date": completed["date"],
                "circuit": {"fullName": "Silverstone Circuit", "address": {"country": "United Kingdom"}},
                "competitions": [completed],
            },
            {
                "id": "future",
                "name": "Dutch Grand Prix",
                "shortName": "Dutch Grand Prix",
                "date": future["date"],
                "circuit": {"fullName": "Circuit Park Zandvoort", "address": {"country": "Netherlands"}},
                "competitions": [future],
            },
        ]
        data.drivers = [
            {"id": "norris", "name": "Lando Norris", "code": "NOR", "number": "4", "position": 1, "points": "299", "constructor_name": "McLaren"},
            {"id": "piastri", "name": "Oscar Piastri", "code": "PIA", "number": "81", "position": 2, "points": "271", "constructor_name": "McLaren"},
            {"id": "russell", "name": "George Russell", "code": "RUS", "number": "63", "position": 3, "points": "220", "constructor_name": "Mercedes"},
        ]
        data.constructors = [
            {"id": "mclaren", "name": "McLaren", "position": 1, "points": "570", "wins": "9"},
        ]
        data.selected_driver_id = "norris"
        data.selected_constructor_id = "mclaren"

        for kind in DASHBOARDS:
            with self.subTest(kind=kind):
                dashboard = data.dashboard(kind)
                self.assertTrue(dashboard["eyebrow"])
                self.assertTrue(dashboard["title"])
                self.assertNotEqual(dashboard["title"], "未知看板")


class CanvasTests(unittest.TestCase):
    def test_default_assets_use_standalone_assets_directory(self) -> None:
        path = Assets().path("track-zandvoort.png")
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.parent.name, "assets")

    def test_task_discovery_prefers_configured_canvas(self) -> None:
        items = [
            {"type": "TEXT_API", "key": "text"},
            {"type": "CANVAS_API", "key": "canvas-new"},
            {"type": "canvas_api", "key": "canvas-two"},
        ]
        self.assertEqual(CanvasClient.canvas_task_key(items, "canvas-two"), "canvas-two")
        self.assertEqual(CanvasClient.canvas_task_key(items, "missing"), "canvas-new")

    def test_payload_obeys_canvas_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            renderer = CanvasRenderer(Assets(directory))
            payload = renderer.payload(sample_dashboard(), "canvas", "F1 看板")
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.assertLess(len(encoded), 128 * 1024)
            self.assertEqual(payload["taskKey"], "canvas")

    def test_contract_rejects_oversized_text(self) -> None:
        dashboard = sample_dashboard()
        dashboard["title"] = "x" * 4001
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CanvasContractError):
                CanvasRenderer(Assets(directory)).payload(dashboard, "", "F1")

    def test_text_is_hard_thresholded_and_only_artwork_is_dithered(self) -> None:
        renderer = CanvasRenderer()
        with patch("f1_quote0.raster.atkinson_dither", wraps=raster.atkinson_dither) as dither:
            renderer.payload(sample_dashboard(), "canvas", "F1 看板")
            self.assertEqual(dither.call_count, 0)

        countdown = {
            **sample_dashboard(),
            "rows": [],
            "presentation": "hero",
            "hero_metric": None,
            "track_asset": "track-zandvoort.png",
        }
        with patch("f1_quote0.raster.atkinson_dither", wraps=raster.atkinson_dither) as dither:
            renderer.payload(countdown, "canvas", "F1 看板")
            self.assertEqual(dither.call_count, 1)

    def test_all_presentations_are_prerendered_as_native_monochrome_screen(self) -> None:
        countdown = {
            **sample_dashboard(),
            "eyebrow": "下一站正赛",
            "title": "10 天",
            "subtitle": "Dutch GP",
            "status": "8月23日",
            "rows": [],
            "presentation": "hero",
            "detail_primary": "Circuit Park Zandvoort",
            "detail_secondary": "周日 21:00",
            "track_asset": "track-zandvoort.png",
        }
        metric = {
            **sample_dashboard(),
            "eyebrow": "车队积分",
            "title": "P1",
            "subtitle": "McLaren",
            "status": "2026",
            "rows": [],
            "presentation": "hero",
            "hero_metric": "570",
            "detail_primary": "McLaren",
            "detail_secondary": "NOR · PIA",
            "side_asset": "mclaren.png",
        }
        spotlight = {
            **sample_dashboard(),
            "title": "Lando Norris",
            "subtitle": "British GP · 7月5日",
            "rows": [{"rank": "P1", "primary": "#4", "secondary": "McLaren", "tertiary": "", "value": ""}],
            "presentation": "spotlight",
        }
        ranking = {
            **sample_dashboard(),
            "title": "McLaren",
            "rows": [
                {"rank": "P1", "primary": "Lando Norris", "secondary": "#4", "tertiary": "", "value": "299 分"},
                {"rank": "P2", "primary": "Oscar Piastri", "secondary": "#81", "tertiary": "", "value": "271 分"},
            ],
            "presentation": "ranking",
        }

        for name, dashboard in {
            "standard": sample_dashboard(),
            "countdown": countdown,
            "metric": metric,
            "spotlight": spotlight,
            "ranking": ranking,
        }.items():
            with self.subTest(presentation=name):
                self._assert_native_raster(CanvasRenderer().payload(dashboard, "canvas", "F1 看板"))

    def _assert_native_raster(self, payload: dict) -> None:
        nodes: list[dict] = []

        def collect(value) -> None:
            if isinstance(value, dict):
                if value.get("type") in {"span", "img"}:
                    nodes.append(value)
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(payload["windowData"])
        images = [node for node in nodes if node["type"] == "img"]
        self.assertIn(len(images), {1, 3})
        self.assertEqual(sum(int(image["props"]["style"]["height"].removesuffix("px")) for image in images), 152)
        for node in images:
            self.assertEqual(node["props"]["style"]["width"], "296px")
            self.assertEqual(node["props"]["tw"], "img-dither-none")
            source = node["props"]["src"]
            self.assertLess(len(source.encode("utf-8")), 3_500)
            rendered = Image.open(io.BytesIO(base64.b64decode(source.split(",", 1)[1])))
            self.assertEqual(rendered.width, 296)
            self.assertEqual(rendered.mode, "1")


if __name__ == "__main__":
    unittest.main()
