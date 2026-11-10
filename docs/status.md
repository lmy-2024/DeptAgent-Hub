# DeptAgent-Hub 进程记录

> 更新纪律：每次编码会话结束时更新"当前状态"与"已完成"两节；细节看 git log 与 docs/tasks/*.md，本文件只记"进行到哪、卡在哪"。
> 完成动作链：task.md 打勾 + 填 commit hash → 本文件"已完成"加一行 → 随代码一起 commit。

## 当前状态
- 阶段：0（工程基座）
- 当前任务：T0.2–T0.8 编码完成且全部验证通过，待 commit/push（用户确认后执行，含 T0.9 插件真机 spike 由用户操作）
- 最后更新：2026-11-10

## 已完成
- [x] SPEC v0.5 评审修订完成（本地文件，随 T0.1 基线 commit 入库）
- [x] T0.2–T0.8 全部完成：server 骨架/迁移框架/--init-super/登录+JWT/治理四端点/审计/console 脚手架；单测 29 个全绿 + ruff 全过 + 真机冒烟闭环（见下）
- [x] 真机冒烟（uvicorn + curl）：/health、console 首页静态挂载、super 登录、一次性密码创建 admin、admin 登录、403/401 权限矩阵、5 次失败锁定、停用即旧 token 失效（同一 token 403→401）、审计 5 行落库

## 卡点 / 待拍板（SPEC 15 章）
- 开工前：D1 插件命名（倾向 deptagent-link）、D8 员工面板路径（倾向官方前端插件）、D11 密码哈希（Argon2id 已实现为倾向值，待正式确认）——D6 已实质拍板（LICENSE = Apache-2.0）
- 阶段 1 前：D2 上报频率、D3 历史回灌深度、D5 member 页、D7 注册模式（倾向 closed）
- T1.11 前：图表库 ECharts / Recharts（SPEC 4.1 遗留空白）

## 环境事实（中断后恢复用）
- 本地 git：已 init，remote origin = https://github.com/lmy-2024/DeptAgent-Hub.git，main 已有基线 commit 04283f3（README/LICENSE/.gitignore），**从未 push**
- 4 个参考仓库（QwenPaw-main 等）已确认从未被 git 跟踪，.gitignore 已加排除规则
- 宿主机 Windows + PowerShell 5.1：命令连接用 `;`，不用 `&&`
- Python 3.14 + server/.venv 独立虚拟环境（依赖全隔离，pip 清华源安装）；服务启动：`server\.venv\Scripts\python.exe -m uvicorn deptagent.app:create_app --factory`，需设 `DEPTAGENT_DB_PATH` / `DEPTAGENT_JWT_SECRET`
- Node v22 + console 依赖 npmmirror 镜像；构建 `cd console; npm run build`（tsc + vite 全过）
- 校验依据只读：QwenPaw-main v2.2.2 源码（SPEC 源码断言基于此版本）
