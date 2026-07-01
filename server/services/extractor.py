from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

_PROMPT = """你是一个知识提炼助手。请只提炼值得未来 Agent 反复复用的项目规则、约束、坑点、边界。
禁止输出：
1. 操作流水（运行了什么命令、改了哪些文件、测试通过了）
2. 一次性现象（偶发日志、临时报错、没有普遍性的现场现象）
3. 代码常识（从代码一眼能看出的结构、显然事实）
如果没有符合条件的内容，返回空数组 []。
每个 session 最多返回 3 条。
格式：[{{"title": "...", "content": "...", "tags": "逗号分隔标签"}}]。

会话摘要：
{summary}"""

_ALLOWED_MARKERS = ("必须", "不能", "不要", "需要", "仅在", "会导致", "应当")
_FORBIDDEN_MARKERS = ("运行了", "修改了", "测试通过", "查看了", "读取了", "Bash", "Read", "Edit", "pytest")


def _filter_memory_candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    过滤模型提炼结果，只保留可复用的项目规则/约束类记忆。

    参数:
        items: 模型返回的候选记忆列表。

    返回值:
        最多 3 条通过规则过滤的记忆。
    """
    filtered: List[Dict[str, Any]] = []
    for item in items:
        content = (item.get("content") or "").strip()
        if len(content) < 20 or len(content) > 200:
            continue
        if any(marker in content for marker in _FORBIDDEN_MARKERS):
            continue
        if not any(marker in content for marker in _ALLOWED_MARKERS):
            continue
        filtered.append(item)
        if len(filtered) == 3:
            break
    return filtered


def extract_memories(
    summary: str,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    调用提炼模型并过滤结果，只保留可复用的项目知识。

    参数:
        summary: 会话摘要文本。
        project_id: 当前项目 ID，用于回填到提炼结果。

    返回值:
        过滤后的记忆列表；失败时返回空列表。
    """
    client = OpenAI(
        api_key=os.getenv("CT_EXTRACTOR_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", ""),
        base_url=os.getenv("CT_EXTRACTOR_BASE_URL", "https://oneapi-comate.baidu-int.com/v1"),
    )
    model = os.getenv("CT_EXTRACTOR_MODEL", "gpt-5.4")
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": _PROMPT.format(summary=summary)}],
        )
        raw = resp.choices[0].message.content.strip()
        items = json.loads(raw)
        items = _filter_memory_candidates(items)
        for item in items:
            item["project_id"] = project_id
        return items
    except Exception as e:
        logger.warning("知识提炼失败: %s", e)
        return []
