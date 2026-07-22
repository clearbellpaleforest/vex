"""Identity router — /seed, /self, /self/update, /self/calibration."""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(tags=["identity"])


def init(daemon):
    """Called after daemon module is loaded to wire shared state."""
    global _daemon
    _daemon = daemon


@router.get("/seed")
async def get_seed():
    try:
        from seed_kernel import load_seed, SeedIntegrityError
        content = load_seed()
        return PlainTextResponse(content)
    except FileNotFoundError:
        return JSONResponse({"error": "seed not found"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/self")
async def get_self():
    import aiosqlite
    from self_model import load_model, SelfModelError
    try:
        model = load_model()
        return JSONResponse(model)
    except FileNotFoundError:
        return JSONResponse({"error": "self-model not found"}, status_code=500)
    except SelfModelError as e:
        try:
            from daemon import DB_PATH
            async with aiosqlite.connect(str(DB_PATH)) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT json_blob FROM self_snapshots ORDER BY id DESC LIMIT 1"
                )
                row = await cursor.fetchone()
                if row:
                    return JSONResponse(json.loads(row["json_blob"]))
        except Exception:
            pass
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/self/update")
async def post_self_update(request: Request):
    from daemon import check_auth, DB_PATH
    from heartbeat import take_snapshot
    from self_model import load_model, save_model, apply_delta
    if (err := check_auth(request)):
        return err
    try:
        body = await request.json()
        domain = body.get("domain", "")
        delta = body.get("delta", 0.0)
        evidence = body.get("evidence", "")
        if not domain:
            return JSONResponse({"ok": False, "error": "domain is required"}, status_code=400)
        delta = max(-1.0, min(1.0, float(delta)))
        model = load_model()
        model = apply_delta(model, domain, delta, evidence)
        save_model(model)
        await take_snapshot(str(DB_PATH), "skill_update")
        new_skill = model.get("capabilities", {}).get(domain, {}).get("estimated_skill", 0.5)
        return JSONResponse({"ok": True, "domain": domain, "new_skill": new_skill})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/self/calibration")
async def get_self_calibration():
    from self_model import load_model, compute_mps_coherence
    try:
        model = load_model()
        caps = model.get("capabilities", {})
        out = {}
        for name, cap in caps.items():
            if not isinstance(cap, dict):
                continue
            obs = cap.get("n_observations", 0)
            skill = cap.get("estimated_skill", 0)
            conf = cap.get("confidence", 0)
            mastered = obs > 20 and conf > 0.80 and skill > 0.80
            stagnant = obs > 10 and conf < 0.50
            out[name] = {
                "skill": skill, "confidence": conf, "observations": obs,
                "last_evaluated": cap.get("last_evaluated", "never"),
                "mastered": mastered, "stagnant": stagnant,
            }
        return JSONResponse({"ok": True, "calibration": out,
                            "coherence": round(compute_mps_coherence(model), 4)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
