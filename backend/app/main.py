"""FastAPI application: four-direction projection reconstruction workbench."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    Difference,
    FieldError,
    Health,
    LineWitness,
    ReconstructResponse,
    RejectResponse,
    Witness,
)
from .solver import SolveResult, actual_line_sums, solve
from .validation import validate_payload

app = FastAPI(title="复合材料截面四向投影复核台", version="1.0.0")

# Reconstruction is CPU-bound (exhaustive 12x12 search).  It runs in a pool
# of worker processes so that even the worst-case legal input can never
# block the event loop: /api/health and unrelated requests keep being
# served while a reconstruction is in flight, and every queued request is
# still answered with the full none/unique/multiple determination.
_POOL_WORKERS = max(2, min(8, os.cpu_count() or 2))
solver_pool = ProcessPoolExecutor(max_workers=_POOL_WORKERS)


def _solve_clean(clean: Dict[str, Any]) -> SolveResult:
    """Run the solver for an already-validated payload (worker process)."""
    known = [(k["row"], k["col"], k["value"]) for k in clean["known"]]
    return solve(clean["rows"], clean["cols"], clean["row"], clean["col"],
                 clean["diff"], clean["sum"], known)


def _warm_up_solver_pool() -> None:
    # Spawn the worker processes now, while the process is still
    # single-threaded (module import, before uvicorn starts serving), so no
    # fork happens while the asyncio loop and its threads are running and
    # the first reconstruction does not pay the spawn cost.
    list(solver_pool.map(int, range(_POOL_WORKERS)))


_warm_up_solver_pool()


@app.get("/api/health", response_model=Health)
def api_health() -> Health:
    return Health(status="ok", service="reconstruction-api")


@app.post(
    "/api/reconstruct",
    response_model=ReconstructResponse,
    responses={422: {"model": RejectResponse}, 400: {"model": RejectResponse}},
)
async def reconstruct(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=RejectResponse(
                message="请求体不是合法 JSON",
                errors=[FieldError(field="$", code="bad_json",
                                   message="请求体必须是合法的 JSON")],
            ).model_dump(),
        )

    clean, errors = validate_payload(payload)
    if errors:
        return JSONResponse(
            status_code=422,
            content=RejectResponse(
                message="输入校验未通过，请定位下列字段后重试",
                errors=errors,
            ).model_dump(),
        )

    # Off-load the exhaustive search to a worker process; the event loop
    # stays responsive for the whole duration of the computation.
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(solver_pool, _solve_clean, clean)

    R, C = clean["rows"], clean["cols"]
    witnesses: List[Witness] = []
    differences: List[Difference] = []
    for bitstring in result.solutions:
        rs, cs, ds, ss = actual_line_sums(R, C, bitstring)
        witnesses.append(Witness(
            grid=bitstring,
            lines=LineWitness(row=rs, col=cs, diff=ds, sum=ss),
        ))
    if len(witnesses) == 2:
        g1, g2 = witnesses[0].grid, witnesses[1].grid
        for i, (a, b) in enumerate(zip(g1, g2)):
            if a != b:
                r, c = divmod(i, C)
                differences.append(Difference(index=i, row=r, col=c,
                                              values=[int(a), int(b)]))

    body = ReconstructResponse(
        status=result.status,
        rows=R,
        cols=C,
        targets=LineWitness(row=clean["row"], col=clean["col"],
                            diff=clean["diff"], sum=clean["sum"]),
        witnesses=witnesses,
        differences=differences,
    )
    # 200 for every solved outcome, including "none": the request was valid
    # and the certified absence of a solution is the computed result.
    return JSONResponse(status_code=200, content=body.model_dump())


# ---- Static front-end (served by the same container; optional) ----------
_STATIC_DIR = os.environ.get("WEB_STATIC_DIR", "/app/web")
if os.path.isdir(_STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")),
              name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))
