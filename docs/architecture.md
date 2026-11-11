# DeptAgent-Hub 工程架构

> 面向开发者的架构速览：**每节以 Mermaid 图为主，文字只做最小注解**。
> 需求口径见 [SPEC.md](SPEC.md)，安装使用见 [README](../README.md)。

---

## 1. 系统总览

```mermaid
flowchart LR
    subgraph EMP["员工电脑（每台）"]
        QP["QwenPaw 宿主<br/>≥ 2.3.0"] --> PLG["插件 deptagent-link"]
        PLG --> STORE[("plugin-data<br/>binding/seq/watermark")]
    end

    subgraph SRV["部门服务器"]
        API["deptagent-server<br/>FastAPI · :8024"] --> DB[("SQLite<br/>deptagent.db")]
        API -->|"静态托管 /"| DIST["console/dist"]
    end

    BROWSER["管理员浏览器"] -->|"③ 查询页面 + API"| API
    PLG -->|"① 邀请码绑定"| API
    PLG -->|"② 遥测上报<br/>Bearer 设备令牌 + seq"| API
```

**设计原则**：控制面/员工端分离 · 竖切交付（每通道独立闭环） · 隐私最小化（不传对话内容） · seq 幂等防重放 · 格式不兼容时降级仅心跳。

---

## 2. 一次上报的完整链路

```mermaid
sequenceDiagram
    autonumber
    participant SCH as 调度器 scheduler
    participant ADP as 适配器 adapters
    participant COL as 采集器 collectors
    participant UPL as 上报器 uploader
    participant SRV as 服务端 telemetry
    participant DB as SQLite

    SCH->>ADP: 心跳 5min / 台账 15min / 用量 5min
    ADP->>COL: 读宿主数据（含格式探测）
    COL->>UPL: 归一化协议 JSON
    UPL->>UPL: seq+1（文件锁串行）
    UPL->>SRV: POST /api/v1/telemetry/report（Bearer）
    SRV->>DB: 单事务：seq CAS + 三通道 UPSERT
    DB-->>SRV: 落库（重复上报幂等）
    SRV-->>UPL: 200 {plugin_latest, server_config}
    UPL->>UPL: 水位 commit → 状态 ok
    Note over UPL,SRV: 失败分支见 §3 状态机
```

---

## 3. 上报状态机（心跳 / 台账 / 用量共用）

```mermaid
stateDiagram-v2
    state "未绑定" as Unbound
    state "已绑定" as Bound
    state "上报正常" as Ok
    state "网络失败（可重试）" as Error
    state "红灯·已吊销（停报）" as Revoked
    state "红灯·令牌失效（停报）" as Invalid
    state "已暂停（仅心跳）" as Paused
    state "降级·仅心跳（橙灯）" as Degraded

    [*] --> Unbound: 首次安装
    Unbound --> Bound: 邀请码绑定成功
    Bound --> Ok: 200
    Ok --> Ok: 下轮正常
    Ok --> Error: 网络失败（水位不动，下轮重发）
    Error --> Ok: 重试成功
    Ok --> Revoked: 401 revoked（管理端吊销）
    Ok --> Invalid: 401 invalid（换库/令牌失效）
    Revoked --> Unbound: 用户重新绑定
    Invalid --> Unbound: 用户重新绑定
    Ok --> Paused: 用户暂停（心跳携带 paused，管理端显示"已暂停"而非离线）
    Paused --> Ok: 恢复
    Ok --> Degraded: 宿主格式不识别（last_format_probe 上报）
    Degraded --> Ok: 适配新版本后
```

---

## 4. 服务端：三层 + 端点调用关系

```mermaid
flowchart TB
    subgraph API["api/ 路由层（薄壳：校验 + 调用 core）"]
        direction LR
        A1["auth · accounts"] ~~~ A2["bind · telemetry"] ~~~ A3["employees · agents"] ~~~ A4["usage · dashboard"]
    end
    subgraph CORE["core/ 业务层（纯逻辑 + SQL，可单测）"]
        direction LR
        C1["auth · security"] ~~~ C2["bind"] ~~~ C3["employees"] ~~~ C4["agents"] ~~~ C5["usage"] ~~~ C6["dashboard"] ~~~ C7["errors · utc"]
    end
    subgraph STO["storage/ 持久层"]
        direction LR
        S1["database（WAL + 事务）"] ~~~ S2["migrations（编号迁移·幂等）"]
    end
    API --> CORE --> STO --> DB[("SQLite")]
    APP["app.py<br/>配置 → DB → 迁移 → 鉴权依赖 → 路由 → 静态托管"] -.-> API
```

**谁调用哪些端点**：

```mermaid
flowchart LR
    ANY["匿名"] --> H["/health · /api/v1/auth/login<br/>（登录失败锁定 5 次/15min）"]
    PLG["插件·邀请码"] --> B["/api/v1/bind<br/>（IP 限速 10 次/min）"]
    PLG2["插件·设备令牌"] --> T["/api/v1/telemetry/report<br/>（seq CAS 整包拒旧）"]
    SUPER["super"] --> AC["/api/v1/admin/accounts*<br/>账号治理"]
    ADM["admin+"] --> E["员工/设备/邀请码/吊销"]
    LEAD["lead+"] --> L["驾驶舱 / 台账 / 用量 / CSV"]
```

**三个关键机制**：

| 机制 | 实现 |
|---|---|
| seq 防重放 | `UPDATE devices SET last_seq=? WHERE id=? AND last_seq<?`，rowcount≠1 → 409 整包拒绝；客户端按响应重置后重报 |
| 字段白名单 | 上报只允许改 8 个设备字段 + 3 个智能体字段（name/description/last_seen），其余列服务端权威 |
| 宽松覆盖 | `None` 不冲掉旧值（COALESCE）——宿主升级字段消失不丢已有信息 |

---

## 5. 数据模型

```mermaid
erDiagram
    users ||--o{ devices : "1:N 一人多机"
    users ||--o{ agents : "1:N 台账归属"
    users ||--o{ usage_daily : "1:N 用量"
    users ||--o{ invitations : "used_by 一次性"
    agents ||--o{ usage_daily : "agent_id（0=未归属哨兵）"

    users {
        int id PK
        text employee_no UK
        text role "member/lead/admin/super"
        text team "科室快照来源"
        text password_hash "Argon2id"
    }
    devices {
        int id PK
        int user_id FK
        text token_hash UK "令牌只存哈希"
        int last_seq "CAS 防重放水位"
        text last_format_probe "格式探测结果"
        text last_heartbeat "在线判定 15min"
    }
    agents {
        int id PK
        text agent_key "UNIQUE(owner,key)"
        text definition_key "跨员工聚合键"
        text status "new/active/archived/blocked"
    }
    usage_daily {
        int id PK
        text stat_date
        int user_id FK
        int agent_id "0=未归属"
        text team "入库时点快照"
        text provider_id
        text model
        int prompt_tokens "四类 token 分列"
        text source "client/gateway"
    }
    invitations {
        text code PK
        text role "member/lead"
        text expires_at "默认 72h"
        int used_by FK
        text used_at
    }
    audit_log {
        int actor_id
        text action
        text at
    }
```

**`usage_report` VIEW**：`client` 与 `gateway` 双来源合并——同一 `(日期,用户,智能体,厂商,模型)` 存在网关计量行时屏蔽客户端行（网关优先）。

---

## 6. 管理端

```mermaid
flowchart LR
    subgraph SPA["console SPA（React + Vite + ECharts）"]
        LOGIN["/login"] --> LAYOUT["AppLayout<br/>导航按角色裁剪"]
        LAYOUT --> D["/ 驾驶舱<br/>KPI 四卡 + 离线告警 + 趋势/Top"]
        LAYOUT --> E["/employees<br/>在线灯 + 邀请码 + 吊销"]
        LAYOUT --> A["/agents<br/>六列 + 详情抽屉"]
        LAYOUT --> U["/usage<br/>四维×日周月 + CSV"]
    end
    SPA -->|"client.ts：Bearer JWT<br/>401 全局跳登录"| ADM["/api/v1/admin/*"]
    BUILD["npm run build"] --> DIST["dist"] -->|"服务端同域托管，无 CORS"| SPA
```

UI 只是裁剪入口，**服务端每端点独立鉴权**——member 直连 API 一律 403（双层兜底）。

---

## 7. 插件架构

```mermaid
flowchart LR
    subgraph HOST["QwenPaw 宿主"]
        DATA[("agents 注册表<br/>token_usage.json")]
    end

    subgraph PLG["deptagent-link 插件"]
        MAIN["main.py<br/>on_activate / on_deactivate"] --> SCHED["scheduler.py<br/>三通道周期任务（宿主托管）"]
        SCHED --> ADP["adapters/<br/>base 协议 + qwenpaw_2_3"]
        ADP --> COL["collectors/<br/>heartbeat / agents / usage"]
        COL --> UPL["uploader.py<br/>seq + 401/409 状态机"]
        PANEL["panel.py<br/>六个本地端点"] <--> UI["ui/index.js<br/>员工面板 · 30s 轮询"]
        BIND["binding.py<br/>邀请码绑定"] <--> PANEL
    end

    DATA --> ADP
    UPL -->|"POST 遥测"| SRV["deptagent-server"]
    PANEL -->|"状态/同步/暂停/重绑"| SCHED
    PLG <--> FILES[("plugin-data/<br/>binding·seq·status<br/>watermark·paused")]
```

**宿主升级适配 = 新增一个 `adapters/qwenpaw_X_Y.py` + `detect_format` 分支**，collectors / uploader / 服务端零改动。

---

## 8. 插件生命周期

```mermaid
stateDiagram-v2
    [*] --> Loaded: 宿主加载
    Loaded --> Unbound: 未绑定（面板引导）
    Unbound --> Running: 邀请码绑定成功
    Running --> Stopped: 卸载插件
    note right of Stopped: plugin-data 不删除<br/>重装自动恢复绑定与水位
    Stopped --> [*]
```

---

## 9. 权限模型

| 能力 | member | lead | admin | super |
|---|:-:|:-:|:-:|:-:|
| 插件面板（本人设备） | ✅ | ✅ | ✅ | ✅ |
| 驾驶舱 / 台账 / 用量 | ❌ | ✅ | ✅ | ✅ |
| 员工 / 邀请码 / 吊销设备 | ❌ | ❌ | ✅ | ✅ |
| 账号治理（建号/改角色/停用） | ❌ | ❌ | ❌ | ✅ |

JWT 只承载身份，**角色每请求查库**——改角色/停用即时生效，无需等 token 过期。

---

## 10. 部署形态

```mermaid
flowchart LR
    subgraph WIN["员工 Windows 机 ×N"]
        QP["QwenPaw :8088"] --- PLG["插件 deptagent-link"]
    end
    subgraph LIN["部门服务器（单机内网）"]
        UV["uvicorn :8024"] --- DB[("deptagent.db<br/>建议绝对路径 + 单实例")]
    end
    BR["管理员浏览器"] --> UV
    PLG -->|"HTTP :8024"| UV
    OPS["运维：备份 = 停服拷贝 db<br/>机密 = DEPTAGENT_JWT_SECRET 环境变量"] -.-> UV
```

配置项：`DEPTAGENT_JWT_SECRET`（必填）· `DEPTAGENT_DB_PATH`（绝对路径）· `DEPTAGENT_CONSOLE_DIST`（可选覆盖）。

---

## 11. 质量保障与 CI

```mermaid
flowchart LR
    PUSH["git push"] --> CI["GitHub Actions"]
    CI --> J1["server job<br/>ruff + pytest 93"]
    CI --> J2["plugin job<br/>pytest 39（含真 server 进程内端到端冒烟）<br/>+ 官方 check --runtime<br/>+ bundle 语法"]
    J1 --> OK["main 绿灯"]
    J2 --> OK
    LOCAL["本地验收链"] -.->|"Playwright 截图取证"| OK
```

---

## 12. 二次开发扩展点

| 想做什么 | 改哪里 |
|---|---|
| 新增遥测通道 | `collectors/` 新文件 + `scheduler.py` 注册 + 服务端 `telemetry.py` 载荷段 + 新编号迁移 |
| 适配新版 QwenPaw | `adapters/qwenpaw_X_Y.py`（实现 AgentReader 协议）+ `detect_format` 分支 + `check --runtime` 验证 |
| 新增管理页面 | `console/src/pages/` + `client.ts` + 服务端 `core/` `api/` + `app.py` 挂路由 |
| 数据库变更 | `storage/migrations.py` **追加**新编号（不改历史版本） |
| 新增治理动作 | `api/` 端点 + `audit_log` 留痕 + 管理端入口（参考吊销设备） |

---

## 13. 目录结构

```
DeptAgent-Hub/
├── server/src/deptagent/{api,core,storage}/     FastAPI + SQLite（93 项测试）
├── console/src/{api,components,pages}/          React SPA（dist 由服务端托管）
├── client-plugin/deptagent-link/                插件（adapters/collectors/ui + 6 个 py）
├── client-plugin/tests/                         插件 39 项测试 + 端到端冒烟
├── docs/{SPEC.md, architecture.md, status.md, images/}
└── .github/workflows/ci.yml                     CI 双 job
```
