from unittest.mock import MagicMock, patch

from server.services.extractor import _filter_memory_candidates, extract_memories


def test_filter_memory_candidates_keeps_project_constraints():
    """验证过滤器会保留可复用的项目规则/约束类记忆。"""
    items = [{"title": "约束", "content": "MySQL 5.7 不能使用 ADD COLUMN IF NOT EXISTS", "tags": "mysql"}]

    result = _filter_memory_candidates(items)

    assert len(result) == 1


def test_filter_memory_candidates_drops_operational_chatter():
    """验证过滤器会丢弃操作流水和代码常识类噪音。"""
    items = [
        {"title": "操作", "content": "运行了 pytest tests/test_hooks.py 并通过", "tags": "test"},
        {"title": "常识", "content": "server/main.py 是 FastAPI 入口文件", "tags": "code"},
    ]

    result = _filter_memory_candidates(items)

    assert result == []


def test_extract_memories_returns_list():
    """提炼成功时应返回过滤后的知识条目，并补齐 project_id。"""
    fake_response = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = '[{"title":"测试配置","content":"MySQL 5.7 不能使用 ADD COLUMN IF NOT EXISTS","tags":"mysql"}]'
    fake_response.choices = [fake_choice]

    with patch("server.services.extractor.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create.return_value = fake_response
        result = extract_memories("session summary text", project_id="proj-1")

    assert isinstance(result, list)
    assert result[0]["title"] == "测试配置"
    assert result[0]["project_id"] == "proj-1"


def test_extract_memories_handles_invalid_json():
    """提炼接口返回非 JSON 时，应返回空列表而不抛出异常。"""
    fake_response = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "无法解析"
    fake_response.choices = [fake_choice]

    with patch("server.services.extractor.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create.return_value = fake_response
        result = extract_memories("summary", project_id=None)

    assert result == []
