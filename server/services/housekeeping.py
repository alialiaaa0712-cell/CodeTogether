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
    执行记忆轻量维护任务：
    1. 重置超过 7 天未命中的短期记忆窗口统计
    2. 不再自动晋升长期，也不再自动改为 rejected

    参数:
        db: 数据库会话。

    返回值:
        无。
    """
    now = time.time()

    stale_short = (
        db.query(MemoryModel)
        .filter(
            MemoryModel.status == "active",
            MemoryModel.tier == "short",
            MemoryModel.last_hit_at.isnot(None),
            MemoryModel.last_hit_at < now - _7_DAYS,
            MemoryModel.hit_count_7d > 0,
        )
        .all()
    )
    for mem in stale_short:
        mem.hit_count_7d = 0
        mem.review_reason = None
        mem.review_hit_count = None
        mem.updated_at = now
    if stale_short:
        logger.info("housekeeping: %d short hit windows reset", len(stale_short))

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("housekeeping: 提交失败，已回滚")
