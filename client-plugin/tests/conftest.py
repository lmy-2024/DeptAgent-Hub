# -*- coding: utf-8 -*-
"""pytest 环境：插件目录加进 sys.path（插件以目录形态分发，非包；
测试放在分发物之外——同 server/tests ↔ server/src 模式，也避免
qwenpaw.plugins.check 把测试当插件源码扫描）。

server/src 一并注入：三通道端到端冒烟（test_smoke_channels）需要
import deptagent（进程内起真 FastAPI server）；CI 与本地共用一个
解释器环境（qwenpaw + server 依赖并存）。
"""

import sys
from pathlib import Path

import pytest

from fakes import FakeContext

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "deptagent-link"))
sys.path.insert(0, str(_HERE.parents[1] / "server" / "src"))


@pytest.fixture
def context() -> FakeContext:
    return FakeContext()
