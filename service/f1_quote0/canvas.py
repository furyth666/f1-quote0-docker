from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .f1 import team_logo
from .http import HTTPClient, HTTPError
from .raster import DashboardRasterRenderer


MAX_STRING_BYTES = 4_000
MAX_IMAGE_DATA_URI_BYTES = 3_500
MAX_ELEMENTS = 80
MAX_DEPTH = 16
MAX_WINDOW_DATA_BYTES = 128 * 1024
DEVICE_FONT = "chillduansans"


class CanvasContractError(RuntimeError):
    pass


def element(
    children: Any,
    *,
    kind: str = "div",
    style: dict[str, Any] | None = None,
    tw: str | None = None,
) -> dict[str, Any]:
    props: dict[str, Any] = {"children": children}
    if style:
        props["style"] = style
    if tw:
        props["tw"] = tw
    return {"type": kind, "props": props}


def text_style(size: int, weight: str = "400") -> dict[str, str]:
    return {"fontSize": f"{size}px", "fontWeight": weight, "lineHeight": f"{size + 2}px"}


def text_element(
    children: Any,
    size: int,
    weight: str = "400",
    *,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_style: dict[str, Any] = text_style(size, weight)
    resolved_style.update(style or {})
    return element(
        children,
        kind="span",
        style=resolved_style,
        tw=f"text-[{size}px]-{DEVICE_FONT}",
    )


CLIPPED = {"minWidth": 0, "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis"}


class Assets:
    def __init__(self, root: str | Path | None = None):
        configured = root or os.environ.get("ASSET_DIR")
        if configured:
            self.root = Path(configured)
        else:
            self.root = Path(__file__).resolve().parents[2] / "assets"

    def data_uri(self, name: str | None) -> str | None:
        path = self.path(name)
        if not path:
            return None
        source = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        return source if len(source.encode("utf-8")) < MAX_IMAGE_DATA_URI_BYTES else None

    def path(self, name: str | None) -> Path | None:
        if not name or Path(name).name != name or not name.lower().endswith(".png"):
            return None
        path = self.root / name
        return path if path.is_file() else None


class CanvasRenderer:
    def __init__(self, assets: Assets | None = None):
        self.assets = assets or Assets()
        self.raster = DashboardRasterRenderer(self.assets)

    def payload(self, dashboard: dict[str, Any], task_key: str, task_alias: str) -> dict[str, Any]:
        self._validate_dashboard_strings(dashboard)
        root = self._raster_root(dashboard)
        value: dict[str, Any] = {
            "refreshNow": True,
            "taskAlias": task_alias or "F1 看板",
            "windowData": {"default": [root]},
            "layoutFull": {"tw": "p-0"},
            "border": 0,
        }
        if task_key:
            value["taskKey"] = task_key
        self.validate(value)
        return value

    def _raster_root(self, dashboard: dict[str, Any]) -> dict[str, Any]:
        images = []
        for content, height in self.raster.png_parts(dashboard, MAX_IMAGE_DATA_URI_BYTES):
            source = "data:image/png;base64," + base64.b64encode(content).decode("ascii")
            images.append(self._image(source, "296px", f"{height}px", tw="img-dither-none"))
        if len(images) == 1:
            return images[0]
        return element(images, style={
            "display": "flex", "flexDirection": "column", "width": "296px", "height": "152px",
            "minWidth": "296px", "minHeight": "152px", "gap": 0, "overflow": "hidden",
            "backgroundColor": "#ffffff",
        })

    def _validate_dashboard_strings(self, value: Any) -> None:
        if isinstance(value, str):
            length = len(value.encode("utf-8"))
            if length > MAX_STRING_BYTES:
                raise CanvasContractError(f"看板字符串过长：{length}")
            return
        if isinstance(value, list):
            for child in value:
                self._validate_dashboard_strings(child)
            return
        if isinstance(value, dict):
            for key, child in value.items():
                self._validate_dashboard_strings(key)
                self._validate_dashboard_strings(child)

    def encoded(self, dashboard: dict[str, Any], task_key: str, task_alias: str) -> bytes:
        return json.dumps(self.payload(dashboard, task_key, task_alias), ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def validate(self, payload: dict[str, Any]) -> None:
        window = payload.get("windowData")
        if not isinstance(window, dict) or not isinstance(window.get("default"), list):
            raise CanvasContractError("画板内容缺少 default 图层")
        elements, depth = self._audit(window, 0)
        if elements > MAX_ELEMENTS:
            raise CanvasContractError(f"画板元素过多：{elements}")
        if depth > MAX_DEPTH:
            raise CanvasContractError(f"画板层级过深：{depth}")
        size = len(json.dumps(window, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if size > MAX_WINDOW_DATA_BYTES:
            raise CanvasContractError(f"画板内容过大：{size}")

    def _audit(self, value: Any, depth: int) -> tuple[int, int]:
        if isinstance(value, str):
            length = len(value.encode("utf-8"))
            if length > MAX_STRING_BYTES:
                raise CanvasContractError(f"画板字符串过长：{length}")
            if value.startswith("data:image/"):
                if not value.startswith("data:image/png;base64,"):
                    raise CanvasContractError("画板图片必须是 PNG")
                if length >= MAX_IMAGE_DATA_URI_BYTES:
                    raise CanvasContractError(f"画板图片过大：{length}")
            return 0, depth
        if isinstance(value, list):
            values = [self._audit(item, depth) for item in value]
            return sum(item[0] for item in values), max((item[1] for item in values), default=depth)
        if isinstance(value, dict):
            next_depth = depth
            count = 0
            maximum = depth
            if "type" in value:
                if value["type"] not in {"div", "span", "img"}:
                    raise CanvasContractError(f"不支持的元素：{value['type']}")
                next_depth += 1
                count = 1
                maximum = next_depth
            for key, child in value.items():
                key_count, key_depth = self._audit(key, next_depth)
                child_count, child_depth = self._audit(child, next_depth)
                count += key_count + child_count
                maximum = max(maximum, key_depth, child_depth)
            return count, maximum
        return 0, depth

    def _masthead(self, data: dict[str, Any]) -> dict[str, Any]:
        return element([
            text_element(data.get("eyebrow", ""), 11, "700"),
            text_element(data.get("status", ""), 11, "700", style={
                "padding": "2px 7px", "borderRadius": "10px",
                "backgroundColor": "#000000", "color": "#ffffff", "whiteSpace": "nowrap",
            }),
        ], style={
            "display": "flex", "alignItems": "center", "justifyContent": "space-between",
            "height": "24px", "minHeight": "24px", "paddingLeft": "10px", "paddingRight": "10px",
            "boxSizing": "border-box", "borderBottom": "1px solid #000000",
        })

    def _body(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("hero_metric") is not None:
            return self._metric_body(data)
        if data.get("presentation") == "hero" and not data.get("rows"):
            return self._hero_body(data)
        children = [self._headline(data)]
        if data.get("rows"):
            children.append(self._rows(data["rows"]))
        return element(children, style={"display": "flex", "flexDirection": "column", "flex": 1, "minHeight": 0})

    def _headline(self, data: dict[str, Any]) -> dict[str, Any]:
        presentation = data.get("presentation")
        size = 22 if presentation == "spotlight" else 20 if presentation == "ranking" else 18
        text_children = [text_element(data.get("title", ""), size, "700", style=CLIPPED)]
        if data.get("subtitle"):
            text_children.append(text_element(data["subtitle"], 10, "500", style=CLIPPED))
        children: list[dict[str, Any]] = [element(text_children, style={"display": "flex", "flexDirection": "column", "minWidth": 0, "flex": 1})]
        mark = self._asset_mark(data.get("decoration_asset"), 24)
        if mark:
            children.append(mark)
        return element(children, style={
            "display": "flex", "alignItems": "center", "height": "44px", "minHeight": "44px",
            "paddingLeft": "10px", "paddingRight": "8px", "boxSizing": "border-box",
            "borderBottom": "1px solid #000000", "overflow": "hidden",
        })

    def _rows(self, rows: list[dict[str, str]]) -> dict[str, Any]:
        rendered = []
        for index, item in enumerate(rows[:3]):
            text_children = [text_element(item.get("primary", ""), 14, "700", style=CLIPPED)]
            meta = " · ".join(value for value in (item.get("secondary"), item.get("tertiary")) if value)
            if meta:
                text_children.append(text_element(meta, 9, "500", style=CLIPPED))
            children = [
                text_element(item.get("rank", ""), 13, "700", style={
                    "width": "42px", "minWidth": "42px", "textAlign": "center",
                    "padding": "4px", "boxSizing": "border-box", "backgroundColor": "#000000",
                    "color": "#ffffff", "borderRadius": "4px",
                }),
                element(text_children, style={"display": "flex", "flexDirection": "column", "minWidth": 0, "flex": 1, "marginLeft": "9px"}),
            ]
            if item.get("value"):
                children.append(text_element(item["value"], 13, "700", style={"whiteSpace": "nowrap", "marginLeft": "6px"}))
            style = {
                "display": "flex", "alignItems": "center", "flex": 1, "minHeight": 0,
                "paddingLeft": "10px", "paddingRight": "10px", "boxSizing": "border-box", "overflow": "hidden",
            }
            if index < min(len(rows), 3) - 1:
                style["borderBottom"] = "1px solid #000000"
            rendered.append(element(children, style=style))
        return element(rendered, style={"display": "flex", "flexDirection": "column", "flex": 1, "minHeight": 0, "overflow": "hidden"})

    def _hero_body(self, data: dict[str, Any]) -> dict[str, Any]:
        text_children = [text_element(data.get("title", ""), 48, "800", style=CLIPPED)]
        if data.get("subtitle"):
            text_children.append(text_element(data["subtitle"], 22, "800", style=CLIPPED))
        if data.get("detail_primary"):
            text_children.append(text_element(data["detail_primary"], 13, "600", style=CLIPPED))
        if data.get("detail_secondary"):
            text_children.append(text_element(data["detail_secondary"], 13, "600", style=CLIPPED))
        children = [element(text_children, style={"display": "flex", "flexDirection": "column", "justifyContent": "center", "minWidth": 0, "flex": 1})]
        track = self._track_art(data.get("track_asset"))
        if track:
            children.append(track)
        else:
            mark = self._asset_mark(data.get("decoration_asset") or "f1-mark.png", 34)
            if mark:
                children.append(mark)
        return element(children, style={
            "display": "flex", "alignItems": "center", "flex": 1, "minHeight": 0,
            "padding": "8px 12px", "boxSizing": "border-box", "overflow": "hidden",
        })

    def _metric_body(self, data: dict[str, Any]) -> dict[str, Any]:
        metric = element([
            text_element(data.get("hero_metric", "0"), 48, "700"),
            text_element("分", 13, "700", style={"marginLeft": "4px", "paddingBottom": "7px"}),
        ], style={"display": "flex", "alignItems": "flex-end", "whiteSpace": "nowrap"})
        text_children = [metric]
        if data.get("detail_primary"):
            text_children.append(text_element(data["detail_primary"], 15, "700", style=CLIPPED))
        if data.get("detail_secondary"):
            text_children.append(text_element(data["detail_secondary"], 10, "500", style=CLIPPED))
        children = [element(text_children, style={"display": "flex", "flexDirection": "column", "justifyContent": "center", "minWidth": 0, "flex": 1})]
        art = self._side_art(data.get("side_asset"))
        if art:
            children.append(art)
        return element(children, style={
            "display": "flex", "alignItems": "stretch", "flex": 1, "minHeight": 0,
            "paddingLeft": "14px", "boxSizing": "border-box", "overflow": "hidden",
        })

    def _image(self, source: str, width: str, height: str, *, tw: str | None = None) -> dict[str, Any]:
        props: dict[str, Any] = {
            "src": source,
            "style": {
                "display": "block",
                "width": width,
                "height": height,
                "objectFit": "contain",
                "objectPosition": "center",
            },
        }
        if tw:
            props["tw"] = tw
        return {"type": "img", "props": props}

    def _asset_mark(self, name: str | None, size: int) -> dict[str, Any] | None:
        source = self.assets.data_uri(name)
        if not source:
            return None
        is_team = bool(name and team_logo(name.removesuffix(".png")) == name)
        width = round(size * (2.15 if name == "f1-mark.png" else 1))
        return element([self._image(source, "100%", "100%")], style={
            "display": "flex", "alignItems": "center", "justifyContent": "center",
            "width": f"{width}px", "minWidth": f"{width}px", "height": f"{size}px",
            "marginLeft": "4px", "marginRight": "4px", "padding": "3px" if is_team else "0px",
            "boxSizing": "border-box", "overflow": "hidden", "borderRadius": "4px",
            "backgroundColor": "#000000" if is_team else "transparent",
        })

    def _side_art(self, name: str | None) -> dict[str, Any] | None:
        source = self.assets.data_uri(name)
        if not source:
            return None
        return element([self._image(source, "68px", "68px")], style={
            "display": "flex", "alignItems": "center", "justifyContent": "center",
            "width": "92px", "minWidth": "92px", "height": "100%", "boxSizing": "border-box",
            "overflow": "hidden", "backgroundColor": "#000000", "borderLeft": "2px solid #000000",
        })

    def _track_art(self, name: str | None) -> dict[str, Any] | None:
        source = self.assets.data_uri(name) if name and name.startswith("track-") else None
        if not source:
            return None
        return element([self._image(
            source,
            "114px",
            "80px",
            tw="img-dither-diffusion img-kernel-atkinson img-levels-2",
        )], style={
            "display": "flex", "alignItems": "center", "justifyContent": "center",
            "width": "114px", "minWidth": "114px", "height": "80px", "marginLeft": "6px",
            "boxSizing": "border-box", "overflow": "hidden",
        })


class CanvasClient:
    def __init__(
        self,
        api_key: str,
        device_id: str,
        task_key: str = "",
        task_alias: str = "F1 看板",
        *,
        http: HTTPClient | None = None,
        renderer: CanvasRenderer | None = None,
    ):
        self.api_key = api_key
        self.device_id = device_id
        self.preferred_task_key = task_key
        self.task_alias = task_alias
        self.http = http or HTTPClient()
        self.renderer = renderer or CanvasRenderer()
        self.resolved_task_key = ""

    @staticmethod
    def canvas_task_key(items: list[dict[str, Any]], preferred: str = "") -> str | None:
        canvas = [item for item in items if str(item.get("type", "")).upper() == "CANVAS_API"]
        if preferred:
            match = next((item.get("key") for item in canvas if item.get("key") == preferred), None)
            if match:
                return str(match)
        return next((str(item["key"]) for item in canvas if item.get("key")), None)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _resolve_key(self, force: bool = False) -> str:
        if self.resolved_task_key and not force:
            return self.resolved_task_key
        url = f"https://dot.mindreset.tech/api/authV2/open/device/{quote(self.device_id, safe='')}/loop/list"
        items = json.loads(self.http.request(url, headers=self._headers()).decode("utf-8"))
        key = self.canvas_task_key(items, self.preferred_task_key)
        if not key:
            types = "、".join(str(item.get("type", "")) for item in items) or "循环内容为空"
            raise RuntimeError(f"未在设备循环中找到画板 API；当前内容：{types}")
        self.resolved_task_key = key
        return key

    def push(self, dashboard: dict[str, Any]) -> None:
        if not self.api_key:
            raise RuntimeError("缺少 DOT_API_KEY")
        if not self.device_id:
            raise RuntimeError("缺少 QUOTE0_DEVICE_ID")
        url = f"https://dot.mindreset.tech/api/authV2/open/device/{quote(self.device_id, safe='')}/canvas"
        key = self._resolve_key()
        body = self.renderer.encoded(dashboard, key, self.task_alias)
        try:
            self.http.request(url, method="POST", headers=self._headers(), body=body)
        except HTTPError as error:
            if error.status != 404:
                raise
            self.resolved_task_key = ""
            key = self._resolve_key(force=True)
            body = self.renderer.encoded(dashboard, key, self.task_alias)
            try:
                self.http.request(url, method="POST", headers=self._headers(), body=body)
            except HTTPError as retry_error:
                if retry_error.status == 404:
                    raise RuntimeError("Canvas 条目已失效；请在 Dot App 的 Loop 中删除后重新添加画板 API") from retry_error
                raise
