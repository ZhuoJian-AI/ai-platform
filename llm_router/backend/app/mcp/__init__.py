"""MCP server 子包 —— 把归口用户 scope 内五项能力暴露给第三方智能体终端。

入口：``app.mcp.server.mcp_app()`` 返回 streamable HTTP ASGI 子应用，
``app/main.py`` 挂在 ``/mcp``。
"""

from app.mcp.server import mcp_app

__all__ = ["mcp_app"]
