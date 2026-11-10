# deptagent-server

部门智通控制平面（FastAPI + SQLite）。约定与口径的唯一事实来源：[docs/SPEC.md](../docs/SPEC.md)。

## 环境

- Python ≥ 3.11（本机使用项目虚拟环境 `.venv`，不污染全局）
- pip 走清华镜像源

## 首次安装

```powershell
cd server
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 初始化超级管理员（SPEC 1.3）

```powershell
.venv/Scripts/python -m deptagent --init-super SUPER001 --password <密码>
```

密码缺省时交互输入（不回显）或自动生成；幂等——已存在则重置。

## 启动服务

```powershell
.venv/Scripts/python -m uvicorn deptagent.app:create_app --factory --host 0.0.0.0 --port 8000
```

生产必须注入 `DEPTAGENT_JWT_SECRET` 环境变量（SPEC 10.1）；数据库路径可用 `DEPTAGENT_DB_PATH` 覆盖。

## 测试与检查

```powershell
.venv/Scripts/python -m pytest          # 单测（含 14.1 第 8 条账号治理闭环验收）
.venv/Scripts/python -m ruff check src tests
.venv/Scripts/python -m ruff format --check src tests
```
