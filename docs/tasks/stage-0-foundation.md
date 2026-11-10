# 阶段 0：工程基座（task 清单）

> 验收锚点：SPEC 14.1 第 8 条（账号治理闭环）
> 里程碑（SPEC 11 章阶段 0 行）：super/admin 可登录调 API，账号治理端点可用
> 用法：完成一条 → 打勾 → 填 commit hash → `docs/status.md` 记一行 → 随代码 commit
> 纪律：本文件只引用 SPEC 章节号，不复制内容（单一事实来源 = SPEC）

## T0.1 git 基线收口（含本任务体系入库）
- [x] .gitignore 追加：4 个参考仓库、*.zip、本地 db、.env*、.vscode/、node_modules/（SPEC 13.2、10.1）
- [ ] push 基线 commit：README + LICENSE + docs/SPEC.md + docs/tasks/ + docs/status.md
- commit: d8ad44d（docs 基线已提交；push 待用户确认）

## T0.2 server 工程骨架
- [x] server/ 目录：src/deptagent/{api,core,storage} + tests（SPEC 13.1）
- [x] pyproject.toml：包名 deptagent-server，Python 3.11+（SPEC 9.1）
- [x] ruff + pytest 配置；GitHub Actions CI 占位（lint + 单测，SPEC 13.2）
- [x] FastAPI app 工厂 + GET /health
- commit: 1a67e0f

## T0.3 数据库与迁移框架
- [x] SQLite 连接封装：WAL pragma、外键开启（SPEC 7 章、9.1）
- [x] 迁移框架：schema_version 表 + 编号迁移脚本
- [x] 首批表：users、devices、audit_log（含全部索引，SPEC 7 章）
- [x] 单测：迁移幂等（重复执行零变更）
- commit: 1a67e0f

## T0.4 --init-super 命令
- [x] CLI 入口：--init-super 创建/重置 super 账号（SPEC 1.3）
- [x] 密码 Argon2id 哈希（SPEC 10.1，决策点 D11 倾向值）
- commit: 1a67e0f

## T0.5 登录端点 + JWT
- [x] POST /api/v1/auth/login：JWT HS256、12h、secret 环境变量注入（SPEC 10.1）
- [x] 错误响应统一格式（auth_failed，SPEC 8.5）
- [x] 登录失败锁定策略（SPEC 12 章账号风险对策行）
- [x] 单测：正确/错误密码、锁定触发、token 过期
- commit: 1a67e0f

## T0.6 账号治理端点（super 专属）
- [x] 四端点：accounts 创建 / role 调整 / reset-password / disable（SPEC 8.3）
- [x] 权限矩阵：admin 调用 403 forbidden_role；admin 不可提权、不可重置他人密码、不可停用 super（SPEC 8.3 权限约束）
- [x] 单测：403 矩阵含 admin 自我提权尝试（SPEC 14.1 第 8 条）
- commit: 1a67e0f

## T0.7 审计日志
- [x] super 账号治理操作全留痕（actor/action/target/at，SPEC 7 章 audit_log 表）
- [x] 单测：每次治理调用产生一行审计记录
- commit: 1a67e0f

## T0.8 console 脚手架
- [x] Vite + React + TS，目录 api/pages/stores/hooks（SPEC 4.1、13.1）
- [x] 路由骨架 + 空布局；构建产物由 FastAPI 静态挂载（登录页在 T1.8 交付，4.2 页面地图）
- commit: f7e02d2

## T0.9 插件真机 spike（风险前置，可与 T0.2–T0.8 并行）
- [ ] 以官方 templates/hello 为底，跑通安装 → 激活 → 禁用（SPEC 3.2）
- [ ] `python -m qwenpaw.plugins.check <目录> --runtime` 全绿（SPEC 3.9）
- [ ] 实测结论记录到 docs/status.md（源码断言 → 真机验证，QwenPaw v2.2.2）
- commit: ______（spike 代码可不入库，结论记录必须入库）

## T0.10 阶段 0 收口
- [ ] SPEC 14.1 第 8 条逐项走查（8 个子项全过）
- [ ] git tag stage-0；docs/status.md 更新阶段状态
- commit: ______
