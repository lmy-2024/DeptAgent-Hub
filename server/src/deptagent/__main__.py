"""CLI 入口（SPEC 1.3：super 经 --init-super 命令行初始化）。

用法：
    deptagent --init-super SUPER001 [--password <密码>] [--db <路径>]

服务启动不走本入口（保持最小表面积）：
    uvicorn deptagent.app:create_app --factory --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .config import load_settings, with_overrides
from .core.accounts import init_super
from .core.security import generate_password
from .storage.database import Database
from .storage.migrations import migrate


def _resolve_password(explicit: str | None) -> tuple[str, bool]:
    """返回 (密码, 是否自动生成)。显式传入优先；否则交互输入，输入为空则随机生成。"""
    if explicit:
        return explicit, False
    try:
        entered = getpass.getpass("为 super 账号设置密码（输入不回显，至少 8 位，留空自动生成）：")
    except (EOFError, OSError):
        entered = ""
    if entered:
        confirmed = getpass.getpass("再次输入确认：")
        if confirmed != entered:
            print("两次输入不一致，请重试")
            sys.exit(2)
        return entered, False
    return generate_password(), True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deptagent", description="部门智通控制平面")
    parser.add_argument("--init-super", metavar="EMPLOYEE_NO", help="初始化或重置超级管理员账号")
    parser.add_argument("--password", help="super 密码（缺省交互输入或自动生成）")
    parser.add_argument("--db", help="SQLite 数据库路径（缺省读 DEPTAGENT_DB_PATH）")
    args = parser.parse_args(argv)

    if not args.init_super:
        parser.print_help()
        return 0

    settings = load_settings()
    if args.db:
        settings = with_overrides(settings, db_path=args.db)

    db = Database.open(settings.db_path)
    try:
        migrate(db)
        password, generated = _resolve_password(args.password)
        created, final_password = init_super(db, args.init_super, password)
        action = "已创建" if created else "已重置"
        print(f"super 账号 {args.init_super} {action}。")
        if generated or created is False:
            # 随机生成或重置场景必须展示；显式密码场景不回显
            print(f"密码（仅本次显示，请妥善保存）：{final_password}")
        elif not generated:
            print("密码为你输入的值（不再回显）。")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
