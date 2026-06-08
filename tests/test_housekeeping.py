import time
import pytest
from server.services.housekeeping import run_memory_housekeeping
from server.models import Memory as MemoryModel


def test_short_to_long_promotion(db):
    """验证 active/short 且 updated_at 超过 7 天的记忆升级为 long。"""
    old_ts = time.time() - 8 * 86400
    mem = MemoryModel(title="t", content="c", status="active", tier="short", updated_at=old_ts)
    db.add(mem)
    db.commit()

    run_memory_housekeeping(db)
    db.refresh(mem)
    assert mem.tier == "long"


def test_review_expiry(db):
    """验证 review 状态且 updated_at 超过 30 天的记忆被自动 rejected。"""
    old_ts = time.time() - 31 * 86400
    mem = MemoryModel(title="t", content="c", status="review", tier="long", updated_at=old_ts)
    db.add(mem)
    db.commit()

    run_memory_housekeeping(db)
    db.refresh(mem)
    assert mem.status == "rejected"


def test_fresh_short_not_promoted(db):
    """验证 updated_at 不足 7 天的 active/short 记忆不会被晋升。"""
    mem = MemoryModel(title="t", content="c", status="active", tier="short", updated_at=time.time())
    db.add(mem)
    db.commit()

    run_memory_housekeeping(db)
    db.refresh(mem)
    assert mem.tier == "short"
