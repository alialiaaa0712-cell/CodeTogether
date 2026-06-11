import time
from unittest import mock

from server.models import Memory as MemoryModel
from server.services.housekeeping import run_memory_housekeeping


def test_housekeeping_resets_stale_short_hit_window(db):
    """验证 housekeeping 会重置过期短期记忆的命中窗口，但不会晋升层级。"""
    memory = MemoryModel(
        title="规则",
        content="必须携带 token",
        status="active",
        tier="short",
        hit_count_7d=4,
        last_hit_at=1000.0,
        updated_at=1000.0,
    )
    db.add(memory)
    db.commit()

    with mock.patch("server.services.housekeeping.time.time", return_value=1000.0 + 8 * 86400):
        run_memory_housekeeping(db)

    db.refresh(memory)
    assert memory.tier == "short"
    assert memory.hit_count_7d == 0
    assert memory.review_reason is None
    assert memory.review_hit_count is None


def test_housekeeping_does_not_promote_short_to_long(db):
    """验证 housekeeping 不会再把短期记忆自动晋升为长期。"""
    memory = MemoryModel(
        title="边界",
        content="不能跨项目注入",
        status="active",
        tier="short",
        updated_at=1000.0,
    )
    db.add(memory)
    db.commit()

    with mock.patch("server.services.housekeeping.time.time", return_value=1000.0 + 30 * 86400):
        run_memory_housekeeping(db)

    db.refresh(memory)
    assert memory.tier == "short"


def test_housekeeping_keeps_recent_short_hit_window(db):
    """验证 7 天内命中的短期记忆不会被 housekeeping 清空命中窗口。"""
    memory = MemoryModel(
        title="近期规则",
        content="近期命中仍应保留",
        status="active",
        tier="short",
        hit_count_7d=2,
        last_hit_at=1000.0,
        updated_at=time.time(),
    )
    db.add(memory)
    db.commit()

    with mock.patch("server.services.housekeeping.time.time", return_value=1000.0 + 6 * 86400):
        run_memory_housekeeping(db)

    db.refresh(memory)
    assert memory.hit_count_7d == 2
