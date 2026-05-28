"""
Memory Store - 重要性分级记忆模块

特性:
- 四级重要性分层: critical / important / normal / minor
- 时间衰减: normal/minor 记忆自动过期
- SQLite 持久化存储
- 按 tier 分组检索

用法:
    store = MemoryStore(auto_expire_days=30)
    store.add("用户喜欢喝奶茶", tier="important", user_id="wechat_user_123")
    memories = store.get("wechat_user_123", tier="important")
    store.cleanup()  # 清理过期记忆
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("memory_store")

# 默认 tier 顺序（从高到低）
DEFAULT_TIERS = ["critical", "important", "normal", "minor"]

# 每个 tier 的 TTL（天），-1 表示永不过期
DEFAULT_TTL_DAYS = {
    "critical": -1,
    "important": -1,
    "normal": 30,
    "minor": 7,
}


@dataclass
class MemoryEntry:
    """单条记忆"""
    id: int = 0
    user_id: str = ""
    content: str = ""
    tier: str = "normal"
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0


class MemoryStore:
    """
    分层记忆存储器。

    SQLite 持久化，支持多用户隔离，按 tier 过滤。
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        auto_expire_days: int = 30,
        tiers: list[str] | None = None,
    ):
        """
        Args:
            db_path: SQLite 数据库路径（默认: ~/.cyber_girlfriend/memories.db）
            auto_expire_days: normal/minor 记忆的默认过期天数
            tiers: tier 列表（按优先级从高到低）
        """
        self._auto_expire_days = auto_expire_days
        self._tiers = tiers or DEFAULT_TIERS
        self._ttl_days = dict(DEFAULT_TTL_DAYS)
        self._ttl_days["normal"] = auto_expire_days
        self._ttl_days["minor"] = min(auto_expire_days // 4, 7)

        if db_path is None:
            home = Path.home()
            store_dir = home / ".cyber_girlfriend"
            store_dir.mkdir(parents=True, exist_ok=True)
            db_path = store_dir / "memories.db"
        self._db_path = Path(db_path)

        self._lock = threading.RLock()
        self._init_db()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def add(
        self,
        content: str,
        tier: str = "normal",
        user_id: str = "default",
        tags: list[str] | None = None,
    ) -> int:
        """
        添加一条记忆。

        Args:
            content: 记忆内容
            tier: 重要性等级 (critical / important / normal / minor)
            user_id: 用户标识（用于多用户隔离）
            tags: 可选标签列表

        Returns:
            新记忆的 id
        """
        self._validate_tier(tier)
        tags = tags or []
        now = time.time()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (user_id, content, tier, tags, created_at, last_accessed, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, content, tier, json.dumps(tags, ensure_ascii=False), now, now, 0),
            )
            self._conn.commit()
            mid = cursor.lastrowid
            logger.debug("Added memory id=%s tier=%s user=%s", mid, tier, user_id)
            return mid

    def get(
        self,
        user_id: str = "default",
        tier: str | None = None,
        limit: int = 50,
        min_tier: str | None = None,
    ) -> list[MemoryEntry]:
        """
        获取用户的记忆。

        Args:
            user_id: 用户标识
            tier: 只返回指定 tier 的记忆（None 表示所有）
            limit: 最多返回条数
            min_tier: 最低 tier（只返回 >= 此 tier 的记忆）

        Returns:
            MemoryEntry 列表（按 created_at 倒序）
        """
        with self._lock:
            cursor = self._conn.cursor()

            if tier:
                # 精确匹配 tier
                cursor.execute(
                    """
                    SELECT id, user_id, content, tier, tags, created_at, last_accessed, access_count
                    FROM memories
                    WHERE user_id = ? AND tier = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, tier, limit),
                )
            elif min_tier:
                # >= min_tier
                tier_order = self._tiers
                min_idx = tier_order.index(min_tier) if min_tier in tier_order else 0

                def make_or_clause(tier_list: list[str]) -> str:
                    return " OR ".join(f"tier = '{t}'" for t in tier_list)

                tiers_to_get = tier_order[min_idx:]
                clause = make_or_clause(tiers_to_get)
                cursor.execute(
                    f"""
                    SELECT id, user_id, content, tier, tags, created_at, last_accessed, access_count
                    FROM memories
                    WHERE user_id = ? AND ({clause})
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                )
            else:
                # 返回所有
                cursor.execute(
                    """
                    SELECT id, user_id, content, tier, tags, created_at, last_accessed, access_count
                    FROM memories
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                )

            rows = cursor.fetchall()
            return [self._row_to_entry(row) for row in rows]

    def update_access(self, memory_id: int) -> None:
        """更新记忆的访问时间（用于 LRU 追踪）"""
        with self._lock:
            self._conn.execute(
                """
                UPDATE memories
                SET last_accessed = ?, access_count = access_count + 1
                WHERE id = ?
                """,
                (time.time(), memory_id),
            )
            self._conn.commit()

    def delete(self, memory_id: int) -> bool:
        """删除指定记忆"""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def cleanup(self) -> int:
        """
        清理过期记忆（normal/minor tier）。

        Returns:
            删除的记忆条数
        """
        deleted = 0
        with self._lock:
            cursor = self._conn.cursor()
            now = time.time()

            for tier_name in ["normal", "minor"]:
                ttl = self._ttl_days.get(tier_name, self._auto_expire_days)
                if ttl <= 0:
                    continue

                threshold = now - (ttl * 86400)  # 转换为秒
                cursor.execute(
                    "DELETE FROM memories WHERE tier = ? AND created_at < ?",
                    (tier_name, threshold),
                )
                deleted += cursor.rowcount

            self._conn.commit()

        if deleted:
            logger.info("Cleaned up %s expired memories", deleted)
        return deleted

    def search(
        self,
        query: str,
        user_id: str = "default",
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """
        全文搜索记忆内容。

        SQLite FTS5 支持。

        Args:
            query: 搜索关键词
            user_id: 用户标识
            limit: 最多返回条数

        Returns:
            匹配的 MemoryEntry 列表
        """
        with self._lock:
            cursor = self._conn.cursor()
            # 使用 LIKE 模糊匹配（不依赖 FTS5 表存在）
            pattern = f"%{query}%"
            cursor.execute(
                """
                SELECT id, user_id, content, tier, tags, created_at, last_accessed, access_count
                FROM memories
                WHERE user_id = ? AND content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, pattern, limit),
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]

    def get_stats(self, user_id: str = "default") -> dict:
        """获取用户的记忆统计"""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT tier, COUNT(*) FROM memories WHERE user_id = ? GROUP BY tier",
                (user_id,),
            )
            counts = dict(cursor.fetchall())

            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE user_id = ?",
                (user_id,),
            )
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE user_id = ? AND created_at > ?",
                (user_id, time.time() - 86400 * 7),
            )
            recent = cursor.fetchone()[0]

            return {
                "total": total,
                "by_tier": counts,
                "recent_7d": recent,
            }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _init_db(self) -> None:
        """初始化 SQLite 表"""
        with self._lock:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'normal',
                    tags TEXT DEFAULT '[]',
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    access_count INTEGER DEFAULT 0
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)"
            )
            self._conn.commit()
            logger.debug("Memory database initialized at %s", self._db_path)

    def _validate_tier(self, tier: str) -> None:
        """校验 tier 是否合法"""
        if tier not in self._tiers:
            raise ValueError(
                f"Invalid tier '{tier}'. Must be one of: {self._tiers}"
            )

    @staticmethod
    def _row_to_entry(row: tuple) -> MemoryEntry:
        """将数据库行转换为 MemoryEntry"""
        tags_raw = row[4]
        try:
            tags = json.loads(tags_raw) if tags_raw else []
        except (json.JSONDecodeError, TypeError):
            tags = []

        return MemoryEntry(
            id=row[0],
            user_id=row[1],
            content=row[2],
            tier=row[3],
            tags=tags,
            created_at=row[5],
            last_accessed=row[6],
            access_count=row[7],
        )


# =============================================================================
# Conversation Memory Integration Helper
# =============================================================================

class ConversationMemory:
    """
    辅助类：将 MemoryStore 集成到对话流程。

    在每次对话后自动摘要重要信息存入记忆，
    对话时将记忆作为 context 注入 system prompt。
    """

    def __init__(self, memory_store: MemoryStore, user_id: str = "default"):
        self._store = memory_store
        self._user_id = user_id

    def build_context(self, tier: str = "important") -> str:
        """
        构建用于注入 system prompt 的记忆上下文。

        Args:
            tier: 只包含 >= 此 tier 的记忆

        Returns:
            格式化的记忆字符串，如 "【记忆】\n- 用户喜欢喝奶茶\n- ..."
        """
        entries = self._store.get(self._user_id, min_tier=tier, limit=20)
        if not entries:
            return ""

        lines = ["【记忆】"]
        for entry in entries:
            tier_icon = {"critical": "⭐", "important": "💡", "normal": "📝", "minor": "🔹"}.get(
                entry.tier, "📝"
            )
            created = datetime.fromtimestamp(entry.created_at).strftime("%m-%d")
            lines.append(f"- {tier_icon} [{created}] {entry.content}")

        return "\n".join(lines)

    def remember(self, content: str, tier: str = "normal") -> int:
        """快捷方法：存入一条记忆"""
        return self._store.add(content, tier=tier, user_id=self._user_id)