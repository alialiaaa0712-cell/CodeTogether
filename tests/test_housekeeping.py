import time

from server.models import Memory as MemoryModel
from server.models import MemorySearchExposure as MemorySearchExposureModel
from server.services.housekeeping import run_memory_housekeeping


def test_housekeeping_does_not_require_removed_hit_fields(db):
    """验证 housekeeping 在 score 模型下可安全执行，且不依赖已删除的 hit 字段。

    参数:
        db: 测试数据库会话。

    返回值:
        无返回值；通过断言函数执行后不会破坏现有记忆的核心字段来验证兼容性。
    """
    memory = MemoryModel(
        title="规则",
        content="必须携带 token",
        status="active",
        tier="short",
        score_total=6,
        feedback_count=2,
        review_score=4,
        review_reason="manual_review",
        updated_at=1000.0,
    )
    db.add(memory)
    db.commit()

    run_memory_housekeeping(db)

    db.refresh(memory)
    assert memory.status == "active"
    assert memory.tier == "short"
    assert memory.score_total == 6
    assert memory.feedback_count == 2
    assert memory.review_score == 4
    assert memory.review_reason == "manual_review"


def test_housekeeping_does_not_promote_short_to_long(db):
    """验证 housekeeping 不会把短期记忆自动晋升为长期。

    参数:
        db: 测试数据库会话。

    返回值:
        无返回值；通过断言 tier 保持 short 验证当前 housekeeping 仅做安全维护。
    """
    memory = MemoryModel(
        title="边界",
        content="不能跨项目注入",
        status="active",
        tier="short",
        score_total=0,
        feedback_count=0,
        updated_at=1000.0,
    )
    db.add(memory)
    db.commit()

    run_memory_housekeeping(db)

    db.refresh(memory)
    assert memory.tier == "short"
    assert memory.status == "active"


def test_housekeeping_preserves_score_fields_for_recent_memories(db):
    """验证 housekeeping 不会改写已存在记忆的 score 相关字段。

    参数:
        db: 测试数据库会话。

    返回值:
        无返回值；通过断言 score 字段与更新时间保持稳定来验证无副作用。
    """
    memory = MemoryModel(
        title="近期规则",
        content="近期评分仍应保留",
        status="active",
        tier="short",
        score_total=3,
        feedback_count=1,
        last_feedback_at=1000.0,
        updated_at=1000.0,
    )
    db.add(memory)
    db.commit()

    run_memory_housekeeping(db)

    db.refresh(memory)
    assert memory.score_total == 3
    assert memory.feedback_count == 1
    assert memory.last_feedback_at == 1000.0
    assert memory.updated_at == 1000.0


def test_housekeeping_deletes_expired_search_exposures_without_touching_memory_scores(db):
    """验证 housekeeping 会清理过期曝光记录，且不会改写关联记忆评分。

    参数:
        db: 测试数据库会话。

    返回值:
        无返回值；通过断言过期 exposure 被删除且 memory 评分字段保持不变来验证行为。
    """
    now = time.time()
    memory = MemoryModel(
        title="曝光清理",
        content="过期曝光应被清理",
        status="active",
        tier="short",
        score_total=9,
        feedback_count=3,
        last_feedback_at=now - 30,
        review_score=5,
        updated_at=now - 20,
    )
    db.add(memory)
    db.commit()

    expired = MemorySearchExposureModel(
        memory_id=memory.id,
        session_id="sess-expired",
        query="old query",
        exposed_at=now - 3601,
    )
    fresh = MemorySearchExposureModel(
        memory_id=memory.id,
        session_id="sess-fresh",
        query="fresh query",
        exposed_at=now - 300,
    )
    db.add(expired)
    db.add(fresh)
    db.commit()

    run_memory_housekeeping(db)

    db.refresh(memory)
    remaining_ids = {item.id for item in db.query(MemorySearchExposureModel).all()}

    assert expired.id not in remaining_ids
    assert fresh.id in remaining_ids
    assert memory.score_total == 9
    assert memory.feedback_count == 3
    assert memory.last_feedback_at == now - 30
    assert memory.review_score == 5
    assert memory.updated_at == now - 20
