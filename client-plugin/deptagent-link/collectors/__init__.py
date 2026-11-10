# -*- coding: utf-8 -*-
"""三通道采集器包（SPEC 3.4）：heartbeat（T1.5）/ agents（T1.6）/ usage（T1.7）。

采集器只做本机读取，产出 8.1 报文各段数据；网络上报由 uploader.py
统一负责，周期调度由 scheduler.py 驱动（通道 = 采集器 + 上报器组合）。
"""

from __future__ import annotations
