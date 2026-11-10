# -*- coding: utf-8 -*-
"""QwenPaw 2.3.x 本地数据格式适配器（SPEC 3.12 adapters/qwenpaw_2_3.py）。

数据源（真机源码验证，2.3.0b3）：
- ~/.qwenpaw/config.json → agents.profiles：{agent_id: {workspace_dir,
  enabled, pinned, ...}}（智能体注册表）；
- 各 workspace 目录 → agent.json：{id, name, description, ...}
  （每智能体元数据，30KB 级，仅取三字段——隐私最小化，3.4 红线）。

隐私红线（3.4）：只读 id/name/description 与 enabled 开关，不触碰
对话、记忆、提示词等任何内容类文件。
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import working_dir

FORMAT_2_3 = "qwenpaw-2.3"


def _read_json(path: Path) -> object | None:
    """读 JSON 文件；缺失/坏格式/非 UTF-8 一律返回 None（容错降级）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class QwenPaw23Reader:
    """2.3 格式族 Reader（工作区注册表 + agent.json 元数据）。"""

    def probe_format(self) -> str | None:
        """探测：工作目录存在且 config.json 有 agents.profiles 结构。"""
        root = working_dir()
        if not root.is_dir():
            return None
        config = _read_json(root / "config.json")
        if not isinstance(config, dict):
            return None
        agents_section = config.get("agents")
        if not isinstance(agents_section, dict) or "profiles" not in agents_section:
            return None
        return FORMAT_2_3

    def read_agents(self) -> list[dict]:
        """读台账清单（3.4 ②字段；归属不由客户端自报——服务端按令牌登记）。"""
        root = working_dir()
        config = _read_json(root / "config.json")
        if not isinstance(config, dict):
            return []
        agents_section = config.get("agents")
        if not isinstance(agents_section, dict):
            return []
        profiles = agents_section.get("profiles")
        if not isinstance(profiles, dict):
            return []

        agents: list[dict] = []
        for agent_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            agent_key = str(agent_id)

            workspace_dir = profile.get("workspace_dir")
            if isinstance(workspace_dir, str) and workspace_dir:
                ws_path = Path(workspace_dir).expanduser()
            else:
                ws_path = root / "workspaces" / agent_key
            agent_meta = _read_json(ws_path / "agent.json")
            if not isinstance(agent_meta, dict):
                agent_meta = {}

            name = agent_meta.get("name")
            description = agent_meta.get("description")
            enabled = bool(profile.get("enabled", True))
            agents.append(
                {
                    "agent_key": agent_key,
                    # name 缺省回退 agent_key（服务端 agents.name NOT NULL）
                    "name": name if isinstance(name, str) and name else agent_key,
                    "description": description if isinstance(description, str) else None,
                    # 本地启停状态（服务端 7.1 白名单不落库，仅供参考）
                    "status": "active" if enabled else "disabled",
                }
            )
        return agents
