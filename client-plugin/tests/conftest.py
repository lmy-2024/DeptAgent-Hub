# -*- coding: utf-8 -*-
"""pytest 环境：插件目录加进 sys.path（插件以目录形态分发，非包；
测试放在分发物之外——同 server/tests ↔ server/src 模式，也避免
qwenpaw.plugins.check 把测试当插件源码扫描）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deptagent-link"))
