"""Exhaustive cross-checks for the four-direction solver.

For every random projection instance on small grids we enumerate *all*
2^(R*C) binary grids by brute force, then assert that the solver reports
the same status (none / unique / multiple) and, when solutions exist,
returns the same one or two lexicographically smallest bit strings.
"""

import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.solver import actual_line_sums, solve  # noqa: E402


def projections_of(bitstring, R, C):
    return actual_line_sums(R, C, bitstring)


def brute_force(R, C, rows, cols, diffs, sums, known=None):
    known_map = {}
    if known:
        for r, c, v in known:
            known_map[r * C + c] = v
    sols = []
    for bits in itertools.product("01", repeat=R * C):
        s = "".join(bits)
        ok = True
        for idx, v in known_map.items():
            if s[idx] != str(v):
                ok = False
                break
        if not ok:
            continue
        rs, cs, ds, ss = projections_of(s, R, C)
        if rs == list(rows) and cs == list(cols) and ds == list(diffs) and ss == list(sums):
            sols.append(s)
    sols.sort()
    return sols


class SwitchingComponentTests(unittest.TestCase):
    """The canonical 4x4 ambiguous pair (see README)."""

    A = "0010100000010100"  # .01. / 1... / ...1 / .1..
    B = "0100000110000010"  # .10. / ...1 / 1... / ..1.

    def test_pair_has_identical_four_projections(self):
        pa = projections_of(self.A, 4, 4)
        pb = projections_of(self.B, 4, 4)
        self.assertEqual(pa, pb)
        self.assertNotEqual(self.A, self.B)

    def test_status_multiple_and_two_smallest(self):
        rs, cs, ds, ss = projections_of(self.A, 4, 4)
        result = solve(4, 4, rs, cs, ds, ss)
        self.assertEqual(result.status, "multiple")
        self.assertEqual(result.solutions, sorted([self.A, self.B]))

    def test_each_grid_is_unique_witnessed_by_a_known_cell(self):
        rs, cs, ds, ss = projections_of(self.A, 4, 4)
        # Fixing one differing cell to A's value must pin A uniquely.
        diff_idx = next(i for i in range(16) if self.A[i] != self.B[i])
        r, c = divmod(diff_idx, 4)
        result = solve(4, 4, rs, cs, ds, ss, known=[(r, c, int(self.A[diff_idx]))])
        self.assertEqual(result.status, "unique")
        self.assertEqual(result.solutions, [self.A])

    def test_conflicting_known_cell_is_none(self):
        rs, cs, ds, ss = projections_of(self.A, 4, 4)
        # (0,0) is 0 in both solutions; force it to 1 -> no solution.
        result = solve(4, 4, rs, cs, ds, ss, known=[(0, 0, 1)])
        self.assertEqual(result.status, "none")
        self.assertEqual(result.solutions, [])


class ExhaustiveRandomTests(unittest.TestCase):
    def _check_instance(self, R, C, rows, cols, diffs, sums, known=None):
        result = solve(R, C, rows, cols, diffs, sums, known)
        expected = brute_force(R, C, rows, cols, diffs, sums, known)
        if not expected:
            self.assertEqual(result.status, "none")
            self.assertEqual(result.solutions, [])
        elif len(expected) == 1:
            self.assertEqual(result.status, "unique", (R, C, rows, cols, known))
            self.assertEqual(result.solutions, expected[:1])
        else:
            self.assertEqual(result.status, "multiple", (R, C, rows, cols, known))
            self.assertEqual(result.solutions, expected[:2])

    def test_random_4x4_and_4x5_without_known(self):
        rng = random.Random(20260920)
        for R, C, trials in [(4, 4, 60), (4, 5, 30), (5, 4, 20)]:
            nd = R + C - 1
            for _ in range(trials):
                grid = "".join(rng.choice("01") for _ in range(R * C))
                rs, cs, ds, ss = projections_of(grid, R, C)
                self._check_instance(R, C, rs, cs, ds, ss)

    def test_random_with_known_cells(self):
        rng = random.Random(77)
        for R, C, trials in [(4, 4, 40), (4, 5, 20)]:
            nd = R + C - 1
            for _ in range(trials):
                grid = "".join(rng.choice("01") for _ in range(R * C))
                rs, cs, ds, ss = projections_of(grid, R, C)
                k = rng.randint(0, 6)
                idxs = rng.sample(range(R * C), k)
                # Half the time truthful known cells, otherwise arbitrary.
                known = [
                    (i // C, i % C, int(grid[i]) if rng.random() < 0.6 else rng.randint(0, 1))
                    for i in idxs
                ]
                self._check_instance(R, C, rs, cs, ds, ss, known)

    def test_infeasible_projection_totals(self):
        # Row total != column total.
        result = solve(4, 4, [1, 1, 1, 1], [2, 1, 0, 0], [0] * 7, [0] * 7)
        self.assertEqual(result.status, "none")

    def test_all_zero_and_all_one(self):
        nd = 7
        z = solve(4, 4, [0] * 4, [0] * 4, [0] * nd, [0] * nd)
        self.assertEqual(z.status, "unique")
        self.assertEqual(z.solutions, ["0" * 16])
        o = solve(4, 4, [4] * 4, [4] * 4,
                  [1, 2, 3, 4, 3, 2, 1], [1, 2, 3, 4, 3, 2, 1])
        self.assertEqual(o.status, "unique")
        self.assertEqual(o.solutions, ["1" * 16])

    def test_duplicate_known_cell_raises(self):
        nd = 7
        with self.assertRaises(ValueError):
            solve(4, 4, [0] * 4, [0] * 4, [0] * nd, [0] * nd,
                  known=[(0, 0, 0), (0, 0, 1)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
