from unittest.mock import patch, MagicMock
import pytest
from server.services.extractor import extract_memories


@pytest.mark.asyncio
async def test_extract_memories_returns_list():
    """Claude API 返回有效 JSON 时，应解析为知识条目列表。"""
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='[{"title":"测试配置","content":"使用 pytest-asyncio","tags":"test,pytest"}]')]

    with patch("server.services.extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = fake_response
        result = await extract_memories("session summary text", project_id="proj-1")

    assert isinstance(result, list)
    assert result[0]["title"] == "测试配置"


@pytest.mark.asyncio
async def test_extract_memories_handles_invalid_json():
    """Claude API 返回非 JSON 时，应返回空列表而不抛出异常。"""
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="无法解析")]

    with patch("server.services.extractor.anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = fake_response
        result = await extract_memories("summary", project_id=None)

    assert result == []
