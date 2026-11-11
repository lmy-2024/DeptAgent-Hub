# DeptAgent-Hub 工程架构

> 读者：第一次接触本仓库的开发者 / 部署者。目标：5 分钟建立全局认识——系统由什么组成、数据怎么流、代码在哪、要扩展该改哪里。
> 权威口径：需求与验收看 [SPEC.md](SPEC.md)；安装使用看 [README](../README.md)；本文只讲架构与实现机制。

---

## 1. 系统总览

三个物理组件，一条自下而上的数据流：

```
┌──────────────────── 员工电脑（每台一台） ────────────────────┐
│  QwenPaw 宿主 (≥ 2.3.0)                                      │
│   └─ 插件 deptagent-link（本仓库 client-plugin/）             │
│      ├─ 采集：心跳 / 智能体台账 / Token 用量                   │
│      ├─ 上报：HTTP POST + Bearer 设备令牌 + seq 防重放         │
│      └─ 面板：QwenPaw 设置内的员工页（信号灯/暂停/绑定）          │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP :8024
┌──────────────────────────▼─────────────── 部门服务器 ─────────┐
│  deptagent-server（FastAPI + SQLite，server/）                │
│   ├─ /api/v1/bind         邀请码绑定（签发设备令牌）            │
│   ├─ /api/v1/telemetry/report  三通道上报（CAS + UPSERT 落库） │
│   ├─ /api/v1/admin/*      管理端点（员工/台账/用量/驾驶舱）      │
│   └─ /                    托管 console/dist 管理端静态站点      │
└──────────────────────────┬───────────────────────────────────┘
                           │ 浏览器访问 http://<server>:8024/
┌──────────────────────────▼───────────────────────────────────┐
│  管理端 console（React SPA，console/）：驾驶舱 / 员工与设备 /   │
│  智能体台账 / 用量分析                                          │
└──────────────────────────────────────────────────────────────┘
```

**五条设计原则**（贯穿全部代码）：

1. **控制面与员工端分离**：服务端只存「谁在用、用了多少」的摘要数据；员工端不给员工增加操作负担（装插件 + 输一次邀请码即可）。
2. **竖切交付**：每条遥测通道 = 采集 → 端点 → UPSERT 落库 → 页面可查，一条链独立闭环（心跳 T1.5 / 台账 T1.6 / 用量 T1.7）。
3. **隐私最小化**：只上报设备标识、智能体元数据、Token 数量；**不传对话内容、文件、提示词、剪贴板**。
4. **幂等与防重放**：设备级 seq 单调递增（服务端 CAS 拒绝旧包）；SQLite UPSERT 重复上报不重复累加。
5. **优雅降级**：宿主数据格式不认识时降级为「仅心跳」（面板橙灯），不影响宿主正常使用；断网红灯可重试、吊销红灯停报待重绑。

---

## 2. 组件一：服务端 `server/`

### 2.1 分层

```
server/src/deptagent/
├── app.py                # 组装：配置 → DB → 迁移 → 中间件 → 路由 → 静态托管
├── config.py             # Settings（全部来自环境变量，机密不入库）
├── __main__.py           # CLI：python -m deptagent --init-super
├── api/                  # FastAPI 路由层（薄壳：参数校验 + 调用 core + 响应模型）
│   ├── auth.py           #   登录 / 会话
│   ├── accounts.py       #   账号治理（super：建 admin/lead、改角色、停用）
│   ├── bind.py           #   /api/v1/bind 邀请码绑定
│   ├── telemetry.py      #   /api/v1/telemetry/report 遥测上报
│   ├── employees.py      #   员工列表/邀请码/设备子表/吊销
│   ├── agents.py         #   智能体台账列表 + 详情
│   ├── usage.py          #   用量聚合 + CSV 导出
│   ├── dashboard.py      #   驾驶舱单端点
│   └── deps.py           #   鉴权依赖（AdminUser / LeadUser / DeviceToken）
├── core/                 # 业务层（纯逻辑 + SQL，可单测）
│   ├── auth.py           #   Argon2id 校验 + JWT 签发 + 失败锁定
│   ├── bind.py           #   邀请码消费、设备令牌签发/吊销、server_config
│   ├── employees.py      #   员工聚合、在线判定（15 分钟心跳窗口）
│   ├── agents.py         #   台账六列 JOIN + 详情（用量序列/时间线）
│   ├── usage.py          #   四维 × 日/周/月聚合 SQL、CSV 宽表
│   ├── dashboard.py      #   KPI 四卡 + 离线告警 + 30 天趋势补零
│   ├── security.py       #   密码哈希、令牌哈希
│   ├── errors.py         #   统一错误体 {error:{code,message,detail}}（8.5）
│   └── utc.py            #   时间口径
└── storage/              # 持久层
    ├── database.py       #   SQLite 连接（WAL）+ write_transaction 事务封装
    └── migrations.py     #   编号迁移（幂等，schema_version 表）
```

### 2.2 启动流程（`create_app`）

```
load_settings()（环境变量）
  → Database(db_path)（WAL 模式）
  → migrate()（应用未执行的编号迁移）
  → 登录限速器 / 全局异常处理器（8.5 错误体）
  → 挂 API 路由（/api/*）
  → console/dist 存在则挂 SPAStaticFiles（深链接 fallback 到 index.html，API 404 保持 JSON）
```

### 2.3 端点地图

| 分组 | 端点 | 鉴权 |
|---|---|---|
| 健康 | `GET /health` | 无 |
| 认证 | `POST /api/v1/auth/login` | 无（失败锁定 5 次 / 15 分钟） |
| 绑定 | `POST /api/v1/bind` | 邀请码（IP 限速 10 次/分钟） |
| 遥测 | `POST /api/v1/telemetry/report` | **设备令牌**（Bearer） |
| 账号治理 | `/api/v1/admin/accounts*` | **super** |
| 员工与设备 | `GET /api/v1/admin/employees`、`POST /api/v1/admin/invitations`、`GET /api/v1/admin/employees/{id}/devices`、`POST /api/v1/admin/devices/{id}/revoke`、`GET /api/v1/admin/invitations` | admin+ |
| 智能体台账 | `GET /api/v1/admin/agents`、`GET /api/v1/admin/agents/{id}` | lead+ |
| 用量分析 | `GET /api/v1/admin/usage/aggregate`、`GET /api/v1/admin/usage/export` | lead+ |
| 驾驶舱 | `GET /api/v1/admin/dashboard` | lead+ |

### 2.4 数据模型

```
users ──1:N── devices          （一人多机；devices.token_hash 唯一）
users ──1:N── agents           （UNIQUE(owner_user_id, agent_key)：同名 key 只在本人员工内唯一）
users ──1:N── usage_daily      （agent_id=0 为「未归属用量」哨兵）
usage_daily + VIEW usage_report（上报计量 source='client' 与网关计量 source='gateway' 合并，
                                gateway 优先：同一 (日期,用户,智能体,厂商,模型) 有网关行则屏蔽客户端行）
invitations（code 主键，一次性，默认 72h）
audit_log（治理动作全留痕：登录/建号/邀请码/吊销…）
schema_version（迁移版本）
```

关键字段语义（详见 `migrations.py` 注释）：

- `devices.last_seq`：设备级上报水位，服务端 CAS 推进，防重放/防乱序。
- `devices.last_format_probe`：最近一次心跳上报的宿主格式探测结果（`qwenpaw-2.3` / `format_mismatch`），管理端可见的降级事件。
- `agents.status`：`new`（首次上报自动登记）→ 客户端不可覆盖 `blocked`（管理员封停优先）。
- `usage_daily.team`：**入库时点**科室快照——调岗不重算历史报表。
- `usage_daily.UNIQUE(stat_date, user_id, agent_id, provider_id, model, source)`：UPSERT 幂等的骨架。

### 2.5 三个关键机制

1. **seq 防重放（8.5）**：`UPDATE devices SET last_seq=? WHERE id=? AND last_seq<?`，`rowcount != 1` → `409 seq_conflict` 整包拒绝；客户端收到 409 按响应中的 `last_seq` 重置本地序号后重报。
2. **字段白名单（7.1）**：上报只允许改设备 8 个字段、智能体 3 个字段（name/description/last_seen）；其余列服务端权威。
3. **宽松覆盖语义**：心跳字段 `None` 不清空旧值（COALESCE），宿主升级后字段消失不会把已有信息冲掉。

---

## 3. 组件二：管理端 `console/`

- 技术栈：React 19 + React Router 7 + Vite 6 + TypeScript + ECharts（按需引入，`EChart.tsx` 薄封装：init/dispose + setOption + ResizeObserver）。
- 运行形态：`npm run build` 产出 `console/dist`，由服务端同域托管——**无独立前端服务、无跨域配置**；开发期可 `npm run dev`。

| 文件 | 职责 |
|---|---|
| `src/api/client.ts` | 会话管理（localStorage：token/expires_at/role/display_name）+ 全局 401 跳转 + 各端点请求函数 |
| `src/App.tsx` | 路由 + RequireAuth 守卫（未登录/过期 → /login） |
| `src/pages/LoginPage.tsx` | 登录（服务端 8.5 中文错误文案直显） |
| `src/pages/AppLayout.tsx` | 顶栏（用户/退出）+ 导航（**按角色裁剪**：驾驶舱/台账/用量仅 lead+） |
| `src/pages/DashboardPage.tsx` | 驾驶舱：KPI 四卡 + 离线告警 + 趋势/Top 双图 |
| `src/pages/EmployeesPage.tsx` | 员工与设备：邀请码面板、在线灯、设备展开、吊销 |
| `src/pages/AgentsPage.tsx` | 智能体台账：六列 + 筛选 + 详情抽屉（SVG 曲线/时间线） |
| `src/pages/UsagePage.tsx` | 用量分析：四维 × 日/周/月 + 双图 + CSV 导出 |

权限双层兜底：UI 只是裁剪入口，服务端每个端点独立鉴权（member 直连 API 一律 403）。

---

## 4. 组件三：员工端插件 `client-plugin/deptagent-link/`

### 4.1 生命周期（`main.py`）

```
宿主加载插件
  → on_activate(context)
      ├─ 注册 PawApp 前端路由（CUSTOM_APPS，路径 /plugin/deptagent-link/panel）
      └─ 启动调度器（必须走 context.resources.task() 托管——裸 create_task 会被检查报 unhosted_task）
  → on_deactivate：取消任务、清理
```

### 4.2 三通道调度（`scheduler.py`）

| 通道 | 周期 | 内容 |
|---|---|---|
| 心跳 heartbeat | 5 分钟 | 设备在线、宿主/插件版本、格式探测、暂停状态 |
| 智能体台账 agents | 15 分钟 | 智能体元数据（名称/描述/状态） |
| Token 用量 usage | 5 分钟 | 按日增量：当日全量重传 + 历史日 md5 指纹变化才重传，90 天窗口 |

调度器统一拦截：未绑定不发；`telemetry_status` 处于 `revoked/invalid`（红灯）不发；用户暂停时台账/用量跳过、心跳保持并携带 `reporting_paused`（管理端显示「已暂停」而非离线）。

### 4.3 分层：适配器隔离宿主格式

```
adapters/base.py           # AgentReader 协议 + detect_format()（不认识的格式返回 None）
adapters/qwenpaw_2_3.py    # QwenPaw 2.3 格式族实现：定位数据目录、读 agents 注册表、读 token_usage.json
collectors/*.py            # 纯采集：调 adapter → 归一成协议 JSON（不碰 HTTP）
uploader.py                # seq 自增（async.Lock）+ POST + 401/409 状态机
```

宿主升级策略：新增 `adapters/qwenpaw_X_Y.py` + `detect_format` 分支即可，collectors/uploader/服务端零改动。

### 4.4 本地状态文件（`~/.qwenpaw/plugin-data/deptagent-link/`）

| 文件 | 内容 | 丢了会怎样 |
|---|---|---|
| `binding.json` | server_url / 设备令牌 / 员工号 / server_config | 需重新输邀请码绑定 |
| `seq.json` | 上报序号水位 | 服务端 409 自动纠正（不重复计费） |
| `telemetry_status.json` | 上报状态（ok/error/revoked/invalid…） | 红灯状态丢失，可能多试一次 |
| `watermark.json` | 用量增量水位（按日 md5 指纹） | 下轮全量重传（服务端幂等，不重复累加） |
| `today_report.json` | 今日已上报（面板透明展示） | 仅面板展示重置 |
| `reporting_paused.json` | 暂停开关 | 恢复上报 |

**卸载插件不删除此目录**——重装自动恢复绑定。

### 4.5 员工面板（PawApp）

`panel.py` 六端点（挂宿主 `/api/deptagent-link/*`）：`/status`（脱敏，无 token）、`/sync`（手动同步，锁防抖）、`/pause`、`/bind`、`/rebind`、`/diagnostics`（快照导出）。
`ui/index.js` 单文件 IIFE bundle（React/antd 取宿主 `window.QwenPaw.host`，不重复打包）：隐私承诺 + 绑定卡 + 三通道信号灯 + 今日已上报 + 操作四件，30 秒轮询。

---

## 5. 一次上报的完整链路（时序）

```
调度器 tick
  → adapter 读宿主文件（asyncio.to_thread，不阻塞事件循环）
  → collector 归一为协议 JSON        ┐
  → uploader：seq = +1（文件锁）      │ 插件侧（CPU ≈0ms）
  → POST /api/v1/telemetry/report     ┘
       Bearer 设备令牌
       服务端：verify token → seq CAS → 三段 UPSERT（同事务）
  → 200 {plugin_latest, server_config} → 水位 commit + 状态 ok
       401 → 写红灯 revoked/invalid（停报，待重绑）
       409 → 按服务端 last_seq 重置本地序号，下轮重报
       网络失败 → 状态 error（可重试），水位不动（下轮重发，幂等）
```

管理端任何页面查询的都是已落库数据，与上报解耦（页面无缓存，天然拿到最新）。

---

## 6. 权限模型（四角色）

| 能力 | member | lead | admin | super |
|---|---|---|---|---|
| QwenPaw 插件面板（本人设备） | ✅ | ✅ | ✅ | ✅ |
| 驾驶舱 / 智能体台账 / 用量分析 | ❌ | ✅ | ✅ | ✅ |
| 员工列表 / 邀请码 / 吊销设备 | ❌ | ❌ | ✅ | ✅ |
| 账号治理（建号/改角色/停用） | ❌ | ❌ | ❌ | ✅ |

实现：JWT 仅承载身份，**角色每请求查库**——改角色/停用即时生效，无需等 token 过期。

---

## 7. 部署与运行形态

- 单机内网部署：一个 uvicorn 进程 + 一个 SQLite 文件（建议 `DEPTAGENT_DB_PATH` 绝对路径，只跑一个实例）。
- 端口：服务端 8024；员工机 QwenPaw 宿主 8088（插件通过宿主 API 安装）。
- 机密：`DEPTAGENT_JWT_SECRET` 环境变量注入；设备令牌服务端只存哈希。
- 备份：停服拷贝 `deptagent.db`（含 -wal/-shm）；员工端状态在 `plugin-data/`（可不备）。

---

## 8. 质量保障

| 层 | 手段 |
|---|---|
| 服务端 | 93 项 pytest（权限矩阵/绑定/遥测/台账/用量/驾驶舱/SPA）+ ruff check/format |
| 插件 | 39 项 pytest：面板/诊断/三通道**进程内真 server 端到端冒烟**（真 uvicorn + 临时 SQLite + 真 uploader）+ 绑定红灯/格式降级专项 |
| 宿主兼容 | 官方 `qwenpaw.plugins.check --runtime`（load/activation/cleanup + 私有调用扫描），CI 必跑 |
| 管理端 | tsc + vite build；浏览器实测（Playwright 截图取证） |
| CI | GitHub Actions 双 job：server（lint+test）/ plugin（pytest + check --runtime + bundle 语法） |

---

## 9. 二次开发扩展点

| 想做什么 | 改哪里 |
|---|---|
| 新增遥测通道 | `collectors/` 新文件 + `scheduler.py` 注册任务 + 服务端 `api/telemetry.py` 载荷段 + `_store_xxx` UPSERT + 建表迁移 |
| 适配新版 QwenPaw | `adapters/qwenpaw_X_Y.py`（实现 AgentReader 协议）+ `detect_format` 新分支；跑 `check --runtime` 验证 |
| 新增管理页面 | `console/src/pages/` + `client.ts` 请求函数 + 服务端 `core/` + `api/` + `app.py` 挂路由 |
| 数据库变更 | `storage/migrations.py` **追加**新编号迁移（不改历史版本） |
| 新增治理动作 | `api/` 端点 + `audit_log` 留痕 + 管理端入口（参考吊销设备） |

---

## 10. 目录结构（仓库根）

```
DeptAgent-Hub/
├── server/                      # 服务端（FastAPI + SQLite）
│   ├── src/deptagent/{api,core,storage}/ + app.py/config.py/__main__.py
│   └── tests/                   # 93 项单测
├── console/                     # 管理端 React SPA（dist 由服务端托管）
│   └── src/{api,components,pages}/
├── client-plugin/
│   ├── deptagent-link/          # QwenPaw 插件
│   │   ├── main.py / scheduler.py / uploader.py / binding.py / panel.py
│   │   ├── diagnostics.py / state.py / config.py
│   │   ├── adapters/ collectors/ ui/
│   │   └── plugin.json
│   └── tests/                   # 插件 39 项单测 + 三通道端到端冒烟
├── docs/
│   ├── SPEC.md                  # 需求与验收唯一事实来源
│   ├── tasks/stage-1-mvp.md     # 阶段任务与验收记录
│   ├── status.md                # 进度与卡点
│   ├── architecture.md          # 本文
│   └── images/                  # README 截图
└── .github/workflows/ci.yml     # CI 双 job
```
