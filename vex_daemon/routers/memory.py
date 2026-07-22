"""Memory router — /memory, /memory/recent, /memory/search, /diary, /reconstruct."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["memory"])


@router.post("/memory")
async def post_memory(request: Request):
    from daemon import check_auth, read_json_limited, VEX_HOME
    if (err := check_auth(request)):
        return err
    try:
        body, err = await read_json_limited(request)
        if err:
            return err
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = VEX_HOME / "vex_memory" / f"{today}.jsonl"
        entry = {
            "date": today,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": body.get("summary", ""),
            "decisions": body.get("decisions", []),
            "skills": body.get("skills", []),
            "relationships": body.get("relationships", {}),
            "files": body.get("files", []),
            "repo": body.get("repo", ""),
            "branch": body.get("branch", ""),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # Rebuild index so new entry is searchable
        try:
            from memory_index import build_index
            build_index()
        except Exception:
            pass
        # Auto-calibrate
        try:
            if entry["skills"]:
                from self_model import load_model, save_model, auto_calibrate
                model = load_model()
                model = auto_calibrate(model, [entry])
                save_model(model)
        except Exception:
            pass
        return JSONResponse({"ok": True, "written": str(path)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/memory/recent")
async def get_memory_recent():
    from daemon import VEX_HOME
    memory_dir = VEX_HOME / "vex_memory"
    if not memory_dir.exists():
        return JSONResponse([])
    sessions = []
    files = sorted([f for f in memory_dir.iterdir() if f.suffix == ".jsonl"], reverse=True)
    for f in files[:5]:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    sessions.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
    return JSONResponse(sessions[:10])


@router.post("/memory/search")
async def post_memory_search(request: Request):
    from daemon import read_json_limited
    body, err = await read_json_limited(request)
    if err:
        return err
    query = body.get("query", "").strip()
    k = max(1, min(int(body.get("k", 5)), 20))
    if not query:
        return JSONResponse({"ok": False, "error": "query is required"}, status_code=400)
    from recall import recall as _recall
    results = _recall(query, k=k)
    return JSONResponse({"ok": True, "query": query, "results": results})


@router.get("/reconstruct")
async def get_reconstruct():
    try:
        from reconstruct import reconstruct as _reconstruct
        result = _reconstruct()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/diary")
async def post_diary(request: Request):
    from daemon import check_auth, read_json_limited
    from heartbeat import write_diary
    if (err := check_auth(request)):
        return err
    try:
        body, err = await read_json_limited(request)
        if err:
            return err
        entry = body.get("entry", "")
        if not entry:
            return JSONResponse({"ok": False, "error": "entry is required"}, status_code=400)
        await write_diary(entry, source="api")
        return JSONResponse({"ok": True, "written": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
