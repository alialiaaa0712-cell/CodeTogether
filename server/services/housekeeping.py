from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session as DBSession

from server.models import MemorySearchExposure as MemorySearchExposureModel

logger = logging.getLogger(__name__)

_EXPOSURE_TTL_SECONDS = 3600


def run_memory_housekeeping(db: DBSession) -> None:
    """执行记忆轻量维护任务，并确保 score 模型下的定时任务安全无副作用。

    参数:
        db: 数据库会话。

    返回值:
        无。
    """
    cutoff = time.time() - _EXPOSURE_TTL_SECONDS
    expired_exposures = (
        db.query(MemorySearchExposureModel)
        .filter(MemorySearchExposureModel.exposed_at < cutoff)
        .all()
    )

    for exposure in expired_exposures:
        db.delete(exposure)

    if expired_exposures:
        logger.info("housekeeping: deleted %d expired memory search exposures", len(expired_exposures))

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("housekeeping: 提交失败，已回滚")
