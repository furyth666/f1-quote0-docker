from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class HTTPError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class HTTPClient:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.opener = urllib.request.build_opener()

    def json(self, url: str) -> Any:
        return json.loads(self.request(url).decode("utf-8"))

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> bytes:
        request_headers = {"User-Agent": "F1Quote0Docker/1.0"}
        request_headers.update(headers or {})
        request = urllib.request.Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            message = error.read(4096).decode("utf-8", errors="replace")
            raise HTTPError(error.code, message) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"网络请求失败：{error.reason}") from error
