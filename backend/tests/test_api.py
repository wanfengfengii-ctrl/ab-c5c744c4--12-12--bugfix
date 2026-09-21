"""End-to-end tests of the FastAPI reconstruction API."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.solver import actual_line_sums  # noqa: E402

client = TestClient(app)

A = "0010100000010100"  # .01. / 1... / ...1 / .1..
B = "0100000110000010"  # .10. / ...1 / 1... / ..1.
# Four projections shared by A and B (computed from witness A):
ROW, COL, DIFF, SUM = actual_line_sums(4, 4, A)


class ApiTests(unittest.TestCase):
    def test_health(self):
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_multiple_ambiguous_pair(self):
        r = client.post("/api/reconstruct", json={
            "rows": 4, "cols": 4,
            "row": ROW, "col": COL, "diff": DIFF, "sum": SUM, "known": [],
        })
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "multiple")
        self.assertEqual([w["grid"] for w in body["witnesses"]], [A, B])
        self.assertEqual(len(body["differences"]), 8)
        for d in body["differences"]:
            self.assertEqual(d["values"], [int(A[d["index"]]), int(B[d["index"]])])
        for w in body["witnesses"]:
            self.assertEqual(w["lines"]["row"], ROW)
            self.assertEqual(w["lines"]["col"], COL)
            self.assertEqual(w["lines"]["diff"], DIFF)
            self.assertEqual(w["lines"]["sum"], SUM)

    def test_unique_with_known_cell(self):
        r = client.post("/api/reconstruct", json={
            "rows": 4, "cols": 4,
            "row": ROW, "col": COL, "diff": DIFF, "sum": SUM,
            "known": [{"row": 0, "col": 2, "value": 1}],
        })
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "unique")
        self.assertEqual(body["witnesses"][0]["grid"], A)
        self.assertEqual(body["differences"], [])

    def test_none_status_is_http_200(self):
        # Projections that pass every local check (lengths, bounds, equal
        # totals) yet admit no binary grid at all.
        r = client.post("/api/reconstruct", json={
            "rows": 4, "cols": 4,
            "row": [0, 0, 4, 4], "col": [0, 4, 4, 0],
            "diff": [0, 2, 2, 0, 2, 1, 1],
            "sum": [1, 0, 1, 3, 2, 0, 1],
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "none")
        self.assertEqual(r.json()["witnesses"], [])

    def test_invalid_dims_are_locatable(self):
        r = client.post("/api/reconstruct", json={"rows": 3, "cols": 4})
        self.assertEqual(r.status_code, 422)
        body = r.json()
        self.assertIn("errors", body)
        fields = {e["field"]: e for e in body["errors"]}
        self.assertIn("rows", fields)
        self.assertEqual(fields["rows"]["code"], "out_of_range")

    def test_bad_length_and_total_mismatch(self):
        r = client.post("/api/reconstruct", json={
            "rows": 4, "cols": 4,
            "row": [1, 1, 1], "col": [1, 1, 1, 1],
            "diff": DIFF, "sum": SUM,
        })
        self.assertEqual(r.status_code, 422)
        codes = {(e["field"], e["code"]) for e in r.json()["errors"]}
        self.assertIn(("row", "bad_length"), codes)

        r2 = client.post("/api/reconstruct", json={
            "rows": 4, "cols": 4,
            "row": [1, 1, 1, 1], "col": [2, 1, 0, 0],
            "diff": DIFF, "sum": SUM,
        })
        self.assertEqual(r2.status_code, 422)
        self.assertTrue(any(e["code"] == "total_mismatch"
                            for e in r2.json()["errors"]))

    def test_duplicate_and_conflict_known(self):
        base = {"rows": 4, "cols": 4, "row": ROW, "col": COL,
                "diff": DIFF, "sum": SUM}
        dup = dict(base, known=[{"row": 0, "col": 0, "value": 0},
                                {"row": 0, "col": 0, "value": 0}])
        r = client.post("/api/reconstruct", json=dup)
        self.assertEqual(r.status_code, 422)
        self.assertTrue(any(e["code"] == "duplicate" for e in r.json()["errors"]))

        conf = dict(base, known=[{"row": 0, "col": 0, "value": 0},
                                 {"row": 0, "col": 0, "value": 1}])
        r = client.post("/api/reconstruct", json=conf)
        self.assertEqual(r.status_code, 422)
        self.assertTrue(any(e["code"] == "conflict" for e in r.json()["errors"]))

    def test_value_too_large_and_negative(self):
        r = client.post("/api/reconstruct", json={
            "rows": 4, "cols": 4,
            "row": [5, 0, 0, 0], "col": [1, 1, 1, 1],
            "diff": DIFF, "sum": SUM,
        })
        self.assertEqual(r.status_code, 422)
        self.assertTrue(any(e["field"] == "row[0]" and e["code"] == "too_large"
                            for e in r.json()["errors"]))

    def test_bad_json(self):
        r = client.post("/api/reconstruct", content="{not json",
                        headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
