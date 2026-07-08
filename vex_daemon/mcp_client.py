"""
MCP Client for Vex Daemon — using the official MCP Python SDK.

Provides Vex access to external MCP servers for capabilities beyond
local filesystem: web fetch, databases, APIs, etc.

Servers are configured in vex_mcp_config.json. Default: empty (no servers).
Each server is user-auditable — you decide what Vex can touch.
"""

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

from config import VEX_HOME, MCP_CONFIG_PATH

# A subprocess gets ONLY these host vars plus whatever the server config
# declares in its own "env" block. Never inherit the full environment —
# that would hand API keys and tokens to every MCP server Vex talks to.
_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR")


def load_config() -> dict:
    """Load MCP server configuration. Returns {mcpServers: {}}."""
    if not MCP_CONFIG_PATH.exists():
        return {"mcpServers": {}}
    try:
        return json.loads(MCP_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"mcpServers": {}}


def _build_params(srv: dict) -> StdioServerParameters:
    """Build stdio params with a minimal, non-leaking environment."""
    base_env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    merged_env = {**base_env, **srv.get("env", {})}
    return StdioServerParameters(
        command=srv.get("command", ""),
        args=srv.get("args", []),
        env=merged_env,
    )


def _resolve_server(server_name: str) -> tuple[dict | None, dict | None]:
    """Return (srv_config, error_response). Exactly one is non-None."""
    servers = load_config().get("mcpServers", {})
    if server_name not in servers:
        return None, {"ok": False, "error": f"Server '{server_name}' not configured"}
    srv = servers[server_name]
    if not srv.get("command"):
        return None, {"ok": False, "error": f"No command for server '{server_name}'"}
    return srv, None


async def call_tool(server_name: str, tool_name: str, arguments: dict) -> dict:
    """Call a tool on a configured MCP server. One-shot: connect, call, disconnect."""
    srv, err = _resolve_server(server_name)
    if err:
        return err
    try:
        async with stdio_client(_build_params(srv)) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def list_tools(server_name: str) -> dict:
    """List available tools on a configured MCP server."""
    srv, err = _resolve_server(server_name)
    if err:
        return err
    try:
        async with stdio_client(_build_params(srv)) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return {"ok": True, "tools": [
                    {"name": t.name, "description": t.description}
                    for t in tools_result.tools
                ]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
