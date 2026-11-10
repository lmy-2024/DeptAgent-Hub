# -*- coding: utf-8 -*-
"""测试假件（test_panel / test_smoke_channels 共用）。

FakeContext 只实现插件实际使用的 PluginContext 面（storage/logger/
resources）；冒烟测试同用——handler 与通道编排是纯逻辑，宿主注入面
一致（PawApp 注册层仅做路由分发）。
"""

from __future__ import annotations


class FakeStorage:
    """内存实现 context.storage（aread/awrite/adelete）。"""

    def __init__(self) -> None:
        self._files: dict[str, object] = {}

    async def aread_json(self, name: str, default=None):
        return self._files.get(name, default)

    async def awrite_json(self, name: str, value) -> None:
        self._files[name] = value

    async def adelete(self, name: str) -> None:
        self._files.pop(name, None)


class FakeLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, message: str, fields: dict | None = None) -> None:
        self.lines.append(message)

    def warning(self, message: str, fields: dict | None = None) -> None:
        self.lines.append(message)


class FakeResources:
    """托管任务桩：记录 description 并关闭协程（不真正执行）。"""

    def __init__(self) -> None:
        self.descriptions: list[str] = []

    def task(self, coro, description: str | None = None):
        self.descriptions.append(description or "")
        coro.close()


class FakeContext:
    def __init__(self) -> None:
        self.storage = FakeStorage()
        self.logger = FakeLogger()
        self.resources = FakeResources()
