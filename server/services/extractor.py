from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

_PROMPT = """你是一个知识提炼助手。以下是一段 Claude Code Agent 的会话摘要。
请从中提炼出对未来 Agent 有价值的项目知识，以 JSON 数组返回，每条格式为：
{{"title": "...", "content": "...", "tags": "逗号分隔的标签"}}

只返回 JSON 数组，不要有任何解释文字。如果没有值得记录的知识，返回空数组 []。

会话摘要：
{summary}"""


def extract_memories(
    summary: str,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = OpenAI(
        api_key=os.getenv("ANTHROPIC_AUTH_TOKEN", ""),
        base_url="https://oneapi-comate.baidu-int.com/v1",
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-5.4",
            max_tokens=1024,
            messages=[{"role": "user", "content": _PROMPT.format(summary=summary)}],
        )
        raw = resp.choices[0].message.content.strip()
        items = json.loads(raw)
        for item in items:
            item["project_id"] = project_id
        return items
    except Exception as e:
        logger.warning("知识提炼失败: %s", e)
        return []
