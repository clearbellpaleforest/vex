"""Update router — /update, /update/check, /restart."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["update"])


@router.post("/update/check")
async def post_update_check(request: Request):
    from daemon import check_auth
    from updater import check_updates
    if (err := check_auth(request)):
        return err
    try:
        result = check_updates()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/update")
async def post_update(request: Request):
    from daemon import check_auth
    from updater import apply_update
    if (err := check_auth(request)):
        return err
    try:
        result = apply_update()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/restart")
async def post_restart(request: Request):
    from daemon import check_auth
    from updater import restart_daemon
    if (err := check_auth(request)):
        return err
    try:
        result = restart_daemon()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
