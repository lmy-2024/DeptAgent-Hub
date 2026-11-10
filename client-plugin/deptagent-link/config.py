# -*- coding: utf-8 -*-
"""插件自有配置与状态存储键（SPEC 3.2 config.py：服务器地址 / 员工偏好）。

存储键集中在此声明（3.12 第 5 条：持久化只走 context.storage），
binding / scheduler / uploader / collectors 共同引用——独立模块避免
相互导入成环。
"""

from __future__ import annotations

from datetime import datetime

# 与 plugin.json version 保持一致（心跳 plugin_version 字段上报用）
PLUGIN_VERSION = "0.1.0"

# context.storage 相对路径键
STORAGE_FILES = {
    "offline_queue": "offline_queue.json",  # 离线上报队列（T1.4 退避补传完善）
    "watermark": "watermark.json",  # 各通道增量水位（T1.7 usage 指纹 + 通道执行时间）
    "binding": "binding.json",  # 绑定状态（binding.py）
    "seq": "seq.json",  # 本地上报序号（uploader 防重放配合，8.1）
    "telemetry_status": "telemetry_status.json",  # 三通道状态（面板信号灯/红灯，3.8）
    "today_report": "today_report.json",  # 今日已上报快照（3.4 透明展示，面板 3.8）
}

# 隐私红线（3.4）：员工"暂停本机上报"开关（缺省关闭 = 正常上报）
REPORTING_PAUSED_FILE = "reporting_paused.json"

# 运行时状态（非持久化）：插件激活时刻。scheduler 启动时写入，
# collectors.heartbeat 读取以计算运行时长（uptime_hours）。
# 经 config 模块属性共享，避免 collectors 反向依赖 scheduler 成环。
ACTIVATED_AT: datetime | None = None
