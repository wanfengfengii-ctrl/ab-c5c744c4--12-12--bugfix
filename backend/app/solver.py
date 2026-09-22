"""Four-direction binary discrete tomography solver.

A section is an R x C binary grid (4 <= R, C <= 12).  Four families of
line projections must all be satisfied:

  * rows:      sum over cell (r, c) for fixed r
  * columns:   sum over cell (r, c) for fixed c
  * diagonals  r - c = k, ordered by increasing r - c
  * diagonals  r + c = s, ordered by increasing r + c

Some cells may be known (fixed 0 or fixed 1).  The solver enumerates
solutions exhaustively by depth-first backtracking with constraint
propagation (no greedy, no random search) and proves uniqueness:

    status "none"     -> there is no solution
    status "unique"   -> exactly one solution exists
    status "multiple" -> at least two solutions exist

For "multiple" the two lexicographically smallest solutions are returned,
where solutions are compared as row-major bit strings with 0 preceding 1
(i.e. ordinary lexicographic order on "0"/"1" strings).

Ordering guarantee
------------------
Branching visits free cells in strictly row-major order and tries 0 before
1.  Before branching, forced cells are propagated to a fixpoint: a cell
that can only take one value under the current prefix is a logical
consequence of that prefix, so recording it skips no solution.  The DFS
therefore emits solutions in ascending row-major lexicographic order, and
uniqueness is established only after the search space is exhausted.

Propagation is driven by critical lines: for a line with ``need`` ones
still to place among ``remain`` free cells, a cell on it can be forced
only when ``need == 0`` (all free cells must be 0) or ``need == remain``
(all must be 1) — exactly the arc-consistency condition for a cardinality
constraint.  Every assignment re-checks only its four incident lines and
queues them when they turn critical, so the search reaches the same
fixpoint as repeatedly testing every free cell, while doing a constant
amount of work per assignment.  Free cells are tracked in an integer
bitmask so the row-major branch cell is the lowest set bit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass
class SolveResult:
    status: str  # "none" | "unique" | "multiple"
    solutions: List[str]  # 0/1 row-major strings, length R*C, sorted ascending


def solve(
    rows: int,
    cols: int,
    row_sum: Sequence[int],
    col_sum: Sequence[int],
    diff_sum: Sequence[int],
    sum_sum: Sequence[int],
    known: Optional[Sequence[Tuple[int, int, int]]] = None,
) -> SolveResult:
    R, C = rows, cols
    n = R * C
    nd = R + C - 1
    n_lines = R + C + 2 * nd

    # Cell -> its four line indices (row, col, r-c, r+c).
    cell_lines: List[Tuple[int, int, int, int]] = [(0, 0, 0, 0)] * n
    line_lists: List[List[int]] = [[] for _ in range(n_lines)]
    for r in range(R):
        for c in range(C):
            idx = r * C + c
            lr, lc = r, R + c
            ld = R + C + (r - c + C - 1)
            ls = R + C + nd + (r + c)
            cell_lines[idx] = (lr, lc, ld, ls)
            for li in (lr, lc, ld, ls):
                line_lists[li].append(idx)
    line_cells: List[Tuple[int, ...]] = [tuple(cs) for cs in line_lists]

    target: List[int] = list(row_sum) + list(col_sum) + list(diff_sum) + list(sum_sum)
    cur = [0] * n_lines                       # number of 1s currently on line
    remain = [len(cs) for cs in line_cells]  # number of free cells on line
    grid = [-1] * n                          # -1 free, else 0/1
    free = (1 << n) - 1                      # bitmask of unassigned cells

    def assign(idx: int, v: int) -> List[int]:
        """Fix cell idx to v; return incident lines that turned critical."""
        nonlocal free
        grid[idx] = v
        free &= ~(1 << idx)
        critical = []
        for li in cell_lines[idx]:
            remain[li] -= 1
            if v == 1:
                cur[li] += 1
            rem = remain[li]
            if rem > 0:
                need = target[li] - cur[li]
                if need == 0 or need == rem:
                    critical.append(li)
        return critical

    def undo(idx: int) -> None:
        nonlocal free
        v = grid[idx]
        grid[idx] = -1
        free |= 1 << idx
        for li in cell_lines[idx]:
            remain[li] += 1
            if v == 1:
                cur[li] -= 1

    if known:
        seen = set()
        for (r, c, v) in known:
            idx = r * C + c
            if idx in seen:
                raise ValueError(f"duplicate known cell at row {r}, column {c}")
            seen.add(idx)
            assign(idx, v)
        for li in range(n_lines):
            need = target[li] - cur[li]
            if need < 0 or need > remain[li]:
                return SolveResult("none", [])

    found: List[str] = []
    stop = False

    def all_lines_feasible() -> bool:
        for li in range(n_lines):
            need = target[li] - cur[li]
            if need < 0 or need > remain[li]:
                return False
        return True

    def snapshot() -> str:
        return "".join("1" if grid[i] == 1 else "0" for i in range(n))

    def propagate(queue: List[int], trail: List[int]) -> bool:
        """Force every cell settled by a critical line, to a fixpoint.

        ``queue`` holds lines to inspect.  A line with ``need == 0`` forces
        all its free cells to 0, ``need == remain`` forces them to 1; each
        forced assignment re-checks its four incident lines and queues the
        ones that turn critical.  Returns True as soon as a line becomes
        infeasible (its remaining ones no longer fit its free cells).
        """
        nonlocal free
        while queue:
            li = queue.pop()
            rem = remain[li]
            if rem == 0:
                continue
            need = target[li] - cur[li]
            if need == 0:
                v = 0
            elif need == rem:
                v = 1
            else:
                continue  # no longer critical; nothing to force
            for idx in line_cells[li]:
                bit = 1 << idx
                if not free & bit:
                    continue
                grid[idx] = v
                free &= ~bit
                trail.append(idx)
                # Update all four incident lines first, then judge: an
                # infeasible line must still leave the counters consistent
                # so the caller can roll the trail back cleanly.
                bad = False
                for lj in cell_lines[idx]:
                    remain[lj] -= 1
                    if v == 1:
                        cur[lj] += 1
                    rem2 = remain[lj]
                    need2 = target[lj] - cur[lj]
                    if need2 < 0 or need2 > rem2:
                        bad = True
                    elif rem2 > 0 and (need2 == 0 or need2 == rem2):
                        queue.append(lj)
                if bad:
                    return True
        return False

    def search(queue: List[int]) -> None:
        nonlocal stop
        if stop:
            return

        trail: List[int] = []
        contradiction = propagate(queue, trail)

        if not contradiction:
            if free == 0:
                found.append(snapshot())
                found.sort()
                if len(found) > 2:
                    found.pop()
                if len(found) == 2:
                    stop = True
            else:
                # Row-major smallest free cell (lowest set bit); branch 0
                # before 1 so solutions are emitted in ascending order.
                p = (free & -free).bit_length() - 1
                for v in (0, 1):
                    search(assign(p, v))
                    undo(p)
                    if stop:
                        break

        for idx in trail:
            undo(idx)

    if all_lines_feasible():
        search(list(range(n_lines)))

    if not found:
        return SolveResult("none", [])
    if len(found) == 1:
        return SolveResult("unique", found)
    return SolveResult("multiple", found[:2])


def actual_line_sums(
    rows: int,
    cols: int,
    bitstring: str,
) -> Tuple[List[int], List[int], List[int], List[int]]:
    """Return the four line-sum families (rows, cols, r-c, r+c)."""
    R, C = rows, cols
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
