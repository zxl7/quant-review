#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HTTP 层：封装 biyingapi 请求（GET + 超时 + JSON）

目标：
- 让业务层只关心 endpoint 与参数，不关心 urllib 细节
- 便于后续统一加：重试、熔断、日志、mock
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class HttpClient:
    base_url: str
    token: str
    timeout: int = 30
    retries: int = 2

    def _open_json(self, req: urllib.request.Request) -> Any:
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (500, 502, 503, 504) and attempt < self.retries:
                    last_err = e
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
                if attempt < self.retries:
                    last_err = e
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise
        if last_err:
            raise last_err
        raise RuntimeError("unexpected http client state")

    def api(self, path: str, *, exit_on_404: bool = True, quiet_404: bool = False) -> Optional[Any]:
        """
        调用标准 REST path：{base}/{path}/{token}
        """
        # 关键安全校验：token 必须来自环境变量（见 daily_review/config.py）
        if not self.token:
            raise RuntimeError("未设置 BIYING_TOKEN：请先 export BIYING_TOKEN=... 再运行")
        url = f"{self.base_url}/{path}/{self.token}"
        req = urllib.request.Request(url)
        try:
            return self._open_json(req)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                if exit_on_404:
                    if not quiet_404:
                        raise
                    return None
                return None
            raise

    def get_json(self, url: str) -> Any:
        req = urllib.request.Request(url)
        return self._open_json(req)
