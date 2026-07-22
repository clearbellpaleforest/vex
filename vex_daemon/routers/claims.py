"""Claims router — /claim/file, /claim/release, /claims."""

import time as _t

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["claims"])

CLAIM_TTL = 600.0
_CLAIMS: dict[str, dict] = {}


@router.post("/claim/file")
async def post_claim_file(request: Request):
    try:
        body = await request.json()
        fp = (body.get("file") or "").strip()
        owner = (body.get("owner") or "").strip()
        ttl = float(body.get("timeout", CLAIM_TTL))
        if not fp or not owner:
            return JSONResponse({"ok": False, "error": "file and owner required"}, status_code=400)
        now_t = _t.time()
        for k in list(_CLAIMS):
            if now_t - _CLAIMS[k].get("claimed_at", 0) > CLAIM_TTL:
                del _CLAIMS[k]
        existing = _CLAIMS.get(fp)
        if existing and existing.get("owner") != owner and (now_t - existing.get("claimed_at", 0) <= CLAIM_TTL):
            return JSONResponse({"ok": True, "claimed": False, "owner": existing["owner"]})
        _CLAIMS[fp] = {"owner": owner, "claimed_at": now_t, "ttl": ttl}
        return JSONResponse({"ok": True, "claimed": True, "file": fp, "owner": owner})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/claim/release")
async def post_claim_release(request: Request):
    try:
        body = await request.json()
        fp = (body.get("file") or "").strip()
        owner = (body.get("owner") or "").strip()
        existing = _CLAIMS.get(fp)
        if existing and existing.get("owner") == owner:
            del _CLAIMS[fp]
            return JSONResponse({"ok": True, "released": True, "file": fp})
        return JSONResponse({"ok": True, "released": False, "note": "not your claim or not found"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/claims")
async def get_claims(request: Request):
    now_t = _t.time()
    for k in list(_CLAIMS):
        if now_t - _CLAIMS[k].get("claimed_at", 0) > CLAIM_TTL:
            del _CLAIMS[k]
    return JSONResponse({"ok": True, "claims": _CLAIMS})
