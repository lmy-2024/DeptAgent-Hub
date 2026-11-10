# -*- coding: utf-8 -*-
"""格式适配层包（SPEC 3.12 adapters/）：格式探测 + 版本独立演进。

上游 QwenPaw 本地数据格式变化只影响本包内一个适配器文件（SPEC A3
协议独立决策）；collectors 通过 detect_format() 取得格式族标签与
Reader，不直接触碰具体格式。
"""

from __future__ import annotations
