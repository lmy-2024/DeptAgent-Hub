# -*- coding: utf-8 -*-
"""deptagent-link 后端入口：导出模块级 plugin 实例（SPEC 3.12 第 2 条）。

阶段 1 骨架：register 仅做声明式注册；调度器/上报循环自 T1.2 起在
context.on_activate 回调内启动（SPEC 3.2 运行时纪律第 1 条——
register 内创建资源会被宿主以 ResourceError 拒绝）。
"""

from qwenpaw.plugins import PluginContext

PLUGIN_VERSION = "0.1.0"


class Plugin:
    def register(self, context: PluginContext) -> None:
        context.logger.info(
            "deptagent-link registered",
            fields={"plugin_version": PLUGIN_VERSION},
        )


plugin = Plugin()
