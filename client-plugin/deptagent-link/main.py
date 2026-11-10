# -*- coding: utf-8 -*-
"""deptagent-link 后端入口：导出模块级 plugin 实例（SPEC 3.12 第 2 条）。

register 仅做声明式注册；调度器与员工面板路由等资源在
context.on_activate 回调内创建/注册（3.12 第 3 条——register 内创建
资源被宿主以 ResourceError 拒绝）。
"""

from qwenpaw.plugins import PluginContext

import panel
from binding import get_binding
from config import PLUGIN_VERSION
from scheduler import start_scheduler


class Plugin:
    def register(self, context: PluginContext) -> None:
        context.logger.info(
            "deptagent-link registered",
            fields={"plugin_version": PLUGIN_VERSION},
        )
        context.on_activate(self._on_activate)

    async def _on_activate(self, context: PluginContext) -> None:
        # 员工面板数据层（SPEC 3.8、D8）：注入上下文 + 注册 PawApp 路由
        # （一插件一 PawApp；路由随注册资源在停用时自动摘除）
        panel.bind_context(context)
        panel.paw.register(context)
        # 后台任务的唯一启动点（SPEC 3.2 运行时纪律第 1 条）；
        # 已绑定 → 首轮立即执行（SPEC 3.5 首次全量上报，采集器 T1.5–T1.7）
        binding = await get_binding(context)
        await start_scheduler(context, run_immediately=binding is not None)


plugin = Plugin()
