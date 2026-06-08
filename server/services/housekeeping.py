from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session as DBSession

from server.models import Memory as MemoryModel

logger = logging.getLogger(__name__)

_7_DAYS = 7 * 86400
_30_DAYS = 30 * 86400


def run_memory_housekeeping(db: DBSession) -> None:
    """
    执行记忆生命周期清理任务：
    1. active/short 且 updated_at 超过 7 天 → 升级为 long
    2. review 且 updated_at 超过 30 天 → 标记为 rejected

    参数:
        db: 数据库会话。

    返回值:
        无。
    """
    now = time.time()

    promoted = (
        db.query(MemoryModel)
        .filter(
            MemoryModel.status == "active",
            MemoryModel.tier == "short",
            MemoryModel.updated_at < now - _7_DAYS,
        )
        .all()
    )
    for mem in promoted:
        mem.tier = "long"
        mem.updated_at = now
    if promoted:
        logger.info("housekeeping: %d short→long", len(promoted))

    expired = (
        db.query(MemoryModel)
        .filter(
            MemoryModel.status == "review",
            MemoryModel.updated_at < now - _30_DAYS,
        )
        .all()
    )
    for mem in expired:
        mem.status = "rejected"
        mem.updated_at = now
    if expired:
        logger.info("housekeeping: %d review→rejected", len(expired))

    db.commit()
