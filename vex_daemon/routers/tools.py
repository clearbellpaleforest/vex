"""Tools router — /tools, /tools/list, /mcp/*, /projects, /files."""

import io
import tarfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

import tools as _tools

router = APIRouter(tags=["tools"])


@router.post("/tools")
async def post_tools(request: Request):
    from daemon import check_auth
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        tool_name = body.get("tool", "")
        if not tool_name:
            return JSONResponse({"ok": False, "error": "tool name required"}, status_code=400)
        kwargs = body.get("args", {})
        result = _tools.run_tool(tool_name, **kwargs)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/tools/list")
async def get_tools_list():
    return JSONResponse({
        "ok": True,
        "tools": [
            {"name": "read_file", "description": "Read a file within allowed paths"},
            {"name": "write_file", "description": "Write a file atomically within allowed paths"},
            {"name": "edit_file", "description": "Exact string replacement in a file"},
            {"name": "list_directory", "description": "List directory contents"},
            {"name": "grep_code", "description": "Recursive grep for a pattern within allowed paths"},
            {"name": "run_command", "description": "Run a sandboxed shell command within allowed paths"},
            {"name": "git_status", "description": "Git status of a repository"},
            {"name": "git_diff", "description": "Show working tree and staged diff"},
            {"name": "git_log", "description": "Recent git log entries"},
            {"name": "run_tests", "description": "Run a test command and capture results"},
            {"name": "discover_projects", "description": "Find and report on all known git repos"},
            {"name": "playwright_screenshot", "description": "Take a PNG screenshot of a URL"},
            {"name": "playwright_text", "description": "Extract visible text from a web page"},
            {"name": "playwright_check_links", "description": "Check links on a page for broken ones"},
        ],
    })


@router.post("/mcp/call")
async def post_mcp_call(request: Request):
    from daemon import check_auth
    import mcp_client
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        server = body.get("server", "")
        tool = body.get("tool", "")
        arguments = body.get("arguments", {})
        if not server or not tool:
            return JSONResponse({"ok": False, "error": "server and tool required"}, status_code=400)
        result = await mcp_client.call_tool(server, tool, arguments)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/mcp/servers")
async def get_mcp_servers():
    import mcp_client
    config = mcp_client.load_config()
    servers = {}
    for name, srv in config.get("mcpServers", {}).items():
        servers[name] = {"command": srv.get("command", ""), "args": srv.get("args", [])}
    return JSONResponse({"ok": True, "servers": servers})


@router.get("/projects")
async def get_projects():
    result = _tools.discover_projects()
    return JSONResponse(result)


@router.get("/files")
async def get_files(path: str = "", request: Request = None):
    from daemon import check_auth, VEX_HOME
    if (err := check_auth(request)):
        return err
    resolved = (VEX_HOME / path).resolve()
    if not _tools._is_safe_path(resolved):
        return JSONResponse({"ok": False, "error": f"Path not in allowed roots: {path}"}, status_code=403)
    if not resolved.exists():
        return JSONResponse({"ok": False, "error": f"Not found: {path}"}, status_code=404)
    if resolved.is_file():
        return PlainTextResponse(resolved.read_text(),
                                headers={"X-Vex-Path": str(resolved.relative_to(VEX_HOME))})
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(resolved, arcname=resolved.name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/gzip",
                             headers={"Content-Disposition": f'attachment; filename="{resolved.name}.tar.gz"',
                                      "X-Vex-Path": str(resolved.relative_to(VEX_HOME))})
