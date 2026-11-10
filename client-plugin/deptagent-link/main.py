# -*- coding: utf-8 -*-
"""deptagent-link 后端入口：导出模块级 plugin 实例（SPEC 3.12 第 2 条）。

register 仅做声明式注册；调度器等后台任务在 context.on_activate
回调内启动（3.12 第 3 条——register 内创建资源被宿主以 ResourceError
拒绝）。
"""

from qwenpaw.plugins import PluginContext

from scheduler import start_scheduler

PLUGIN_VERSION = "0.1.0"


class Plugin:
    def register(self, context: PluginContext) -> None:
        context.logger.info(
            "deptagent-link registered",
            fields={"plugin_version": PLUGIN_VERSION},
        )
        context.on_activate(self._on_activate)

    async def _on_activate(self, context: PluginContext) -> None:
        # 后台任务的唯一启动点（SPEC 3.2 运行时纪律第 1 条）
        await start_scheduler(context)


plugin = Plugin()
