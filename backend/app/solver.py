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

Performance note
----------------
A 12x12 grid carries 46 line constraints and the search visits many nodes.
Two observations keep propagation cheap:

  * Line counters (ones placed, cells still free) are plain arrays, so the
    feasible values of a cell are four O(1) window checks.
  * On a feasible line a free cell is forced to one value exactly when the
    line is saturated (the line still needs 0 ones, or needs every free
    cell to be 1).  Propagation is therefore a work queue that, after each
    assignment, revisits only cells on lines that just saturated.  At a
    branch child only the branched cell's four lines changed relative to
    the parent fixpoint, so the queue is seeded from just those lines; the
    root of the search examines every free cell once.
"""

from __future__ import annotations

from collections import deque
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
    # Line -> incident cells, in row-major cell order.
    line_cells: List[List[int]] = [[] for _ in range(n_lines)]
    for r in range(R):
        for c in range(C):
            idx = r * C + c
            lr, lc = r, R + c
            ld = R + C + (r - c + C - 1)
            ls = R + C + nd + (r + c)
            cell_lines[idx] = (lr, lc, ld, ls)
            for li in (lr, lc, ld, ls):
                line_cells[li].append(idx)

    target: List[int] = (
        list(row_sum) + list(col_sum) + list(diff_sum) + list(sum_sum)
    )
    cur = [0] * n_lines                       # number of 1s currently on line
    remain = [len(cs) for cs in line_cells]  # number of free cells on line
    grid = [-1] * n                          # -1 free, else 0/1
    free_count = n

    def assign(idx: int, v: int) -> None:
        nonlocal free_count
        grid[idx] = v
        free_count -= 1
        for li in cell_lines[idx]:
            remain[li] -= 1
            if v == 1:
                cur[li] += 1

    def undo(idx: int) -> None:
        nonlocal free_count
        v = grid[idx]
        grid[idx] = -1
        free_count += 1
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

    def snapshot() -> str:
        return "".join("1" if grid[i] == 1 else "0" for i in range(n))

    def search(seed_lines: Optional[Sequence[int]] = None) -> None:
        """Propagate to a fixpoint, then branch on the first free cell.

        ``seed_lines`` restricts the initial propagation wave: at a branch
        child only the branched cell's lines changed relative to the
        parent's fixpoint.  ``None`` (search root) examines every free cell.
        """
        nonlocal stop
        if stop:
            return

        # Fixpoint work queue with a per-node dedup bitmap.
        queue: deque[int] = deque()
        queued = bytearray(n)

        def enqueue(j: int) -> None:
            if grid[j] == -1 and not queued[j]:
                queued[j] = 1
                queue.append(j)

        trail: List[int] = []  # cells propagated at this node
        contradiction = False

        if seed_lines is not None:
            # The branched assignment in the parent frame changed only these
            # lines.  Check their windows explicitly: an over-tight line
            # with no free cell left would never reach the cell queue.
            for li in seed_lines:
                need = target[li] - cur[li]
                if need < 0 or need > remain[li]:
                    contradiction = True
                    break

        if not contradiction:
            if seed_lines is None:
                for i in range(n):
                    enqueue(i)
            else:
                for li in seed_lines:
                    for j in line_cells[li]:
                        enqueue(j)

        while queue:
            idx = queue.popleft()
            queued[idx] = 0
            if grid[idx] != -1:
                continue
            can0 = True
            can1 = True
            for li in cell_lines[idx]:
                need = target[li] - cur[li]
                rem = remain[li]  # includes idx, which is still free
                # idx = 0: need ones among rem-1 other free cells
                if not (0 <= need <= rem - 1):
                    can0 = False
                # idx = 1: need-1 ones among rem-1 other free cells
                if not (1 <= need <= rem):
                    can1 = False
                if not can0 and not can1:
                    break
            if not can0 and not can1:
                contradiction = True
                break
            if can0 and can1:
                continue

            # Forced cell: apply it, then propagate through any incident
            # line that just saturated.  An out-of-window line contradicts.
            v = 1 if not can0 else 0
            assign(idx, v)
            trail.append(idx)
            for li in cell_lines[idx]:
                need = target[li] - cur[li]
                rem = remain[li]
                if need < 0 or need > rem:
                    contradiction = True
                    break
                if need == 0 or need == rem:
                    for j in line_cells[li]:
                        enqueue(j)
            if contradiction:
                break

        if not contradiction:
            if free_count == 0:
                found.append(snapshot())
                found.sort()
                if len(found) > 2:
                    found.pop()
                if len(found) == 2:
                    stop = True
            else:
                # Row-major smallest free cell; branch 0 before 1 so that
                # solutions are emitted in ascending bit-string order.
                p = 0
                while grid[p] != -1:
                    p += 1
                for v in (0, 1):
                    assign(p, v)
                    search(cell_lines[p])
                    undo(p)
                    if stop:
                        break

        for idx in trail:
            undo(idx)

    # Initial line feasibility (cheap, 46 counters) before the deep search.
    feasible = True
    for li in range(n_lines):
        need = target[li] - cur[li]
        if need < 0 or need > remain[li]:
            feasible = False
            break

    if feasible:
        search()

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
