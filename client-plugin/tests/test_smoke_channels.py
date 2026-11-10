# -*- coding: utf-8 -*-
"""三通道端到端冒烟（SPEC 3.9 升级验证流水线：CI 用新版起容器装插件跑
check --runtime + 三通道冒烟）。

链路全真（唯一假件 = FakeContext 的宿主注入面与假 QwenPaw 数据目录）：
真 FastAPI server（进程内 uvicorn、随机端口、临时 SQLite）+ 真
binding/collectors/uploader（真 HTTP）→ 断言 server 侧四表落库 +
diagnostics.self_check 汇总为 ok。

QwenPaw 数据目录经 QWENPAW_WORKING_DIR 注入 tmp（adapters/base.py
同宿主 constant.py 优先级）；token_usage 造当日两行（一行归属台账
smoke-agent-a、一行未归属）+ 90 天窗口外一行（不报不记，D3）。
"""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import uvicorn

import diagnostics
from binding import bind_device
from config import STORAGE_FILES
from fakes import FakeContext

INVITE_CODE = "SMOKE-INVITE-001"
EMPLOYEE_NO = "SMOKE001"


@pytest.fixture
def qwenpaw_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """假 QwenPaw 工作目录：config.json agents 注册表 + 两个 workspace
    （其一无 agent.json，覆盖 name 回退 agent_key 路径）+ token_usage。
    """
    root = tmp_path / "qwenpaw-home"
    root.mkdir()
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(root))

    (root / "config.json").write_text(
        json.dumps(
            {
                "agents": {
                    "profiles": {
                        "smoke-agent-a": {"enabled": True},
                        "smoke-agent-b": {"enabled": True},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    ws_a = root / "workspaces" / "smoke-agent-a"
    ws_a.mkdir(parents=True)
    (ws_a / "agent.json").write_text(
        json.dumps({"name": "冒烟智能体A", "description": "e2e"}), encoding="utf-8"
    )
    # smoke-agent-b：无 workspace/agent.json → name 回退 agent_key（8.1）

    today = datetime.now().strftime("%Y-%m-%d")
    (root / "token_usage.json").write_text(
        json.dumps(
            {
                today: {
                    "k1": {
                        "provider_id": "aliyun-tokenplan",
                        "model_name": "glm-5.2",
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "cache_read_tokens": 4,
                        "cache_write_tokens": 2,
                        "call_count": 2,
                        "agent_id": "smoke-agent-a",
                    },
                    "k2": {
                        "provider_id": "deepseek",
                        "model_name": "v4",
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "call_count": 1,
                    },
                },
                # 90 天窗口外（D3）：不报不记
                "2000-01-01": {
                    "old": {"provider_id": "x", "model_name": "y", "prompt_tokens": 1}
                },
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture
async def live_server(tmp_path: Path):
    """进程内真 FastAPI server（随机端口 + 临时 SQLite）；yield (base, db)。"""
    from deptagent.app import create_app
    from deptagent.config import Settings

    db_path = tmp_path / "smoke-server.db"
    app = create_app(Settings(db_path=str(db_path), jwt_secret="smoke-test-secret"))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(100):  # 最多等 10s（含 lifespan 迁移）
        try:
            if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("冒烟 server 未就绪")

    # 邀请码直插（管理端点链路由 server/tests 覆盖；冒烟只关心三通道）
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO invitations (code, team, role) VALUES (?, ?, ?)",
            (INVITE_CODE, "平台组", "member"),
        )
        conn.commit()
    finally:
        conn.close()

    yield base, str(db_path)

    server.should_exit = True
    thread.join(timeout=5)


async def test_smoke_three_channels_end_to_end(
    qwenpaw_data: Path,
    live_server: tuple[str, str],
    context: FakeContext,
):
    base, db_path = live_server

    # 1. 输码绑定（真 HTTP → 真 server：邀请码校验 + 令牌签发 + 建档）
    binding = await bind_device(
        context, base, INVITE_CODE, EMPLOYEE_NO, name="冒烟员工"
    )
    assert binding["device_token"]
    assert binding["server_config"]["report_intervals_sec"]["usage"] == 300

    # 2. 三通道手动同步（真 collectors → 真 uploader → 真 server）
    results = await diagnostics.run_manual_sync(context)
    assert results == {"heartbeat": "ok", "agents": "ok", "usage": "ok"}

    # 3. 今日透明数据已记录（3.4：员工可见"本机今日已上报内容"）
    today_report = await context.storage.aread_json(
        STORAGE_FILES["today_report"], {}
    )
    assert today_report["usage_tokens"] == 100 + 20 + 4 + 2 + 10 + 5
    assert today_report["agents_count"] == 2
    assert today_report["usage_rows"] and len(today_report["usage_rows"]) == 2

    # 4. server 侧四表落库
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        user = conn.execute(
            "SELECT id, role, team, status FROM users WHERE employee_no = ?",
            (EMPLOYEE_NO,),
        ).fetchone()
        assert user["status"] == "active"
        assert (user["role"], user["team"]) == ("member", "平台组")

        device = conn.execute(
            "SELECT status, last_seq, last_heartbeat, reporting_paused FROM devices "
            "WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
        assert device["status"] == "active"
        assert device["last_seq"] == 3  # 三通道各占一个递增 seq
        assert device["last_heartbeat"]
        assert device["reporting_paused"] == 0

        agent_keys = {
            row["agent_key"]
            for row in conn.execute("SELECT agent_key FROM agents")
        }
        assert agent_keys == {"smoke-agent-a", "smoke-agent-b"}

        today = datetime.now().strftime("%Y-%m-%d")
        usage_rows = conn.execute(
            "SELECT agent_id, provider_id, model, prompt_tokens, completion_tokens, "
            "call_count, source FROM usage_daily WHERE stat_date = ? ORDER BY model",
            (today,),
        ).fetchall()
        assert len(usage_rows) == 2
        by_model = {row["model"]: row for row in usage_rows}
        assert by_model["glm-5.2"]["agent_id"] != 0  # 归属解析到本人台账
        assert (
            by_model["glm-5.2"]["prompt_tokens"],
            by_model["glm-5.2"]["call_count"],
        ) == (100, 2)
        assert by_model["v4"]["agent_id"] == 0  # 未归属哨兵
        assert all(row["source"] == "client" for row in usage_rows)

        # 90 天窗口外日期不落库（D3）
        stale = conn.execute(
            "SELECT COUNT(*) AS n FROM usage_daily WHERE stat_date = '2000-01-01'"
        ).fetchone()["n"]
        assert stale == 0
    finally:
        conn.close()

    # 5. 诊断自检（3.9）：三通道跑通后汇总结论为 ok
    check = await diagnostics.self_check(context)
    assert check["verdict"] == "ok"
    assert all(item["ok"] for item in check["items"])
    assert check["binding"]["employee_no"] == EMPLOYEE_NO
    # 隐私红线：自检产物不含设备令牌
    assert "device_token" not in json.dumps(check)
