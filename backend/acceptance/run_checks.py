#!/usr/bin/env python3
"""One-shot acceptance suite for the four-projection review workbench.

Runs entirely on the Python standard library so the ``verify`` container
needs no extra dependencies.  It checks, over real HTTP:

  * API health  (API_URL,   default http://api:8000)
  * Web health, index page, built assets and /api reverse proxy
                (WEB_URL,   default http://web:80)
  * ambiguous 4x4 pair -> "multiple", witnesses equal the two smallest
    solutions found by an *independent* brute-force enumeration of 2^16
  * a known cell pins the witness uniquely
  * a locally-valid but jointly-infeasible instance -> "none"
  * illegal input -> HTTP 422 with locatable error codes
  * 12x12 smoke test: every returned witness really satisfies all four
    projection families and every known cell, recomputed independently

Exits 0 only when every check passes; 1 otherwise.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

API_URL = os.environ.get("API_URL", "http://api:8000").rstrip("/")
WEB_URL = os.environ.get("WEB_URL", "http://web:80").rstrip("/")

FAILURES: List[str] = []
PASSES: List[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSES.append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(f"{name} :: {detail}")
        print(f"  FAIL  {name} :: {detail}")


def request(method: str, url: str, payload: Any = None,
            want_status: int = None, payload_raw: str = None) -> Tuple[int, Any]:
    headers = {}
    data = None
    if payload_raw is not None:
        data = payload_raw.encode()
        headers["content-type"] = "application/json"
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = body
    if want_status is not None:
        check(f"HTTP {status} == {want_status} for {method} {url}",
              status == want_status, f"got {status}, body={body[:200]}")
    return status, parsed


def line_sums(bitstring: str, R: int, C: int):
    rs = [0] * R
    cs = [0] * C
    ds = [0] * (R + C - 1)
    ss = [0] * (R + C - 1)
    for i, ch in enumerate(bitstring):
        if ch == "1":
            r, c = divmod(i, C)
            rs[r] += 1
            cs[c] += 1
            ds[r - c + C - 1] += 1
            ss[r + c] += 1
    return rs, cs, ds, ss


def brute_force(R, C, rows, cols, diffs, sums, known=None):
    kmap = {}
    for k in known or []:
        kmap[k["row"] * C + k["col"]] = k["value"]
    out = []
    for bits in itertools.product("01", repeat=R * C):
        s = "".join(bits)
        if any(s[i] != str(v) for i, v in kmap.items()):
            continue
        rs, cs, ds, ss = line_sums(s, R, C)
        if (rs, cs, ds, ss) == (list(rows), list(cols), list(diffs), list(sums)):
            out.append(s)
    return sorted(out)


A = "0010100000010100"
B = "0100000110000010"
ROW, COL, DIFF, SUMV = line_sums(A, 4, 4)

AMBIGUOUS = {
    "rows": 4, "cols": 4,
    "row": ROW, "col": COL, "diff": DIFF, "sum": SUMV, "known": [],
}
NONE_PAYLOAD = {
    "rows": 4, "cols": 4,
    "row": [0, 0, 4, 4], "col": [0, 4, 4, 0],
    "diff": [0, 2, 2, 0, 2, 1, 1],
    "sum": [1, 0, 1, 3, 2, 0, 1],
    "known": [],
}


def check_health_and_web() -> None:
    print("[1] health & static web")
    st, body = request("GET", f"{API_URL}/api/health", want_status=200)
    check("api health payload", isinstance(body, dict) and body.get("status") == "ok",
          str(body))

    st, body = request("GET", f"{WEB_URL}/health", want_status=200)
    check("web health endpoint", st == 200, str(body)[:120])

    st, index_html = request("GET", f"{WEB_URL}/", want_status=200)
    check("web serves index.html", 'id="root"' in index_html and "<script" in index_html,
          index_html[:120])

    # The hashed asset referenced by index must be reachable via the web.
    asset = None
    marker = 'src="'
    i = index_html.find(marker)
    if i >= 0:
        j = index_html.find('"', i + len(marker))
        asset = index_html[i + len(marker):j]
    check("index references an asset path", asset and asset.startswith("/assets/"),
          str(asset))
    if asset:
        st, _ = request("GET", f"{WEB_URL}{asset}", want_status=200)

    # The web container must reverse-proxy the API.
    st, body = request("POST", f"{WEB_URL}/api/reconstruct", AMBIGUOUS,
                       want_status=200)
    check("web /api proxy reaches reconstruction", isinstance(body, dict)
          and body.get("status") == "multiple", str(body)[:200])


def check_ambiguous() -> None:
    print("[2] ambiguous 4x4 switching component")
    st, body = request("POST", f"{API_URL}/api/reconstruct", AMBIGUOUS,
                       want_status=200)
    check("status multiple", body.get("status") == "multiple", str(body.get("status")))
    grids = [w["grid"] for w in body.get("witnesses", [])]
    check("exactly two witnesses", grids == [A, B], str(grids))

    expected = brute_force(4, 4, ROW, COL, DIFF, SUMV)
    check("brute force finds exactly the same two grids", expected == [A, B],
          str(expected))
    check("returned witnesses are the two smallest", grids == expected[:2],
          f"{grids} vs {expected[:2]}")
    check("witnesses differ", A != B, "")
    check("bit-string order (0 precedes 1)", A < B, "")

    diffs = body.get("differences", [])
    diff_idx = {d["index"] for d in diffs}
    real_idx = {i for i in range(16) if A[i] != B[i]}
    check("differences exactly the 8 switching cells", diff_idx == real_idx,
          f"{sorted(diff_idx)} vs {sorted(real_idx)}")

    # Independently recompute each witness's actual sums from the grid.
    for n, w in enumerate(body.get("witnesses", [])):
        rs, cs, ds, ss = line_sums(w["grid"], 4, 4)
        check(f"witness {n + 1} row sums", rs == ROW, str(rs))
        check(f"witness {n + 1} col sums", cs == COL, str(cs))
        check(f"witness {n + 1} r-c sums", ds == DIFF, str(ds))
        check(f"witness {n + 1} r+c sums", ss == SUMV, str(ss))
        # The reported per-line witness must match the recomputation.
        rep = w["lines"]
        check(f"witness {n + 1} reported sums are truthful",
              rep == {"row": rs, "col": cs, "diff": ds, "sum": ss}, str(rep))


def check_unique() -> None:
    print("[3] known cell pins a unique witness")
    payload = dict(AMBIGUOUS,
                   known=[{"row": 0, "col": 2, "value": 1}])
    st, body = request("POST", f"{API_URL}/api/reconstruct", payload,
                       want_status=200)
    check("status unique", body.get("status") == "unique", str(body.get("status")))
    grids = [w["grid"] for w in body.get("witnesses", [])]
    check("unique grid is A", grids == [A], str(grids))
    check("known cell honoured", grids and grids[0][0 * 4 + 2] == "1", "")
    check("no differences for unique result", body.get("differences") == [],
          str(body.get("differences")))
    expected = brute_force(4, 4, ROW, COL, DIFF, SUMV, payload["known"])
    check("brute force confirms uniqueness", expected == [A], str(expected))

    # Fixing the opposite value at another differing cell pins B.
    payload2 = dict(AMBIGUOUS,
                    known=[{"row": 0, "col": 1, "value": 1}])
    st, body2 = request("POST", f"{API_URL}/api/reconstruct", payload2,
                        want_status=200)
    check("opposite known cell pins B",
          body2.get("status") == "unique"
          and body2["witnesses"][0]["grid"] == B, str(body2)[:200])


def check_none() -> None:
    print("[4] certified no-solution")
    st, body = request("POST", f"{API_URL}/api/reconstruct", NONE_PAYLOAD,
                       want_status=200)
    check("status none", body.get("status") == "none", str(body.get("status")))
    check("no witnesses returned", body.get("witnesses") == [],
          str(body.get("witnesses")))
    expected = brute_force(4, 4, NONE_PAYLOAD["row"], NONE_PAYLOAD["col"],
                           NONE_PAYLOAD["diff"], NONE_PAYLOAD["sum"])
    check("brute force also finds zero solutions", expected == [],
          f"{len(expected)} solutions")


def check_rejections() -> None:
    print("[5] locatable rejections")

    def codes(payload):
        st, body = request("POST", f"{API_URL}/api/reconstruct", payload)
        check("rejected with 422", st == 422, f"status {st}")
        errs = body.get("errors", []) if isinstance(body, dict) else []
        return st, {(e["field"], e["code"]) for e in errs}, errs

    st, got, _ = codes({"rows": 3, "cols": 4})
    check("dims out of range", ("rows", "out_of_range") in got, str(got))

    st, got, _ = codes({
        "rows": 4, "cols": 4,
        "row": [1, 1, 1], "col": [1, 1, 1, 1],
        "diff": DIFF, "sum": SUMV,
    })
    check("vector bad length", ("row", "bad_length") in got, str(got))

    st, got, _ = codes({
        "rows": 4, "cols": 4,
        "row": [1, 1, 1, 1], "col": [2, 1, 0, 0],
        "diff": DIFF, "sum": SUMV,
    })
    check("projection total mismatch",
          any(c == "total_mismatch" for _, c in got), str(got))

    base = {"rows": 4, "cols": 4, "row": ROW, "col": COL,
            "diff": DIFF, "sum": SUMV}
    st, got, _ = codes(dict(base, known=[
        {"row": 0, "col": 0, "value": 0},
        {"row": 0, "col": 0, "value": 0},
    ]))
    check("duplicate known cell", any(c == "duplicate" for _, c in got), str(got))

    st, got, _ = codes(dict(base, known=[
        {"row": 0, "col": 0, "value": 0},
        {"row": 0, "col": 0, "value": 1},
    ]))
    check("conflicting known cell", any(c == "conflict" for _, c in got), str(got))

    st, got, _ = codes({
        "rows": 4, "cols": 4,
        "row": [5, 0, 0, 0], "col": [1, 1, 1, 1],
        "diff": DIFF, "sum": SUMV,
    })
    check("line value above cell count",
          ("row[0]", "too_large") in got, str(got))

    st, body = request("POST", f"{API_URL}/api/reconstruct",
                       payload_raw="{not json")
    check("malformed JSON -> 400", st == 400, f"status {st}")


def check_large_grid() -> None:
    print("[6] 12x12 smoke test and witness validity")
    # Deterministic "random" 12x12 grid; project it; ask for reconstruction.
    R = C = 12
    bits = []
    state = 0x1234ABCD
    for _ in range(R * C):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        bits.append("1" if state % 100 < 45 else "0")
    grid = "".join(bits)
    rs, cs, ds, ss = line_sums(grid, R, C)
    payload = {"rows": R, "cols": C, "row": rs, "col": cs, "diff": ds,
               "sum": ss, "known": [
                   {"row": 0, "col": 0, "value": int(grid[0])},
                   {"row": 11, "col": 11, "value": int(grid[-1])},
               ]}
    st, body = request("POST", f"{API_URL}/api/reconstruct", payload,
                       want_status=200)
    status = body.get("status")
    check("12x12 status in {unique, multiple, none}",
          status in ("unique", "multiple", "none"), str(status))
    check("12x12 expected a witness for these projections", status != "none",
          "projections were generated from a real grid")
    if status == "none":
        return
    witnesses = body.get("witnesses", [])
    check("one or two witnesses", len(witnesses) in (1, 2), str(len(witnesses)))
    for n, w in enumerate(witnesses):
        g = w["grid"]
        check(f"12x12 witness {n + 1} has 144 bits", len(g) == 144, str(len(g)))
        r2, c2, d2, s2 = line_sums(g, R, C)
        check(f"12x12 witness {n + 1} row sums match", r2 == rs, "")
        check(f"12x12 witness {n + 1} col sums match", c2 == cs, "")
        check(f"12x12 witness {n + 1} r-c sums match", d2 == ds, "")
        check(f"12x12 witness {n + 1} r+c sums match", s2 == ss, "")
        check(f"12x12 witness {n + 1} honours known cells",
              g[0] == grid[0] and g[-1] == grid[-1], "")
    if len(witnesses) == 2:
        g1, g2 = witnesses[0]["grid"], witnesses[1]["grid"]
        check("multiple witnesses are distinct", g1 != g2, "")
        check("returned in ascending bit-string order", g1 < g2,
              f"{g1[:16]}... !< ...{g2[:16]}")
        real = {i for i in range(R * C) if g1[i] != g2[i]}
        reported = {d["index"] for d in body.get("differences", [])}
        check("12x12 difference cells are exact", real == reported, "")


def main() -> int:
    print(f"Acceptance against API={API_URL} WEB={WEB_URL}\n")
    try:
        check_health_and_web()
        check_ambiguous()
        check_unique()
        check_none()
        check_rejections()
        check_large_grid()
    except Exception as e:  # network errors etc. must fail the run
        FAILURES.append(f"unexpected exception: {e!r}")
        print(f"  ERROR {e!r}")

    print(f"\n{len(PASSES)} checks passed, {len(FAILURES)} failed")
    if FAILURES:
        print("\nFAILURES:")
        for f in FAILURES:
            print(" -", f)
        return 1
    print("ALL ACCEPTANCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
