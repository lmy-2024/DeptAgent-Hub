"""SQLite 访问层（SPEC 7 章 / 9.1：WAL 模式、外键开启）。

设计口径：
- FastAPI 同步路由运行于线程池，多线程共享单连接（check_same_thread=False），
  写操作由 threading.Lock 串行化——SQLite WAL 单写多读，SPEC 9.2 实测负载
  0.4 RPS，此模型余量充足；
- 阶段 0 不引入 ORM：SPEC 第 7 章的 DDL / 7.1 UPSERT 白名单 / 7.2 VIEW 均
  为原生 SQL 语义，手写 SQL 与"SQLite→PG 迁移限于方言差异"（7 章导语）对齐。
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class Database:
    """线程安全的 SQLite 封装（单连接 + 写锁）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._write_lock = threading.Lock()

    @classmethod
    def open(cls, path: str | Path) -> Database:
        """打开（必要时创建）数据库并应用 PRAGMA（SPEC 9.1）。"""
        target = Path(path)
        if target.parent and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # SPEC 7 章：WAL 模式
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return cls(conn)

    # ---- 写路径 ----

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """执行写语句（自动提交），返回 lastrowid。"""
        with self._write_lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur.lastrowid or 0

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """原子写事务：块内任一语句失败整体回滚（迁移等 DDL 序列用）。"""
        with self._write_lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- 读路径 ----

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        cur = self._conn.execute(sql, tuple(params))
        return cur.fetchone()

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        cur = self._conn.execute(sql, tuple(params))
        return cur.fetchall()

    def close(self) -> None:
        self._conn.close()
