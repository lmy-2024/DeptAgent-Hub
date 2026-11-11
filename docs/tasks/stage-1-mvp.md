# 阶段 1：MVP（遥测闭环 + 管理端五页）

> 验收锚点：SPEC 14.1 全 8 条 + SPEC 3.11 插件验收
> 里程碑（SPEC 11 章阶段 1 行）：10 名试点员工数据上墙
> 前置：阶段 0 收口；开工前拍板 D2/D3/D5/D7（SPEC 15 章，均有倾向值）；真机宿主 qwenpaw 2.3.0b3 已就位（T0.9 实测），插件任务可真机验证
> 竖切纪律：每条链 = 插件采集 → 端点 → UPSERT 白名单 → 落库 → 页面可查，逐链交付

## 插件端

## T1.1 插件包骨架
- [x] plugin.json manifest：id=deptagent-link、type=general、entry、qwenpaw_version min=2.3.0、max=3.0.0、sdk 声明（SPEC 3.2 v0.6）
- [x] main.py 导出模块级 plugin 实例（SPEC 3.12 第 2 条）
- [x] `python -m qwenpaw.plugins.check ./deptagent-link` 静态校验通过（实测直跑 --runtime：ok=true、load/activation/cleanup 全 passed、compatible；Windows 需 PYTHONUTF8=1 见 status.md）
- commit: e0559af

## T1.2 调度器与生命周期
- [x] 常驻调度/上报循环只在 on_activate 回调内启动（SPEC 3.2 运行时纪律第 1 条）——实测裸 create_task 会被 check 报 unhosted_task，正确姿势是 context.resources.task()（托管+卸载自动停）
- [x] StaleContextError → 视为正常停机信号安静退出（SPEC 3.7、3.12 第 8 条）——调度循环内捕获 return + CancelledError 传播；托管任务由 resources.close 兜底停
- [x] 离线队列/增量水位/绑定状态存 context.storage（SPEC 3.12 第 5 条）——STORAGE_FILES 集中声明三键，水位读写真机验证（restored_watermark 日志）
- [x] 验证：check --runtime 三次迭代全绿（load/activation/cleanup 全 passed，发现并修复任务托管问题）
- commit: ______

## T1.3 绑定链路
- [x] 服务端 POST /api/v1/bind：IP 限速 10 次/分钟（SPEC 8.2、10.1）——滑动窗口，成功/失败都计数（防枚举）
- [x] 令牌 secrets.token_urlsafe(32) 签发、库存 SHA-256、明文仅绑定响应返回一次（SPEC 10.1）——含一次性原子防线（UPDATE WHERE used_by IS NULL）
- [x] 插件 binding.py：输码 → 存（**v0.7 源码校准**：SDK 无 secrets 写 API，改存 binding.json）→ 触发首次全量上报（run_immediately 机制就位，采集器 T1.5–T1.7）
- [x] 单测：错码/过期码/枚举限速（10 个测试：含一次性/一人多机/停用员工/密码可登录；40 全绿）
- commit: ______

## T1.4 上报端点骨架
- [x] POST /api/v1/telemetry/report：Bearer 设备令牌鉴权（SPEC 8.1）——token_hash 反查设备， revoked → 401 token_revoked（与 3.7 吊销链路闭环）
- [x] seq 水位防重放：seq <= devices.last_seq → 409 seq_conflict 整包拒绝（SPEC 8.1、8.5）——CAS 推进（WHERE last_seq < ?）防并发重复受理
- [x] 错误响应统一格式全量接入（SPEC 8.5）——鉴权/防重放/宽松校验（422）/响应结构（plugin_latest + server_config）六测试全绿
- commit: ______

## 三通道（每条 = 插件 collector + 服务端 UPSERT）

## T1.5 心跳通道
- [x] collectors/heartbeat.py：SPEC 3.4 ①全字段（含 reporting_paused）
- [x] 服务端 device UPSERT（7.1 白名单：客户端只更新 8 个字段）——COALESCE 宽松语义（None 不覆盖），单测 2 个入库断言
- [x] 吊销链路实测：吊销 → 401 token_revoked → 插件红灯停报（SPEC 3.7、8.5、3.11 第 5 条）——端到端冒烟（真 server uvicorn + 插件 uploader 真代码 + FakeContext）：UploadStopped + telemetry_status 写 revoked + reporting_stopped()=True
- [x] 配套：uploader.py（seq async.Lock + 409 重置）、config.py（STORAGE_FILES 集中声明解导入环）、scheduler 三通道接真实采集器
- commit: ______

## T1.6 台账通道
- [x] collectors/agents.py：SPEC 3.4 ②字段（归属不由客户端自报）——经 adapters 层读真机数据（config.json agents.profiles + 各 workspace agent.json，仅取 id/name/description/enabled 三元组，隐私最小化）
- [x] agents UPSERT：owner_user_id = 首次上报用户、new 状态自动标记（SPEC 8.1 归属语义、5.3）——blocked 不被客户端覆盖、name/description None 不清空、多员工同名 key 各自成行；单测 50 全绿
- [x] 配套：adapters/base.py（working_dir 定位 + AgentReader 协议 + detect_format 降级判定）+ qwenpaw_2_3.py（2.3 格式族）+ 心跳 format_probe 接真实探测
- [x] 端到端冒烟：真机 ~/.qwenpaw 双智能体（default/QA）经适配器→uploader→server 落库，归属/维护人/new 状态断言全过
- commit: ______

## T1.7 用量通道
- [x] collectors/usage.py：SPEC 3.4 ③六项计数（agent_key 可空；不上报 cache_eligible/observed 两字段）——经 adapters/qwenpaw_2_3.py read_usage 读真机 token_usage.json（旧记录无 agent_id/cache_* 归一 None/0）
- [x] 增量算法：当日全量重传（UPSERT 覆盖）、历史日仅变化时重传（SPEC 3.6）——按日 md5 指纹水位，上报成功才 commit（失败/红灯下轮自动重传）；90 天回灌窗口外不报不记水位（D3）
- [x] usage_daily UPSERT：agent_key=null → agent_id=0 哨兵；team 列仅首写（SPEC 7.1、8.1）——归属解析仅限本人台账（跨员工同名 key 不混）、provider/model None 归一空串（UNIQUE 不判 NULL 防重复堆积）；迁移 004（表 + 双索引）+ 单测 54 全绿
- [x] 创建 usage_report VIEW，全部报表走它（SPEC 7.2）——gateway 优先/无 gateway 回退 client，阶段一退化全量 client，VIEW 单测验证双 source 口径
- [x] 端到端冒烟：真机今日 3 条（glm-5.2/deepseek-v4-pro/deepseek-v4.1-flash）上报落库 + 103 天前历史日（2026-07-30）窗口外跳过断言 + 两轮重传幂等（SMOKE T1.7 PASSED）
- commit: ______

## 管理端页面

## T1.8 console 登录页
- [x] 登录表单 + JWT 持有/过期处理（SPEC 4.2 页面地图：登录页页面级交付在阶段 1）——Session（token/expires_at/role）localStorage 持有；RequireAuth 路由守卫（过期主动检查）+ 请求期 401 被动兜底（清 session 回登录页）；登录请求不走全局 401 跳转分支（错误文案直抛表单）
- [x] 401 auth_failed 中文提示（SPEC 8.5）——服务端中文文案原样展示；浏览器实测：错误文案「工号或密码不正确」红色提示不跳转表单保留；锁定文案「失败次数过多，账号已临时锁定」链路 curl 验证（同源同路径）
- [x] 配套：AppLayout 顶栏用户信息 + 退出登录（清 session 回登录页）；已持有效会话访问 /login 直达首页；tsc + vite build 全过；浏览器三场景实测（守卫重定向/登录失败/登录成功+退出）全过
- commit: ______

## T1.9 员工与设备页
- [x] 员工列表：角色/科室/心跳灯/已暂停状态（SPEC 4.2）——服务端 GET /admin/employees 分页聚合（8.5 分页 + 排序白名单 + 科室/关键词过滤）+ 前端表格；心跳灯 = 任一设备 15 分钟内心跳（3×5min 周期 D2），暂停/停用徽标；lead 403 角色门槛 + 导航按角色裁剪（4.2）
- [x] 邀请码生成 UI（科室/角色/有效期/一次性，SPEC 5.2）——POST/GET /admin/invitations；role 仅 member/lead（admin+ 不经邀请码）、DA-XXXXXXXX 8 位码、有效期 1–720h 缺省 72h；生成/使用状态列表 + 复制按钮；审计 invitation.create
- [x] 设备令牌吊销操作（SPEC 4.2、5.2 一人多机子表）——GET /admin/employees/{id}/devices（token_hash 不出管理端）+ POST /admin/devices/{id}/revoke（幂等 + 审计 device.revoke）；浏览器实测吊销后设备变已吊销、活跃设备数 0/1、另设备不受影响；服务端验证吊销令牌上报即 401 token_revoked
- [x] 配套修复：SPA 深链接 fallback（SPAStaticFiles：非 API 路径 404 → index.html，API 保持 8.5 JSON；Windows path 分隔符坑用 scope 原始路径判断）；浏览器 18/18 全过（含 lead 导航裁剪/直接访问 /employees 展示 403 文案）
- commit: ______

## T1.10 智能体台账页
- [x] 台账六列 + 多维筛选 + 排序分页（SPEC 4.2、5.3；分页约定 8.5）——GET /admin/agents（require_lead：member 403 兑底）：名称/功能描述/创建人/维护人/状态/所属科室 + 附加 Token 消耗列（5.3，usage_report 关联子查询）；状态（Literal 422）/科室/关键词筛选 + 排序白名单默认 -last_seen_at + 8.5 分页；阶段 1 只读（治理动作留后续），new=待确认徽标；坑：Query 参数注解引模块级 Literal 别名触发 ruff B008（str 注解不触发），改内联 Literal 保 422 校验
- [x] 详情抽屉：用量曲线、变更时间线（SPEC 4.2）——GET /admin/agents/{id}：全字段 + usage_series（最近 90 天按日，SVG polyline 曲线 + 悬停按日明细）+ 全期汇总三卡（累计 Token/调用次数/活跃天数）+ timeline 快照节点（首次发现/首末用量/最近上报）；空用量显示「暂无用量数据」；浏览器 9/9 全过（lead 导航裁剪/筛选/排序/双抽屉/member 403 文案/深链接刷新）
- commit: ______

## T1.11 用量分析页
- [x] 前置拍板：图表库 ECharts（SPEC 4.1 遗留空白，用户拍板，D12）——echarts/core 按需引入（Line/Bar + Grid/Legend/Tooltip + Canvas，~278KB gzip）+ EChart.tsx 薄包装（init/dispose 生命周期 + setOption notMerge + ResizeObserver 自适应），T1.12 驾驶舱复用
- [x] 四维（人/智能体/模型/科室）× 日/周/月聚合，数据源 usage_report（SPEC 4.2、7.2）——GET /admin/usage/aggregate（LeadUser 门槛；维度/粒度白名单 SQL 片段拼接零注入面；周桶归一到周一日期、月桶 YYYY-MM；缺省窗口 30 天，from>to 422）；agent_id 哨兵/NULL → 未归属智能体、model 双列 group、team 快照 COALESCE
- [x] 排行榜 + CSV 导出 UTF-8 with BOM（SPEC 8.5；成本折算列留阶段 2，4.2"成本折算 2"）——series 本身即排行（total_tokens DESC）；GET /admin/usage/export 宽表 CSV（成员×桶列+合计两列，BOM+CRLF+Content-Disposition）；console blob 下载（JWT 需 header）；单测 75→87 全绿；浏览器 11/11（四维交叉验证/周月桶/窗口过滤/BOM arrayBuffer 验证/403 兑底/深链接）
- commit: ______

## T1.12 驾驶舱
- [x] KPI 卡：智能体总数/活跃数、本月 Token 与成本、活跃员工数、离线设备告警（SPEC 4.2）——GET /admin/dashboard（LeadUser；DashboardResponse 7 字段）；活跃口径 = 近 30 天 usage_report 出现（与台账 status 解耦，阶段 1 status 全 new）；成本不显示（无单价表宁缺毋滥，阶段 2）；console DashboardPage 四卡（fmtTokens 千分位）+ member 首页分流落地提示（不调 API 避免打开即 403，员工侧功能 T1.13 插件面板承接）
- [x] 离线告警排除 reporting_paused=1 设备（SPEC 3.4、4.2 注）——SQL 条件 COALESCE(d.reporting_paused, 0)=0；离线判定 Python 端 is_online()（ISO 带时区偏移的 last_heartbeat 与 sqlite datetime() 字符串比较不可靠）；告警区块红/绿双态 + 暂停设备不泄漏；驾驶舱 NavLink 补 isLead 门控（4.2 导航裁剪补齐）
- [x] 趋势图 + 部门 Top 榜（SPEC 4.2）——服务端 30 天逐日补零（连续时间轴）+ team_top LIMIT 10；EChart 复用（趋势 Line areaStyle + Top Bar 横向）；单测 87→93 全绿（+6 dashboard：403/空态/KPI/离线矩阵/趋势 Top）+ ruff 全绿 + build + 浏览器 9/9（KPI 数值/离线矩阵/双 canvas/导航权限/刷新/403 兑底/JSON 交叉验证）
- commit: ______

## T1.13 员工面板（插件内）
- [x] 按 D8 拍板路径实现：entry.frontend JS bundle + console 插槽/路由/菜单（SPEC 3.8、决策点 D8）——plugin.json entry.frontend=ui/index.js（529 行 IIFE，React/antd 取 window.QwenPaw.host 免重复打包）+ registerRoutes("/plugin/deptagent-link/panel")（非 /apps/ 前缀 → 设置区插件分组，即「QwenPaw 设置内一页」）；数据层 PawApp（app_id=deptagent-link，六端点挂 /api/deptagent-link/*，qwenpaw.plugins.apps 在 PUBLIC_API 白名单内）；console 启动时 usePluginLoader 按需动态加载
- [x] 状态卡：绑定信息/三通道信号灯/今日上报数；操作：立即同步/暂停上报/重新绑定/诊断导出（SPEC 3.8）——GET /status（binding 脱敏无 device_token + 三通道 last_run + today_report）；POST /sync（run_manual_sync 锁防抖 + busy→409）/ /pause（reporting_paused.json 开关：agents/usage 停发、心跳继续携状态，3.4 红线）/ /rebind（clear_binding 连带清 telemetry_status，红灯复位不永久拦截新令牌）/ /diagnostics（快照导出 JSON）；顺带修 scheduler watermark 覆盖 bug（usage 按日指纹被时间戳顶掉 → channels 子键 + state.py 文件锁多写方并发保护 + collect 防御 + commit 自愈）；单测 21 passed + check --runtime 全绿
- [x] 顶部常驻隐私承诺 + "今日已上报内容"透明展示（SPEC 3.4）——Alert 常驻（不上传对话内容/记忆/文件/提示词文本/剪贴板）+ 今日已上报 Statistic×3 + 明细 Table（agent/provider/model/tokens/calls，today_report.json 跨日重置）；真机宿主实测：热装后浏览器 8/8（面板渲染/绑定成功/首次全量上报 1 秒完成 514,678 tokens/手动同步 ok×3/暂停开关/诊断导出下载）+ server 侧 users+devices+agents+usage_daily 四表落库 + 邀请码一次性消费 + last_seq 持续心跳
- commit: ______

## 收口

## T1.14 插件自检与 CI 冒烟
- [x] diagnostics.py：自检/手动同步/诊断导出（SPEC 3.2 包结构）——self_check（本地五项聚合 + 服务器 /health 可达探测，纯只读不发遥测不占 seq；verdict ∈ not_bound/ok/degraded，供 CI 冒烟与 3.9 升级验证流水线消费）+ run_manual_sync/SyncBusyError 统一入口（re-export，实现归 scheduler 单一事实源：周期与手动共用同一套通道编排）+ build_diagnostics（panel /diagnostics 薄壳化，构造逻辑归位）；附修 self_check 水位结构判定（子键缺失 = 从未运行非损坏）
- [x] CI 接入 check --runtime + 三通道冒烟（SPEC 3.9 升级验证流水线）——ci.yml 新增 plugin job：单解释器环境（qwenpaw==2.3.0b3 + fastapi/argon2/pyjwt 并存）跑 pytest client-plugin/tests（30 passed = 21 面板 + 8 诊断 + 1 三通道端到端冒烟：进程内 uvicorn 真 server + 假 QwenPaw 数据目录（QWENPAW_WORKING_DIR 注入）+ 真 binding/collectors/uploader → 四表落库/seq=3/归属解析/未归属哨兵/90 天窗口外不报/今日透明数据断言）+ 官方 check --runtime（cwd 插件目录外 + PYTHONUTF8 固定，Windows 实测两坑带进 CI 纪律）+ node --check bundle；QwenPaw 官方发新版时改版本号重跑即升级验证（通过零动作，失败只发适配器新版）；fakes.py 测试假件公共化 + conftest 注入 server/src
- commit: ______

## T1.15 回归验收与试点上墙
- [x] SPEC 3.11 七项逐条实测（10 分钟上墙/断网补传幂等/卸载无残留/格式破坏降级/吊销停报/资源开销/工具链全绿）——①绑定+首报 0.44~0.81s（远小于 10 分钟）；②断网幂等：停 server → 三通道 failed 且 upload_state=error（可重试非停报）、水位不动 → 起 server → sync 恢复、usage_daily 行数与 token 值逐一等于基线（UPSERT 不重复累加）；③卸载无残留：DELETE 后 frontend_plugin 列表无 deptagent-link（其余 5 插件正常）、/health 200、宿主重启正常、重装自动恢复；④格式破坏降级：写坏 token_usage.json → sync={heartbeat:ok, agents:skipped_degraded, usage:skipped_no_data}（严格仅心跳）、面板 status.collect.degraded=true、server devices.last_format_probe=format_mismatch（管理端事件可见）、恢复文件即回 qwenpaw-2.3；⑤吊销秒级红灯：revoke → 周期心跳 401 → upload_state=revoked（「设备令牌已被吊销，请联系管理员」）→ sync 全 skipped_stopped → 重绑恢复；⑥资源：RSS 增量 2.5MB<20MB（卸载基线 305.7MB vs 装插件 308.2MB）、p95 增量 7.53ms<10ms（外部 /health 探针 55/200 样本）、插件侧采集+序列化 CPU≈0ms<200ms（冒烟测试断言固化）；⑦check --runtime ok:true findings:[] lifecycle load/activation/cleanup 全 passed compatible。**实测抓到并修复三处缺陷**：重绑不清红灯（binding.py 绑定成功后 adelete telemetry_status + test_binding.py 3 用例）；降级链三缺口（probe 检查 token_usage.json 解析失败→None、heartbeat format_probe 落 "format_mismatch" 字符串而非 None（服务端 COALESCE 不覆盖）、panel status 增 collect.degraded + UI 橙灯「数据格式不兼容，已降级为仅心跳上报」+ agents 严格静默 skipped_degraded + test_format_fallback.py 6 用例）；插件单测 33→39 passed
- [x] SPEC 14.1 第 1/2/6/7 条实测（安装 ≤5 分钟/绑定 10 分钟可见/断电恢复/卸载回归）——①真机热装（REST DELETE + install 秒级）+ 输码绑定 0.44s，全流程 <1 分钟；②绑定即见三通道（心跳/台账/用量同轮落库）；⑥server 停起两轮数据无损、客户端自动补传；⑦卸载回归见 3.11-3（列表干净 + 宿主 200 + 重启正常 + 重装自动恢复）
- [x] 10 名试点员工数据上墙；git tag stage-1——EMP001（真机宿主）+ EMP002-EMP010（模拟 9 人：四科室轮换、每人 2 智能体 3 用量行）；终态 users 11 / devices 13 / agents 20 / usage_daily 30（今天 18 + 昨天 12）；管理端浏览器 4/4 实测（驾驶舱 KPI 20/19/626.7k/10 + 双图表、员工与设备 11 人 13 设备、智能体台账 20 行、用量分析 Top10+趋势+CSV），0 console error；Playwright 1440 宽截图存 .smoke-t115/screenshots/
- commit: ______
