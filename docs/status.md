# DeptAgent-Hub 进程记录

> 更新纪律：每次编码会话结束时更新"当前状态"与"已完成"两节；细节看 git log 与 docs/tasks/*.md，本文件只记"进行到哪、卡在哪"。
> 完成动作链：task.md 打勾 + 填 commit hash → 本文件"已完成"加一行 → 随代码一起 commit。

## 当前状态
- 阶段：1（MVP 竖切）
- 当前任务：T1.9 员工与设备页完成；下一步 T1.10 智能体台账页（六列 + 筛选 + 详情抽屉）
- 后挂事项：无（origin/main = 40372cd = 本地 HEAD；后续每任务 commit 后照常 L3+push）
- 最后更新：2026-11-10

## 已完成
- [x] SPEC v0.5 评审修订完成（commit d8ad44d）
- [x] T0.2–T0.7 server：commit 1a67e0f；T0.8 console+CI：commit f7e02d2（单测 29 全绿 + ruff + 真机冒烟闭环）
- [x] 真机冒烟（uvicorn + curl）：/health、console 静态挂载、super 登录、一次性密码建 admin、403/401 矩阵、锁定、停用即失效、审计 5 行落库
- [x] T0.9 插件真机 spike：QwenPaw 宿主升级 2.3.0b3 后全链路通过（安装→激活→禁用→重启用，check --runtime 全绿；实测结论见下方环境事实）
- [x] SPEC v0.6 版本口径修正（用户拍板“更新为最新”）：断言版本 v2.2.2→v2.3.0b3；manifest min 2.2.2→2.3.0（2.2.x 宿主缺新 SDK 实测不兼容，宿主 pre-release 归一化比较使 2.3.0b3 真机满足 min）；格式族标签/适配器 2_2→2_3
- [x] T0.10 之 14.1 第 8 条逐项走查：①init-super ②super 建 admin ③角色即时生效（JWT 不携带角色、每请求查库）④admin 治理端点 403 ⑤自我提权拒绝 ⑥旧密码立即失效 ⑦lead 无写入口（本次补测 test_lead_cannot_call_any_governance_endpoint，API 层；console 登录页入口 T1.8 交付后复验）⑧审计全留痕；单测 29→30 全绿 + ruff 全过
- [x] T1.1 插件包骨架：client-plugin/deptagent-link/{plugin.json,main.py}；check --runtime 全绿（ok/compatible/load+activation+cleanup 全 passed，宿主日志确认 registered）；决策点 D1/D2/D3/D5/D7/D8/D11 按倾向值拍板落定
- [x] T1.2 调度器与生命周期：scheduler.py（D2 拍板频率 5/15/5 min 三通道 + Stale 安静停机 + storage 三键集中声明）+ main.py 接入 on_activate；关键发现：插件后台任务必须走 context.resources.task() 托管（裸 create_task → check 报 unhosted_task/cleanup failed）；resources 还提供 connection/thread/process 托管（T1.4 HTTP 客户端可用）
- [x] T1.3 绑定链路：服务端 core/bind.py + api/bind.py（限速/一次性/一人多机/停用拒绝）+ 迁移 002 invitations + 插件 binding.py + requirements.txt（httpx）；**SPEC v0.7 源码校准**：2.3.0b3 SDK 无插件侧 secrets 写 API（config 仅只读快照），设备令牌改存 binding.json（本机域+可吊销兑底）；8.2 协议补 name? 字段（users.name NOT NULL 原协议缺）；单测 30→40 全绿 + check --runtime 全绿
- [x] T1.4 上报端点骨架：api/telemetry.py（Bearer 鉴权 + seq CAS 防重放 + 宽松校验 + plugin_latest 响应）；三段入库钩子就位（_store_heartbeat/agents/usage，T1.5–T1.7 逐链填充）；坑：FastAPI Annotated 依赖必须 Depends() 包装（裸函数会被当 Form 触发 python-multipart 错误）；单测 40→46 全绿
- [x] T1.5 心跳通道：插件 collectors/heartbeat.py（3.4 ①全 8 字段含 reporting_paused 隐私开关）+ uploader.py（seq 自增 async.Lock 防三通道交错 + 401 红灯停报 + 409 seq 重置）+ config.py（STORAGE_FILES 集中声明解导入环，PLUGIN_VERSION/ACTIVATED_AT 共享）；服务端 _store_heartbeat（7.1 白名单 7 列 COALESCE 宽松语义）；吊销链路端到端实测通过（真 server + 真 uploader：吊销→401 token_revoked→UploadStopped→telemetry_status 写 revoked→红灯检查 True）；单测 46→48 全绿 + check --runtime 全绿
- [x] T1.6 台账通道：插件 adapters/{base,qwenpaw_2_3}.py（3.12 包结构落地：working_dir 定位复刻宿主 constant.py 优先级 + AgentReader 协议 + detect_format 降级判定；2.3 格式族读真机 config.json agents.profiles + workspace agent.json 仅取 name/description/enabled）+ collectors/agents.py（asyncio.to_thread 文件 IO）；服务端迁移 003 agents 表 + _store_agents UPSERT（8.1 归属：owner=令牌对应员工、维护人默认同创建人；7.1 白名单：客户端只可更新 name/description/last_seen，status INSERT 首写 new、blocked 永不被覆盖；多员工同名 key 各自成行）；心跳 format_probe 接真实探测；端到端冒烟：真机双智能体全链路落库；单测 48→50 全绿 + check --runtime 全绿；4ae8241+a50bd7c 网络自愈后已推送（1ed99b8..a50bd7c）
- [x] T1.7 用量通道：插件 collectors/usage.py（3.6 增量算法：当日全量重传 + 历史日 md5 指纹变化重传，上报成功才 commit 水位，90 天窗口外不报不记）+ adapters read_usage（真机 token_usage.json {date: {key: {...}}}，旧记录无 agent_id/cache_* 归一）+ scheduler 三通道接真实增量；服务端迁移 004 usage_daily 表 + usage_report VIEW（7.2 双 source 合并）+ _store_usage（归属解析仅限本人台账、agent_id=0 哨兵、team INSERT 首写快照、provider/model None 归一空串防 UNIQUE NULL 不判重）；端到端冒烟：真机今日 3 条上报落库 + 103 天前窗口外跳过 + 两轮重传幂等；单测 50→54 全绿 + check --runtime 全绿
- [x] T1.8 console 登录页：client.ts 重构（Session 对象存 localStorage：token/expires_at/role/display_name + isSessionExpired 主动过期检查 + login 请求 auth:false 不走全局 401 跳转——登录失败文案直抛表单）+ LoginPage（服务端 8.5 中文文案展示）+ RequireAuth 路由守卫（未登录/过期 → /login；有效会话访问 /login → /）+ AppLayout（用户信息 + 退出登录）；浏览器三场景实测（守卫/失败文案/成功+退出）+ 锁定文案链路验证全过；tsc + vite build 全过（commit 40372cd，用户自推 T1.7+fix(ci)，本轮补推 T1.8）
- [x] T1.9 员工与设备页：服务端 core/employees.py + api/employees.py 五端点（员工分页聚合/邀请码生成列表/设备子表/令牌吊销；AdminUser 门槛 admin+super；在线灯 3×心跳周期；DA-XXXXXXXX 邀请码；吊销幂等 + 审计 invitation.create/device.revoke）+ console EmployeesPage（心跳灯/角色裁剪导航/邀请码面板/设备展开/吊销确认）+ **SPA 深链接 fallback 补丁**（SPAStaticFiles：非 API 404 → index.html，API 保持 8.5 JSON；Windows path 分隔符坑改用 scope 原始路径判断）；单测 54→67 全绿（+10 employees + 3 SPA）+ ruff format/check 全过 + tsc/vite build + 浏览器 18/18 实测（含 lead 导航裁剪/403 文案/吊销链路）

## 卡点 / 待拍板（SPEC 15 章）
- 已拍板（2026-11-10，用户授权按倾向值落定）：D1 插件命名 deptagent-link、D2 上报频率 5/15/5 min（用量/台账/心跳）、D3 回灌深度台账全量+用量 90 天、D5 员工仅插件面板、D7 注册模式 closed、D8 官方前端插件（PawApp 数据层）、D11 Argon2id（既成实现）；此前 D6 License=Apache-2.0
- 阶段 3 前：D4 网关实现、D9 网关智能体识别、D10 QwenPaw 429 提示实测
- T1.11 前：图表库 ECharts / Recharts（SPEC 4.1 遗留空白）

## 环境事实（中断后恢复用）
- 本地 git：remote origin = https://github.com/lmy-2024/DeptAgent-Hub.git，已推送至 eba2060；本地新增阶段 0 收口 commits（6f278d8 + 回填）与 tag stage-0 待推送；GitHub Actions CI（lint+单测）已首次触发
- 4 个参考仓库（QwenPaw-main 等）已确认从未被 git 跟踪，.gitignore 已加排除规则
- 宿主机 Windows + PowerShell 5.1：命令连接用 `;`，不用 `&&`
- Python 3.14 + server/.venv 独立虚拟环境（依赖全隔离，pip 清华源安装）；服务启动：`server\.venv\Scripts\python.exe -m uvicorn deptagent.app:create_app --factory`，需设 `DEPTAGENT_DB_PATH` / `DEPTAGENT_JWT_SECRET`
- Node v22 + console 依赖 npmmirror 镜像；构建 `cd console; npm run build`（tsc + vite 全过）
- 校验依据只读：QwenPaw-main v2.3.0b3 源码（SPEC 源码断言基于此版本）
- QwenPaw 真机宿主 `D:\project\Qwenpaw`（独立 venv，Python 3.11）：已升级 qwenpaw 2.3.0b3 + typesafe-sdk 0.7.5（2026-11-10），与参考源码版本对齐；宿主运行于 `http://127.0.0.1:8088/api`
- 插件 check 命令在 Windows 必须带 `PYTHONUTF8=1`（如 `$env:PYTHONUTF8="1"; python -m qwenpaw.plugins.check <目录> --runtime`）：工具静态读取用默认编码，GBK 下读 UTF-8 中文插件文件报 invalid-input/syntax；宿主 loader 显式 utf-8 不受影响。T1.14 CI 接入 check 时必须固定此环境变量
- 插件 check --runtime 的 **cwd 陷阱（2026-11-10 实测）**：工具把 `<frozen importlib._bootstrap>` 等伪文件名用 `Path.resolve()` 归因，Windows 下 `<>` 是合法路径字符，解析结果落在 **cwd**——若 cwd 在插件目录内，宿主自身 import 的全部模块执行（loop/browser/memory 等 317 个模块）被误归因为插件私有调用（runtime-private-call 误报、ok=false）。**必须从插件目录外运行**（directory 传绝对路径）；T1.14 CI 接入时同时固定 cwd 与 PYTHONUTF8
- T0.9 实测结论（2026-11-10，宿主 2.3.0b3）：① `qwenpaw plugin install <本地目录>` 自动走 REST 热装（`POST /plugins/install`），安装至 `~/.qwenpaw/plugins/hello-sdk`，立即加载 active；② `POST /plugins/{id}/enabled`（body `{"enabled": false/true}`）禁用 = 卸载实例保留文件（clean+quiescent，无需重启），重新启用 = 从磁盘重载 active；③ `python -m qwenpaw.plugins.check <目录> --runtime` 返回 ok=true、load/activation/cleanup 全 passed、compatibility=compatible；④ SPEC 3.2 各断言（安装位置、PluginContext 导入、manifest 校验、模块级 plugin 实例）真机均成立；⑤ 旧宿主 2.2.2.post1 不兼容新 SDK（缺 PluginContext），升级是硬前提
