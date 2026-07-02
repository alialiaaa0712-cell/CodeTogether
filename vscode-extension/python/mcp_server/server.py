"""CodeTogether 记忆 MCP stdio 服务入口。"""
import os
import sys
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mcp_server.tools import memory_create_tool, memory_feedback_tool, memory_search_tool



def build_server():
    """
    创建并注册 CodeTogether 记忆 MCP 服务。

    参数:
        无。

    返回值:
        已注册工具的 FastMCP 服务实例。
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("codetogether-memory")

    @server.tool(description="当你完成了一个阶段性任务（如修复一个 bug、实现一个功能、解决一个问题）后，主动调用此工具记录关键结论、约束或坑点，供未来参考。只记录可复用的规则/约束/教训，不记录操作流水。")
    def memory_create(title: str, content: str, tags: Optional[str] = None, session_id: Optional[str] = None) -> dict:
        """
        主动创建一条短期记忆，在完成阶段性任务时调用。

        参数:
            title: 记忆标题，简短描述核心结论（10-30字）。
            content: 记忆正文，描述约束/规则/坑点及其原因（20-200字）。
            tags: 可选的逗号分隔标签。
            session_id: 可选显式会话 ID，用于调试。

        返回值:
            包含 session_id 和已创建记忆对象的字典。
        """
        return memory_create_tool(title, content, tags=tags, session_id=session_id)

    @server.tool(description="在实现、改动或排障前，先查当前项目的相关记忆，优先获取项目规则、边界约束和历史坑点。调用时必须将环境变量 CLAUDE_CODE_SESSION_ID 的值作为 session_id 参数传入。")
    def memory_search(query: str, limit: int = 3, session_id: Optional[str] = None) -> dict:
        """
        搜索当前项目下与关键词相关的记忆条目。

        参数:
            query: 搜索关键词。
            limit: 最多返回条数，默认 3。
            session_id: 可选显式会话 ID，用于调试。

        返回值:
            包含 session_id、结果数量和记忆列表的对象。
        """
        return memory_search_tool(query, limit=limit, session_id=session_id)

    @server.tool()
    def memory_feedback(memory_id: str, score: int, reason: str, session_id: Optional[str] = None) -> dict:
        """
        针对已曝光记忆提交有用度反馈。

        参数:
            memory_id: 目标记忆 ID。
            score: 反馈分值，只允许 -2/-1/0/1/2。
            reason: 反馈原因。
            session_id: 可选显式会话 ID，用于调试。

        返回值:
            包含 session_id 和更新后记忆对象的结果。
        """
        return memory_feedback_tool(memory_id, score=score, reason=reason, session_id=session_id)

    return server



def main() -> None:
    """
    启动 CodeTogether 记忆 MCP stdio 服务。

    参数:
        无。

    返回值:
        无。
    """
    try:
        server = build_server()
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("mcp"):
            raise RuntimeError("缺少 mcp 依赖，请先安装 requirements.txt 中的 MCP 依赖") from exc
        raise
    server.run()



if __name__ == "__main__":
    main()
