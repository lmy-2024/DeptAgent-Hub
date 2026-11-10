# DeptAgent-Hub 进程记录

> 更新纪律：每次编码会话结束时更新"当前状态"与"已完成"两节；细节看 git log 与 docs/tasks/*.md，本文件只记"进行到哪、卡在哪"。
> 完成动作链：task.md 打勾 + 填 commit hash → 本文件"已完成"加一行 → 随代码一起 commit。

## 当前状态
- 阶段：0（工程基座）
- 当前任务：阶段 0 全部完成（收口 commit 6f278d8 + hash 回填 commit；tag stage-0 于 push 前打上）；下一步进入阶段 1（T1.1 插件包骨架，开工前拍板 D2/D3/D5/D7）
- 最后更新：2026-11-10

## 已完成
- [x] SPEC v0.5 评审修订完成（commit d8ad44d）
- [x] T0.2–T0.7 server：commit 1a67e0f；T0.8 console+CI：commit f7e02d2（单测 29 全绿 + ruff + 真机冒烟闭环）
- [x] 真机冒烟（uvicorn + curl）：/health、console 静态挂载、super 登录、一次性密码建 admin、403/401 矩阵、锁定、停用即失效、审计 5 行落库
- [x] T0.9 插件真机 spike：QwenPaw 宿主升级 2.3.0b3 后全链路通过（安装→激活→禁用→重启用，check --runtime 全绿；实测结论见下方环境事实）
- [x] SPEC v0.6 版本口径修正（用户拍板“更新为最新”）：断言版本 v2.2.2→v2.3.0b3；manifest min 2.2.2→2.3.0（2.2.x 宿主缺新 SDK 实测不兼容，宿主 pre-release 归一化比较使 2.3.0b3 真机满足 min）；格式族标签/适配器 2_2→2_3
- [x] T0.10 之 14.1 第 8 条逐项走查：①init-super ②super 建 admin ③角色即时生效（JWT 不携带角色、每请求查库）④admin 治理端点 403 ⑤自我提权拒绝 ⑥旧密码立即失效 ⑦lead 无写入口（本次补测 test_lead_cannot_call_any_governance_endpoint，API 层；console 登录页入口 T1.8 交付后复验）⑧审计全留痕；单测 29→30 全绿 + ruff 全过

## 卡点 / 待拍板（SPEC 15 章）
- 开工前：D1 插件命名（倾向 deptagent-link）、D8 员工面板路径（倾向官方前端插件）、D11 密码哈希（Argon2id 已实现为倾向值，待正式确认）——D6 已实质拍板（LICENSE = Apache-2.0）
- 阶段 1 前：D2 上报频率、D3 历史回灌深度、D5 member 页、D7 注册模式（倾向 closed）
- T1.11 前：图表库 ECharts / Recharts（SPEC 4.1 遗留空白）

## 环境事实（中断后恢复用）
- 本地 git：remote origin = https://github.com/lmy-2024/DeptAgent-Hub.git，已推送至 eba2060；本地新增阶段 0 收口 commits（6f278d8 + 回填）与 tag stage-0 待推送；GitHub Actions CI（lint+单测）已首次触发
- 4 个参考仓库（QwenPaw-main 等）已确认从未被 git 跟踪，.gitignore 已加排除规则
- 宿主机 Windows + PowerShell 5.1：命令连接用 `;`，不用 `&&`
- Python 3.14 + server/.venv 独立虚拟环境（依赖全隔离，pip 清华源安装）；服务启动：`server\.venv\Scripts\python.exe -m uvicorn deptagent.app:create_app --factory`，需设 `DEPTAGENT_DB_PATH` / `DEPTAGENT_JWT_SECRET`
- Node v22 + console 依赖 npmmirror 镜像；构建 `cd console; npm run build`（tsc + vite 全过）
- 校验依据只读：QwenPaw-main v2.3.0b3 源码（SPEC 源码断言基于此版本）
- QwenPaw 真机宿主 `D:\project\Qwenpaw`（独立 venv，Python 3.11）：已升级 qwenpaw 2.3.0b3 + typesafe-sdk 0.7.5（2026-11-10），与参考源码版本对齐；宿主运行于 `http://127.0.0.1:8088/api`
- T0.9 实测结论（2026-11-10，宿主 2.3.0b3）：① `qwenpaw plugin install <本地目录>` 自动走 REST 热装（`POST /plugins/install`），安装至 `~/.qwenpaw/plugins/hello-sdk`，立即加载 active；② `POST /plugins/{id}/enabled`（body `{"enabled": false/true}`）禁用 = 卸载实例保留文件（clean+quiescent，无需重启），重新启用 = 从磁盘重载 active；③ `python -m qwenpaw.plugins.check <目录> --runtime` 返回 ok=true、load/activation/cleanup 全 passed、compatibility=compatible；④ SPEC 3.2 各断言（安装位置、PluginContext 导入、manifest 校验、模块级 plugin 实例）真机均成立；⑤ 旧宿主 2.2.2.post1 不兼容新 SDK（缺 PluginContext），升级是硬前提
