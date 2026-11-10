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
- commit: ______

## T1.2 调度器与生命周期
- [ ] 常驻调度/上报循环只在 on_activate 回调内启动（SPEC 3.2 运行时纪律第 1 条）
- [ ] StaleContextError → 视为正常停机信号安静退出（SPEC 3.7、3.12 第 8 条）
- [ ] 离线队列/增量水位/绑定状态存 context.storage（SPEC 3.12 第 5 条）
- commit: ______

## T1.3 绑定链路
- [ ] 服务端 POST /api/v1/bind：IP 限速 10 次/分钟（SPEC 8.2、10.1）
- [ ] 令牌 secrets.token_urlsafe(32) 签发、库存 SHA-256、明文仅绑定响应返回一次（SPEC 10.1）
- [ ] 插件 binding.py：输码 → 存 sdk.secrets → 触发首次全量上报（SPEC 3.5）
- [ ] 单测：错码/过期码/枚举限速
- commit: ______

## T1.4 上报端点骨架
- [ ] POST /api/v1/telemetry/report：Bearer 设备令牌鉴权（SPEC 8.1）
- [ ] seq 水位防重放：seq <= devices.last_seq → 409 seq_conflict 整包拒绝（SPEC 8.1、8.5）
- [ ] 错误响应统一格式全量接入（SPEC 8.5）
- commit: ______

## 三通道（每条 = 插件 collector + 服务端 UPSERT）

## T1.5 心跳通道
- [ ] collectors/heartbeat.py：SPEC 3.4 ①全字段（含 reporting_paused）
- [ ] 服务端 device UPSERT（7.1 白名单：客户端只更新 8 个字段）
- [ ] 吊销链路实测：吊销 → 401 token_revoked → 插件红灯停报（SPEC 3.7、8.5、3.11 第 5 条）
- commit: ______

## T1.6 台账通道
- [ ] collectors/agents.py：SPEC 3.4 ②字段（归属不由客户端自报）
- [ ] agents UPSERT：owner_user_id = 首次上报用户、new 状态自动标记（SPEC 8.1 归属语义、5.3）
- commit: ______

## T1.7 用量通道
- [ ] collectors/usage.py：SPEC 3.4 ③六项计数（agent_key 可空；不上报 cache_eligible/observed 两字段）
- [ ] 增量算法：当日全量重传（UPSERT 覆盖）、历史日仅变化时重传（SPEC 3.6）
- [ ] usage_daily UPSERT：agent_key=null → agent_id=0 哨兵；team 列仅首写（SPEC 7.1、8.1）
- [ ] 创建 usage_report VIEW，全部报表走它（SPEC 7.2）
- commit: ______

## 管理端页面

## T1.8 console 登录页
- [ ] 登录表单 + JWT 持有/过期处理（SPEC 4.2 页面地图：登录页页面级交付在阶段 1）
- [ ] 401 auth_failed 中文提示（SPEC 8.5）
- commit: ______

## T1.9 员工与设备页
- [ ] 员工列表：角色/科室/心跳灯/已暂停状态（SPEC 4.2）
- [ ] 邀请码生成 UI（科室/角色/有效期/一次性，SPEC 5.2）
- [ ] 设备令牌吊销操作（SPEC 4.2、5.2 一人多机子表）
- commit: ______

## T1.10 智能体台账页
- [ ] 台账六列 + 多维筛选 + 排序分页（SPEC 4.2、5.3；分页约定 8.5）
- [ ] 详情抽屉：用量曲线、变更时间线（SPEC 4.2）
- commit: ______

## T1.11 用量分析页
- [ ] 前置拍板：图表库 ECharts / Recharts（SPEC 4.1 遗留空白，T1.11 开工前定）
- [ ] 四维（人/智能体/模型/科室）× 日/周/月聚合，数据源 usage_report（SPEC 4.2、7.2）
- [ ] 排行榜 + CSV 导出 UTF-8 with BOM（SPEC 8.5；成本折算列留阶段 2，4.2"成本折算 2"）
- commit: ______

## T1.12 驾驶舱
- [ ] KPI 卡：智能体总数/活跃数、本月 Token 与成本、活跃员工数、离线设备告警（SPEC 4.2）
- [ ] 离线告警排除 reporting_paused=1 设备（SPEC 3.4、4.2 注）
- [ ] 趋势图 + 部门 Top 榜（SPEC 4.2）
- commit: ______

## T1.13 员工面板（插件内）
- [ ] 按 D8 拍板路径实现：entry.frontend JS bundle + console 插槽/路由/菜单（SPEC 3.8、决策点 D8）
- [ ] 状态卡：绑定信息/三通道信号灯/今日上报数；操作：立即同步/暂停上报/重新绑定/诊断导出（SPEC 3.8）
- [ ] 顶部常驻隐私承诺 + "今日已上报内容"透明展示（SPEC 3.4）
- commit: ______

## 收口

## T1.14 插件自检与 CI 冒烟
- [ ] diagnostics.py：自检/手动同步/诊断导出（SPEC 3.2 包结构）
- [ ] CI 接入 check --runtime + 三通道冒烟（SPEC 3.9 升级验证流水线）
- commit: ______

## T1.15 回归验收与试点上墙
- [ ] SPEC 3.11 七项逐条实测（10 分钟上墙/断网补传幂等/卸载无残留/格式破坏降级/吊销停报/资源开销/工具链全绿）
- [ ] SPEC 14.1 第 1/2/6/7 条实测（安装 ≤5 分钟/绑定 10 分钟可见/断电恢复/卸载回归）
- [ ] 10 名试点员工数据上墙；git tag stage-1
- commit: ______
