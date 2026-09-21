"""FastAPI application: four-direction projection reconstruction workbench."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
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

# Reconstruction is an exhaustive, purely CPU-bound search: a 12x12
# instance can keep a core busy for seconds.  Running it directly inside the
# async endpoint (or in a GIL-bound thread) would freeze the event loop and
# starve /api/health and every other concurrent request.  A small process
# pool keeps the event loop responsive while reconstructions run in full
# parallel on separate interpreters.  One process beyond the core count is
# kept as headroom so a quick independent request is not stuck behind a
# full set of multi-second 12x12 searches.
_SOLVE_WORKERS = max(2, min(4, (os.cpu_count() or 2) + 1))
_solve_pool: "ProcessPoolExecutor | None" = None


def _run_solve(payload: Dict[str, Any]) -> SolveResult:
    """Top-level worker so it is picklable across the process boundary."""
    return solve(
        payload["rows"],
        payload["cols"],
        payload["row"],
        payload["col"],
        payload["diff"],
        payload["sum"],
        payload["known"],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _solve_pool
    from concurrent.futures import ProcessPoolExecutor

    _solve_pool = ProcessPoolExecutor(max_workers=_SOLVE_WORKERS)
    try:
        yield
    finally:
        _solve_pool.shutdown(wait=True)
        _solve_pool = None


app = FastAPI(
    title="复合材料截面四向投影复核台",
    version="1.0.0",
    lifespan=lifespan,
)


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

    R, C = clean["rows"], clean["cols"]
    known = [(k["row"], k["col"], k["value"]) for k in clean["known"]]

    # Offload the CPU-bound exhaustive search; the event loop stays free to
    # serve /api/health and other concurrent requests while it runs.
    loop = asyncio.get_running_loop()
    result: SolveResult = await loop.run_in_executor(
        _solve_pool,
        _run_solve,
        {
            "rows": R,
            "cols": C,
            "row": clean["row"],
            "col": clean["col"],
            "diff": clean["diff"],
            "sum": clean["sum"],
            "known": known,
        },
    )

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
